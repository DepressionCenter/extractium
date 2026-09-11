"""
Summary: Reads YouTube on behalf of the youtube source: lists a channel
or playlist through the YouTube Data API v3 with a key taken from the
environment, and fetches one video's caption track through
youtube-transcript-api. Listing and captions come from different places
for a reason -- the Data API answers a hosted runner, the caption
endpoint refuses one -- so the two are separate calls a caller can use
independently. See docs/extractium-spec.md section 5.

This file is part of Extractium™
extractium/sources/youtube_client.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-11
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
__date__ = "2026-09-11"

import os
import re
import time

import requests

from extractium.core.fetch import DEFAULT_USER_AGENT, REQUEST_TIMEOUT_SECONDS

### Constants ###

# Where the Data API lives. Listing a channel or a playlist is the only
# thing it is used for; captions do not come from here.
DATA_API_URL = "https://www.googleapis.com/youtube/v3"

# The environment variable the API key is read from. A key is a
# credential, so it never appears in config.yaml, which is committed to a
# data repository alongside the output it produced.
API_KEY_ENV = "YOUTUBE_API_KEY"

# Largest page of playlist items the Data API serves, so a fifty-video
# playlist costs one request rather than three.
PAGE_SIZE = 50

# Largest number of video identifiers one videos.list request accepts.
DETAILS_BATCH = 50

# The oEmbed endpoint, which names a public video without a key. It is
# how a build with explicit video_ids and no API key still gets real
# titles instead of bare identifiers. It reports no publication date,
# which is why a video read this way has none.
OEMBED_URL = "https://www.youtube.com/oembed"

# Hard stops on paging and on how many videos one listing may contribute.
# A channel larger than this is far outside what one knowledge base
# should hold, and the ceilings mean a listing that never ends cannot run
# a build out of time or memory.
MAX_PAGES = 100
MAX_VIDEOS = 5_000

# Where a reader opens a video, and the parameter that opens it at a
# moment. YouTube accepts the offset in whole seconds with a trailing
# "s", which is the form its own share links use.
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
WATCH_URL_AT = "https://www.youtube.com/watch?v={video_id}&t={seconds}s"

# A video identifier is eleven characters from the base64url alphabet. A
# playlist or channel identifier is a longer run of the same. Both are
# matched rather than trusted: they arrive from configuration or from an
# API response, and both end up in a request and in a cache file name.
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
LISTING_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,64}$")

# A channel identifier YouTube assigns starts with "UC" and runs 24
# characters. The uploads playlist of that channel is the same string
# with "UU" in place of "UC", which is a documented property of the
# service and saves a request per channel.
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
CHANNEL_TO_UPLOADS_PREFIX = ("UC", "UU")


### Errors ###

class YouTubeError(Exception):
    """
    Base class for every failure this client reports. The message names
    what was asked for and is safe to show a user: no API key, no cookie,
    and no header is ever quoted in it.
    """


class YouTubeUnavailable(YouTubeError):
    """Raised when YouTube could not be reached, or answered an error."""


class YouTubeNotFound(YouTubeError):
    """Raised when YouTube has no channel, playlist, or video at an identifier."""


class YouTubeNoApiKey(YouTubeError):
    """
    Raised when a channel or playlist must be listed and no API key is
    set. Explicit video identifiers need no key, so this is not a
    condition every build meets.
    """


class YouTubeBlocked(YouTubeError):
    """
    Raised when YouTube refused the request because of where it came
    from. This is the expected answer on a hosted runner: YouTube blocks
    cloud-provider address ranges, which is why transcripts are fetched
    on an operator's machine and committed to the data repository.
    """


class TranscriptUnavailable(YouTubeError):
    """
    Raised when a video has no caption track this build can read: none at
    all, none in the languages asked for, or captions turned off by the
    person who published it. A video without captions is a normal thing
    to meet, not a broken build.
    """


class TranscriptLibraryMissing(YouTubeError):
    """
    Raised when a transcript has to be fetched and youtube-transcript-api
    is not installed. Reading stored transcripts needs no library, so a
    build that works from a committed cache never raises this.
    """


class _NeverRaised(Exception):
    """
    Stands in for one of the caption library's exception classes when the
    library is absent, so the handlers below stay valid `except` clauses
    that simply never match. Nothing raises it.
    """


### Identifier Checks ###

def checked_video_id(value):
    """
    Returns value when it is a YouTube video identifier.

    Args:
        value (str): the candidate, from configuration or a response.

    Returns:
        str: the identifier, unchanged.

    Raises:
        YouTubeError: if it is not one. Checked because the identifier
            reaches both a request URL and a cache file name.
    """
    if isinstance(value, str) and VIDEO_ID_RE.match(value):
        return value
    raise YouTubeError(
        f"a video id must be eleven characters of letters, digits, hyphen, or "
        f"underscore, as in the v= part of a watch link; got {value!r}."
    )


def checked_listing_id(value):
    """
    Returns value when it is a YouTube playlist or channel identifier.

    Args:
        value (str): the candidate.

    Returns:
        str: the identifier, unchanged.

    Raises:
        YouTubeError: if it is not one.
    """
    if isinstance(value, str) and LISTING_ID_RE.match(value):
        return value
    raise YouTubeError(
        f"a playlist or channel id must be 2 to 64 characters of letters, digits, "
        f"hyphen, or underscore; got {value!r}."
    )


def uploads_playlist_id(channel_id):
    """
    The identifier of the playlist holding everything one channel has
    published.

    Every channel has such a playlist, and its identifier is the
    channel's own with "UU" in place of the leading "UC". Deriving it
    saves a request, and a channel identifier in any other shape is
    refused rather than guessed at.

    Args:
        channel_id (str): a channel identifier, "UC" and 22 characters.

    Returns:
        str: the uploads playlist identifier.

    Raises:
        YouTubeError: if channel_id is not a channel identifier.
    """
    if not isinstance(channel_id, str) or not CHANNEL_ID_RE.match(channel_id):
        raise YouTubeError(
            f"a channel id must start with 'UC' and run 24 characters, as in "
            f"UCxxxxxxxxxxxxxxxxxxxxxx; got {channel_id!r}. A channel's @handle "
            "or custom address is not a channel id; open the channel and copy the "
            "id from its page source or from the address of any of its videos."
        )
    old, new = CHANNEL_TO_UPLOADS_PREFIX
    return new + channel_id[len(old):]


def watch_url(video_id, seconds=None):
    """
    Where a reader opens one video, optionally at a moment in it.

    Args:
        video_id (str): the video's identifier.
        seconds (int | float | None): how far into the video to open it.
            None, or zero, gives the plain address.

    Returns:
        str: a youtube.com watch address.

    Raises:
        YouTubeError: if video_id is not a video identifier.
    """
    checked_video_id(video_id)
    if not seconds:
        return WATCH_URL.format(video_id=video_id)
    return WATCH_URL_AT.format(video_id=video_id, seconds=int(seconds))


def api_key(environ=None):
    """
    The Data API key, or None when none is set.

    Args:
        environ (Mapping | None): the environment to read; the process
            environment by default.

    Returns:
        str | None: the key, stripped, or None when the variable is
        absent or blank.
    """
    value = (environ if environ is not None else os.environ).get(API_KEY_ENV)
    value = (value or "").strip()
    return value or None


### Client ###

class YouTubeClient:
    """
    Lists a channel or playlist through the YouTube Data API v3.

    The session and the progress callback come from the caller, so a
    library user, a test, and a person at a terminal each control them.
    The client never constructs a session and never prints.

    The API key is a credential. It travels as a query parameter because
    that is the only form the Data API accepts, and it is therefore kept
    out of every message this class raises or reports: a key in a log is
    a key that leaked.

    Args:
        session: the HTTP session to request through (requests.Session or
            a test double with the same get() signature).
        key (str | None): the Data API key. None means listing is
            unavailable and only explicit video identifiers can be read.
        user_agent (str): how the build introduces itself.
        progress (Callable[[str], None] | None): receives one line per
            event worth reporting.
        delay_seconds (float): pause before each request after the first.

    Attributes:
        request_count (int): how many requests this client has made.
    """

    def __init__(self, session, key=None, user_agent=DEFAULT_USER_AGENT,
                 progress=None, delay_seconds=0.0):
        self.session = session
        self.key = key
        self.user_agent = user_agent
        self.progress = progress
        self.delay_seconds = float(delay_seconds or 0.0)
        self.request_count = 0

    ### Requests ###

    def _report(self, line):
        """Sends one line to the progress callback, when there is one."""
        if self.progress is not None:
            self.progress(line)

    def _pace(self):
        """Waits the configured delay before every request but the first."""
        if self.request_count and self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

    def _get(self, resource, params):
        """
        Makes one Data API request and classifies the answer.

        Args:
            resource (str): the API resource, such as "playlistItems".
            params (Mapping): query parameters, without the key.

        Returns:
            dict: the decoded document.

        Raises:
            YouTubeNoApiKey: if no key is set.
            YouTubeNotFound: if YouTube has nothing at that identifier.
            YouTubeUnavailable: if the host could not be reached, the
                answer was an error, or the body was not a JSON object.
        """
        if not self.key:
            raise YouTubeNoApiKey(
                f"listing a channel or playlist needs a YouTube Data API key in "
                f"{API_KEY_ENV}. Explicit video_ids need no key."
            )
        url = f"{DATA_API_URL}/{resource}"
        self._pace()
        try:
            response = self.session.get(
                url,
                headers={"Accept": "application/json", "User-Agent": self.user_agent},
                params={**dict(params), "key": self.key},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            # The key is a query parameter, so the request URL is never
            # quoted here: a requests exception carries the full URL.
            raise YouTubeUnavailable(
                f"the YouTube Data API could not be reached for {resource} ({type(e).__name__})."
            ) from e

        self.request_count += 1
        status = response.status_code
        if status == 404:
            raise YouTubeNotFound(f"the YouTube Data API has no {resource} at that id.")
        if status in (401, 403):
            raise YouTubeUnavailable(
                f"the YouTube Data API refused the request for {resource} ({status}). "
                f"Check that the key in {API_KEY_ENV} is current and that the "
                "YouTube Data API v3 is enabled for its project."
            )
        if status >= 400:
            raise YouTubeUnavailable(f"the YouTube Data API answered {status} for {resource}.")
        try:
            document = response.json()
        except ValueError as e:
            raise YouTubeUnavailable(
                f"the YouTube Data API answered something other than data for {resource}."
            ) from e
        if not isinstance(document, dict):
            raise YouTubeUnavailable(
                f"the YouTube Data API answered a {type(document).__name__} rather than "
                f"a record for {resource}."
            )
        return document

    ### Listing ###

    def playlist_video_ids(self, playlist_id):
        """
        Every video identifier one playlist holds, in playlist order.

        Args:
            playlist_id (str): the playlist identifier. A channel's
                uploads playlist works here; see uploads_playlist_id.

        Returns:
            tuple[str, ...]: the video identifiers, in order, without
            duplicates.

        Raises:
            YouTubeError: if playlist_id is not an identifier.
            YouTubeNoApiKey, YouTubeNotFound, YouTubeUnavailable: as
                _get raises them.
        """
        checked_listing_id(playlist_id)
        video_ids = []
        seen = set()
        page_token = None
        for _ in range(MAX_PAGES):
            params = {
                "part": "contentDetails",
                "playlistId": playlist_id,
                "maxResults": PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            document = self._get("playlistItems", params)
            for item in document.get("items") or ():
                if not isinstance(item, dict):
                    continue
                details = item.get("contentDetails")
                if not isinstance(details, dict):
                    continue
                video_id = details.get("videoId")
                # A deleted or private entry keeps its place in a
                # playlist but names no readable video, so it is skipped
                # rather than treated as a broken response.
                if not isinstance(video_id, str) or not VIDEO_ID_RE.match(video_id):
                    continue
                if video_id in seen:
                    continue
                seen.add(video_id)
                video_ids.append(video_id)
                if len(video_ids) >= MAX_VIDEOS:
                    self._report(
                        f"playlist {playlist_id}: stopping at {MAX_VIDEOS} videos, "
                        "which is this build's ceiling."
                    )
                    return tuple(video_ids)
            page_token = document.get("nextPageToken")
            if not page_token:
                break
        return tuple(video_ids)

    def video_details(self, video_ids):
        """
        The title and publication stamp of each video named.

        Args:
            video_ids (Sequence[str]): video identifiers.

        Returns:
            dict[str, dict]: identifier to a record holding `title` and
            `published_at`. A video YouTube would not describe -- deleted,
            private, or never existing -- is absent from the result
            rather than reported as an error, because one unreadable
            video should not end a build over a channel.

        Raises:
            YouTubeError: if an identifier is not a video identifier.
            YouTubeNoApiKey, YouTubeUnavailable: as _get raises them.
        """
        wanted = [checked_video_id(video_id) for video_id in video_ids]
        details = {}
        for start in range(0, len(wanted), DETAILS_BATCH):
            batch = wanted[start:start + DETAILS_BATCH]
            document = self._get("videos", {"part": "snippet", "id": ",".join(batch)})
            for item in document.get("items") or ():
                if not isinstance(item, dict):
                    continue
                video_id = item.get("id")
                snippet = item.get("snippet")
                if not isinstance(video_id, str) or not isinstance(snippet, dict):
                    continue
                if not VIDEO_ID_RE.match(video_id):
                    continue
                details[video_id] = {
                    "title": str(snippet.get("title") or "").strip(),
                    "published_at": str(snippet.get("publishedAt") or "").strip(),
                }
        return details

    def public_video_details(self, video_ids):
        """
        The title of each video named, read without an API key.

        The oEmbed endpoint describes any public video to anybody, one
        request per video. It is slower per video than videos.list and
        reports no publication date, so it is the fallback for a build
        that has video identifiers but no key, not the normal path.

        Args:
            video_ids (Sequence[str]): video identifiers.

        Returns:
            dict[str, dict]: identifier to a record holding `title` and
            an empty `published_at`. A video the endpoint will not
            describe -- private, deleted, or embedding disabled -- is
            absent rather than reported as an error.

        Raises:
            YouTubeError: if an identifier is not a video identifier.
        """
        details = {}
        for video_id in video_ids:
            checked_video_id(video_id)
            self._pace()
            try:
                response = self.session.get(
                    OEMBED_URL,
                    headers={"Accept": "application/json", "User-Agent": self.user_agent},
                    params={"url": watch_url(video_id), "format": "json"},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as e:
                raise YouTubeUnavailable(
                    f"YouTube could not be reached to name video {video_id} "
                    f"({type(e).__name__})."
                ) from e
            self.request_count += 1
            if response.status_code >= 400:
                continue
            try:
                document = response.json()
            except ValueError:
                continue
            if not isinstance(document, dict):
                continue
            title = str(document.get("title") or "").strip()
            if title:
                details[video_id] = {"title": title, "published_at": ""}
        return details


### Transcripts ###

def transcript_reader(session=None):
    """
    A youtube-transcript-api reader, built only when one is needed.

    The import is deferred because reading stored transcripts needs no
    library at all. A build on a hosted runner works entirely from the
    committed cache, and should not have to install a package it will
    never call.

    Args:
        session: the HTTP session the reader should request through, so a
            build's timeouts and proxy settings apply to captions too.
            None lets the library make its own.

    Returns:
        youtube_transcript_api.YouTubeTranscriptApi: the reader.

    Raises:
        TranscriptLibraryMissing: if the package is not installed.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as e:
        raise TranscriptLibraryMissing(
            "fetching captions needs youtube-transcript-api, which is not "
            "installed. Install it with: pip install \"extractium[youtube]\". A "
            "build that reads only stored transcripts does not need it."
        ) from e
    return YouTubeTranscriptApi(http_client=session) if session is not None else YouTubeTranscriptApi()


def fetch_transcript(video_id, languages=("en",), reader=None, session=None):
    """
    One video's caption track, as timed lines.

    Args:
        video_id (str): the video's identifier.
        languages (Sequence[str]): language codes in descending
            preference. The first track that exists is used.
        reader: a reader with a `fetch(video_id, languages=...)` method.
            None builds one through transcript_reader.
        session: the HTTP session to pass to transcript_reader when it
            builds the reader.

    Returns:
        tuple[str, tuple[dict, ...]]: the language code of the track that
        answered, and its lines, each holding `text` and `start` in
        seconds from the beginning of the video.

    Raises:
        YouTubeError: if video_id is not a video identifier.
        YouTubeBlocked: if YouTube refused the request because of where
            it came from, which is what a hosted runner gets.
        TranscriptUnavailable: if the video has no readable caption track.
        TranscriptLibraryMissing: if the library is needed and absent.
        YouTubeUnavailable: for any other failure reaching YouTube.
    """
    checked_video_id(video_id)
    if reader is None:
        reader = transcript_reader(session)
    # Imported here rather than at module scope for the reason
    # transcript_reader gives: a build that only reads stored
    # transcripts must work with the package absent.
    try:
        from youtube_transcript_api import (
            CouldNotRetrieveTranscript,
            NoTranscriptFound,
            RequestBlocked,
            TranscriptsDisabled,
            VideoUnavailable,
        )
    except ImportError:
        # Only reachable when the caller brought its own reader: without
        # one, transcript_reader has already refused. The handlers below
        # keep their shape and match nothing.
        CouldNotRetrieveTranscript = NoTranscriptFound = _NeverRaised
        RequestBlocked = TranscriptsDisabled = VideoUnavailable = _NeverRaised

    try:
        fetched = reader.fetch(video_id, languages=tuple(languages))
    except RequestBlocked as e:
        raise YouTubeBlocked(
            f"YouTube refused a caption request for {video_id} because of where it "
            "came from. It blocks cloud-provider address ranges, so fetch "
            "transcripts on your own machine and commit the cache."
        ) from e
    except (TranscriptsDisabled, NoTranscriptFound) as e:
        raise TranscriptUnavailable(
            f"video {video_id} has no caption track in "
            f"{', '.join(languages) or 'any language asked for'}."
        ) from e
    except VideoUnavailable as e:
        raise YouTubeNotFound(f"YouTube has no readable video at {video_id}.") from e
    except CouldNotRetrieveTranscript as e:
        raise YouTubeUnavailable(
            f"the caption track for {video_id} could not be read ({type(e).__name__})."
        ) from e
    except requests.RequestException as e:
        raise YouTubeUnavailable(
            f"YouTube could not be reached for the captions of {video_id} "
            f"({type(e).__name__})."
        ) from e

    return transcript_lines(fetched)


def transcript_lines(fetched):
    """
    The language code and timed lines of a fetched caption track.

    Reads the library's own result object and also the plain list of
    dicts an older release returned, so a caller is not tied to one
    version of the package.

    Args:
        fetched: a FetchedTranscript, or a sequence of mappings each
            holding `text` and `start`.

    Returns:
        tuple[str, tuple[dict, ...]]: the language code, blank when the
        result does not carry one, and the lines in time order.
    """
    language = str(getattr(fetched, "language_code", "") or "")
    if hasattr(fetched, "snippets"):
        raw = [
            {"text": snippet.text, "start": float(snippet.start)}
            for snippet in fetched.snippets
        ]
    else:
        raw = [
            {"text": str(line["text"]), "start": float(line["start"])}
            for line in fetched
            if isinstance(line, dict) and "text" in line and "start" in line
        ]
    raw.sort(key=lambda line: line["start"])
    return language, tuple(raw)
