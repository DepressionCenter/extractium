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
Last Modified: 2026-09-12
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
import time

from extractium.core import cache as cache_module
from extractium.core.fetch import DEFAULT_USER_AGENT
from extractium.core.models import Document
from extractium.sources.youtube_client import (
    CHANNEL_ID_RE,
    TranscriptLibraryMissing,
    TranscriptUnavailable,
    YouTubeBlocked,
    YouTubeClient,
    YouTubeError,
    YouTubeNotFound,
    api_key,
    fetch_transcript,
    uploads_playlist_id,
    watch_url,
)
from extractium.sources.youtube_pages import (
    YouTubePages,
    parse_channel_selector,
    parse_playlist_selector,
    parse_video_selector,
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

# Shortest pause between requests to YouTube, whatever the build's own
# delay is. YouTube is far less tolerant than a documentation site: a
# run that asked for about 145 transcripts back to back was refused
# partway through, and everything after that would have been refused
# too. A build reading a few hundred videos is doing so once and then
# working from its committed cache, so a second per video costs a few
# minutes on the first run and nothing afterwards.
MIN_DELAY_SECONDS = 1.0

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
    refuses before anything at all could be read. The message names the
    fix and quotes no credential.
    """


class _Blocked(Exception):
    """
    One caption request was refused because of where it came from.

    Caught inside fetch rather than shown to a caller: whether a block
    ends the build depends on whether anything was read before it, and
    only fetch knows that.
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
        self.include_playlists = bool(options.get("include_playlists", True))
        self.configured_delay = options.get("delay_seconds")
        self.only_channel_videos = bool(options.get("only_channel_videos", True))
        # Channel ids a video may have been published by, filled in as
        # the configured channels are resolved. Empty means no channel
        # was named, so there is nothing to compare a video against and
        # the publisher rule does not apply.
        self.allowed_channels = set()
        self.skipped_other_channels = 0
        # Videos linked from crawled pages that this source was offered:
        # how many there were, how many it read, and how many it left out
        # because no channel it names published them. Reading a linked
        # video means a linked video's words enter the knowledge base on
        # the strength of one link, so the rule is strict: the publisher
        # must be known and must be a named channel.
        self.found_offered = 0
        self.found_read = 0
        self.found_left_out = 0
        self._read_ids = set()
        # How many videos were read before YouTube began refusing this
        # machine, or 0 when it never did.
        self.blocked_after = 0
        # Built on first use, and only when there is no API key.
        self.page_reader = None
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
                User-Agent, politeness delay, and robots.txt setting. The
                last one decides how much of a listing a build with no
                API key may read; see YouTubePages.
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
        client = self._client(session, progress)
        video_ids, discovered = self._video_ids(client, progress)
        if not video_ids:
            progress("YouTube:      nothing to read")
            return
        progress(f"YouTube:      {len(video_ids)} video(s)")
        titles = self._titles(client, video_ids, progress)
        # A video the channel published is read as itself. One that
        # turned up in a playlist is read only if the same channel
        # published it, so a playlist holding somebody else's talk
        # does not put their words in this knowledge base.
        wanted = [
            video_id for video_id in video_ids
            if video_id not in discovered
            or self._published_by_an_allowed_channel(video_id, titles, client, progress)
        ]
        yield from self._read_videos(client, wanted, titles, progress)
        if self.skipped_other_channels:
            progress(
                f"  {self.skipped_other_channels} video(s) in those playlists were "
                "published by another channel and were left out"
            )

    def read_found_links(self, session, cache, progress, links):
        """
        Reads the videos linked from crawled pages that a channel this
        source names published, and nothing else.

        A site handler collects video links during a crawl; the command
        line offers them to every source that defines this method once
        every source has run. Only a video whose publisher is known and is
        one of this source's named channels is read. A source that names
        no channel reads none of them, and a video whose publisher cannot
        be determined is left out rather than guessed at, because one
        link on one page is not an operator's decision to index somebody
        else's words. The `only_channel_videos` setting does not relax
        this rule; it governs playlists, which the operator chose to read.

        Args:
            session: HTTP session to request through.
            cache (dict): the fetch cache metadata. Unused, as in fetch.
            progress (Callable[[str], None]): receives one line per event.
            links (Iterable[str]): the addresses the handlers held back.

        Yields:
            extractium.core.models.Document: one per stretch of each
            video read, addressed at the moment the stretch begins.
        """
        video_ids = []
        for link in links:
            try:
                video_id = parse_video_selector(link)
            except YouTubeError:
                continue
            if video_id not in self._read_ids and video_id not in video_ids:
                video_ids.append(video_id)
        if not video_ids:
            return
        self.found_offered = len(video_ids)
        if not self.allowed_channels:
            self.found_left_out = len(video_ids)
            progress(
                f"  {len(video_ids)} linked video(s) were left out: this youtube source "
                "names no channel, so none of them can be known to be yours"
            )
            return
        progress(f"YouTube:      {len(video_ids)} video(s) linked from crawled pages")
        client = self._client(session, progress)
        details = self._details(client, video_ids, progress)
        wanted = [
            video_id for video_id in video_ids
            if self._published_by_an_allowed_channel(video_id, details, client, progress, strict=True)
        ]
        self.found_left_out = len(video_ids) - len(wanted)
        if self.found_left_out:
            progress(
                f"  {self.found_left_out} linked video(s) were left out: not published by "
                "a channel this source names, or the publisher could not be read"
            )
        before = len(self.coverage)
        yield from self._read_videos(client, wanted, details, progress)
        self.found_read = len(self.coverage) - before

    def _client(self, session, progress):
        """The Data API client for one run, keyed from the environment when a key is set."""
        return YouTubeClient(
            session,
            key=api_key(),
            user_agent=self._user_agent(),
            progress=progress,
            delay_seconds=self._delay_seconds(),
        )

    def _read_videos(self, client, video_ids, titles, progress):
        """
        Reads each video in order and yields its stretches.

        Args:
            client (YouTubeClient): the Data API client.
            video_ids (Sequence[str]): the videos to read, already chosen.
            titles (Mapping): what is known about each, keyed by id.
            progress (Callable[[str], None]): receives one line per event.

        Yields:
            extractium.core.models.Document: one per stretch.

        Raises:
            YouTubeSourceError: if YouTube refuses this machine before a
                single video was read.
        """
        missing = []
        produced = 0
        for video_id in video_ids:
            try:
                record, from_store = self._video(client, video_id, titles, progress)
            except _Blocked as e:
                # YouTube has started refusing this machine. Every later
                # request would be refused too, so no more are made. What
                # was already read is kept: a build that indexed a
                # hundred videos and then got blocked is worth having,
                # and the report says plainly that it is incomplete.
                if not produced:
                    raise YouTubeSourceError(
                        f"{e} Nothing was read before that, so this build has no "
                        "video content at all."
                    ) from e
                self.blocked_after = produced
                progress(
                    f"  YouTube refused this machine after {produced} video(s). "
                    "Keeping those and reading no more; the rest need a machine "
                    "YouTube answers, or a stored transcript."
                )
                break
            if record is None:
                missing.append(video_id)
                continue
            stretches = segments(record["segments"])
            for stretch in stretches:
                yield self._document(video_id, record["title"], stretch)
            produced += 1
            self._read_ids.add(video_id)
            self.coverage += ((record["title"], len(stretches), from_store),)
        self.without_captions += tuple(missing)
        if missing:
            progress(f"  {len(missing)} video(s) had no captions to read")

    ### Choosing What To Read ###

    def _video_ids(self, client, progress):
        """
        Every video this source should read, in configuration order.

        Explicit identifiers come first, then each named playlist, then
        the channel: everything it published, and then the playlists it
        shows, which is where a video it did not publish can appear.

        Args:
            client (YouTubeClient): the Data API client.
            progress (Callable[[str], None]): receives one line per event.

        Returns:
            tuple[tuple[str, ...], set]: the video ids in order, and the
            subset of them that arrived by way of a playlist rather than
            from the channel's own uploads. The second set is what the
            publisher rule applies to: the channel's own uploads need no
            checking, and an operator's explicit list is their own choice.

        Raises:
            YouTubeSourceError: if a configured value is malformed, or a
                listing can be neither read nor recovered.
        """
        ordered = []
        seen = set()
        discovered = set()

        def add(video_id, from_playlist=False):
            if video_id not in seen:
                seen.add(video_id)
                ordered.append(video_id)
                if from_playlist:
                    discovered.add(video_id)

        for value in self.video_ids:
            try:
                add(parse_video_selector(value))
            except YouTubeError as e:
                raise YouTubeSourceError(f"video_ids: {e}") from e

        playlists = []
        for value in self.playlist_ids:
            try:
                playlists.append(parse_playlist_selector(value))
            except YouTubeError as e:
                raise YouTubeSourceError(f"playlist_ids: {e}") from e

        if self.channel_id:
            channel_id = self._resolve_channel(client, progress)
            self.allowed_channels.add(channel_id)
            for video_id in self._listing(client, uploads_playlist_id(channel_id), progress):
                add(video_id)
            if self.include_playlists:
                playlists.extend(self._channel_playlists(client, channel_id, progress))

        for playlist_id in playlists:
            for video_id in self._listing(client, playlist_id, progress):
                add(video_id, from_playlist=True)
        return tuple(ordered), discovered

    def _resolve_channel(self, client, progress):
        """
        The channel id for whatever the settings file named.

        An id costs nothing. A handle or an address costs one request,
        stored afterwards so later builds cost none: a channel address
        does not change, and when one does, deleting the stored file is
        how an operator says so.

        Args:
            client (YouTubeClient): the Data API client, for its session.
            progress (Callable[[str], None]): receives one line per event.

        Returns:
            str: the channel id.

        Raises:
            YouTubeSourceError: if the value is not a channel, or the
                address cannot be read.
        """
        try:
            selector = parse_channel_selector(self.channel_id)
        except YouTubeError as e:
            raise YouTubeSourceError(f"channel_id: {e}") from e
        kind, value = selector
        if kind == "id":
            return value

        stored = cache_module.load_channel_id(value)
        if stored and CHANNEL_ID_RE.match(stored):
            return stored
        try:
            channel_id = self._pages(client, progress).resolve_channel(selector)
        except YouTubeError as e:
            raise YouTubeSourceError(f"channel_id: {e}") from e
        try:
            cache_module.save_channel_id(value, channel_id)
        except (OSError, ValueError) as e:
            progress(f"  the channel id could not be stored ({e})")
        return channel_id

    def _channel_playlists(self, client, channel_id, progress):
        """
        The playlists a channel shows, so the videos they hold are read
        too.

        Queried whether or not the settings file named a playlist,
        because a channel's playlists are where it gathers the material
        it wants people to watch, and some of that may be older uploads
        it no longer lists. Videos it did not publish are held back by
        the publisher rule rather than by not looking.

        Args:
            client (YouTubeClient): the Data API client.
            channel_id (str): the channel id.
            progress (Callable[[str], None]): receives one line per event.

        Returns:
            list[str]: playlist ids, empty when they cannot be listed. A
            channel with no readable playlists is not a failed build.
        """
        try:
            if client.key:
                return list(client.channel_playlist_ids(channel_id))
            return list(self._pages(client, progress).channel_playlist_ids(channel_id))
        except YouTubeError as e:
            progress(f"  the channel's playlists could not be listed ({e})")
            return []

    def _pages(self, client, progress):
        """
        The page reader, built once per build and only when needed.

        Args:
            client (YouTubeClient): the client holding the session.
            progress (Callable[[str], None]): receives one line per event.

        Returns:
            YouTubePages: the reader.
        """
        if self.page_reader is None:
            self.page_reader = YouTubePages(
                client.session,
                user_agent=self._user_agent(),
                progress=progress,
                delay_seconds=self._delay_seconds(),
                respect_robots_txt=getattr(self.settings, "respect_robots_txt", True),
            )
        return self.page_reader

    def _listing(self, client, listing_id, progress):
        """
        The videos one playlist holds, from the Data API, from YouTube's
        pages, or from the store.

        Three ways of reading a listing, tried in order: the Data API
        when a key is set, YouTube's own pages when none is, and the
        stored copy when neither answers. A listing that can be read none
        of those ways ends the build, because silently indexing nothing
        looks like a channel that went empty.

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
            if client.key:
                video_ids = client.playlist_video_ids(listing_id)
            else:
                video_ids = self._pages(client, progress).playlist_video_ids(listing_id)
        except YouTubeError as e:
            stored = cache_module.load_listing(listing_id)
            if stored is None:
                raise YouTubeSourceError(
                    f"playlist {listing_id} could not be listed ({e}) and nothing is "
                    "stored for it. Build once on a machine that can reach YouTube, "
                    "then commit the cache folder."
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

    def _published_by_an_allowed_channel(self, video_id, titles, client, progress, strict=False):
        """
        Whether a video found through a playlist was published by one of
        the channels this build was pointed at.

        A playlist is a list of whatever its owner chose, so a channel's
        own playlists routinely hold other people's videos: a conference
        talk, a partner organization's explainer, something the owner
        simply liked. Indexing those would put another organization's
        words into this knowledge base under this organization's name.

        The publisher is already known for every video that needed
        naming, so this costs no extra request in the ordinary case: the
        Data API reports it beside the title, and the public endpoint
        reports the channel's address, which resolves the way a
        configured channel does.

        Args:
            video_id (str): the video.
            titles (Mapping): what _titles learned, keyed by video id.
            client (YouTubeClient): the Data API client.
            progress (Callable[[str], None]): receives one line per event.

            strict (bool): True for a video linked from a crawled page,
                where an unknown publisher keeps the video out and the
                `only_channel_videos` setting does not apply.

        Returns:
            bool: True when the video may be indexed. For a playlist video
            this is True also when the publisher cannot be determined at
            all: holding a video back on a failed lookup would quietly
            shrink a knowledge base, and what was held back is reported
            either way. For a linked video the unknown case is False.
        """
        if not strict and (not self.only_channel_videos or not self.allowed_channels):
            return True
        record = titles.get(video_id) or {}
        channel_id = (record.get("channel_id") or "").strip()
        if not channel_id:
            author_url = (record.get("author_url") or "").strip()
            if author_url:
                channel_id = self._channel_for_author(author_url, client, progress)
        if not channel_id:
            return not strict
        if channel_id in self.allowed_channels:
            return True
        if not strict:
            self.skipped_other_channels += 1
        return False

    def _channel_for_author(self, author_url, client, progress):
        """
        The channel id one channel address belongs to, stored so a
        playlist full of another organization's videos costs one request
        rather than one per video.

        Args:
            author_url (str): the channel address a video reported.
            client (YouTubeClient): the Data API client.
            progress (Callable[[str], None]): receives one line per event.

        Returns:
            str: the channel id, or "" when the address cannot be read.
        """
        try:
            kind, value = parse_channel_selector(author_url)
        except YouTubeError:
            return ""
        if kind == "id":
            return value
        stored = cache_module.load_channel_id(value)
        if stored and CHANNEL_ID_RE.match(stored):
            return stored
        try:
            channel_id = self._pages(client, progress).resolve_channel((kind, value))
        except YouTubeError:
            return ""
        try:
            cache_module.save_channel_id(value, channel_id)
        except (OSError, ValueError):
            pass
        return channel_id

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
        return self._details(client, unknown, progress)

    def _details(self, client, video_ids, progress):
        """
        What YouTube says about each video: its title, and its publisher
        where the interface reports one. Asked for every id given, stored
        transcript or not, because a linked video's publisher has to be
        known before it is read.

        Args:
            client (YouTubeClient): the Data API client.
            video_ids (Sequence[str]): the videos to name.
            progress (Callable[[str], None]): receives one line per event.

        Returns:
            dict[str, dict]: identifier to record, empty when nothing
            could be read.
        """
        if not video_ids:
            return {}
        try:
            if client.key:
                return client.video_details(video_ids)
            return client.public_video_details(video_ids)
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
        self._pace()
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
        except YouTubeBlocked as e:
            raise _Blocked(str(e)) from e
        except TranscriptLibraryMissing as e:
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
        """
        The pause between requests to YouTube.

        The source's own `delay_seconds` wins, then the build's, and
        MIN_DELAY_SECONDS is a floor under both: a delay that is fine for
        a website gets this source refused partway through a channel.

        Returns:
            float: seconds to wait between requests.
        """
        if self.configured_delay is not None:
            chosen = float(self.configured_delay)
        else:
            chosen = float(getattr(self.settings, "delay_seconds", 0.0) or 0.0)
        return max(chosen, MIN_DELAY_SECONDS)

    def _pace(self):
        """
        Waits before a caption request.

        The caption library is called directly rather than through this
        project's client, so it is paced here. Without this the API and
        page requests were spaced out and the transcript requests -- by
        far the most numerous -- were not, which is what got a real run
        refused partway through a channel.
        """
        delay = self._delay_seconds()
        if delay > 0:
            time.sleep(delay)

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
        if self.skipped_other_channels:
            lines.append(
                f"{self.skipped_other_channels} video(s) left out: another channel "
                "published them"
            )
        if self.found_offered:
            lines.append(
                f"{self.found_offered} video(s) linked from crawled pages: "
                f"{self.found_read} read, {self.found_left_out} left out because no "
                "channel this source names is known to have published them"
            )
        if self.blocked_after:
            lines.append(
                f"INCOMPLETE: YouTube refused this machine after {self.blocked_after} "
                "video(s). Raise delay_seconds, or build where YouTube answers, then "
                "commit the cache and build again to pick up the rest."
            )
        capped = getattr(self.page_reader, "capped_listings", ())
        if capped:
            lines.append(
                f"{len(capped)} listing(s) read only as far as robots.txt allows; set "
                "an API key, or respect_robots_txt to false, for the whole listing"
            )
        return lines

