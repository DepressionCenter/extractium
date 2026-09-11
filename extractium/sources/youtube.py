"""
Summary: The YouTube captions source plugin. Accepts explicit video ids,
playlist ids, and a channel id; lists playlists and channels through the
YouTube Data API v3 with a key read from the YOUTUBE_API_KEY environment
variable, never from config.yaml; fetches captions with
youtube-transcript-api; stores each transcript under the cache directory
so a build that cannot reach YouTube still produces the same index; and
yields one document per stretch of a video, addressed at the moment that
stretch begins. See docs/extractium-spec.md section 5.

This file is part of Extractium™
extractium/sources/youtube.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-11
Notes: See README file for documentation and full license information.
"""

# Copyright © 2026 The Regents of the University of Michigan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>.

__author__ = "Gabriel Mongefranco, University of Michigan."
__copyright__ = "Copyright (C) 2026 The Regents of the University of Michigan"
__license__ = "GPLv3 or later"
__date__ = "2026-08-17"

import re

from extractium.core import cache as cache_module
from extractium.core.fetch import DEFAULT_USER_AGENT
from extractium.core.models import Document
from extractium.sources.youtube_client import (
    TranscriptLibraryMissing,
    TranscriptUnavailable,
    YouTubeBlocked,
    YouTubeClient,
    YouTubeError,
    YouTubeNotFound,
    api_key,
    checked_video_id,
    fetch_transcript,
    uploads_playlist_id,
    watch_url,
)

### Constants ###

# How much transcript text one indexed stretch holds, in characters.
# Below the chunker's own ceiling, so a stretch stays one section with
# one address rather than being cut again into two sections that both
# claim the same moment.
SEGMENT_TARGET_CHARS = 950

# A stretch shorter than this is folded into the one before it. Captions
# do not divide into equal pieces, and the chunker drops a section under
# CHUNK_MIN_CHARS, so a short tail would otherwise be lost from the end
# of every video.
SEGMENT_MIN_CHARS = 120

# Seconds in a minute and in an hour, for turning an offset into the
# clock reading a viewer sees under the player.
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600

# Captions arrive as one line per phrase, often with the speaker's
# stumbles and the transcriber's markers. These are removed: "[Music]"
# and "(applause)" describe the soundtrack rather than saying anything,
# and a search hit on them helps nobody.
SOUND_MARKER_RE = re.compile(r"[\[(](?:music|applause|laughter|inaudible|silence)[\])]", re.I)

# Collapses every run of whitespace, including the newlines caption files
# use inside a single phrase, into one space.
WHITESPACE_RUN = re.compile(r"\s+")


### Errors ###

class YouTubeSourceError(Exception):
    """
    Raised when this source cannot produce the documents it was asked
    for: a channel or playlist that cannot be listed and has nothing
    stored, or captions that must be fetched from a machine YouTube
    refuses. The message names the fix and quotes no credential.
    """


### Timestamps ###

def timestamp(seconds):
    """
    An offset into a video as the clock reading a viewer sees.

    Args:
        seconds (int | float): how far into the video, in seconds.

    Returns:
        str: "m:ss" inside the first hour, "h:mm:ss" after it. Matches
        what YouTube itself shows under the player, so a heading reads
        the same as the timeline a person is looking at.
    """
    whole = max(0, int(seconds))
    hours, rest = divmod(whole, SECONDS_PER_HOUR)
    minutes, second = divmod(rest, SECONDS_PER_MINUTE)
    if hours:
        return f"{hours}:{minutes:02d}:{second:02d}"
    return f"{minutes}:{second:02d}"


### Transcript Text ###

def clean_line(text):
    """
    One caption line as a sentence fragment worth indexing.

    Args:
        text (str): the line as the caption track holds it.

    Returns:
        str: the line with sound markers removed and whitespace
        collapsed. Empty when the line said nothing but a marker.
    """
    without_markers = SOUND_MARKER_RE.sub(" ", text or "")
    return WHITESPACE_RUN.sub(" ", without_markers).strip()


def segments(lines, target_chars=SEGMENT_TARGET_CHARS, min_chars=SEGMENT_MIN_CHARS):
    """
    Groups caption lines into the stretches a search returns.

    Captions arrive one phrase at a time, which is far too small to
    answer a question with: a hit has to come back as enough speech to
    read. Lines are therefore joined in order up to target_chars, and
    each stretch keeps the start time of its first line so it can be
    cited at the moment it begins.

    Grain: one record per stretch of one video, ordered by time. Every
    line of the transcript appears in exactly one stretch, so the whole
    is the transcript and nothing is counted twice.

    Args:
        lines (Sequence[Mapping]): caption lines, each holding `text` and
            `start` in seconds. Expected in time order.
        target_chars (int): how much text a stretch aims to hold.
        min_chars (int): shortest stretch that may stand alone. A final
            stretch below this is folded into the one before it, so the
            end of a video is never dropped for being short.

    Returns:
        list[dict]: one record per stretch, each holding `start` in
        seconds and `text`.
    """
    grouped = []
    for line in lines:
        text = clean_line(line.get("text", ""))
        if not text:
            continue
        start = float(line.get("start") or 0.0)
        if grouped and len(grouped[-1]["text"]) + 1 + len(text) <= target_chars:
            grouped[-1]["text"] += " " + text
        else:
            grouped.append({"start": start, "text": text})

    # A short tail reads as a fragment and would be dropped downstream,
    # so it joins the stretch before it rather than standing alone.
    if len(grouped) > 1 and len(grouped[-1]["text"]) < min_chars:
        tail = grouped.pop()
        grouped[-1]["text"] += " " + tail["text"]
    return grouped


### Source ###

class YouTubeSource:
    """
    Indexes the captions of named videos, playlists, and one channel.

    Two things about YouTube shape this source. Listing a channel or a
    playlist needs a Data API key, while reading one video's captions
    needs none. And YouTube answers caption requests from
    cloud-provider address ranges with a block, so a scheduled build on
    a hosted runner cannot fetch a transcript at all. Everything read is
    therefore stored under the cache directory, and that store is meant
    to be committed to the data repository: an operator builds once on
    their own machine, commits what came back, and every later build
    reuses it.

    Args:
        options (Mapping): the validated options of a `youtube` entry:
            channel_id, playlist_ids, video_ids, and languages.

    Attributes:
        coverage (tuple): one record per video indexed, in the order
            read: its title, how many stretches it contributed, and
            whether its transcript came from the store or the network.
    """

    name = "youtube"

    def __init__(self, options):
        self.channel_id = (options.get("channel_id") or "").strip() or None
        self.playlist_ids = tuple(options.get("playlist_ids") or ())
        self.video_ids = tuple(options.get("video_ids") or ())
        self.languages = tuple(options.get("languages") or ("en",))
        self.settings = None
        # A caller with its own caption reader may set this; a build
        # leaves it alone and one is built on first use. It is the seam
        # the tests drive the source through, so a test needs neither the
        # network nor the transcript library.
        self.reader = None
        self.coverage = ()
        self.stored = 0
        self.fetched = 0
        self.without_captions = ()

    def configure(self, registry, settings):
        """
        Adopts the build's global crawl settings.

        Only two of them apply here: how the build introduces itself, and
        how long it waits between requests. Videos are read through an
        interface rather than crawled, so nothing else is used.

        Args:
            registry (extractium.core.registry.Registry): unused; a
                caption track needs no site handler.
            settings (extractium.sources.web.CrawlSettings): the build's
                User-Agent and politeness delay.
        """
        self.settings = settings

    ### Reading ###

    def fetch(self, session, cache, progress):
        """
        Yields one Document per stretch of every video asked for.

        Args:
            session: HTTP session to request through.
            cache (dict): the fetch cache metadata. Unused: a transcript
                is stored under the video's own identifier rather than by
                URL, because YouTube offers nothing to revalidate it
                against.
            progress (Callable[[str], None]): receives one line per event.

        Yields:
            extractium.core.models.Document: one per stretch of one
            video, addressed at the moment the stretch begins.

        Raises:
            YouTubeSourceError: if a channel or playlist cannot be listed
                and nothing is stored for it, or captions have to be
                fetched from a machine YouTube refuses.
        """
        client = YouTubeClient(
            session,
            key=api_key(),
            user_agent=self._user_agent(),
            progress=progress,
            delay_seconds=self._delay_seconds(),
        )
        video_ids = self._video_ids(client, progress)
        if not video_ids:
            progress("YouTube:      nothing to read")
            return

        progress(f"YouTube:      {len(video_ids)} video(s)")
        titles = self._titles(client, video_ids, progress)
        missing = []
        for video_id in video_ids:
            record, from_store = self._video(client, video_id, titles, progress)
            if record is None:
                missing.append(video_id)
                continue
            stretches = segments(record["segments"])
            for stretch in stretches:
                yield self._document(video_id, record["title"], stretch)
            self.coverage += ((record["title"], len(stretches), from_store),)
        self.without_captions = tuple(missing)
        if missing:
            progress(f"  {len(missing)} video(s) had no captions to read")

    ### Choosing What To Read ###

    def _video_ids(self, client, progress):
        """
        Every video this source should read, in configuration order.

        Explicit identifiers come first, then each playlist, then the
        channel's own uploads. A video named twice is read once.

        Args:
            client (YouTubeClient): the Data API client.
            progress (Callable[[str], None]): receives one line per event.

        Returns:
            tuple[str, ...]: video identifiers, in order, without
            duplicates.

        Raises:
            YouTubeSourceError: if a configured identifier is malformed,
                or a listing can be neither read nor recovered.
        """
        ordered = []
        seen = set()

        def add(video_id):
            if video_id not in seen:
                seen.add(video_id)
                ordered.append(video_id)

        for video_id in self.video_ids:
            try:
                add(checked_video_id(video_id))
            except YouTubeError as e:
                raise YouTubeSourceError(f"video_ids: {e}") from e

        listings = list(self.playlist_ids)
        if self.channel_id:
            try:
                listings.append(uploads_playlist_id(self.channel_id))
            except YouTubeError as e:
                raise YouTubeSourceError(f"channel_id: {e}") from e

        for listing_id in listings:
            for video_id in self._listing(client, listing_id, progress):
                add(video_id)
        return tuple(ordered)

    def _listing(self, client, listing_id, progress):
        """
        The videos one playlist holds, from the Data API or from the store.

        A listing is stored after every successful read, so a build that
        cannot reach the Data API -- no key on this machine, or the API
        unreachable -- still indexes the same videos it indexed last
        time. A listing that can be neither read nor recovered ends the
        build, because silently indexing nothing looks like a channel
        that went empty.

        Args:
            client (YouTubeClient): the Data API client.
            listing_id (str): the playlist identifier.
            progress (Callable[[str], None]): receives one line per event.

        Returns:
            tuple[str, ...]: the video identifiers.

        Raises:
            YouTubeSourceError: if the listing is unavailable and nothing
                is stored for it.
        """
        try:
            video_ids = client.playlist_video_ids(listing_id)
        except YouTubeError as e:
            stored = cache_module.load_listing(listing_id)
            if stored is None:
                raise YouTubeSourceError(
                    f"playlist {listing_id} could not be listed ({e}) and nothing is "
                    "stored for it. Build once on a machine that can reach the "
                    "YouTube Data API, then commit the cache folder."
                ) from e
            progress(
                f"  playlist {listing_id}: using the {len(stored)} stored video(s); "
                "the listing could not be read now"
            )
            return stored

        try:
            cache_module.save_listing(listing_id, video_ids)
        except (OSError, ValueError) as e:
            progress(f"  playlist {listing_id}: the listing could not be stored ({e})")
        return video_ids

    def _titles(self, client, video_ids, progress):
        """
        A title for each video that has no stored transcript yet.

        A stored transcript carries the title it was stored with, so
        nothing is asked about a video already in hand. The rest are
        named in one batch through the Data API when a key is set, and
        one at a time through the public endpoint when none is.

        Args:
            client (YouTubeClient): the Data API client.
            video_ids (Sequence[str]): every video to be read.
            progress (Callable[[str], None]): receives one line per event.

        Returns:
            dict[str, dict]: identifier to a record holding `title` and
            `published_at`, for the videos that needed naming.
        """
        unknown = [
            video_id for video_id in video_ids
            if cache_module.load_video(video_id) is None
        ]
        if not unknown:
            return {}
        try:
            if client.key:
                return client.video_details(unknown)
            return client.public_video_details(unknown)
        except YouTubeError as e:
            # A missing title costs a readable heading, not the build:
            # the identifier stands in, and the transcript is still
            # indexed and still cited at the right moment.
            progress(f"  video titles could not be read ({e}); using video ids instead")
            return {}

    ### Reading One Video ###

    def _video(self, client, video_id, titles, progress):
        """
        One video's title and transcript, from the store or the network.

        Args:
            client (YouTubeClient): the Data API client.
            video_id (str): the video's identifier.
            titles (Mapping): what _titles learned, keyed by identifier.
            progress (Callable[[str], None]): receives one line per event.

        Returns:
            tuple[dict | None, bool]: a record holding `title` and
            `segments`, and whether it came from the store. The record is
            None when the video has no captions this build can read,
            which is a normal thing to meet rather than a failure.

        Raises:
            YouTubeSourceError: if the transcript must be fetched and
                YouTube refuses this machine, or the library needed to
                fetch it is absent.
        """
        stored = cache_module.load_video(video_id)
        if stored is not None:
            self.stored += 1
            return {
                "title": stored.get("title") or video_id,
                "segments": stored["segments"],
            }, True

        title = (titles.get(video_id) or {}).get("title") or video_id
        published_at = (titles.get(video_id) or {}).get("published_at") or ""
        try:
            language, lines = fetch_transcript(
                video_id,
                languages=self.languages,
                reader=self.reader,
                session=client.session,
            )
        except TranscriptUnavailable as e:
            progress(f"  {title}: {e}")
            return None, False
        except YouTubeNotFound as e:
            progress(f"  {video_id}: {e}")
            return None, False
        except (YouTubeBlocked, TranscriptLibraryMissing) as e:
            raise YouTubeSourceError(
                f"{e} Nothing is stored for {video_id}, so this build cannot read it."
            ) from e
        except YouTubeError as e:
            progress(f"  {title}: {e}")
            return None, False

        self.fetched += 1
        try:
            cache_module.save_video(video_id, title, published_at, language, lines)
        except (OSError, ValueError) as e:
            progress(f"  {title}: the transcript could not be stored ({e})")
        return {"title": title, "segments": list(lines)}, False

    def _document(self, video_id, title, stretch):
        """
        One stretch of one video as an indexed document.

        The address carries the moment the stretch begins, so a citation
        opens the video where the quoted words are said rather than at
        the start. The heading carries the same moment as a clock
        reading, so a reader who sees only the heading knows where to
        look.

        Args:
            video_id (str): the video's identifier.
            title (str): the video's title.
            stretch (Mapping): one record from segments(), holding
                `start` and `text`.

        Returns:
            extractium.core.models.Document: the document to index.
        """
        return Document(
            url=watch_url(video_id, stretch["start"]),
            title=f"{title} -- {timestamp(stretch['start'])}",
            content=stretch["text"],
            source_type="youtube",
            content_type="video_transcript",
        )

    ### Reporting ###

    def _user_agent(self):
        """How this source introduces itself: the build's identity, or the default."""
        return self.settings.user_agent if self.settings else DEFAULT_USER_AGENT

    def _delay_seconds(self):
        """The pause between requests, taken from the build's crawl settings."""
        return getattr(self.settings, "delay_seconds", 0.0) or 0.0

    def summary_lines(self):
        """
        One line per video read, and a closing count of where the
        transcripts came from.

        Whether a transcript was stored or fetched is the number an
        operator actually needs: a scheduled build that fetched anything
        is a build that reached YouTube, which will stop working the
        first time it runs somewhere YouTube blocks.

        Returns:
            list[str]: the coverage report, empty when nothing was read.
        """
        if not self.coverage:
            return []
        width = max(len(title) for title, _, _ in self.coverage)
        lines = [
            f"{title:<{width}}  {count} section(s)  "
            f"{'stored' if from_store else 'fetched'}"
            for title, count, from_store in self.coverage
        ]
        lines.append(
            f"{len(self.coverage)} video(s): {self.stored} from the cache, "
            f"{self.fetched} fetched from YouTube"
        )
        if self.without_captions:
            lines.append(f"{len(self.without_captions)} video(s) had no captions to read")
        return lines

