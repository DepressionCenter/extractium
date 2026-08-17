"""
Summary: Local page cache for crawled content. Reads and writes
.kb_cache/meta.json (per-URL conditional-GET validators: ETag,
Last-Modified, fetch timestamp, content sha256), and derives the on-disk
file path for a cached page body from its URL.

This file is part of Extractium™
extractium/core/cache.py

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
import json
import os

### Cache Layout ###

# Local page cache -- add this directory to .gitignore. Speeds up repeat
# builds by skipping re-download of pages whose Last-Modified/ETag hasn't
# changed since the last run.
CACHE_DIR = ".kb_cache"
CACHE_META_PATH = os.path.join(CACHE_DIR, "meta.json")
CACHE_PAGES_DIR = os.path.join(CACHE_DIR, "pages")

# How many successful fetches (200s or 304 cache hits) accumulate between
# meta.json writes -- rewriting after every single page dominates
# wall-clock time once caching makes per-page work otherwise cheap. The
# caller does one unconditional final save so a normal exit never loses
# more than the last partial batch.
CACHE_SAVE_INTERVAL = 25


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
