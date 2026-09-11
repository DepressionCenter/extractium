"""
Summary: Local caches for content a build has already fetched: the
page cache for crawled URLs, the GitHub cache for content read through
the API, the repository cache for text a scholarly repository
extracted from a deposit's files, and the YouTube cache for video
listings and caption transcripts. Reads and writes
.kb_cache/meta.json (per-URL conditional-GET validators: ETag,
Last-Modified, fetch timestamp, content sha256), and derives the on-disk
file path for a cached page body from its URL.

This file is part of Extractium™
extractium/core/cache.py

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
__date__ = "2026-09-10"

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

# Text a scholarly repository extracted from a deposited file, kept apart
# from the page cache because it is keyed differently: a repository names
# every deposit with an identifier and reports when that deposit last
# changed, so the pair of the two says whether stored text is still
# current. Nothing else about a deposit is stored here; its metadata comes
# back with the listing that says whether the deposit moved at all.
CACHE_REPOSITORY_DIR = os.path.join(CACHE_DIR, "repository")

# Video listings and caption transcripts. This subtree is the one cache
# a build may be unable to refill: YouTube answers requests from
# cloud-provider address ranges with a block, so a scheduled run on a
# hosted runner cannot fetch a transcript at all. What an operator
# fetched on their own machine is therefore committed to the data
# repository and read back here, which is why nothing under this tree is
# keyed by a validator: a stored transcript is used because it exists,
# not because it was checked against the server.
CACHE_YOUTUBE_DIR = os.path.join(CACHE_DIR, "youtube")
CACHE_YOUTUBE_VIDEOS_DIR = os.path.join(CACHE_YOUTUBE_DIR, "videos")
CACHE_YOUTUBE_LISTINGS_DIR = os.path.join(CACHE_YOUTUBE_DIR, "listings")

# A blob SHA is a Git object name: forty hexadecimal characters and
# nothing else. Checked before it is used in a path, because the SHA
# arrives in an API response, which is untrusted input like any other.
_BLOB_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# A repository deposit is named by a UUID. Checked before it is used in a
# path for the same reason a blob SHA is: the identifier arrives in an API
# response, and an unchecked value in a path could reach outside the cache
# directory.
_DEPOSIT_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# A YouTube video is named by eleven characters from the base64url
# alphabet, and a playlist or channel by a longer run of the same. Both
# arrive either from configuration or from an API response, so both are
# checked before they are used in a path: an unchecked identifier
# holding a path separator or a parent-directory step would decide where
# a cache file lands.
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_LISTING_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,64}$")

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
    global CACHE_REPOSITORY_DIR
    global CACHE_YOUTUBE_DIR, CACHE_YOUTUBE_VIDEOS_DIR, CACHE_YOUTUBE_LISTINGS_DIR
    CACHE_DIR = str(path)
    CACHE_META_PATH = os.path.join(CACHE_DIR, "meta.json")
    CACHE_PAGES_DIR = os.path.join(CACHE_DIR, "pages")
    CACHE_GITHUB_DIR = os.path.join(CACHE_DIR, "github")
    CACHE_GITHUB_BLOBS_DIR = os.path.join(CACHE_GITHUB_DIR, "blobs")
    CACHE_GITHUB_REPOSITORIES_DIR = os.path.join(CACHE_GITHUB_DIR, "repositories")
    CACHE_GITHUB_ANALYSIS_DIR = os.path.join(CACHE_GITHUB_DIR, "analysis")
    CACHE_REPOSITORY_DIR = os.path.join(CACHE_DIR, "repository")
    CACHE_YOUTUBE_DIR = os.path.join(CACHE_DIR, "youtube")
    CACHE_YOUTUBE_VIDEOS_DIR = os.path.join(CACHE_YOUTUBE_DIR, "videos")
    CACHE_YOUTUBE_LISTINGS_DIR = os.path.join(CACHE_YOUTUBE_DIR, "listings")


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


### Repository Deposit Cache ###

def deposit_text_path(deposit_id):
    """
    The on-disk path for the text a repository extracted from one
    deposit's files.

    Args:
        deposit_id (str): the repository's identifier for the deposit, a
            lowercase UUID.

    Returns:
        str: path under CACHE_REPOSITORY_DIR.

    Raises:
        ValueError: if deposit_id is not a lowercase UUID. The identifier
            arrives in an API response, so it is checked rather than
            trusted: an unchecked value used in a path could reach
            outside the cache directory.
    """
    if not isinstance(deposit_id, str) or not _DEPOSIT_ID_RE.match(deposit_id):
        raise ValueError(f"a deposit identifier must be a lowercase UUID; got {deposit_id!r}.")
    return os.path.join(CACHE_REPOSITORY_DIR, deposit_id + ".json")


def load_deposit_text(deposit_id, last_modified):
    """
    Reads stored text for one deposit, but only while it is still current.

    The repository reports when each deposit last changed, and that stamp
    is stored beside the text. Text stored under a different stamp is
    ignored, so an edited deposit is read again instead of being served
    from a stale copy.

    Args:
        deposit_id (str): the deposit's identifier.
        last_modified (str): the change stamp the repository reports for
            the deposit now, compared exactly as given.

    Returns:
        str | None: the stored text, or None when nothing is stored, the
        stored copy belongs to an older version of the deposit, or the
        file cannot be read. Anything unreadable degrades to a fresh
        download rather than failing the build.
    """
    try:
        with open(deposit_text_path(deposit_id), "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(stored, dict) or stored.get("last_modified") != last_modified:
        return None
    text = stored.get("text")
    return text if isinstance(text, str) else None


def save_deposit_text(deposit_id, last_modified, text):
    """
    Stores the text extracted from one deposit's files, with the change
    stamp it belongs to.

    Args:
        deposit_id (str): the deposit's identifier.
        last_modified (str): the change stamp the repository reported.
        text (str): the extracted text, as the repository served it.

    Raises:
        ValueError: if deposit_id is not a lowercase UUID.
        OSError: if the cache directory or file cannot be written.
    """
    os.makedirs(CACHE_REPOSITORY_DIR, exist_ok=True)
    path = deposit_text_path(deposit_id)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"last_modified": last_modified, "text": text}, f)
    os.replace(tmp_path, path)


### Code Analysis Cache ###

def analysis_path(blob_sha):
    """
    The on-disk path for what the parsers found in one file.

    Args:
        blob_sha (str): the Git object name of the file that was read.

    Returns:
        str: path under CACHE_GITHUB_ANALYSIS_DIR.

    Raises:
        ValueError: if blob_sha is not forty lowercase hexadecimal
            characters, for the same reason a blob body's name is
            checked: it arrived in an API response.
    """
    if not isinstance(blob_sha, str) or not _BLOB_SHA_RE.match(blob_sha):
        raise ValueError(f"a blob SHA must be 40 lowercase hexadecimal characters; got {blob_sha!r}.")
    return os.path.join(CACHE_GITHUB_ANALYSIS_DIR, blob_sha + ".json")


def load_analysis(blob_sha, key):
    """
    Reads stored analysis for one file, but only while every part of it
    still applies.

    A parse depends on more than the file: the engine, its version, the
    grammar, the grammar's version, and the shape of the records
    themselves. All of that travels in the key, and a stored result under
    a different key is ignored, so upgrading a grammar reparses rather
    than serving what the old one said.

    Args:
        blob_sha (str): the file's Git object name.
        key (Mapping): what the analysis depended on.

    Returns:
        dict | None: the stored records, or None when nothing applies.
        Anything unreadable degrades to parsing again.
    """
    try:
        with open(analysis_path(blob_sha), "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(stored, dict) or stored.get("key") != dict(key):
        return None
    records = stored.get("records")
    return records if isinstance(records, dict) else None


def save_analysis(blob_sha, key, records):
    """
    Stores what the parsers found in one file, with everything the result
    depended on.

    Args:
        blob_sha (str): the file's Git object name.
        key (Mapping): the engine, versions, and schema the result
            belongs to.
        records (Mapping): the file's records, as plain data.

    Raises:
        ValueError: if blob_sha is not a Git object name.
        OSError: if the cache directory or file cannot be written.
    """
    os.makedirs(CACHE_GITHUB_ANALYSIS_DIR, exist_ok=True)
    path = analysis_path(blob_sha)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"key": dict(key), "records": dict(records)}, f)
    os.replace(tmp_path, path)


### YouTube Cache ###

def video_path(video_id):
    """
    The on-disk path for one video's title and caption transcript.

    Args:
        video_id (str): YouTube's identifier for the video, eleven
            characters from the base64url alphabet.

    Returns:
        str: path under CACHE_YOUTUBE_VIDEOS_DIR.

    Raises:
        ValueError: if video_id is not a YouTube video identifier. The
            identifier arrives from configuration or from an API
            response, so it is checked rather than trusted: an unchecked
            value used in a path could reach outside the cache directory.
    """
    if not isinstance(video_id, str) or not _VIDEO_ID_RE.match(video_id):
        raise ValueError(
            f"a YouTube video identifier must be eleven characters of "
            f"letters, digits, hyphen, or underscore; got {video_id!r}."
        )
    return os.path.join(CACHE_YOUTUBE_VIDEOS_DIR, video_id + ".json")


def load_video(video_id):
    """
    Reads one video's stored title and transcript.

    There is no freshness check, and that is deliberate. YouTube blocks
    requests from cloud-provider address ranges, so a scheduled build
    cannot refetch a transcript even to confirm one it already holds. A
    stored transcript is therefore authoritative until somebody deletes
    it. Captions that changed after they were stored are picked up by
    deleting the file and building again on a machine YouTube answers.

    Args:
        video_id (str): the video's identifier.

    Returns:
        dict | None: a record holding `title`, `published_at`,
        `language`, and `segments`, or None when nothing is stored or
        the stored file cannot be read. Anything unreadable degrades to
        a fresh fetch rather than failing the build.

    Raises:
        ValueError: if video_id is not a YouTube video identifier.
    """
    try:
        with open(video_path(video_id), "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(stored, dict) or not isinstance(stored.get("segments"), list):
        return None
    return stored


def save_video(video_id, title, published_at, language, segments):
    """
    Stores one video's title and caption transcript.

    Args:
        video_id (str): the video's identifier.
        title (str): the video's title, as YouTube reported it.
        published_at (str): when the video was published, as YouTube
            reported it: an ISO 8601 stamp in UTC.
        language (str): the caption track's language code.
        segments (Sequence[Mapping]): the caption lines, each holding
            `text` and `start` in seconds from the beginning.

    Raises:
        ValueError: if video_id is not a YouTube video identifier.
        OSError: if the cache directory or file cannot be written.
    """
    os.makedirs(CACHE_YOUTUBE_VIDEOS_DIR, exist_ok=True)
    path = video_path(video_id)
    tmp_path = path + ".tmp"
    record = {
        "title": title,
        "published_at": published_at,
        "language": language,
        "segments": [
            {"text": segment["text"], "start": float(segment["start"])}
            for segment in segments
        ],
    }
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(record, f)
    os.replace(tmp_path, path)


def listing_path(listing_id):
    """
    The on-disk path for the video identifiers one playlist or channel
    held the last time it was listed.

    Args:
        listing_id (str): a playlist or channel identifier.

    Returns:
        str: path under CACHE_YOUTUBE_LISTINGS_DIR.

    Raises:
        ValueError: if listing_id is not a YouTube playlist or channel
            identifier. Checked for the same reason a video identifier
            is: it reaches a file path.
    """
    if not isinstance(listing_id, str) or not _LISTING_ID_RE.match(listing_id):
        raise ValueError(
            f"a YouTube playlist or channel identifier must be 2 to 64 characters "
            f"of letters, digits, hyphen, or underscore; got {listing_id!r}."
        )
    return os.path.join(CACHE_YOUTUBE_LISTINGS_DIR, listing_id + ".json")


def load_listing(listing_id):
    """
    Reads the video identifiers stored for one playlist or channel.

    Stored without a freshness check, for the reason load_video gives: a
    build that cannot reach YouTube still has to produce the same
    knowledge base it produced last time.

    Args:
        listing_id (str): the playlist or channel identifier.

    Returns:
        tuple[str, ...] | None: the stored video identifiers in listing
        order, or None when nothing is stored or the file cannot be read.

    Raises:
        ValueError: if listing_id is not a playlist or channel identifier.
    """
    try:
        with open(listing_path(listing_id), "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(stored, dict):
        return None
    video_ids = stored.get("video_ids")
    if not isinstance(video_ids, list):
        return None
    return tuple(v for v in video_ids if isinstance(v, str))


def save_listing(listing_id, video_ids):
    """
    Stores the video identifiers one playlist or channel holds.

    Args:
        listing_id (str): the playlist or channel identifier.
        video_ids (Sequence[str]): the video identifiers, in listing order.

    Raises:
        ValueError: if listing_id is not a playlist or channel identifier.
        OSError: if the cache directory or file cannot be written.
    """
    os.makedirs(CACHE_YOUTUBE_LISTINGS_DIR, exist_ok=True)
    path = listing_path(listing_id)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"video_ids": list(video_ids)}, f)
    os.replace(tmp_path, path)
