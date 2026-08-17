#!/usr/bin/env python
"""
Summary: Crawls a website (or TDX KB portal) and produces a Field Station AI-compatible RAG index.json.

This file is part of Field Station AI
build-kb-index.py

Author(s): Gabriel Mongefranco.
Created: 2026-07-20
Notes: See README file for documentation and full license information.

Usage (edit USER CONFIG below, then just run):
    python build-kb-index.py

Or with CLI overrides:
    python build-kb-index.py --url "https://..." --out index.json --max-pages 500 --delay 0.5
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
__date__ = "2026-07-20"

# ---------------------------------------------------------------------------
# Vendoring note (added when this file was copied into Extractium):
# Frozen snapshot of the upstream script, vendored verbatim for
# characterization testing only -- not a maintained module, never imported
# by the real extractium package, never edited to add features or fix bugs.
# Upstream: https://github.com/DepressionCenter/FieldStationAI/blob/main/build-kb-index.py
# Commit:   3bd74f8646db19bb038c340b8bd4bfc93c528be0 (2026-08-17)
# ---------------------------------------------------------------------------

# ===========================================================================
# USER CONFIG -- edit these; CLI args override at runtime
# ===========================================================================

# Seed URL to start crawling from
SEED_URL = "https://teamdynamix.umich.edu/TDClient/210/DepressionCenter/Home/"

# Output file path
OUT_PATH = "index.json"

# Max pages to crawl (safety ceiling)
MAX_PAGES = 10000

# Polite delay between requests in seconds (0 = no delay)
DELAY = 0.5

# ---------------------------------------------------------------------------
# INCLUDE_PATTERNS -- only crawl URLs matching at least one of these.
#
# Each entry is a regex string matched against the full URL (case-insensitive).
#
# Leave as [] for automatic defaults:
#   - TDX URLs (containing /TDClient/<digits>/<slug>/):
#       auto-restricts to that exact /TDClient/<digits>/<slug>/ prefix
#   - All other URLs:
#       auto-restricts to the same origin (scheme + host)
#
# Examples:
#   [r"/TDClient/210/DepressionCenter/"]   # explicit TDX prefix
#   [r"https://example\.com/docs/"]        # non-TDX subfolder
#   [r"/KB/", r"/Articles/"]              # multiple allowed subtrees
# ---------------------------------------------------------------------------
INCLUDE_PATTERNS = [
    r"/TDClient/210/DepressionCenter/", # Depression Center Knowledge Base
    r"depressioncenter\.org/research-services/", # Depression Center public site - research resources
    r"depressioncenter\.org/outreach-education/", # Depression Center public site - outreach and education program and depression toolkit
    r"code\.depressioncenter\.org", # Depression Center code repository hub
    r"github\.com/depressioncenter/[A-Za-z0-9_.-]+(?:/|$)", # Depression Center GitHub org
    r"github\.com/DepressionCenter/[A-Za-z0-9_.-]+(?:/|$)" # Depression Center GitHub org (case-sensitive)

    #r"github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/|$)", # GitHub repo landing page and subpaths
    #r"gitlab\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/|$)", # GitLab repo landing page and subpaths
    # r"git\.[A-Za-z0-9_.-]+\.(?:com|edu|org|io)/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/|$)", # Generic git host repo landing page and subpaths
    # r"(?:[A-Za-z0-9_.-]+\.)?github\.io(?:/|$)", # GitHub Pages site root and subpaths

]

# ---------------------------------------------------------------------------
# BINARY_EXTENSIONS / SOURCE_EXTENSIONS -- shared with ASSET_RE further
# below, so the crawl-scope check (ASSET_RE, applied to every URL
# regardless of include/exclude lists) and the human-readable exclude
# lists below can't drift out of sync with each other.
#
# SOURCE_EXTENSIONS covers a repo's source/config files: GitHub's file
# viewer renders these (like any other non-Markdown blob) as an empty
# client-hydrated shell with no scrapeable content, and they aren't
# documentation anyway -- see is_git_blob_text_url/extract_content for how
# Markdown/text files are handled instead.
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# CRAWL_EXCLUDE_PATTERNS -- do not follow links matching any of these.
#
# Each entry is a regex string matched against the full URL (case-insensitive).
# Evaluated after the include check.
#
# The defaults below skip search, login, tag, and similar non-content pages.
# Add more as needed.
# ---------------------------------------------------------------------------
CRAWL_EXCLUDE_PATTERNS = [
    r"/Search[/?$]",
        r"/Login[/?$]",
        r"/Login\.aspx",
        r"/Tags[/?$]",
        r"/Print[/?$]",
        r"/PrintArticle\?ID=",
        r"\?print=",
        r"/Archive[/?$]",
        r"/FileOpen[/?$]",
        r"/FileDownload[/?$]",
        r"/pulse$",
        r"/tags$",
        r"/tagged$",
        # r"/CategoryID=",
        # r"/CategoryID/[0-9]+",
        r"/TagID=",
        r"/TagID/[0-9]+",
        # r"/Category/",
        r"&tab=",
        r"/issues?[/?]",
        r"/projects?[/?]",
        r"/pulls?[/?]",
        r"/pushes?[/?]",
        r"/forks?[/?]",
        r"/network[/?]",
        r"/commits?[/?]",
        r"/discussions?[/?]",
        r"/categories[/?]",
        r"/announcements?[/?]",
        r"/settings[/?]",
        r"/contribs?[/?]",
        r"/contributions?[/?]",
        r"/checks?[/?]",
        r"/comments?[/?]",
        r"/author[/?]",
        r"/profile[/?]",
        r"/watchers[/?]",
        r"/stargazers[/?]",
        r"/stars[/?]",
        r"/graphs[/?]",        # contributors, commit-activity, code-frequency, punch-card, traffic
        r"/actions[/?]",       # CI workflow runs
        r"/security[/?]",      # security advisories -- not KB content; /releases stays indexable
        r"/compare[/?]",
        r"/blame/",
        r"/raw/",              # Markdown/text file content is fetched directly from
                                # raw.githubusercontent.com instead (see is_git_blob_text_url /
                                # to_git_raw_url), so this only prevents redundantly re-crawling
                                # the github.com redirect URL if a page happens to link to it.
        r"/find/",
        r"/deployments[/?]",
        r"/environments[/?]",
        r"/packages[/?]",
        r"/sponsors[/?]",
        r"/people[/?]",
        r"/followers[/?]",
        r"/following[/?]",
        # GitHub wiki housekeeping actions (edit form, revision history, new-page draft,
        # access settings) -- not real content.
        r"/_edit$",
        r"/_history$",
        r"/_new$",
        r"/_access$",
] + [rf"\.{ext}$" for ext in BINARY_EXTENSIONS + SOURCE_EXTENSIONS]

# ---------------------------------------------------------------------------
# INDEX_EXCLUDE_PATTERNS -- allow the page to be reached/crawled, but do not
# add its content to the generated index.
# ---------------------------------------------------------------------------
INDEX_EXCLUDE_PATTERNS = [
    r"/Search[/?$]",
    r"/Login[/?$]",
    r"/Login\.aspx",
    r"/Tags[/?$]",
    r"/Print[/?$]",
    r"/PrintArticle\?ID=",
    r"\?print=",
    r"/Archive[/?$]",
    r"/FileOpen[/?$]",
    r"/FileDownload[/?$]",
    r"/pulse$",
    r"/tags$",
    r"/tagged$",
    r"/CategoryID=",
    r"/CategoryID/[0-9]+",
    r"/TagID=",
    r"/TagID/[0-9]+",
    r"/Category/",
    r"&tab=",
    r"/tree/",              # directory listings -- pure navigation, no server-rendered content to index
    r"/issues?[/?]",
    r"/projects?[/?]",
    r"/pulls?[/?]",
    r"/pushes?[/?]",
    r"/forks?[/?]",
    r"/network[/?]",
    r"/commits?[/?]",
    r"/discussions?[/?]",
    r"/categories[/?]",
    r"/announcements?[/?]",
    r"/settings[/?]",
    r"/contribs?[/?]",
    r"/contributions?[/?]",
    r"/checks?[/?]",
    r"/comments?[/?]",
    r"/author[/?]",
    r"/profile[/?]",
    r"/watchers[/?]",
    r"/stargazers[/?]",
    r"/stars[/?]",
    r"/graphs[/?]",         # contributors, commit-activity, code-frequency, punch-card, traffic
    r"/actions[/?]",        # CI workflow runs
    r"/security[/?]",       # security advisories -- not KB content; /releases stays indexable
    r"/compare[/?]",
    r"/blame/",
    r"/raw/",               # Markdown/text file content is fetched directly from
                             # raw.githubusercontent.com instead (see is_git_blob_text_url /
                             # to_git_raw_url), so this only prevents redundantly re-crawling
                             # the github.com redirect URL if a page happens to link to it.
    r"/find/",
    r"/deployments[/?]",
    r"/environments[/?]",
    r"/packages[/?]",
    r"/sponsors[/?]",
    r"/people[/?]",
    r"/followers[/?]",
    r"/following[/?]",
    # GitHub wiki housekeeping actions (edit form, revision history, new-page draft,
    # access settings) -- not real content.
    r"/_edit$",
    r"/_history$",
    r"/_new$",
    r"/_access$",
] + [rf"\.{ext}$" for ext in BINARY_EXTENSIONS + SOURCE_EXTENSIONS]

# ===========================================================================
# END USER CONFIG
# ===========================================================================

import re
import sys
import subprocess


def _ensure(pkg, import_as=None, upgrade=False):
    try:
        if not upgrade:
            __import__(import_as or pkg)
            return
    except ImportError:
        pass
    args = [sys.executable, "-m", "pip", "install"]
    if upgrade:
        args.append("--upgrade")
    args.append(pkg)
    subprocess.check_call(args)


_ensure("typing_extensions", upgrade=True)
_ensure("requests")
_ensure("beautifulsoup4", "bs4")
_ensure("sentence_transformers", "sentence_transformers")
_ensure("numpy")
_ensure("Markdown", "markdown")

import argparse
import hashlib
import html
import json
import os
import struct
import time
from collections import Counter, deque
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import markdown
import numpy as np
import requests
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_MODEL_BROWSER_ID = "Xenova/bge-small-en-v1.5"
DIMS = 384

# "Parent" chunk sizing -- a parent is one full section (see
# split_into_parents), the text actually sent to the model. Parents are
# never embedded/searched directly; see CHILD_* below for the small-to-big
# retrieval unit that is.
CHUNK_MAX_CHARS = 1200
CHUNK_MIN_CHARS = 60

# "Child" chunk sizing -- the small, precise window that gets embedded and
# matched against a query (small-to-big retrieval: search small, return
# big). ~15% overlap so a fact sitting right at a window boundary is still
# fully contained in at least one child.
CHILD_CHUNK_MAX_CHARS = 350
CHILD_CHUNK_MIN_CHARS = 60
CHILD_OVERLAP_CHARS = 53

# Local page cache -- add this directory to .gitignore. Speeds up repeat runs
# by skipping re-download of pages whose Last-Modified/ETag hasn't changed.
CACHE_DIR = ".kb_cache"
CACHE_META_PATH = os.path.join(CACHE_DIR, "meta.json")
CACHE_PAGES_DIR = os.path.join(CACHE_DIR, "pages")

# How many successful fetches (200s or 304 cache hits) accumulate between
# meta.json writes -- rewriting after every single page dominates wall-clock
# time once caching makes per-page work otherwise cheap. crawl() also does
# one unconditional final save so a normal exit never loses more than the
# last partial batch.
CACHE_SAVE_INTERVAL = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
TDX_CONTENT_SELECTORS = [
    "#tdBodyContent",
    ".kb-article-body",
    ".td-page-body",
    "[data-region='article-body']",
    "#articleBody",
    ".article-content",
    "main",
]
STRIP_TAGS = [
    "script", "style", "noscript", "nav", "footer", "header",
    "aside", ".breadcrumb", ".td-utility-bar", ".td-nav", ".pager",
    ".pagination", "#tdBreadcrumb", "#tdNavigation", "#tdSideMenu",
    ".td-side-menu",
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


# ---------------------------------------------------------------------------
# URL scope helpers
# ---------------------------------------------------------------------------

def derive_auto_prefix(seed_url):
    """
    TDX URL -> /TDClient/<digits>/<slug>/ prefix scoped to its origin.
    Anything else -> same origin only.
    """
    parsed = urlparse(seed_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    m = re.search(r"(/TDClient/\d+/[^/]+/)", seed_url)
    if m:
        return origin + m.group(1)
    return origin


def compile_patterns(patterns):
    compiled = []
    for p in patterns:
        # If the pattern contains no regex special chars beyond what a plain
        # substring would have, re.escape is unnecessary -- but compile as-is
        # so users can write either plain substrings or real regexes.
        compiled.append(re.compile(p, re.IGNORECASE))
    return compiled


def get_origin(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def is_git_host_url(url):
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
    server-rendered HTML and don't need this path; see extract_content().
    """
    return is_git_host_url(url) and bool(GIT_TEXT_FILE_RE.search(urlparse(url).path))


def to_git_raw_url(blob_url):
    """
    Rewrites a github.com blob URL to its raw.githubusercontent.com
    equivalent: /<owner>/<repo>/blob/<branch>/<path> -> /<owner>/<repo>/<branch>/<path>.
    Only meaningful for URLs already matched by is_git_blob_text_url.
    """
    path = re.sub(r"^/([^/]+)/([^/]+)/blob/", r"/\1/\2/", urlparse(blob_url).path)
    return f"https://raw.githubusercontent.com{path}"


def markdown_text_to_soup(raw_text, url):
    """
    Converts a fetched .md/.txt file's raw text into a minimal HTML
    document so it flows through the existing heading-based chunker
    (split_into_parents) unchanged: Markdown files get real <h1>-<h6>/<a>
    tags via python-markdown; plain-text files are wrapped in a single
    <pre> so they still yield one parent chunk.
    """
    if url.lower().endswith((".md", ".markdown")):
        body_html = markdown.markdown(raw_text, extensions=["fenced_code", "tables"])
    else:
        body_html = "<pre>" + html.escape(raw_text) + "</pre>"
    return BeautifulSoup(f"<body>{body_html}</body>", "html.parser")


def derive_title_from_blob_path(url):
    """Fallback title for a repo text file with no Markdown H1: docs/setup.md -> 'Setup'."""
    name = urlparse(url).path.rsplit("/", 1)[-1]
    stem = re.sub(r"\.(md|markdown|txt)$", "", name, flags=re.I)
    return re.sub(r"[-_]+", " ", stem).strip().title() or "Untitled"


def in_scope(url, auto_prefix, origin, include_res, crawl_exclude_res):
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


def normalise(url):
    """Strip fragment and trailing slash for dedup."""
    return url.split("#")[0].strip().rstrip("/")


# ---------------------------------------------------------------------------
# Local page cache
# ---------------------------------------------------------------------------

def load_cache_meta():
    if os.path.exists(CACHE_META_PATH):
        try:
            with open(CACHE_META_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    return {}


def save_cache_meta(cache_meta):
    """Atomically writes meta.json via a temp file + os.replace, so an
    interrupted run (Ctrl+C mid-write) never leaves a truncated/corrupt file."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp_path = CACHE_META_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cache_meta, f)
    os.replace(tmp_path, CACHE_META_PATH)


def cache_page_path(url):
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_PAGES_DIR, h + ".html")


# ---------------------------------------------------------------------------
# Fetch + parse
# ---------------------------------------------------------------------------

def _flush_cache_meta_periodically(session, cache_meta):
    """Saves meta.json every CACHE_SAVE_INTERVAL successful fetches. Call
    once per fetch() call that mutates cache_meta (a fresh 200, or a 304
    cache hit's fetched_at bump)."""
    count = getattr(session, "_kb_fetch_save_counter", 0) + 1
    session._kb_fetch_save_counter = count
    if count % CACHE_SAVE_INTERVAL == 0:
        save_cache_meta(cache_meta)


def _store_fetched_page(r, url, session, cache_meta, expect_html):
    """
    Validates content-type, writes the cache file, and records fresh cache
    metadata (etag/last_modified/fetched_at/sha256) for a 200 response.
    sha256 is unused today -- reserved for a future delta-build feature.
    Returns None (without writing anything) if content-type doesn't match
    expect_html -- callers treat that as "nothing usable at this URL."
    """
    content_type = r.headers.get("content-type", "")
    if expect_html and "text/html" not in content_type:
        return None
    if not expect_html and "text/plain" not in content_type:
        return None
    os.makedirs(CACHE_PAGES_DIR, exist_ok=True)
    with open(cache_page_path(url), "w", encoding="utf-8") as f:
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

    expect_html=True (default) requires a `text/html` response and returns
    a parsed BeautifulSoup document. expect_html=False requires
    `text/plain` (e.g. a raw.githubusercontent.com file) and returns the
    decoded text as-is, with no HTML parsing.
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
                with open(cache_page_path(url), "r", encoding="utf-8") as f:
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


def normalise_page_title(title, url=None):
    if url and "teamdynamix." in url.lower():
        for prefix in ("Article - ", "Question Detail - "):
            title = title.removeprefix(prefix)
    return title


def get_title(soup, url=None):
    t = soup.find("title")
    if t:
        title = re.sub(r"\s*[|]\s*.+$", "", t.get_text(" ", strip=True))
        return normalise_page_title(title, url)
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
        return normalise_page_title(title, url)
    if url and is_git_blob_text_url(url):
        return derive_title_from_blob_path(url)
    return "Untitled"


def extract_content(soup, url=None):
    if url and "teamdynamix." in url.lower():
        for sel in ("#divMainContent", "#questionsContent"):
            node = soup.select_one(sel)
            if node:
                for noise in STRIP_TAGS:
                    for el in node.select(noise):
                        el.decompose()
                if node.get_text(" ", strip=True):
                    return node
        return None

    if url and is_git_blob_text_url(url):
        # Content already came from a raw .md/.txt fetch (see crawl()) and
        # was converted to a clean, chrome-free document in
        # markdown_text_to_soup -- no nav/footer noise to strip.
        body = soup.find("body")
        return body if body and body.get_text(strip=True) else None

    if is_git_host_url(url or ""):
        path = urlparse(url).path.rstrip("/").lower()
        if "/wiki" in path:
            # Wiki pages are still classic server-rendered (Gollum) HTML.
            selectors = (".markdown-body", "#wiki-content", "article", "main")
        elif re.search(r"/releases/tag/[^/]+$", path):
            # Individual release-notes pages are server-rendered inline.
            selectors = (".markdown-body",)
        else:
            # Repo root / tree / commit list / etc: client-hydrated shell
            # with no server-rendered content -- link-discovery hop only.
            return None
        for sel in selectors:
            node = soup.select_one(sel)
            if node:
                for noise in STRIP_TAGS:
                    for el in node.select(noise):
                        el.decompose()
                if node.get_text(" ", strip=True):
                    return node
        return None

    for sel in TDX_CONTENT_SELECTORS:
        node = soup.select_one(sel)
        if node:
            for noise in STRIP_TAGS:
                for el in node.select(noise):
                    el.decompose()
            return node
    return None


def extract_links(soup, base_url):
    links = []
    for a in soup.find_all("a", href=True):
        href = normalise(urljoin(base_url, a["href"]))
        if href:
            links.append(href)
    return links


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_kind(url):
    """
    Coarse per-chunk provenance facet, consumed by the browser's
    router-driven facet filter (e.g. a code question shouldn't be scored
    against outreach pages) -- reserved for a future YouTube producer,
    which will add a fourth kind alongside these three.
    """
    if is_git_host_url(url):
        return "code"
    if "teamdynamix." in url.lower():
        return "kb"
    return "page"


def split_into_parents(title, node, url):
    """
    Splits one page's content into "parent" chunks: one per <h2>/<h3>
    section (or the whole page, if it has no headings), further cut at
    CHUNK_MAX_CHARS if a section runs long. Parents are the full text
    handed to the model at answer time -- see split_parent_into_children
    for the smaller windows actually embedded and searched.
    """
    chunks = []
    host = urlparse(url).netloc.lower()
    kind = chunk_kind(url)

    def _make(heading, text):
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) < CHUNK_MIN_CHARS:
            return
        while len(text) > CHUNK_MAX_CHARS:
            cut = text.rfind("\n", 0, CHUNK_MAX_CHARS)
            if cut < CHUNK_MIN_CHARS:
                cut = CHUNK_MAX_CHARS
            chunks.append({"t": heading, "x": text[:cut], "u": url, "host": host, "kind": kind, "weight": 1.0})
            text = text[cut:].strip()
        if text:
            chunks.append({"t": heading, "x": text, "u": url, "host": host, "kind": kind, "weight": 1.0})

    headings = node.find_all(["h2", "h3"])
    if headings:
        before = []
        for el in node.children:
            if hasattr(el, "name") and el.name in ("h2", "h3"):
                break
            if hasattr(el, "get_text"):
                before.append(el.get_text(" ", strip=True))
        _make(title, " ".join(before))
        for h in headings:
            section_title = f"{title} -- {h.get_text(' ', strip=True)}"
            parts = []
            for sib in h.next_siblings:
                if hasattr(sib, "name") and sib.name in ("h2", "h3"):
                    break
                if hasattr(sib, "get_text"):
                    parts.append(sib.get_text(" ", strip=True))
            _make(section_title, " ".join(parts))
    else:
        text = node.get_text("\n", strip=True)
        _make(title, text)

    return chunks


def split_parent_into_children(parent):
    """
    Small-to-big child splitter. A parent shorter than CHILD_CHUNK_MAX_CHARS
    is returned as its own single child -- splitting an already-short
    section would only hand drop_near_duplicates a near-identical extra
    vector to discard later. Longer parents get a fixed-step sliding
    window (CHILD_OVERLAP_CHARS of overlap between windows, so a fact
    sitting at a window boundary still lands fully inside at least one
    child), each window trimmed back to the nearest preceding newline so
    children don't split mid-sentence any more than the parent splitter
    itself does.
    """
    text = parent["x"]
    if len(text) <= CHILD_CHUNK_MAX_CHARS:
        return [dict(parent)]

    children = []
    step = max(CHILD_CHUNK_MAX_CHARS - CHILD_OVERLAP_CHARS, CHILD_CHUNK_MIN_CHARS)
    n = len(text)
    start = 0
    while start < n:
        end = min(start + CHILD_CHUNK_MAX_CHARS, n)
        cut = text.rfind("\n", start, end) if end < n else end
        if cut <= start:
            cut = end
        child_text = text[start:cut].strip()
        if len(child_text) >= CHILD_CHUNK_MIN_CHARS:
            children.append({**parent, "x": child_text})
        if end >= n:
            break
        start += step  # fixed step, independent of `cut` -- guarantees progress every iteration
    return children if children else [dict(parent)]


def build_parent_and_child_chunks(title, node, url):
    """
    Produces one page's parent chunks (full section text, sent to the
    model) and child chunks (small windows, embedded/searched). Each
    child's `pid` is a 0-based index into THIS page's own parent list;
    crawl() offsets it into a globally valid index as pages accumulate.
    """
    parents = split_into_parents(title, node, url)
    children = []
    for pid, parent in enumerate(parents):
        for child in split_parent_into_children(parent):
            child = dict(child)
            child["pid"] = pid
            children.append(child)
    return parents, children


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_chunks(chunks):
    print(f"\nLoading embedding model: {EMBED_MODEL}")
    model = SentenceTransformer(EMBED_MODEL)
    texts = [((c["t"] + "\n") if c.get("t") else "") + c["x"] for c in chunks]
    print(f"Embedding {len(texts)} chunks...")
    vecs = model.encode(texts, normalize_embeddings=True,
                        batch_size=64, show_progress_bar=True)
    return vecs.astype(np.float32)


# Near-duplicate collapse at build time. Boilerplate (nav sidebars, footers,
# repeated disclaimers) crawls into many chunks that are near-identical after
# embedding; collapsing them here means every query-time retrieval benefits,
# instead of filtering the same boilerplate out of every top-k result forever.
NEAR_DUP_COSINE_THRESHOLD = 0.95


def drop_near_duplicates(chunks, vecs, threshold=NEAR_DUP_COSINE_THRESHOLD):
    """
    Greedy sequential near-duplicate collapse. Vectors are already
    L2-normalized (embed_chunks uses normalize_embeddings=True), so cosine
    similarity between any two rows is a single dot product -- one matrix
    multiply against the kept set per chunk, cheap at this corpus size.
    Keeps the first occurrence encountered (crawl order) of each
    near-duplicate cluster and drops the rest.

    Returns (kept_chunks, kept_vecs, dropped_count).
    """
    if len(chunks) == 0:
        return chunks, vecs, 0
    kept_rows = []      # indices into the original chunks/vecs arrays
    kept_matrix = None  # np.ndarray, grows as rows are kept
    for i in range(len(chunks)):
        v = vecs[i]
        if kept_matrix is not None and kept_matrix.shape[0] > 0:
            sims = kept_matrix @ v
            if float(sims.max()) > threshold:
                continue  # near-duplicate of an already-kept chunk -- drop
        kept_rows.append(i)
        row = v.reshape(1, -1)
        kept_matrix = row if kept_matrix is None else np.vstack([kept_matrix, row])
    dropped = len(chunks) - len(kept_rows)
    kept_chunks = [chunks[i] for i in kept_rows]
    kept_vecs = vecs[kept_rows]
    return kept_chunks, kept_vecs, dropped


def remap_parents_after_dedup(parents, children):
    """
    drop_near_duplicates can remove every child of a parent (e.g. an
    entirely-boilerplate section), orphaning that parent. Rebuilds the
    parent list to include only parents with at least one surviving
    child, and rewrites every child's `pid` to the new, compacted index.
    Must build the old->new map over surviving parents FIRST, then rewrite
    children in a second pass -- children still hold old-parent indices
    until this function returns.
    """
    live_pids = {c["pid"] for c in children}
    old_to_new = {}
    new_parents = []
    for old_pid, p in enumerate(parents):
        if old_pid in live_pids:
            old_to_new[old_pid] = len(new_parents)
            new_parents.append(p)
    for c in children:
        c["pid"] = old_to_new[c["pid"]]
    return new_parents, children


# int8 vector quantization. Vectors are L2-normalized, so every component
# already lies in roughly [-1, 1] -- round(v * INT8_SCALE) loses negligible
# precision at 384 dims and needs no per-vector calibration. Reversed in the
# browser by dividing back by the same scale (see parseKbIndexBody's vecsQ
# branch in index.html).
INT8_SCALE = 127


def quantize_int8(vecs):
    return np.clip(np.round(vecs * INT8_SCALE), -INT8_SCALE, INT8_SCALE).astype(np.int8)


# ---------------------------------------------------------------------------
# Hybrid retrieval: BM25 corpus statistics
# ---------------------------------------------------------------------------
# Formula and default constants (k, b, d) read from oramasearch/orama's
# BM25() implementation as a design reference -- not vendored/imported.
# `d` is a Lucene-style smoothing term Orama adds on top of classical
# Robertson BM25; kept here because it prevents a zero score for a single
# sparse-term match. Fusion with vector scores (Reciprocal Rank Fusion) is
# computed query-time in the browser, NOT here -- this only emits the
# corpus-wide statistics (document frequency, postings, average doc
# length) a query can't compute on its own.
BM25_K1 = 1.2
BM25_B = 0.75
BM25_D = 0.5

# MUST match index.html's query-side tokenizer (/[a-z0-9]{3,}/g) exactly --
# a mismatch here silently degrades every BM25 match, since postings built
# with one tokenization rule can't be looked up correctly with another.
TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def tokenize(text):
    return TOKEN_RE.findall(text.lower())


def build_bm25_index(children):
    """
    Builds BM25 corpus statistics over the final child list. MUST run
    after drop_near_duplicates and remap_parents_after_dedup -- postings'
    doc indices are positions into `children` as shipped in the index, so
    building this against a pre-dedup list would point at chunks that no
    longer exist (or the wrong ones) once dedup runs afterward.
    """
    doc_len = []
    df = {}
    postings = {}
    for i, c in enumerate(children):
        tokens = tokenize((c.get("t") or "") + " " + c["x"])
        doc_len.append(len(tokens))
        for term, tf in Counter(tokens).items():
            df[term] = df.get(term, 0) + 1
            postings.setdefault(term, []).append([i, tf])
    avg_doc_len = (sum(doc_len) / len(doc_len)) if doc_len else 0.0
    return {
        "k": BM25_K1,
        "b": BM25_B,
        "d": BM25_D,
        "avgDocLen": avg_doc_len,
        "docLen": doc_len,
        "df": df,
        "postings": postings,
    }


# ---------------------------------------------------------------------------
# Relevance calibration
# ---------------------------------------------------------------------------
# Sample-based corpus statistics letting the browser threshold on a
# z-score instead of an absolute cosine cutoff hand-tuned for one specific
# corpus/embedding model (see index.html's diversifyHits).
CALIBRATION_SAMPLE_SIZE = 500


def compute_calibration_stats(vecs, sample_size=CALIBRATION_SAMPLE_SIZE):
    """
    Samples up to `sample_size` embedded children (all of them, if fewer)
    and computes each sampled row's best (max) cosine similarity against
    every OTHER child -- a proxy for "the best score a real query is
    likely to achieve against this corpus." mean/std of those maxes is
    what the browser calibrates its relevance threshold against. Vectors
    are already L2-normalized (embed_chunks), so cosine similarity is a
    single dot product.
    """
    n = vecs.shape[0]
    if n < 2:
        return {"mean": 0.0, "std": 0.0, "sampleSize": 0}
    rng = np.random.default_rng(seed=42)  # deterministic across rebuilds of the same corpus
    sample_idx = rng.choice(n, size=min(sample_size, n), replace=False)
    sims = vecs[sample_idx] @ vecs.T  # (sample_size, n)
    for row_pos, doc_idx in enumerate(sample_idx):
        sims[row_pos, doc_idx] = -1.0  # exclude self-match
    best = sims.max(axis=1)
    return {"mean": float(best.mean()), "std": float(best.std()), "sampleSize": int(len(sample_idx))}


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------

def crawl(seed_url, max_pages, delay, include_res, crawl_exclude_res, index_exclude_res):
    auto_prefix = derive_auto_prefix(seed_url)
    origin = get_origin(seed_url)
    seed_norm = normalise(seed_url)

    print(f"Seed:         {seed_url}")
    print(f"Auto prefix:  {auto_prefix}")
    if include_res:
        print(f"Include pats: {[r.pattern for r in include_res]}")
    else:
        print(f"Include pats: (auto -- prefix only)")
    print(f"Crawl exclude pats: {[r.pattern for r in crawl_exclude_res]}")
    print(f"Index exclude pats: {[r.pattern for r in index_exclude_res]}")
    print()

    session = requests.Session()
    cache_meta = load_cache_meta()
    visited = set()
    queued = {seed_norm}   # dedup before download
    queue = deque([seed_norm])
    all_parents = []
    all_children = []
    site_name = "Knowledge Base"

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        print(f"[{len(visited):4d}] {url}")
        if is_git_blob_text_url(url):
            raw_text = fetch(session, to_git_raw_url(url), cache_meta, expect_html=False)
            soup = markdown_text_to_soup(raw_text, url) if raw_text else None
        else:
            soup = fetch(session, url, cache_meta)
        if soup is None:
            continue

        if len(visited) == 1:
            site_name = get_title(soup, url)

        # Enqueue new in-scope links, deduped before download
        for link in extract_links(soup, url):
            if link not in visited and link not in queued:
                if in_scope(link, auto_prefix, origin, include_res, crawl_exclude_res):
                    queued.add(link)
                    queue.append(link)

        # Index exclusion only prevents indexing, not crawling.
        if any(r.search(url) for r in index_exclude_res):
            if delay > 0:
                time.sleep(delay)
            continue

        content = extract_content(soup, url)
        if content is None:
            continue

        title = get_title(soup, url)
        page_parents, page_children = build_parent_and_child_chunks(title, content, url)
        if page_parents:
            # Offset this page's locally 0-based `pid`s into globally
            # valid indices as pages accumulate into all_parents.
            pid_offset = len(all_parents)
            for c in page_children:
                c["pid"] += pid_offset
            all_parents.extend(page_parents)
            all_children.extend(page_children)
            print(f"       +{len(page_parents)} section(s), +{len(page_children)} chunk(s): {title[:70]}")

        if delay > 0:
            time.sleep(delay)

    save_cache_meta(cache_meta)  # final flush -- catches any partial batch below CACHE_SAVE_INTERVAL

    print(f"\nCrawled {len(visited)} pages, produced {len(all_parents)} section(s), {len(all_children)} chunk(s).")
    return all_parents, all_children, site_name


# ---------------------------------------------------------------------------
# Build index
# ---------------------------------------------------------------------------

def build_index(parents, children, site_name, out_path, float32_vecs=False):
    """
    Writes the RAG index as a single self-describing binary container:
    [4-byte little-endian uint32 header length N][N bytes UTF-8 JSON
    header][raw int8/float32 vector bytes]. Replaces the earlier
    base64-in-JSON transport -- base64 cost ~33% extra bytes and a slow
    JSON.parse over one giant string for no benefit once nothing else
    needs the vectors to be JSON-representable. No backward-compat path:
    this is a single-user tool and every consumer rebuilds from source.
    """
    if not children:
        print("No chunks -- nothing to write.")
        return

    vecs = embed_chunks(children)
    assert vecs.shape == (len(children), DIMS), f"Shape mismatch: {vecs.shape}"

    children, vecs, dropped_dupes = drop_near_duplicates(children, vecs)
    if dropped_dupes:
        print(f"Dropped {dropped_dupes} near-duplicate chunk(s) (cosine > {NEAR_DUP_COSINE_THRESHOLD}).")

    parents, children = remap_parents_after_dedup(parents, children)

    bm25 = build_bm25_index(children)
    calibration = compute_calibration_stats(vecs)

    if float32_vecs:
        payload_bytes = vecs.tobytes()
        vecs_q_field = None
    else:
        payload_bytes = quantize_int8(vecs).tobytes()
        vecs_q_field = "i8"

    # Distinct source pages actually contributing content, not total pages
    # visited (which includes pages skipped by INDEX_EXCLUDE_PATTERNS or
    # with no extractable content) -- this is what "staleness" means to a
    # reader of the badge: how much of the site is actually represented.
    source_count = len({c["u"] for c in children})
    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    index = {
        "_license": (
            "This file is part of Field Station AI. Copyright © 2026 The Regents "
            "of the University of Michigan. This program is free software: you can "
            "redistribute it and/or modify it under the terms of the GNU General "
            "Public License as published by the Free Software Foundation, either "
            "version 3 of the License, or (at your option) any later version. This "
            "program is distributed in the hope that it will be useful, but WITHOUT "
            "ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or "
            "FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License "
            "for more details. You should have received a copy of the GNU General "
            "Public License along with this program. If not, see "
            "https://www.gnu.org/licenses/."
        ),
        "v": 2,  # binary-container format; sanity/cache-mismatch marker only, not a compat flag
        "model": EMBED_MODEL_BROWSER_ID,
        "dims": DIMS,
        "builtAt": built_at,
        "sourceCount": source_count,
        "site": site_name,
        # Parents are index-addressed: parents[i] <-> a child's `pid == i`.
        # `chunks` holds CHILDREN only -- the searchable, embedded unit in
        # small-to-big retrieval. Full section text lives in `parents`,
        # looked up by pid.
        "parents": parents,
        "chunks": children,
        "bm25": bm25,
        "calibration": calibration,
    }
    if vecs_q_field:
        index["vecsQ"] = vecs_q_field
        index["vecsScale"] = INT8_SCALE

    header_bytes = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with open(out_path, "wb") as f:
        f.write(struct.pack("<I", len(header_bytes)))  # 4-byte LE header length
        f.write(header_bytes)
        f.write(payload_bytes)

    size_mb = len(payload_bytes) / 1024 / 1024
    header_mb = len(header_bytes) / 1024 / 1024
    print(f"\nWrote: {out_path}")
    print(f"  parents: {len(parents)}")
    print(f"  chunks : {len(children)}")
    print(f"  vecs   : {size_mb:.2f} MB " + ("float32" if float32_vecs else "int8 (quantized)"))
    print(f"  header : {header_mb:.2f} MB (JSON manifest incl. BM25 postings + calibration)")
    print(f"  site   : {site_name}")
    print(f"  built  : {built_at}")
    print(f"  sources: {source_count}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build Field Station AI RAG index from a website or TDX KB portal"
    )
    parser.add_argument("--url", default=SEED_URL)
    parser.add_argument("--out", default=OUT_PATH)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--delay", type=float, default=DELAY)
    parser.add_argument("--float32-vecs", action="store_true",
                        help="Write vectors as float32 instead of the default int8 quantization.")
    args = parser.parse_args()

    include_res = compile_patterns(INCLUDE_PATTERNS)
    crawl_exclude_res = compile_patterns(CRAWL_EXCLUDE_PATTERNS)
    index_exclude_res = compile_patterns(INDEX_EXCLUDE_PATTERNS)

    parents, children, site_name = crawl(args.url, args.max_pages, args.delay,
                              include_res, crawl_exclude_res, index_exclude_res)
    build_index(parents, children, site_name, args.out, float32_vecs=args.float32_vecs)


if __name__ == "__main__":
    main()