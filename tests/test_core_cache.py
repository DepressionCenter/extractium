"""
Summary: Tests pinning extractium.core.cache's and extractium.core.fetch's
.kb_cache/ behavior: load_cache_meta, save_cache_meta (atomic write),
cache_page_path, _flush_cache_meta_periodically, _store_fetched_page, and
fetch()'s full conditional-GET contract. Mirrors tests/test_cache.py
(which pins the same behavior on the frozen reference script) against the
real, ported implementation, proving the port is behavior-identical. All
network access is replaced by FakeSession/FakeResponse from conftest.py --
nothing here touches a real network or the real repo tree (cache paths are
redirected via the isolated_core_cache fixture).

This file is part of Extractium™
tests/test_core_cache.py

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

from extractium.core import cache, fetch
from tests.conftest import FakeResponse


# ---------------------------------------------------------------------------
# load_cache_meta / save_cache_meta / cache_page_path
# ---------------------------------------------------------------------------

def test_load_cache_meta_missing_file_returns_empty_dict(isolated_core_cache):
    assert cache.load_cache_meta() == {}


def test_load_cache_meta_reads_existing_valid_json(isolated_core_cache):
    os.makedirs(isolated_core_cache, exist_ok=True)
    with open(cache.CACHE_META_PATH, "w", encoding="utf-8") as f:
        json.dump({"https://example.org/a": {"etag": "abc"}}, f)
    assert cache.load_cache_meta() == {"https://example.org/a": {"etag": "abc"}}


def test_load_cache_meta_invalid_json_returns_empty_dict(isolated_core_cache):
    os.makedirs(isolated_core_cache, exist_ok=True)
    with open(cache.CACHE_META_PATH, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert cache.load_cache_meta() == {}


def test_save_cache_meta_writes_atomically_no_leftover_tmp_file(isolated_core_cache):
    meta = {"https://example.org/a": {"etag": "abc", "fetched_at": 123.0}}
    cache.save_cache_meta(meta)
    assert os.path.exists(cache.CACHE_META_PATH)
    with open(cache.CACHE_META_PATH, encoding="utf-8") as f:
        assert json.load(f) == meta
    assert not os.path.exists(cache.CACHE_META_PATH + ".tmp")


def test_cache_page_path_is_sha1_of_url_under_pages_dir(isolated_core_cache):
    url = "https://example.org/kb/article-1"
    expected_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()
    expected = os.path.join(cache.CACHE_PAGES_DIR, expected_hash + ".html")
    assert cache.cache_page_path(url) == expected


# ---------------------------------------------------------------------------
# fetch() -- conditional-GET contract
# ---------------------------------------------------------------------------

def test_fetch_200_first_visit_sends_no_conditional_headers_and_stores_validators(
    isolated_core_cache, fake_session_factory
):
    url = "https://example.org/kb/article-1"
    session = fake_session_factory(
        {url: FakeResponse(status_code=200, headers={
            "Content-Type": "text/html",
            "ETag": '"v1"',
            "Last-Modified": "Mon, 17 Aug 2026 00:00:00 GMT",
        }, text="<html><body><h1>Hi</h1></body></html>")}
    )
    cache_meta = {}

    result = fetch.fetch(session, url, cache_meta)

    assert session.calls[0]["headers"].get("If-None-Match") is None
    assert session.calls[0]["headers"].get("If-Modified-Since") is None
    assert result.find("h1").get_text() == "Hi"
    assert cache_meta[url]["etag"] == '"v1"'
    assert cache_meta[url]["last_modified"] == "Mon, 17 Aug 2026 00:00:00 GMT"
    assert cache_meta[url]["sha256"] == hashlib.sha256(
        "<html><body><h1>Hi</h1></body></html>".encode("utf-8")
    ).hexdigest()
    assert os.path.exists(cache.cache_page_path(url))


def test_fetch_sends_stored_validators_verbatim_including_weak_prefix(
    isolated_core_cache, fake_session_factory
):
    url = "https://example.org/kb/article-1"
    # A weak validator (W/ prefix) must be sent exactly as stored, never
    # normalized -- per fetch()'s own docstring.
    cache_meta = {
        url: {"etag": 'W/"v1"', "last_modified": "Mon, 17 Aug 2026 00:00:00 GMT"}
    }
    os.makedirs(cache.CACHE_PAGES_DIR, exist_ok=True)
    with open(cache.cache_page_path(url), "w", encoding="utf-8") as f:
        f.write("<html><body><h1>Cached</h1></body></html>")

    session = fake_session_factory({url: FakeResponse(status_code=304)})
    result = fetch.fetch(session, url, cache_meta)

    assert session.calls[0]["headers"]["If-None-Match"] == 'W/"v1"'
    assert session.calls[0]["headers"]["If-Modified-Since"] == "Mon, 17 Aug 2026 00:00:00 GMT"
    assert result.find("h1").get_text() == "Cached"
    assert cache_meta[url]["fetched_at"] is not None


def test_fetch_no_head_request_ever_issued(isolated_core_cache, fake_session_factory):
    # fetch() only ever calls session.get -- FakeSession has no get-only
    # surface that would silently accept a .head() call, so a real HEAD
    # call would raise AttributeError; asserting every recorded call has a
    # "url"/"headers" shape from .get() is sufficient given FakeSession's
    # single get() method.
    url = "https://example.org/kb/article-1"
    session = fake_session_factory(
        {url: FakeResponse(status_code=200, headers={"Content-Type": "text/html"}, text="<html></html>")}
    )
    fetch.fetch(session, url, {})
    assert len(session.calls) == 1


def test_fetch_304_missing_cache_file_falls_back_to_plain_get(
    isolated_core_cache, fake_session_factory
):
    url = "https://example.org/kb/article-1"
    cache_meta = {url: {"etag": '"stale"', "last_modified": "Mon, 17 Aug 2026 00:00:00 GMT"}}
    # No page file written to disk -- the 304 disk-read will raise OSError.
    session = fake_session_factory(
        {
            url: [
                FakeResponse(status_code=304),
                FakeResponse(
                    status_code=200,
                    headers={"Content-Type": "text/html", "ETag": '"fresh"'},
                    text="<html><body><h1>Refetched</h1></body></html>",
                ),
            ]
        }
    )

    result = fetch.fetch(session, url, cache_meta)

    assert len(session.calls) == 2
    # First call carries the conditional headers; the fallback plain GET does not.
    assert session.calls[0]["headers"].get("If-None-Match") == '"stale"'
    assert "If-None-Match" not in session.calls[1]["headers"]
    assert result.find("h1").get_text() == "Refetched"
    assert cache_meta[url]["etag"] == '"fresh"'


def test_fetch_content_type_mismatch_returns_none_without_caching(
    isolated_core_cache, fake_session_factory
):
    url = "https://example.org/kb/article-1.json"
    session = fake_session_factory(
        {url: FakeResponse(status_code=200, headers={"Content-Type": "application/json"}, text="{}")}
    )
    cache_meta = {}

    result = fetch.fetch(session, url, cache_meta)

    assert result is None
    assert url not in cache_meta
    assert not os.path.exists(cache.cache_page_path(url))


def test_fetch_exception_returns_none(isolated_core_cache):
    class RaisingSession:
        def get(self, url, headers=None, timeout=None):
            raise ConnectionError("simulated network failure")

    result = fetch.fetch(RaisingSession(), "https://example.org/kb/article-1", {})
    assert result is None


def test_fetch_expect_html_false_returns_raw_text(isolated_core_cache, fake_session_factory):
    url = "https://raw.githubusercontent.com/example-org/example-repo/main/docs/setup.md"
    session = fake_session_factory(
        {url: FakeResponse(status_code=200, headers={"Content-Type": "text/plain"}, text="# Setup")}
    )
    result = fetch.fetch(session, url, {}, expect_html=False)
    assert result == "# Setup"


# ---------------------------------------------------------------------------
# _flush_cache_meta_periodically
# ---------------------------------------------------------------------------

def test_flush_cache_meta_periodically_saves_only_every_cache_save_interval(
    isolated_core_cache, monkeypatch
):
    # Patches cache.save_cache_meta (the real module attribute) and relies
    # on fetch.py reaching it via a qualified `cache.save_cache_meta(...)`
    # call rather than a value import -- proving the qualified-import rule
    # this port depends on for correct test isolation.
    calls = []
    monkeypatch.setattr(cache, "save_cache_meta", lambda meta: calls.append(meta))

    class _Session:
        pass

    session = _Session()
    cache_meta = {}
    for _ in range(cache.CACHE_SAVE_INTERVAL - 1):
        fetch._flush_cache_meta_periodically(session, cache_meta)
    assert calls == []

    fetch._flush_cache_meta_periodically(session, cache_meta)
    assert len(calls) == 1
