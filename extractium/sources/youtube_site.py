"""
Summary: The YouTube site handler. Its one job is to recognise a YouTube
address given as a crawl seed -- a channel, a playlist, or one video --
and hand the crawl over to the youtube source, which reads captions
rather than pages. A YouTube page holds almost no readable text, so
crawling one produces a document worth nothing; every YouTube address
this handler sees is therefore kept out of the crawl. See
docs/extractium-spec.md sections 2 and 5.

This file is part of Extractium™
extractium/sources/youtube_site.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-11
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
__date__ = "2026-09-11"

import urllib.parse

from extractium.sources.youtube_client import YouTubeError
from extractium.sources.youtube_pages import (
    SHORT_HOSTS,
    YOUTUBE_HOSTS,
    parse_channel_selector,
    parse_playlist_selector,
    parse_video_selector,
)

### Constants ###

# Every host this handler answers for.
VIDEO_HOSTS = frozenset(YOUTUBE_HOSTS | SHORT_HOSTS)

# The source a YouTube seed is read through, and the content type its
# documents carry. Named here so the offer and the source agree.
VIDEO_SOURCE = "youtube"
VIDEO_CONTENT_TYPE = "video_transcript"


### Handler ###

class YouTubeHandler:
    """
    Recognises a YouTube address and keeps the crawl away from it.

    A YouTube page is a shell around a player: the words are in the
    caption track, which no crawler reads, so a crawled YouTube page
    yields a document with a title and almost nothing else. This handler
    therefore refuses every YouTube address for crawling, and offers the
    `youtube` source instead when one is given as a seed.

    A seed may be a channel, in any of the forms a browser shows, a
    playlist, or a single video. Each becomes the matching option on the
    source, so pointing a build at `youtube.com/@ExampleChannel` reads
    that channel's captions and pointing it at one watch address reads
    that one video.

    Attributes:
        skipped (int): how many YouTube addresses were kept out of the
            crawl, so a build can say once that it saw them and why they
            were not read as pages.
        found_videos (dict): the videos those addresses named, in the
            order found, keyed by video id. A `youtube` source in the
            same build reads the ones a channel it names published.
    """

    name = "youtube"

    # What a document from a YouTube address is, in the vocabulary every
    # parent record uses.
    source_type = "youtube"

    # Nothing to add to the crawl's own exclusions: this handler refuses
    # every address it recognises outright, which no pattern can express
    # more clearly than `allows` does.
    default_crawl_exclude_patterns = ()
    default_index_exclude_patterns = ()

    def __init__(self):
        self.skipped = 0
        self.found_videos = {}
        self._observed = set()

    def observe_link(self, url):
        """
        Notes a YouTube address the crawl discovered, wherever it led.

        The crawl discards an address on another host before asking any
        handler whether to follow it, so this is the only place a video
        linked from an ordinary page is seen. A link naming a video is
        kept for the `youtube` source to consider; a link to a channel or
        a playlist is counted and not kept, because following either
        would pull a whole listing into a build on the strength of one
        link.

        Args:
            url (str): a link the crawl found on a page.
        """
        if not self.matches(url) or url in self._observed:
            return
        self._observed.add(url)
        self.skipped += 1
        video_id = _read(parse_video_selector, url)
        if video_id:
            self.found_videos.setdefault(video_id, watch_url(video_id))

    def found_links(self):
        """
        The video addresses found on crawled pages, in the order found,
        for a source that reads videos to consider.

        Returns:
            tuple[str, ...]: one watch address per distinct video.
        """
        return tuple(self.found_videos.values())

    ### Recognition ###

    def matches(self, url):
        """True for any address on a YouTube host."""
        return _host_of(url) in VIDEO_HOSTS

    def allows(self, url):
        """
        Whether the crawl may follow an address.

        False for every YouTube address. The page holds no content worth
        indexing, and what is worth indexing on it is reached through the
        `youtube` source instead. An address on any other host is not
        this handler's business and is always allowed.

        Args:
            url (str): a URL the crawl is considering.

        Returns:
            bool: True unless the address is on a YouTube host.

        Side effects:
            Counts each address held back, so the build reports once what
            it saw rather than once per link.
        """
        if not self.matches(url):
            return True
        if url not in self._observed:
            self.skipped += 1
        return False

    def offer_source(self, seed_url):
        """
        Offers the youtube source for a crawl seeded at a YouTube
        address.

        The offer is for the seed only, which is the same rule the GitHub
        handler follows: one stray link to a video, found halfway through
        crawling an unrelated site, should not pull a whole channel into
        a small build.

        A channel address becomes `channel_id`, a playlist becomes one
        entry in `playlist_ids`, and a single video becomes one entry in
        `video_ids`. The three are read in that order, because a watch
        address inside a playlist names both and the video is the more
        specific request.

        Args:
            seed_url (str): the URL the crawl would start from.

        Returns:
            tuple[str, dict] | None: the source name and its options, or
            None when the seed is not a YouTube address this handler can
            turn into a request.
        """
        if not self.matches(seed_url):
            return None

        video_id = _read(parse_video_selector, seed_url)
        if video_id:
            return (VIDEO_SOURCE, {"video_ids": (video_id,)})

        playlist_id = _read(parse_playlist_selector, seed_url)
        if playlist_id:
            return (VIDEO_SOURCE, {"playlist_ids": (playlist_id,)})

        channel = _read(parse_channel_selector, seed_url)
        if channel:
            return (VIDEO_SOURCE, {"channel_id": seed_url})
        return None

    def skipped_page_report(self):
        """
        One line saying how many YouTube addresses were kept out of the
        crawl.

        Returns:
            str: the report, or an empty string when none were seen. An
            operator who wanted those videos indexed can see that the
            links were found, and add a `youtube` source to read them.
        """
        if not self.skipped:
            return ""
        return (
            f"{self.skipped} YouTube link(s) were not crawled: a video's words are in "
            f"its captions, not its page. {len(self.found_videos)} of them name a video; "
            "a youtube source naming your channel reads the ones that channel published."
        )

    ### Page Reading ###

    def fetch_url(self, url):
        """The address is requested as it stands; nothing here rewrites one."""
        return url

    def expects_html(self, url):
        """True: a YouTube address answers a web page, whatever else is true of it."""
        return True

    def extract(self, soup, url):
        """
        Nothing. A YouTube page holds no content this project indexes.

        Reached only if an operator turned this handler off for crawling
        and something else let the address through. Returning nothing is
        the honest answer: the words are in the caption track.

        Args:
            soup: the parsed page.
            url (str): where it came from.

        Returns:
            tuple[str, None, tuple]: an empty title, no content node, and
            no categories.
        """
        return ("", None, ())

    def content_type(self, url):
        """What a document from a YouTube address is, for the one source that makes them."""
        return VIDEO_CONTENT_TYPE


### Reading An Address ###

def watch_url(video_id):
    """The plain watch address of one video."""
    return f"https://www.youtube.com/watch?v={video_id}"


def _host_of(url):
    """The lowercase host of an address, or "" when it has none."""
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _read(read_one, value):
    """
    What a selector reader makes of a value, or None when it makes
    nothing of it.

    Here an address that is not a channel, a playlist, or a video is an
    ordinary answer rather than a mistake: the three are tried in turn
    and the first that succeeds decides.
    """
    try:
        return read_one(value)
    except YouTubeError:
        return None
