"""
Summary: Tests for the crawler etiquette in extractium.core.fetch: the
truthful default User-Agent and its header, the progress callback that
replaces printing, and RobotsPolicy (allow and disallow rules, the 4xx
and 5xx fallbacks, one request per origin, and the plain Accept header
the robots request carries). The conditional-GET cache behavior of
fetch() is pinned separately in tests/test_core_cache.py. Uses
FakeSession -- no real network.

This file is part of Extractium™
tests/test_core_fetch.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-04
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

from extractium import __version__
from extractium.core import cache, fetch
from tests.conftest import FakeResponse

ORIGIN = "https://example.org"
ROBOTS_URL = f"{ORIGIN}/robots.txt"


def robots(text, status=200):
    return FakeResponse(status_code=status, headers={"Content-Type": "text/plain"}, text=text)


# ---------------------------------------------------------------------------
# User-Agent and request headers
# ---------------------------------------------------------------------------

def test_default_user_agent_names_the_tool_and_its_repository():
    assert fetch.DEFAULT_USER_AGENT.startswith(f"Extractium/{__version__} ")
    assert "github.com/DepressionCenter/extractium" in fetch.DEFAULT_USER_AGENT
    assert "Mozilla" not in fetch.DEFAULT_USER_AGENT


def test_request_headers_carry_user_agent_accept_and_extras():
    headers = fetch.request_headers("ExampleBot/1.0", {"If-None-Match": '"v1"'})
    assert headers["User-Agent"] == "ExampleBot/1.0"
    assert headers["Accept"].startswith("text/html")
    assert headers["If-None-Match"] == '"v1"'


def test_fetch_sends_the_given_user_agent(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/page"
    session = fake_session_factory({url: FakeResponse(200, {"Content-Type": "text/html"}, "<html></html>")})

    fetch.fetch(session, url, {}, user_agent="ExampleBot/1.0")

    assert session.calls[0]["headers"]["User-Agent"] == "ExampleBot/1.0"


def test_fetch_defaults_to_the_truthful_user_agent(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/page"
    session = fake_session_factory({url: FakeResponse(200, {"Content-Type": "text/html"}, "<html></html>")})
    fetch.fetch(session, url, {})
    assert session.calls[0]["headers"]["User-Agent"] == fetch.DEFAULT_USER_AGENT


# ---------------------------------------------------------------------------
# Progress instead of print
# ---------------------------------------------------------------------------

def test_failed_fetch_reports_through_progress_and_prints_nothing(isolated_core_cache, fake_session_factory, capsys):
    url = f"{ORIGIN}/page"
    session = fake_session_factory({url: FakeResponse(status_code=500)})
    lines = []

    assert fetch.fetch(session, url, {}, progress=lines.append) is None

    assert lines == [f"  SKIP {url} -- 500 error"]
    assert capsys.readouterr().out == ""


def test_cache_hit_reports_through_progress(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/page"
    cache_meta = {url: {"etag": '"v1"'}}
    os.makedirs(cache.CACHE_PAGES_DIR, exist_ok=True)
    with open(cache.cache_page_path(url), "w", encoding="utf-8") as f:
        f.write("<html><body>cached</body></html>")
    session = fake_session_factory({url: FakeResponse(status_code=304)})
    lines = []

    fetch.fetch(session, url, cache_meta, progress=lines.append)

    assert lines == ["       (cached, not modified)"]


def test_fetch_without_progress_stays_silent(isolated_core_cache, fake_session_factory, capsys):
    url = f"{ORIGIN}/page"
    session = fake_session_factory({url: FakeResponse(status_code=404)})
    assert fetch.fetch(session, url, {}) is None
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# RobotsPolicy
# ---------------------------------------------------------------------------

def test_robots_policy_applies_disallow_and_allow_rules(fake_session_factory):
    session = fake_session_factory({ROBOTS_URL: robots("User-agent: *\nDisallow: /private/\nAllow: /\n")})
    policy = fetch.RobotsPolicy(session, "ExampleBot/1.0")
    assert policy.allows(f"{ORIGIN}/public/page") is True
    assert policy.allows(f"{ORIGIN}/private/page") is False


def test_robots_policy_matches_the_crawler_by_product_name(fake_session_factory):
    text = "User-agent: extractium\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    session = fake_session_factory({ROBOTS_URL: robots(text)})
    assert fetch.RobotsPolicy(session, fetch.DEFAULT_USER_AGENT).allows(f"{ORIGIN}/page") is False
    assert fetch.RobotsPolicy(session, "OtherBot/2.0").allows(f"{ORIGIN}/page") is True


def test_robots_policy_fetches_each_origin_once(fake_session_factory):
    session = fake_session_factory({
        ROBOTS_URL: robots("User-agent: *\nAllow: /\n"),
        "https://other.example/robots.txt": robots("User-agent: *\nDisallow: /\n"),
    })
    policy = fetch.RobotsPolicy(session, "ExampleBot/1.0")

    assert policy.allows(f"{ORIGIN}/a") and policy.allows(f"{ORIGIN}/b")
    assert policy.allows("https://other.example/a") is False

    assert [c["url"] for c in session.calls] == [ROBOTS_URL, "https://other.example/robots.txt"]


def test_robots_policy_requests_plain_text_with_the_user_agent(fake_session_factory):
    session = fake_session_factory({ROBOTS_URL: robots("User-agent: *\nAllow: /\n")})
    fetch.RobotsPolicy(session, "ExampleBot/1.0").allows(f"{ORIGIN}/a")
    headers = session.calls[0]["headers"]
    assert headers["User-Agent"] == "ExampleBot/1.0"
    assert headers["Accept"].startswith("text/plain")
    assert session.calls[0]["timeout"] == fetch.REQUEST_TIMEOUT_SECONDS


def test_robots_policy_missing_file_allows_everything(fake_session_factory):
    session = fake_session_factory({ROBOTS_URL: FakeResponse(status_code=404)})
    assert fetch.RobotsPolicy(session, "ExampleBot/1.0").allows(f"{ORIGIN}/anything") is True


def test_robots_policy_server_error_disallows_everything_and_reports(fake_session_factory):
    session = fake_session_factory({ROBOTS_URL: FakeResponse(status_code=503)})
    lines = []
    policy = fetch.RobotsPolicy(session, "ExampleBot/1.0", progress=lines.append)
    assert policy.allows(f"{ORIGIN}/anything") is False
    assert lines == [f"  robots.txt unavailable for {ORIGIN} (HTTP 503); skipping that site"]


def test_robots_policy_network_failure_disallows_everything_and_reports(fake_session_factory):
    session = fake_session_factory({})   # KeyError stands in for a connection failure
    lines = []
    policy = fetch.RobotsPolicy(session, "ExampleBot/1.0", progress=lines.append)
    assert policy.allows(f"{ORIGIN}/anything") is False
    assert len(lines) == 1 and lines[0].startswith(f"  robots.txt unreadable for {ORIGIN}")


def test_robots_policy_disabled_allows_without_a_request(fake_session_factory):
    session = fake_session_factory({})
    policy = fetch.RobotsPolicy(session, "ExampleBot/1.0", enabled=False)
    assert policy.allows(f"{ORIGIN}/anything") is True
    assert session.calls == []


# ---------------------------------------------------------------------------
# Content types, and document files
# ---------------------------------------------------------------------------

def test_any_text_type_but_html_is_accepted_when_text_is_expected(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/sheet"
    session = fake_session_factory({
        url: FakeResponse(200, {"Content-Type": "text/csv; charset=utf-8"}, "a,b\n1,2\n"),
    })
    assert fetch.fetch(session, url, {}, expect_html=False) == "a,b\n1,2\n"


def test_an_answer_of_the_wrong_kind_is_reported_with_where_it_landed(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/export"
    session = fake_session_factory({
        url: FakeResponse(200, {"Content-Type": "text/html"}, "<html/>", url=f"{ORIGIN}/login"),
    })
    lines = []
    assert fetch.fetch(session, url, {}, expect_html=False, progress=lines.append) is None
    assert lines == [
        f"  SKIP {url} -- answered text/html where text was expected; the request landed on {ORIGIN}/login"
    ]


def test_a_page_that_answers_plain_text_is_reported(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/page"
    session = fake_session_factory({url: FakeResponse(200, {"Content-Type": "text/plain"}, "words")})
    lines = []
    assert fetch.fetch(session, url, {}, expect_html=True, progress=lines.append) is None
    assert lines == [f"  SKIP {url} -- answered text/plain where HTML was expected"]


def test_a_byte_order_mark_is_dropped_from_a_text_answer(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/export"
    session = fake_session_factory({
        url: FakeResponse(200, {"Content-Type": "text/plain"}, chr(0xFEFF) + "Title line"),
    })
    assert fetch.fetch(session, url, {}, expect_html=False) == "Title line"


def test_fetch_bytes_stores_the_file_and_its_validators(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/files/plan.docx"
    data = b"PK\x03\x04 pretend"
    session = fake_session_factory({
        url: FakeResponse(200, {"Content-Type": "application/octet-stream", "ETag": '"abc"'}, content=data),
    })
    meta = {}

    assert fetch.fetch_bytes(session, url, meta, max_bytes=1_000) == data

    assert meta[url]["etag"] == '"abc"'
    assert meta[url]["sha256"] == hashlib.sha256(data).hexdigest()
    with open(cache.cache_document_path(url), "rb") as f:
        assert f.read() == data
    assert session.calls[0]["headers"]["Accept"].startswith("application/vnd.openxmlformats-officedocument")
    assert session.calls[0]["headers"]["User-Agent"] == fetch.DEFAULT_USER_AGENT


def test_fetch_bytes_serves_an_unchanged_file_from_the_cache(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/files/plan.docx"
    data = b"PK\x03\x04 pretend"
    session = fake_session_factory({url: [
        FakeResponse(200, {"Content-Type": "application/octet-stream", "ETag": '"abc"'}, content=data),
        FakeResponse(304),
    ]})
    meta = {}
    lines = []

    fetch.fetch_bytes(session, url, meta, max_bytes=1_000)
    assert fetch.fetch_bytes(session, url, meta, max_bytes=1_000, progress=lines.append) == data

    assert session.calls[1]["headers"]["If-None-Match"] == '"abc"'
    assert lines == ["       (cached, not modified)"]


def test_fetch_bytes_refuses_a_web_page_and_names_where_it_landed(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/files/plan.docx"
    session = fake_session_factory({
        url: FakeResponse(200, {"Content-Type": "text/html; charset=utf-8"}, "<html/>", url=f"{ORIGIN}/login"),
    })
    lines = []
    assert fetch.fetch_bytes(session, url, {}, max_bytes=1_000, progress=lines.append) is None
    assert lines == [
        f"  SKIP {url} -- answered text/html; charset=utf-8 where a document file was expected; "
        f"the request landed on {ORIGIN}/login"
    ]
    assert not os.path.exists(cache.cache_document_path(url))


def test_fetch_bytes_refuses_a_file_over_the_ceiling(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/files/plan.docx"
    session = fake_session_factory({
        url: FakeResponse(200, {"Content-Type": "application/octet-stream"}, content=b"x" * 11),
    })
    lines = []
    assert fetch.fetch_bytes(session, url, {}, max_bytes=10, progress=lines.append) is None
    assert lines == [f"  SKIP {url} -- 11 bytes is over the 10 byte ceiling for a document"]
    assert not os.path.exists(cache.cache_document_path(url))


def test_fetch_bytes_reports_a_failed_request_and_never_raises(isolated_core_cache, fake_session_factory):
    url = f"{ORIGIN}/files/plan.docx"
    session = fake_session_factory({url: FakeResponse(500)})
    lines = []
    assert fetch.fetch_bytes(session, url, {}, max_bytes=10, progress=lines.append) is None
    assert lines and lines[0].startswith(f"  SKIP {url} -- ")


def test_readable_files_pass_the_asset_check_and_leave_the_default_excludes():
    docx = "https://example.org/files/plan.docx"
    scope = dict(auto_prefix="https://example.org", origin="https://example.org", include_res=[], crawl_exclude_res=[])
    readable = re.compile(r"\.docx$", re.I)

    assert fetch.in_scope(docx, **scope) is False
    assert fetch.in_scope(docx, readable_re=readable, **scope) is True
    assert fetch.in_scope("https://example.org/a.pdf", readable_re=readable, **scope) is False
    assert r"\.docx$" in fetch.asset_exclude_patterns()
    assert r"\.docx$" not in fetch.asset_exclude_patterns(readable=("docx",))
    assert r"\.pdf$" in fetch.asset_exclude_patterns(readable=("docx",))
    assert fetch.ASSET_EXCLUDE_PATTERNS == fetch.asset_exclude_patterns()
