"""
Summary: Reads YouTube's own web pages, for the two things the Data API
would otherwise be needed for: turning a channel handle or address into a
channel id, and listing what a channel or playlist holds when no API key
is set. This is the fallback path, and it reads the page a browser would
get, so it depends on YouTube's page shape and will need repair when that
shape changes; the Data API path in youtube_client.py is the stable one.

YouTube's robots.txt allows the channel and playlist pages read here and
disallows /youtubei/, which is the endpoint a page's own scrolling calls
for its next batch. So one allowed request yields the newest hundred
videos of a listing and no more. Reading past that means calling the
disallowed endpoint, which happens only when the build has set
respect_robots_txt to false -- the same deliberate switch that allows the
browser identity a challenged page is retried with. See
docs/extractium-spec.md section 5 and docs/bot-protection-transport.md.

This file is part of Extractium™
extractium/sources/youtube_pages.py

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

import re
import time
import urllib.parse

import requests

from extractium.core.fetch import (
    BLOCKED_STATUS_CODES,
    BROWSER_USER_AGENT,
    DEFAULT_USER_AGENT,
    REQUEST_TIMEOUT_SECONDS,
)
from extractium.sources.youtube_client import (
    CHANNEL_ID_RE,
    LISTING_ID_RE,
    VIDEO_ID_RE,
    YouTubeError,
    YouTubeNotFound,
    YouTubeUnavailable,
    uploads_playlist_id,
)

### Constants ###

# The only hosts this module will request from. An address arrives from
# configuration and a canonical link arrives from a page, so neither is
# trusted to say where a build's requests go.
YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"})

# The link-shortener YouTube's own share button produces, where the path
# is the video id rather than a query parameter.
SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})

# Paths that carry a video id directly instead of in a v= parameter.
VIDEO_PATH_PREFIXES = ("/shorts/", "/live/", "/embed/", "/v/")

# Where a channel's pages live, and the two tabs worth reading.
CHANNEL_URL = "https://www.youtube.com/channel/{channel_id}"
PLAYLIST_URL = "https://www.youtube.com/playlist?list={playlist_id}"
PLAYLISTS_TAB = "playlists"

# The endpoint the page's own scrolling calls for the next batch. Reached
# with a token the page handed out, never with one this project composed.
#
# YouTube's robots.txt disallows /youtubei/. This endpoint is therefore
# called only when the build has turned robots.txt off, and a build that
# has not gets the first page of a listing and a line saying so.
BROWSE_URL = "https://www.youtube.com/youtubei/v1/browse"
BROWSE_PATH_DISALLOWED_BY_ROBOTS = "/youtubei/"

# The client name the continuation endpoint expects alongside the version
# the page reports for itself.
BROWSE_CLIENT_NAME = "WEB"

# Fallback client version, used only when the page does not state one.
# The endpoint rejects a request with no version at all.
BROWSE_CLIENT_VERSION = "2.20260911.01.00"

# Largest page body this module will read. A channel page is about 1.5 MB;
# the cap keeps a redirect to something enormous from being read into
# memory in full.
MAX_PAGE_BYTES = 8 * 1024 * 1024

# Hard stops on continuation paging. A channel larger than this is far
# outside what one knowledge base should hold, and the ceilings mean a
# listing that keeps handing out tokens cannot run a build out of time.
MAX_CONTINUATIONS = 60
MAX_VIDEOS = 5_000

# A YouTube page carries continuation tokens for shelves that have
# nothing to do with the listing being read, so the presence of a token
# does not mean there is a second page of results. A listing that came
# back with fewer than this many items is treated as complete: a playlist
# page serves a hundred at a time and a channel tab thirty, so anything
# short of thirty is the whole thing. Without this, a four-video playlist
# would claim to be truncated and, with robots.txt turned off, would cost
# a pointless request to prove otherwise.
LIKELY_MORE_THRESHOLD = 30

# The canonical address a channel page states for itself, which is how a
# handle or a custom address becomes a channel id.
CANONICAL_RE = re.compile(r'<link\s+rel="canonical"\s+href="([^"]+)"', re.I)

# The same id, as the page's own data states it. Read only when the
# canonical link is absent or says nothing useful.
EXTERNAL_ID_RE = re.compile(r'"(?:externalId|channelId)":"(UC[A-Za-z0-9_-]{22})"')

# What the page hands out for its own scrolling: the endpoint's public
# parameter, the version it reports, and the next-batch tokens.
INNERTUBE_KEY_RE = re.compile(r'"INNERTUBE_API_KEY":"([A-Za-z0-9_-]+)"')
CLIENT_VERSION_RE = re.compile(r'"INNERTUBE_CONTEXT_CLIENT_VERSION":"([\d.]+)"')
CONTINUATION_RE = re.compile(r'"continuationCommand":\s*\{\s*"token":\s*"([^"]+)"')

# Identifiers as they appear in a page or a continuation answer. The
# spacing differs between the two, so both are matched.
PAGE_VIDEO_ID_RE = re.compile(r'"videoId":\s*"([A-Za-z0-9_-]{11})"')
PAGE_PLAYLIST_ID_RE = re.compile(r'"playlistId":\s*"(PL[A-Za-z0-9_-]{2,})"')

# The path shapes a channel address can take. "@handle" and a bare name
# are both custom addresses; "/channel/" carries the id itself.
CHANNEL_PATH_RE = re.compile(r"^/channel/(UC[A-Za-z0-9_-]{22})(?:/.*)?$")
HANDLE_PATH_RE = re.compile(r"^/(@[A-Za-z0-9_.-]{1,100})(?:/.*)?$")

# A handle written on its own. The name after the "@" is required: a bare
# "@" names nothing.
HANDLE_RE = re.compile(r"^@[A-Za-z0-9_.-]{1,100}$")
NAMED_PATH_RE = re.compile(r"^/(?:c|user)/([A-Za-z0-9_.-]{1,100})(?:/.*)?$")
BARE_PATH_RE = re.compile(r"^/([A-Za-z0-9_.-]{1,100})(?:/.*)?$")

# Path segments that are YouTube's own pages rather than somebody's
# channel, so a bare address naming one of them is a mistake rather than
# a custom channel name.
RESERVED_SEGMENTS = frozenset({
    "watch", "playlist", "results", "feed", "shorts", "live", "embed",
    "channel", "c", "user", "about", "account", "premium", "gaming",
    "music", "movies", "sports", "news", "learning", "hashtag", "post",
    "playables", "podcasts", "source", "t", "howyoutubeworks",
})


### Channel Selectors ###

def parse_channel_selector(value):
    """
    Reads whichever way of naming a channel an operator had in hand.

    A channel can be named five ways, and an operator has whichever one
    the browser showed them. All five are accepted, because asking
    somebody to convert a handle into an id by hand is asking them to go
    and find a tool that does it.

    | Written as | Example |
    |---|---|
    | The id itself | `UCxxxxxxxxxxxxxxxxxxxxxx` |
    | A handle | `@ExampleChannel` |
    | A handle's address | `https://www.youtube.com/@ExampleChannel` |
    | A custom address | `https://www.youtube.com/examplechannel` |
    | The id's address | `https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx` |

    A trailing `/videos`, `/playlists`, or any other tab is ignored, so
    the address copied out of the browser while looking at a channel's
    videos works as it was copied.

    Args:
        value (str): the channel as it was written in the settings file.

    Returns:
        tuple[str, str]: `("id", channel_id)` when the id is already
        known, or `("page", url)` with the channel address to resolve.
        The second form costs one request; the first costs none.

    Raises:
        YouTubeError: if the value is empty, is an address on another
            host, or names one of YouTube's own pages rather than a
            channel. The message says what was wrong with it.
    """
    text = (value or "").strip()
    if not text:
        raise YouTubeError("a channel must be named; got an empty value.")

    # Already an id, or a handle written on its own.
    if CHANNEL_ID_RE.match(text):
        return ("id", text)
    if text.startswith("@"):
        if not HANDLE_RE.match(text):
            raise YouTubeError(
                f"{value!r} is not a handle. A handle is an '@' and then the "
                "channel's name, as in @ExampleChannel."
            )
        return ("page", f"https://www.youtube.com/{text}")

    if "/" not in text and ":" not in text:
        if text.lower() in RESERVED_SEGMENTS:
            raise YouTubeError(
                f"{text!r} is one of YouTube's own pages, not a channel. Give the "
                "channel's handle, its address, or its id."
            )
        return ("page", f"https://www.youtube.com/@{text}")

    parsed = urllib.parse.urlsplit(text if "//" in text else f"https://{text}")
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        raise YouTubeError(
            f"a channel address must be on youtube.com; {value!r} is on "
            f"{host or 'no host'}."
        )

    path = parsed.path if parsed.path.startswith("/") else "/" + parsed.path
    by_id = CHANNEL_PATH_RE.match(path)
    if by_id:
        return ("id", by_id.group(1))
    handle = HANDLE_PATH_RE.match(path)
    if handle:
        return ("page", f"https://www.youtube.com/{handle.group(1)}")
    named = NAMED_PATH_RE.match(path)
    if named:
        return ("page", f"https://www.youtube.com/@{named.group(1)}")
    bare = BARE_PATH_RE.match(path)
    if bare:
        if bare.group(1).lower() in RESERVED_SEGMENTS:
            raise YouTubeError(
                f"{value!r} is one of YouTube's own pages, not a channel. Open the "
                "channel and copy its address from there."
            )
        return ("page", f"https://www.youtube.com/@{bare.group(1)}")
    raise YouTubeError(
        f"{value!r} does not look like a channel. Give the channel's handle "
        "(@ExampleChannel), its address, or its id (UC and 22 more characters)."
    )


def parse_playlist_selector(value):
    """
    Reads a playlist written as an id or as the address holding one.

    Args:
        value (str): the playlist as it was written in the settings file.

    Returns:
        str: the playlist id.

    Raises:
        YouTubeError: if no playlist id can be read out of the value.
    """
    text = (value or "").strip()
    if not text:
        raise YouTubeError("a playlist must be named; got an empty value.")
    if LISTING_ID_RE.match(text) and "/" not in text and ":" not in text:
        return text

    parsed = urllib.parse.urlsplit(text if "//" in text else f"https://{text}")
    host = (parsed.hostname or "").lower()
    if host and host not in YOUTUBE_HOSTS:
        raise YouTubeError(
            f"a playlist address must be on youtube.com; {value!r} is on {host}."
        )
    listed = urllib.parse.parse_qs(parsed.query).get("list") or []
    if listed and LISTING_ID_RE.match(listed[0]):
        return listed[0]
    raise YouTubeError(
        f"{value!r} does not name a playlist. Give the playlist id, or the address "
        "holding it, which has list= in it."
    )


def parse_video_selector(value):
    """
    Reads a video written as an id or as any address that names one.

    Args:
        value (str): the video as it was written, or as it was linked.

    Returns:
        str: the video id.

    Raises:
        YouTubeError: if no video id can be read out of the value.
    """
    text = (value or "").strip()
    if not text:
        raise YouTubeError("a video must be named; got an empty value.")
    if VIDEO_ID_RE.match(text):
        return text

    parsed = urllib.parse.urlsplit(text if "//" in text else f"https://{text}")
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if host in SHORT_HOSTS:
        candidate = path.lstrip("/").split("/")[0]
        if VIDEO_ID_RE.match(candidate):
            return candidate
    elif host in YOUTUBE_HOSTS:
        watched = urllib.parse.parse_qs(parsed.query).get("v") or []
        if watched and VIDEO_ID_RE.match(watched[0]):
            return watched[0]
        for prefix in VIDEO_PATH_PREFIXES:
            if path.startswith(prefix):
                candidate = path[len(prefix):].split("/")[0]
                if VIDEO_ID_RE.match(candidate):
                    return candidate
    raise YouTubeError(
        f"{value!r} does not name a video. Give the eleven-character id, or a watch "
        "address, which has v= in it."
    )


def video_id_in(url):
    """
    The video one address names, or None when it names no video.

    The same reading as parse_video_selector, for a link found in crawled
    content rather than written in a settings file: there, an address
    that is not a video is an ordinary link and not a mistake.

    Args:
        url (str): a link.

    Returns:
        str | None: the video id, or None.
    """
    try:
        return parse_video_selector(url)
    except YouTubeError:
        return None


### Page Reader ###

class YouTubePages:
    """
    Reads YouTube's web pages when the Data API is not available.

    Two jobs: turn a channel handle or address into a channel id, and
    list what a channel or a playlist holds. Both are things the Data API
    does better; this class exists so a build with no API key still
    works, which is the common case for somebody indexing their own
    organization's videos for the first time.

    This reads a page meant for a browser and calls the same endpoint
    that page's own scrolling calls, with a token the page handed out. It
    therefore depends on YouTube's page shape, and will need repair when
    that shape changes. Every failure says so, so a broken build points
    at the cause rather than at the configuration.

    Args:
        session: the HTTP session to request through (requests.Session or
            a test double with the same get() and post() signatures).
        user_agent (str): how the build introduces itself. Truthful.
        progress (Callable[[str], None] | None): receives one line per
            event worth reporting.
        delay_seconds (float): pause before each request after the first.
        respect_robots_txt (bool): the build's own setting. True, the
            default, keeps this reader to the pages YouTube's robots.txt
            allows, which means the newest hundred videos of a listing.
            False lets it page past that through the disallowed
            continuation endpoint, and lets a challenged page be retried
            with the browser identity, exactly as a crawl does.

    Attributes:
        request_count (int): how many requests this reader has made.
        capped_listings (tuple): one entry per listing that stopped at
            its first page because robots.txt is being respected, so the
            build can say once what it did not read.
    """

    def __init__(self, session, user_agent=DEFAULT_USER_AGENT,
                 progress=None, delay_seconds=0.0, respect_robots_txt=True):
        self.session = session
        self.user_agent = user_agent
        self.progress = progress
        self.delay_seconds = float(delay_seconds or 0.0)
        self.respect_robots_txt = bool(respect_robots_txt)
        self.request_count = 0
        self.capped_listings = ()
        # The reason a listing stopped short is the same every time, and a
        # channel has dozens of playlists. It is explained once and then
        # counted, so the explanation does not bury the rest of the build.
        self._explained_the_cap = False

    ### Requests ###

    def _report(self, line):
        """Sends one line to the progress callback, when there is one."""
        if self.progress is not None:
            self.progress(line)

    def _pace(self):
        """Waits the configured delay before every request but the first."""
        if self.request_count and self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

    def _headers(self):
        """
        The headers one request sends.

        The language is asked for explicitly, because the page's wording
        changes with it and a build should not read a different page on a
        different machine. No credential travels here or anywhere else.
        """
        return {
            "User-Agent": self.user_agent,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        }

    def _checked_url(self, url):
        """
        Returns url when it is a YouTube page address.

        Raises:
            YouTubeError: if it is anywhere else. Addresses reach this
                class from configuration and from a page's own links, so
                neither is trusted to redirect a build's requests off the
                host it meant to read.
        """
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if host not in YOUTUBE_HOSTS:
            raise YouTubeError(f"refusing to request {host or 'an address with no host'}.")
        return url

    def _get_page(self, url):
        """
        Reads one YouTube page as text.

        Args:
            url (str): the page address, on a YouTube host.

        Returns:
            str: the page body, cut at MAX_PAGE_BYTES.

        Raises:
            YouTubeError: if the address is not on a YouTube host.
            YouTubeNotFound: if YouTube has nothing there.
            YouTubeUnavailable: if the host could not be reached or
                answered an error.
        """
        self._checked_url(url)
        response = self._request(url, self.user_agent)

        # A filter that refuses anything not shaped like a browser gives
        # one of these whatever the page itself allows. One retry with the
        # browser identity, and only when the operator has turned
        # robots.txt off for this build, which is the same rule the crawl
        # follows for a challenged page.
        if (response.status_code in BLOCKED_STATUS_CODES
                and not self.respect_robots_txt):
            self._report(
                f"  {response.status_code} for {self.user_agent!r}; "
                "retrying once as a browser"
            )
            response = self._request(url, BROWSER_USER_AGENT)

        if response.status_code == 404:
            raise YouTubeNotFound(f"YouTube has nothing at {url}.")
        if response.status_code in BLOCKED_STATUS_CODES:
            raise YouTubeUnavailable(
                f"YouTube answered {response.status_code} for {url}. It refused this "
                "machine rather than saying the page is missing. Set an API key, or "
                "set respect_robots_txt to false to allow one retry as a browser."
            )
        if response.status_code >= 400:
            raise YouTubeUnavailable(f"YouTube answered {response.status_code} for {url}.")
        return (response.text or "")[:MAX_PAGE_BYTES]

    def _request(self, url, user_agent):
        """
        One GET, with the given identity.

        Args:
            url (str): the page address, already checked.
            user_agent (str): the identity to send.

        Returns:
            The response.

        Raises:
            YouTubeUnavailable: if the host could not be reached.
        """
        self._pace()
        headers = dict(self._headers())
        headers["User-Agent"] = user_agent
        try:
            response = self.session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            raise YouTubeUnavailable(
                f"YouTube could not be reached at {url} ({type(e).__name__})."
            ) from e
        self.request_count += 1
        return response

    def _continue(self, token, api_parameter, client_version):
        """
        Asks for the next batch of a listing.

        Args:
            token (str): the continuation token the previous answer gave.
                Never composed here; only handed back.
            api_parameter (str): the public parameter the page states for
                its own requests to this endpoint.
            client_version (str): the version the page reports.

        Returns:
            str: the answer as text, cut at MAX_PAGE_BYTES, or "" when
            the request failed. A batch that cannot be read ends the
            paging with what was gathered so far rather than losing the
            whole listing.
        """
        self._pace()
        request = continuation_payload(token, api_parameter, client_version)
        try:
            response = self.session.post(
                request["url"],
                params=request["params"],
                json=request["json"],
                headers={"User-Agent": self.user_agent, "Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            self._report(f"  a further batch could not be read ({type(e).__name__})")
            return ""
        self.request_count += 1
        if response.status_code >= 400:
            self._report(f"  a further batch was answered {response.status_code}")
            return ""
        return (response.text or "")[:MAX_PAGE_BYTES]

    ### Resolving A Channel ###

    def resolve_channel(self, selector):
        """
        Turns a channel selector into a channel id.

        An `("id", ...)` selector is returned as it is and costs no
        request. A `("page", url)` selector costs one: the channel page
        states its own canonical address, and the id is in it.

        Args:
            selector (tuple[str, str]): from parse_channel_selector.

        Returns:
            str: the channel id.

        Raises:
            YouTubeError: if the selector is malformed, or the page names
                no channel id. A handle that does not exist answers a
                page about nothing, so the message says the handle may be
                wrong rather than blaming the page.
            YouTubeNotFound, YouTubeUnavailable: as _get_page raises them.
        """
        kind, value = selector
        if kind == "id":
            return value
        if kind != "page":
            raise YouTubeError(f"a channel selector must be an id or a page; got {kind!r}.")

        html = self._get_page(value)
        for candidate in self._canonical_ids(html):
            if CHANNEL_ID_RE.match(candidate):
                self._report(f"  {value} is channel {candidate}")
                return candidate
        raise YouTubeError(
            f"{value} names no channel id. Check the handle or address: YouTube "
            "answers a page even for a channel that does not exist."
        )

    @staticmethod
    def _canonical_ids(html):
        """
        Channel ids the page states for itself, best first.

        The canonical link is the page's own statement of where it lives
        and is preferred. The id in the page's data is read only as a
        fallback, because a channel page mentions other channels too and
        the first such mention is not necessarily this one.
        """
        found = []
        for href in CANONICAL_RE.findall(html):
            path = urllib.parse.urlsplit(href).path
            match = CHANNEL_PATH_RE.match(path if path.startswith("/") else "/" + path)
            if match:
                found.append(match.group(1))
        found.extend(EXTERNAL_ID_RE.findall(html))
        return found

    ### Listing Without A Key ###

    def channel_video_ids(self, channel_id):
        """
        Every video a channel has published, newest first.

        Read from the channel's uploads playlist rather than its videos
        tab, for two reasons. The playlist page lists a hundred videos in
        one request where the tab lists thirty, and the playlist holds
        everything the channel published, including its shorts and its
        past live streams, where the tab holds only what it calls
        videos. A channel with no shorts and no streams also answers
        those tabs with its home page, whose shelves can carry other
        people's videos, and nothing good comes of reading those as
        though the channel had published them.

        Args:
            channel_id (str): the channel id.

        Returns:
            tuple[str, ...]: video ids, newest first, without duplicates.
            Capped at the first page when robots.txt is being respected;
            see the class docstring.

        Raises:
            YouTubeError: if channel_id is not a channel id.
            YouTubeNotFound, YouTubeUnavailable: as _get_page raises them.
        """
        if not CHANNEL_ID_RE.match(channel_id or ""):
            raise YouTubeError(f"a channel id must be 'UC' and 22 characters; got {channel_id!r}.")
        return self.playlist_video_ids(uploads_playlist_id(channel_id))

    def channel_playlist_ids(self, channel_id):
        """
        Every playlist a channel shows on its playlists tab.

        Args:
            channel_id (str): the channel id.

        Returns:
            tuple[str, ...]: playlist ids, in the order shown.

        Raises:
            YouTubeError: if channel_id is not a channel id.
            YouTubeNotFound, YouTubeUnavailable: as _get_page raises them.
        """
        if not CHANNEL_ID_RE.match(channel_id or ""):
            raise YouTubeError(f"a channel id must be 'UC' and 22 characters; got {channel_id!r}.")
        url = f"{CHANNEL_URL.format(channel_id=channel_id)}/{PLAYLISTS_TAB}"
        return self._paged(url, PAGE_PLAYLIST_ID_RE, LISTING_ID_RE, "playlist")

    def playlist_video_ids(self, playlist_id):
        """
        Every video one playlist holds, in playlist order.

        Args:
            playlist_id (str): the playlist id.

        Returns:
            tuple[str, ...]: video ids, in order, without duplicates.

        Raises:
            YouTubeError: if playlist_id is not a playlist id.
            YouTubeNotFound, YouTubeUnavailable: as _get_page raises them.
        """
        if not LISTING_ID_RE.match(playlist_id or ""):
            raise YouTubeError(f"a playlist id must be 2 to 64 plain characters; got {playlist_id!r}.")
        url = PLAYLIST_URL.format(playlist_id=urllib.parse.quote(playlist_id, safe=""))
        return self._paged(url, PAGE_VIDEO_ID_RE, VIDEO_ID_RE, "video")

    def _paged(self, url, found_re, valid_re, noun):
        """
        Reads one listing page and every batch it leads to.

        Paging stops when a batch hands out no new token, adds nothing
        new, or a ceiling is reached. Stopping on "added nothing new"
        matters: a token that keeps answering the same batch would
        otherwise page until the request ceiling.

        Args:
            url (str): the first page.
            found_re (re.Pattern): what an identifier looks like in a
                page or a continuation answer.
            valid_re (re.Pattern): the shape an identifier must have to
                be used. Applied because these arrive in a response.
            noun (str): "video" or "playlist", for the progress line.

        Returns:
            tuple[str, ...]: the identifiers, in order, without duplicates.
        """
        html = self._get_page(url)
        api_parameter = _first(INNERTUBE_KEY_RE, html)
        client_version = _first(CLIENT_VERSION_RE, html) or BROWSE_CLIENT_VERSION
        found = _ordered_unique(found_re.findall(html), valid_re)
        token = _first(CONTINUATION_RE, html)

        # A token on the page does not mean a second page of this
        # listing; see LIKELY_MORE_THRESHOLD.
        if len(found) < LIKELY_MORE_THRESHOLD:
            token = None

        # Reading further means calling an endpoint YouTube's robots.txt
        # disallows, so a build that respects it stops here and says what
        # it did not read rather than quietly returning a partial list as
        # though it were the whole one.
        if self.respect_robots_txt:
            if token:
                self.capped_listings += ((url, len(found)),)
                if self._explained_the_cap:
                    self._report(f"  {len(found)} {noun}(s) listed, again the first page only")
                else:
                    self._explained_the_cap = True
                    self._report(
                        f"  {len(found)} {noun}(s) listed, which is the first page. Reading "
                        f"the rest means {BROWSE_PATH_DISALLOWED_BY_ROBOTS}, which YouTube's "
                        "robots.txt disallows. Set an API key for the whole listing, or set "
                        "respect_robots_txt to false. Later listings will say only that they "
                        "stopped at their first page."
                    )
            else:
                self._report(f"  {len(found)} {noun}(s) listed from YouTube's pages")
            return tuple(found)

        batches = 0
        while token and api_parameter and len(found) < MAX_VIDEOS and batches < MAX_CONTINUATIONS:
            text = self._continue(token, api_parameter, client_version)
            batches += 1
            if not text:
                break
            before = len(found)
            for identifier in _ordered_unique(found_re.findall(text), valid_re):
                if identifier not in found:
                    found.append(identifier)
            if len(found) == before:
                break
            token = _first(CONTINUATION_RE, text)

        if len(found) >= MAX_VIDEOS:
            self._report(f"  stopping at {MAX_VIDEOS} {noun}(s), which is this build's ceiling")
        self._report(f"  {len(found)} {noun}(s) listed from YouTube's pages")
        return tuple(found)


### Reading What A Page Says ###

def _first(pattern, text):
    """The first match of pattern in text, or None."""
    found = pattern.search(text)
    return found.group(1) if found else None


def _ordered_unique(values, valid_re):
    """
    The values that have the right shape, in first-appearance order.

    Every identifier here came out of a response, and every one of them
    reaches a request or a cache file name, so anything of another shape
    is dropped rather than used.
    """
    kept = []
    seen = set()
    for value in values:
        if value in seen or not valid_re.match(value):
            continue
        seen.add(value)
        kept.append(value)
    return kept


def video_ids_in(text):
    """
    Every video id mentioned in a block of text, in first-appearance
    order.

    Used to read a continuation answer, and by the tests to check what a
    page yielded. JSON is not parsed for this: the shape around these
    identifiers changes often, and a regular expression over the whole
    answer survives that where a path through the structure does not.

    Args:
        text (str): a page body or a continuation answer.

    Returns:
        tuple[str, ...]: the video ids.
    """
    return tuple(_ordered_unique(PAGE_VIDEO_ID_RE.findall(text), VIDEO_ID_RE))


def continuation_payload(token, api_parameter, client_version=BROWSE_CLIENT_VERSION):
    """
    The request body one continuation asks with.

    Exposed so a test can check the shape without a network call.

    Args:
        token (str): the token the previous answer handed out.
        api_parameter (str): the public parameter the page states.
        client_version (str): the version the page reports.

    Returns:
        dict: the JSON body, and the query parameters beside it.
    """
    return {
        "url": BROWSE_URL,
        "params": {"key": api_parameter},
        "json": {
            "context": {"client": {
                "clientName": BROWSE_CLIENT_NAME,
                "clientVersion": client_version,
            }},
            "continuation": token,
        },
    }
