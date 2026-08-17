"""
Summary: HTTP fetching with local conditional-GET caching (If-None-Match /
If-Modified-Since against .kb_cache/), plus the URL scope, normalization,
and Git-host classification helpers that decide what a crawl fetches and
how far it follows discovered links.

This file is part of Extractium™
extractium/core/fetch.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-08-17
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

import hashlib
import os
import re
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# cache is imported and referenced by qualified attribute access
# (cache.CACHE_PAGES_DIR, cache.save_cache_meta(...), etc.) everywhere in
# this file, never via `from extractium.core.cache import X`. A value
# import would bind a stale local copy at import time; tests isolate the
# cache by monkeypatching attributes on the real extractium.core.cache
# module object, and only a qualified lookup observes that patch.
from extractium.core import cache

### Constants ###

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# BINARY_EXTENSIONS / SOURCE_EXTENSIONS feed ASSET_RE below, so the
# crawl-scope check (applied to every URL regardless of include/exclude
# configuration) and an operator's human-readable exclude patterns can't
# drift out of sync with each other.
#
# SOURCE_EXTENSIONS covers a repo's source/config files: GitHub's file
# viewer renders these (like any other non-Markdown blob) as an empty
# client-hydrated shell with no scrapeable content, and they aren't
# documentation anyway -- see is_git_blob_text_url/extract_content in
# extractium.core.chunk for how Markdown/text files are handled instead.
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
GIT_HOST_RE = re.compile(
    r"^(?:github\.com|gitlab\.com|git\.[^.]+\.(?:com|edu|org|io)|(?:[^.]+\.)?github\.io)$",
    re.I,
)
GIT_TEXT_FILE_RE = re.compile(r"/blob/[^/]+/.+\.(md|markdown|txt)$", re.I)


### URL Scope And Normalization ###

def derive_auto_prefix(seed_url):
    """
    Derives the default crawl-scope prefix from a seed URL when no
    explicit include pattern is configured.

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


def is_git_host_url(url):
    """True if url's host is GitHub, GitLab, a generic self-hosted git host, or GitHub Pages."""
    host = urlparse(url).netloc.lower()
    return bool(GIT_HOST_RE.match(host))


def is_git_blob_text_url(url):
    """
    True for a GitHub blob URL pointing at a Markdown or plain-text file,
    at any path depth, e.g. .../blob/main/docs/setup.md. GitHub's blob
    viewer is a client-hydrated app -- the file body exists only as JSON
    inside the page's embedded data payload, not as scrapeable HTML -- so
    these are fetched from raw.githubusercontent.com instead of parsed out
    of the blob page. Wiki pages and /releases/tag pages are still classic
    server-rendered HTML and don't need this path.
    """
    return is_git_host_url(url) and bool(GIT_TEXT_FILE_RE.search(urlparse(url).path))


def to_git_raw_url(blob_url):
    """
    Rewrites a github.com blob URL to its raw.githubusercontent.com
    equivalent: /<owner>/<repo>/blob/<branch>/<path> ->
    /<owner>/<repo>/<branch>/<path>. Only meaningful for URLs already
    matched by is_git_blob_text_url.
    """
    path = re.sub(r"^/([^/]+)/([^/]+)/blob/", r"/\1/\2/", urlparse(blob_url).path)
    return f"https://raw.githubusercontent.com{path}"


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


def fetch(session, url, cache_meta, expect_html=True):
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

    Returns:
        BeautifulSoup | str | None: the fetched content, or None if the
        request failed, raised an HTTP error, or the response's
        content-type didn't match expect_html. Failures are logged to
        stdout and never raise -- callers treat None as "skip this URL."
    """
    entry = cache_meta.get(url)
    conditional_headers = {}
    if entry:
        if entry.get("etag"):
            conditional_headers["If-None-Match"] = entry["etag"]
        if entry.get("last_modified"):
            conditional_headers["If-Modified-Since"] = entry["last_modified"]

    try:
        r = session.get(url, headers={**HEADERS, **conditional_headers}, timeout=15)

        if conditional_headers and r.status_code == 304:
            try:
                with open(cache.cache_page_path(url), "r", encoding="utf-8") as f:
                    cached_text = f.read()
            except OSError:
                # Cache file missing/unreadable -- retry once as a plain GET.
                r = session.get(url, headers=HEADERS, timeout=15)
                r.raise_for_status()
                return _store_fetched_page(r, url, session, cache_meta, expect_html)
            entry["fetched_at"] = time.time()
            _flush_cache_meta_periodically(session, cache_meta)
            print("       (cached, not modified)")
            return BeautifulSoup(cached_text, "html.parser") if expect_html else cached_text

        r.raise_for_status()
        return _store_fetched_page(r, url, session, cache_meta, expect_html)
    except Exception as e:
        print(f"  SKIP {url} -- {e}")
        return None
