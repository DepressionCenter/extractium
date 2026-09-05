"""
Summary: HTTP fetching with local conditional-GET caching (If-None-Match /
If-Modified-Since against .kb_cache/), the crawler's etiquette (a truthful
User-Agent and a per-origin robots.txt policy), and the URL scope and
normalization helpers that decide what a crawl fetches. Host-specific URL
rules live in the site handlers under extractium.sources; the one
exception is noted at derive_auto_prefix.

This file is part of Extractium™
extractium/core/fetch.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-04
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
__date__ = "2026-09-04"

import hashlib
import os
import re
import time
import urllib.robotparser
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from extractium import __version__

# cache is imported and referenced by qualified attribute access
# (cache.CACHE_PAGES_DIR, cache.save_cache_meta(...), etc.) everywhere in
# this file, never via `from extractium.core.cache import X`. A value
# import would bind a stale local copy at import time; tests isolate the
# cache by monkeypatching attributes on the real extractium.core.cache
# module object, and only a qualified lookup observes that patch.
from extractium.core import cache

### Constants ###

# The crawler names itself and its repository. A tool distributed to
# other organizations does not pretend to be a browser. Operators change
# it through the user_agent setting.
DEFAULT_USER_AGENT = f"Extractium/{__version__} (+https://github.com/DepressionCenter/extractium)"

# Sent with every page request, alongside the User-Agent.
ACCEPT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# robots.txt is plain text. At least one portal (TeamDynamix) answers 406
# when a request for it accepts only HTML, so the robots request carries
# its own Accept header.
ROBOTS_ACCEPT_HEADERS = {"Accept": "text/plain, */*;q=0.5"}

# Seconds to wait for any single response before giving up on the URL.
REQUEST_TIMEOUT_SECONDS = 15

# BINARY_EXTENSIONS / SOURCE_EXTENSIONS feed ASSET_RE and
# ASSET_EXCLUDE_PATTERNS below, so the crawl-scope check (applied to every
# URL regardless of include/exclude configuration) and an operator's
# human-readable exclude patterns can't drift out of sync with each other.
#
# SOURCE_EXTENSIONS covers a repo's source/config files: GitHub's file
# viewer renders these (like any other non-Markdown blob) as an empty
# client-hydrated shell with no scrapeable content, and they aren't
# documentation anyway -- see extractium.sources.github for how
# Markdown/text files are handled instead.
BINARY_EXTENSIONS = [
    "pdf", "zip", "gz", "exe", "rar", "7z", "tar", "bin", "dmg", "iso", "apk",
    "png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "tiff", "tif", "ico", "avif", "heic",
    "mp4", "mp3", "wav", "ogg", "m4a", "flac", "webm", "mov", "avi", "wmv", "mkv",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "woff", "woff2", "ttf", "eot", "otf",
]
SOURCE_EXTENSIONS = [
    "py", "js", "ts", "jsx", "tsx", "java", "go", "rb", "php", "c", "cpp", "h", "hpp",
    "cs", "swift", "kt", "rs", "sh", "ps1", "sql", "yml", "yaml", "lock", "toml", "ini", "cfg",
]

ASSET_RE = re.compile(
    r"\.(" + "|".join(BINARY_EXTENSIONS + SOURCE_EXTENSIONS + ["ico", "css", "js", "xml", "json"]) + r")(\?|$)",
    re.I,
)

# The host-independent part of the default exclude lists: files whose
# bytes are not indexable text. Site handlers add their own host-specific
# patterns while enabled. Order within an exclude list carries no meaning:
# a URL is excluded when any one pattern matches it.
ASSET_EXCLUDE_PATTERNS = tuple(rf"\.{ext}$" for ext in BINARY_EXTENSIONS + SOURCE_EXTENSIONS)


### URL Scope And Normalization ###

def derive_auto_prefix(seed_url):
    """
    Derives the default crawl-scope prefix from a seed URL when no
    explicit include pattern is configured.

    The TeamDynamix rule below is the one host-specific rule left in core:
    the site-handler protocol has no scope hook, and adding one would
    change the protocol every handler implements. TODO: move this rule to
    the tdx handler if the protocol ever gains a scope method.

    Args:
        seed_url (str): the crawl's starting URL.

    Returns:
        str: for a TeamDynamix URL, the origin plus its
        /TDClient/<digits>/<slug>/ prefix; for anything else, just the
        origin (scheme://host).
    """
    parsed = urlparse(seed_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    m = re.search(r"(/TDClient/\d+/[^/]+/)", seed_url)
    if m:
        return origin + m.group(1)
    return origin


def compile_patterns(patterns):
    """
    Compiles a list of regex pattern strings (matched case-insensitively
    against full URLs) into compiled Pattern objects.

    Args:
        patterns (list[str]): regex strings, or plain substrings (which
            work unmodified as trivial regexes).

    Returns:
        list[re.Pattern]: compiled, case-insensitive patterns.
    """
    compiled = []
    for p in patterns:
        compiled.append(re.compile(p, re.IGNORECASE))
    return compiled


def get_origin(url):
    """Returns just the scheme://host portion of a URL, dropping path and query."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def normalise(url):
    """Strips the fragment and any trailing slash from a URL, for dedup comparisons."""
    return url.split("#")[0].strip().rstrip("/")


def in_scope(url, auto_prefix, origin, include_res, crawl_exclude_res):
    """
    Decides whether a discovered link should be crawled.

    Args:
        url (str): the candidate URL.
        auto_prefix (str): the default scope prefix from derive_auto_prefix,
            used only when include_res is empty.
        origin (str): the seed URL's origin (scheme://host).
        include_res (list[re.Pattern]): explicit include patterns; if
            non-empty, a URL must match at least one, and same-origin URLs
            no longer fall back to being allowed automatically.
        crawl_exclude_res (list[re.Pattern]): patterns to exclude, checked
            after the include check so an exclude always wins over a
            matching include.

    Returns:
        bool: True if url should be queued for crawling.
    """
    # Default rule: keep the crawl within the seed origin unless an explicit
    # include pattern opts into a different host (e.g. GitHub/GitLab repo pages).
    if not url.startswith(origin):
        if not include_res or not any(r.search(url) for r in include_res):
            return False

    # Skip binary assets
    if ASSET_RE.search(url):
        return False

    # Include check
    if include_res:
        if not any(r.search(url) for r in include_res):
            return False
    else:
        # Auto default: must start with derived prefix
        if not url.startswith(auto_prefix):
            return False

    # Crawl exclude check (after include, so excludes win)
    if any(r.search(url) for r in crawl_exclude_res):
        return False

    return True


### Request Headers And Progress ###

def request_headers(user_agent=DEFAULT_USER_AGENT, extra=None):
    """
    Builds the headers one page request sends: the User-Agent, the Accept
    headers, and any conditional-GET validators.

    Args:
        user_agent (str): the User-Agent value to identify the crawler by.
        extra (dict | None): headers merged on top, such as If-None-Match.

    Returns:
        dict: header name -> value.
    """
    headers = {"User-Agent": user_agent, **ACCEPT_HEADERS}
    if extra:
        headers.update(extra)
    return headers


def _report(progress, line):
    """Sends one progress line to the callback, or nowhere when the caller gave none."""
    if progress is not None:
        progress(line)


### Robots Policy ###

class RobotsPolicy:
    """
    Answers "may this crawler fetch this URL?" from each origin's
    robots.txt, fetched once per origin through the caller's session.

    The policy follows the robots exclusion standard (RFC 9309) for
    unavailable files: a 4xx answer means the site publishes no rules and
    everything is allowed, while a 5xx answer or a network failure means
    the rules are unknown and every URL on that origin is refused. Failing
    closed is deliberate: a crawler that cannot read a site's rules must
    not guess that it is welcome.

    Args:
        session: HTTP session to request robots.txt through (a
            requests.Session or a test double with the same get()).
        user_agent (str): the User-Agent sent with the request and matched
            against the file's User-agent lines.
        enabled (bool): False allows every URL without any request, for a
            site the operator owns.
        progress (Callable[[str], None] | None): receives one line when a
            robots.txt cannot be read.
    """

    def __init__(self, session, user_agent=DEFAULT_USER_AGENT, enabled=True, progress=None):
        self.session = session
        self.user_agent = user_agent
        self.enabled = enabled
        self.progress = progress
        # origin -> RobotFileParser; each origin's file is fetched once
        # per crawl, however many of its pages are visited.
        self._parsers = {}

    def allows(self, url):
        """
        True when the crawler may fetch url.

        Args:
            url (str): the URL that is about to be requested.

        Returns:
            bool: False when the origin's robots.txt disallows the URL for
            this User-Agent, or when the file could not be read at all.
        """
        if not self.enabled:
            return True
        origin = get_origin(url)
        parser = self._parsers.get(origin)
        if parser is None:
            parser = self._load(origin)
            self._parsers[origin] = parser
        return parser.can_fetch(self.user_agent, url)

    def _load(self, origin):
        """Fetches and parses one origin's robots.txt, falling back per the rules in the class docstring."""
        parser = urllib.robotparser.RobotFileParser()
        robots_url = f"{origin}/robots.txt"
        headers = {"User-Agent": self.user_agent, **ROBOTS_ACCEPT_HEADERS}
        try:
            r = self.session.get(robots_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            status = r.status_code
        except Exception as e:
            _report(self.progress, f"  robots.txt unreadable for {origin} ({e}); skipping that site")
            parser.disallow_all = True
            return parser
        if 400 <= status < 500:
            parser.allow_all = True
        elif status >= 500:
            _report(self.progress, f"  robots.txt unavailable for {origin} (HTTP {status}); skipping that site")
            parser.disallow_all = True
        else:
            parser.parse(r.text.splitlines())
        return parser


### Fetch ###

def _flush_cache_meta_periodically(session, cache_meta):
    """
    Saves cache_meta to disk every cache.CACHE_SAVE_INTERVAL successful
    fetches. Called once per fetch() call that mutates cache_meta (a fresh
    200, or a 304 cache hit's fetched_at bump).

    Args:
        session: the HTTP session in use; a per-session counter is stashed
            on it as an attribute so the interval is tracked per crawl run.
        cache_meta (dict): the in-memory cache metadata to flush.
    """
    count = getattr(session, "_kb_fetch_save_counter", 0) + 1
    session._kb_fetch_save_counter = count
    if count % cache.CACHE_SAVE_INTERVAL == 0:
        cache.save_cache_meta(cache_meta)


def _store_fetched_page(r, url, session, cache_meta, expect_html):
    """
    Validates content-type, writes the cache file, and records fresh cache
    metadata (etag/last_modified/fetched_at/sha256) for a 200 response.
    sha256 is unused today -- reserved for a future delta-build feature.

    Args:
        r (requests.Response): the successful (200) response.
        url (str): the fetched URL.
        session: the HTTP session, forwarded to _flush_cache_meta_periodically.
        cache_meta (dict): mutated in place with this URL's fresh metadata.
        expect_html (bool): True to require text/html and return parsed
            BeautifulSoup; False to require text/plain and return raw text.

    Returns:
        BeautifulSoup | str | None: parsed document, raw text, or None if
        content-type doesn't match expect_html (nothing usable at this URL).
    """
    content_type = r.headers.get("content-type", "")
    if expect_html and "text/html" not in content_type:
        return None
    if not expect_html and "text/plain" not in content_type:
        return None
    os.makedirs(cache.CACHE_PAGES_DIR, exist_ok=True)
    with open(cache.cache_page_path(url), "w", encoding="utf-8") as f:
        f.write(r.text)
    cache_meta[url] = {
        "etag": r.headers.get("ETag"),
        "last_modified": r.headers.get("Last-Modified"),
        "fetched_at": time.time(),
        "sha256": hashlib.sha256(r.text.encode("utf-8")).hexdigest(),
    }
    _flush_cache_meta_periodically(session, cache_meta)
    return BeautifulSoup(r.text, "html.parser") if expect_html else r.text


def fetch(session, url, cache_meta, expect_html=True, user_agent=DEFAULT_USER_AGENT, progress=None):
    """
    Fetches one URL through the local page cache. If a cache entry exists,
    sends a single conditional GET with If-None-Match / If-Modified-Since
    built from the previously stored ETag/Last-Modified (sent verbatim --
    never normalized, including any W/ weak-validator prefix). A 304 serves
    the cached file from disk; a 200 overwrites the cache entry and file.

    No HEAD request is issued: many servers (TDX included) omit
    ETag/Last-Modified on HEAD responses even though they send them on GET,
    and GitHub's raw CDN can return a different ETag representation on HEAD
    vs GET -- HEAD-based revalidation both under- and over-invalidates.

    Args:
        session (requests.Session): the HTTP session to fetch through.
        url (str): the URL to fetch.
        cache_meta (dict): the in-memory cache metadata, read for
            conditional headers and mutated with fresh validators.
        expect_html (bool): True (default) requires a text/html response
            and returns a parsed BeautifulSoup document. False requires
            text/plain (e.g. a raw.githubusercontent.com file) and returns
            the decoded text as-is, with no HTML parsing.
        user_agent (str): the User-Agent header value to send.
        progress (Callable[[str], None] | None): receives one line for a
            cache hit or a skipped URL; None reports nothing.

    Returns:
        BeautifulSoup | str | None: the fetched content, or None if the
        request failed, raised an HTTP error, or the response's
        content-type didn't match expect_html. Failures are reported
        through progress and never raise -- callers treat None as "skip
        this URL."
    """
    entry = cache_meta.get(url)
    conditional_headers = {}
    if entry:
        if entry.get("etag"):
            conditional_headers["If-None-Match"] = entry["etag"]
        if entry.get("last_modified"):
            conditional_headers["If-Modified-Since"] = entry["last_modified"]

    try:
        r = session.get(
            url,
            headers=request_headers(user_agent, conditional_headers),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        if conditional_headers and r.status_code == 304:
            try:
                with open(cache.cache_page_path(url), "r", encoding="utf-8") as f:
                    cached_text = f.read()
            except OSError:
                # Cache file missing/unreadable -- retry once as a plain GET.
                r = session.get(url, headers=request_headers(user_agent), timeout=REQUEST_TIMEOUT_SECONDS)
                r.raise_for_status()
                return _store_fetched_page(r, url, session, cache_meta, expect_html)
            entry["fetched_at"] = time.time()
            _flush_cache_meta_periodically(session, cache_meta)
            _report(progress, "       (cached, not modified)")
            return BeautifulSoup(cached_text, "html.parser") if expect_html else cached_text

        r.raise_for_status()
        return _store_fetched_page(r, url, session, cache_meta, expect_html)
    except Exception as e:
        _report(progress, f"  SKIP {url} -- {e}")
        return None
