"""
Summary: Local caches for content a build has already fetched: the
page cache for crawled URLs, and the GitHub cache for content read
through the API. Reads and writes
.kb_cache/meta.json (per-URL conditional-GET validators: ETag,
Last-Modified, fetch timestamp, content sha256), and derives the on-disk
file path for a cached page body from its URL.

This file is part of Extractium™
extractium/core/cache.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-09
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
__date__ = "2026-09-09"

import hashlib
import json
import os
import re

### Cache Layout ###

# Local page cache -- add this directory to .gitignore. Speeds up repeat
# builds by skipping re-download of pages whose Last-Modified/ETag hasn't
# changed since the last run.
CACHE_DIR = ".kb_cache"
CACHE_META_PATH = os.path.join(CACHE_DIR, "meta.json")
CACHE_PAGES_DIR = os.path.join(CACHE_DIR, "pages")

# Content read through the GitHub API, kept apart from the page cache
# because it is keyed differently: GitHub gives every file body a blob
# SHA, and the same SHA means the same bytes whatever branch or path
# points at it. Repository metadata and trees are keyed by the commit or
# tree SHA they belong to, which changes whenever the content does.
#
# Nothing written under this tree may contain an access token. Bodies are
# stored exactly as GitHub returned them, and no request header is ever
# recorded alongside them.
CACHE_GITHUB_DIR = os.path.join(CACHE_DIR, "github")
CACHE_GITHUB_BLOBS_DIR = os.path.join(CACHE_GITHUB_DIR, "blobs")
CACHE_GITHUB_REPOSITORIES_DIR = os.path.join(CACHE_GITHUB_DIR, "repositories")
CACHE_GITHUB_ANALYSIS_DIR = os.path.join(CACHE_GITHUB_DIR, "analysis")

# A blob SHA is a Git object name: forty hexadecimal characters and
# nothing else. Checked before it is used in a path, because the SHA
# arrives in an API response, which is untrusted input like any other.
_BLOB_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# How many successful fetches (200s or 304 cache hits) accumulate between
# meta.json writes -- rewriting after every single page dominates
# wall-clock time once caching makes per-page work otherwise cheap. The
# caller does one unconditional final save so a normal exit never loses
# more than the last partial batch.
CACHE_SAVE_INTERVAL = 25


def use_cache_dir(path):
    """
    Points the cache at another folder, honoring the `cache_dir` setting.

    The three paths move together, because a half-moved cache would read
    validators for pages stored somewhere else and serve stale content.
    Every function in this module reads the constants at call time, so a
    caller sets this once before the first fetch.

    Args:
        path (str): folder to hold `meta.json` and `pages/`. Created on
            first write, not here.
    """
    global CACHE_DIR, CACHE_META_PATH, CACHE_PAGES_DIR
    global CACHE_GITHUB_DIR, CACHE_GITHUB_BLOBS_DIR
    global CACHE_GITHUB_REPOSITORIES_DIR, CACHE_GITHUB_ANALYSIS_DIR
    CACHE_DIR = str(path)
    CACHE_META_PATH = os.path.join(CACHE_DIR, "meta.json")
    CACHE_PAGES_DIR = os.path.join(CACHE_DIR, "pages")
    CACHE_GITHUB_DIR = os.path.join(CACHE_DIR, "github")
    CACHE_GITHUB_BLOBS_DIR = os.path.join(CACHE_GITHUB_DIR, "blobs")
    CACHE_GITHUB_REPOSITORIES_DIR = os.path.join(CACHE_GITHUB_DIR, "repositories")
    CACHE_GITHUB_ANALYSIS_DIR = os.path.join(CACHE_GITHUB_DIR, "analysis")


### Cache Metadata ###

def load_cache_meta():
    """
    Reads the per-URL cache metadata (ETag, Last-Modified, fetch timestamp,
    content sha256) from CACHE_META_PATH.

    Returns:
        dict: URL -> metadata dict. Empty dict if the file is missing or
        cannot be parsed as JSON -- a corrupt cache file degrades to a full
        re-fetch on the next build rather than failing the build.
    """
    if os.path.exists(CACHE_META_PATH):
        try:
            with open(CACHE_META_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    return {}


def save_cache_meta(cache_meta):
    """
    Atomically writes cache_meta to CACHE_META_PATH via a temp file +
    os.replace, so an interrupted run (Ctrl+C mid-write) never leaves a
    truncated/corrupt file.

    Args:
        cache_meta (dict): URL -> metadata dict, as returned by
            load_cache_meta and mutated by fetch().
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp_path = CACHE_META_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cache_meta, f)
    os.replace(tmp_path, CACHE_META_PATH)


### Page File Paths ###

def cache_page_path(url):
    """
    Derives the on-disk cache file path for one URL's fetched page body.
    The filename is the URL's sha1 hex digest, so the path never depends
    on the URL's own characters (no path-traversal or filesystem-illegal-
    character risk from a hostile URL).

    Args:
        url (str): the page URL to derive a cache path for.

    Returns:
        str: path under CACHE_PAGES_DIR, e.g. ".kb_cache/pages/<sha1>.html".
    """
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_PAGES_DIR, h + ".html")


### GitHub Cache Paths ###

def github_blob_path(blob_sha):
    """
    The on-disk path for one GitHub file body, keyed by its blob SHA.

    Args:
        blob_sha (str): the forty-character Git object name GitHub
            reported for the file.

    Returns:
        str: path under CACHE_GITHUB_BLOBS_DIR.

    Raises:
        ValueError: if blob_sha is not forty lowercase hexadecimal
            characters. The SHA arrives in an API response, so it is
            checked rather than trusted: an unchecked value used in a
            path could reach outside the cache directory.
    """
    if not isinstance(blob_sha, str) or not _BLOB_SHA_RE.match(blob_sha):
        raise ValueError(f"a blob SHA must be 40 lowercase hexadecimal characters; got {blob_sha!r}.")
    return os.path.join(CACHE_GITHUB_BLOBS_DIR, blob_sha)


def load_github_blob(blob_sha):
    """
    Reads a cached file body.

    Args:
        blob_sha (str): the file's blob SHA.

    Returns:
        str | None: the text, or None when it is not cached or cannot be
        read. An unreadable cache entry degrades to a re-download rather
        than failing the build.
    """
    try:
        with open(github_blob_path(blob_sha), "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def save_github_blob(blob_sha, text):
    """
    Stores one file body under its blob SHA.

    The body is written exactly as it arrived. No request header, and so
    no access token, is ever written alongside it.

    Args:
        blob_sha (str): the file's blob SHA.
        text (str): the decoded file body.
    """
    os.makedirs(CACHE_GITHUB_BLOBS_DIR, exist_ok=True)
    path = github_blob_path(blob_sha)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp_path, path)
