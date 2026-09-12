"""
Summary: Tests for the transport layer: a challenge recognised only by its
status and header, the automatic session retrying a challenged request
once over the browser handshake and keeping that choice per host, a plain
refusal left alone, the plain and browser settings never switching, the
per-host report made once, the pause taken before a retry, the browser
package's absence reported rather than fatal, conditional requests passing
through unchanged, and the fetch layer storing nothing from a challenge.
No test loads the native library and none contacts a live site.

This file is part of Extractium™
tests/test_transport.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-12
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
__date__ = "2026-09-12"

import os

import pytest
import requests

from extractium.core import fetch as fetching
from extractium.core import transport
from tests.conftest import FakeResponse, FakeSession

PAGE = "https://example.org/about"
OTHER = "https://example.org/team"
ELSEWHERE = "https://portal.example.edu/kb/"

HTML = {"content-type": "text/html; charset=utf-8"}
CHALLENGE = {"content-type": "text/html", "cf-mitigated": "challenge", "server": "cloudflare"}


def challenge():
    return FakeResponse(403, CHALLENGE, "<html>Just a moment</html>")


def page(text="<html><body><main>Hello</main></body></html>", **headers):
    return FakeResponse(200, {**HTML, **headers}, text)


class Recorder:
    """Collects progress lines."""

    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


def auto(plain_responses, browser_responses=None, **options):
    """An automatic session over two scripted fakes, the browser one built on demand."""
    plain = FakeSession(plain_responses)
    browser = FakeSession(browser_responses or {})
    built = []

    def factory():
        built.append(browser)
        return browser

    session = transport.AutoSession(plain=plain, browser_factory=factory, **options)
    return session, plain, browser, built


# ---------------------------------------------------------------------------
# Recognising a challenge
# ---------------------------------------------------------------------------

def test_a_challenge_is_a_403_carrying_the_challenge_header():
    assert transport.is_challenge(challenge()) is True
    assert transport.is_challenge(FakeResponse(403, {"CF-Mitigated": "Challenge"})) is True


@pytest.mark.parametrize("response", [
    FakeResponse(403, {}),
    FakeResponse(403, {"server": "cloudflare"}),
    FakeResponse(200, CHALLENGE),
    FakeResponse(429, CHALLENGE),
    FakeResponse(503, {"cf-mitigated": "challenge"}),
])
def test_a_refusal_without_the_header_or_with_another_status_is_not_a_challenge(response):
    assert transport.is_challenge(response) is False


# ---------------------------------------------------------------------------
# The automatic session
# ---------------------------------------------------------------------------

def test_a_challenged_request_is_retried_once_over_the_browser_transport():
    session, plain, browser, built = auto({PAGE: challenge()}, {PAGE: page()})

    response = session.get(PAGE, headers={"User-Agent": "Extractium"}, timeout=5)

    assert response.status_code == 200
    assert len(plain.calls) == 1
    assert len(browser.calls) == 1
    assert built == [browser]


def test_the_retry_sends_the_same_headers_so_the_crawler_still_names_itself():
    session, plain, browser, _ = auto({PAGE: challenge()}, {PAGE: page()})
    headers = {"User-Agent": "Extractium/0.1 (+https://example.org)", "If-None-Match": '"abc"'}

    session.get(PAGE, headers=headers, timeout=5)

    assert browser.calls[0]["headers"] == headers
    assert browser.calls[0]["timeout"] == 5


def test_a_host_that_was_challenged_once_uses_the_browser_transport_from_then_on():
    session, plain, browser, built = auto({PAGE: challenge(), OTHER: challenge()}, {PAGE: page(), OTHER: page()})

    session.get(PAGE)
    session.get(OTHER)

    assert [call["url"] for call in plain.calls] == [PAGE]
    assert [call["url"] for call in browser.calls] == [PAGE, OTHER]
    assert len(built) == 1


def test_a_host_that_was_never_challenged_stays_on_the_plain_transport():
    session, plain, browser, built = auto({ELSEWHERE: page(), PAGE: challenge()}, {PAGE: page()})

    session.get(ELSEWHERE)
    session.get(PAGE)
    session.get(ELSEWHERE)

    assert [call["url"] for call in plain.calls] == [ELSEWHERE, PAGE, ELSEWHERE]
    assert [call["url"] for call in browser.calls] == [PAGE]
    assert session.transport_by_host == {"example.org": "browser", "portal.example.edu": "plain"}


def test_robots_txt_does_not_settle_a_host_s_transport():
    """The protection never challenges a static file, so the pages may still be challenged."""
    progress = Recorder()
    robots = "https://example.org/robots.txt"
    session, plain, browser, _ = auto({robots: FakeResponse(200, {"content-type": "text/plain"}, "User-agent: *"),
                                       PAGE: challenge()}, {PAGE: page()}, progress=progress)

    session.get(robots)
    session.get(PAGE)

    assert progress.lines == [
        "transport: example.org served over the browser transport (a plain request was answered with a challenge)",
    ]
    assert [call["url"] for call in plain.calls] == [robots, PAGE]


def test_a_plain_403_without_the_challenge_header_is_left_alone():
    session, plain, browser, built = auto({PAGE: FakeResponse(403, {"content-type": "text/html"})})

    response = session.get(PAGE)

    assert response.status_code == 403
    assert built == []
    assert browser.calls == []


def test_a_challenge_the_browser_transport_cannot_answer_either_is_returned_as_the_last_answer():
    session, plain, browser, _ = auto({PAGE: challenge()}, {PAGE: FakeResponse(403, CHALLENGE)})

    response = session.get(PAGE)

    assert response.status_code == 403
    assert session.transport_by_host["example.org"] == "browser"


def test_the_transport_is_reported_once_per_host():
    progress = Recorder()
    session, *_ = auto({PAGE: challenge(), OTHER: challenge(), ELSEWHERE: page()}, {PAGE: page(), OTHER: page()},
                       progress=progress)

    for url in (PAGE, OTHER, ELSEWHERE, ELSEWHERE):
        session.get(url)

    assert progress.lines == [
        "transport: example.org served over the browser transport (a plain request was answered with a challenge)",
        "transport: portal.example.edu served over the plain transport",
    ]
    assert session.summary_lines() == ["transport: example.org was served over the browser transport"]


def test_the_pause_between_requests_is_taken_before_a_retry():
    pauses = []
    session, *_ = auto({PAGE: challenge()}, {PAGE: page()}, delay_seconds=0.5, sleep=pauses.append)

    session.get(PAGE)

    assert pauses == [0.5]


def test_no_pause_is_taken_when_the_build_has_none():
    pauses = []
    session, *_ = auto({PAGE: challenge()}, {PAGE: page()}, delay_seconds=0, sleep=pauses.append)

    session.get(PAGE)

    assert pauses == []


def test_a_missing_browser_package_is_reported_once_and_the_challenge_returned():
    progress = Recorder()

    def missing():
        raise transport.TransportUnavailable("the browser transport needs the curl_cffi package")

    session = transport.AutoSession(plain=FakeSession({PAGE: challenge(), OTHER: challenge()}),
                                    browser_factory=missing, progress=progress)

    first = session.get(PAGE)
    second = session.get(OTHER)

    assert first.status_code == 403 and second.status_code == 403
    assert progress.lines == [
        "transport: example.org answered with a challenge, and the browser transport is not installed "
        "(pip install curl_cffi)",
    ]
    assert session.summary_lines() == [
        "transport: example.org answered with a challenge the browser transport could not be tried for",
    ]


def test_closing_closes_both_sessions_and_a_browser_session_that_was_never_built_is_not_built_to_be_closed():
    closed = []

    class Closable(FakeSession):
        def close(self):
            closed.append(self)

    plain = Closable({PAGE: page()})
    browser = Closable({})
    session = transport.AutoSession(plain=plain, browser_factory=lambda: browser)
    session.get(PAGE)
    session.close()

    assert closed == [plain]


# ---------------------------------------------------------------------------
# The settings
# ---------------------------------------------------------------------------

def test_the_plain_setting_is_an_ordinary_session_that_never_switches():
    session = transport.make_session("plain")

    assert isinstance(session, requests.Session)
    assert not hasattr(session, "transport_by_host")


def test_the_browser_setting_builds_the_browser_session_at_once(monkeypatch):
    built = []
    monkeypatch.setattr(transport, "browser_session", lambda: built.append("browser") or FakeSession({}))

    transport.make_session("browser")

    assert built == ["browser"]


def test_the_automatic_setting_is_the_default_and_builds_nothing_native_until_challenged(monkeypatch):
    monkeypatch.setattr(transport, "browser_session", lambda: pytest.fail("built too early"))

    session = transport.make_session()

    assert isinstance(session, transport.AutoSession)
    assert session.browser is None


def test_an_unknown_setting_is_refused():
    with pytest.raises(ValueError, match="transport must be one of"):
        transport.make_session("proxy")


def test_the_browser_session_says_what_to_install_when_its_package_is_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("curl_cffi"):
            raise ImportError("no module named curl_cffi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)

    with pytest.raises(transport.TransportUnavailable, match="pip install curl_cffi"):
        transport.browser_session()


# ---------------------------------------------------------------------------
# Through the fetch layer
# ---------------------------------------------------------------------------

def test_a_challenged_page_is_fetched_through_the_retry_and_only_the_page_is_cached(isolated_core_cache):
    session, plain, browser, _ = auto({PAGE: challenge()}, {PAGE: page(etag='"v1"')})
    cache_meta = {}

    document = fetching.fetch(session, PAGE, cache_meta, user_agent="Extractium/test")

    assert document is not None and document.find("main").get_text() == "Hello"
    assert cache_meta[PAGE]["etag"] == '"v1"'
    stored = open(fetching.cache.cache_page_path(PAGE), encoding="utf-8").read()
    assert "Just a moment" not in stored
    assert not any("cookie" in key.lower() for key in cache_meta[PAGE])


def test_a_conditional_request_over_the_browser_transport_still_yields_not_modified(isolated_core_cache):
    session, plain, browser, _ = auto(
        {PAGE: challenge()},
        {PAGE: [page(etag='"v1"'), FakeResponse(304, {})]},
    )
    cache_meta = {}
    fetching.fetch(session, PAGE, cache_meta, user_agent="Extractium/test")

    document = fetching.fetch(session, PAGE, cache_meta, user_agent="Extractium/test")

    assert document is not None
    assert browser.calls[1]["headers"]["If-None-Match"] == '"v1"'
    assert len(plain.calls) == 1


def test_a_challenge_with_no_browser_transport_is_skipped_and_nothing_is_cached(isolated_core_cache):
    def missing():
        raise transport.TransportUnavailable("not installed")

    session = transport.AutoSession(plain=FakeSession({PAGE: challenge()}), browser_factory=missing)
    cache_meta = {}
    lines = []

    document = fetching.fetch(session, PAGE, cache_meta, user_agent="Extractium/test", progress=lines.append)

    assert document is None
    assert cache_meta == {}
    assert any("SKIP" in line and "403" in line for line in lines)
    assert not os.path.exists(fetching.cache.cache_page_path(PAGE))
