"""
Summary: Chooses how the crawler opens its connections. Some bot-protection
services score the TLS handshake and answer a challenge to any client that
does not open a connection the way a browser does, whatever name it gives.
This module offers three transports: `plain`, an ordinary session;
`browser`, a session whose handshake matches a browser's; and `auto`, the
default, which tries a plain request first and retries once over the
browser handshake only when the answer is a challenge. The crawler's own
User-Agent is sent either way: only the shape of the handshake changes.
Every host's transport is decided once and reported once. The session
the build fetches through also paces requests per host, so a site is
asked at most once per `delay_seconds` however many sources and workers
are reading it.

This file is part of Extractium™
extractium/core/transport.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-12
Last Modified: 2026-09-15
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
__date__ = "2026-09-15"

import threading
import time
from urllib.parse import urlsplit

import requests

### Constants ###

# The three settings, and the default. `auto` costs nothing on a site that
# never challenges, which is why it is the default.
TRANSPORT_PLAIN = "plain"
TRANSPORT_BROWSER = "browser"
TRANSPORT_AUTO = "auto"
TRANSPORT_MODES = (TRANSPORT_AUTO, TRANSPORT_BROWSER, TRANSPORT_PLAIN)
DEFAULT_TRANSPORT = TRANSPORT_AUTO

# The browser whose handshake is imitated. Any current browser scores well
# enough; one is named so the handshake is the same on every machine.
BROWSER_PROFILE = "chrome"

# How a challenge is recognised: the status and the header the protection
# service sets on the page it answers instead of the one asked for. A plain
# 403 without the header is a refusal of a different kind, such as a block
# on the network the build runs from, and is left alone.
CHALLENGE_STATUS = 403
CHALLENGE_HEADER = "cf-mitigated"
CHALLENGE_VALUE = "challenge"

# What the build prints, once per host, when the transport is decided.
PLAIN_REPORT = "transport: {host} served over the plain transport"
BROWSER_REPORT = ("transport: {host} served over the browser transport "
                  "(a plain request was answered with a challenge)")
UNAVAILABLE_REPORT = ("transport: {host} answered with a challenge, and the browser "
                      "transport is not installed (pip install curl_cffi)")

# The package that provides the browser handshake. Imported when a browser
# session is first needed, so a build that is never challenged never
# loads its native library.
BROWSER_PACKAGE = "curl_cffi"


class TransportUnavailable(RuntimeError):
    """The browser transport was asked for and its package is not installed."""


### Recognising A Challenge ###

def is_challenge(response):
    """
    Whether a response is a bot-protection challenge rather than a page.

    Args:
        response: any object with `status_code` and a `headers` mapping.

    Returns:
        bool: True for a 403 carrying the challenge header.
    """
    if getattr(response, "status_code", None) != CHALLENGE_STATUS:
        return False
    headers = getattr(response, "headers", None) or {}
    value = headers.get(CHALLENGE_HEADER) or headers.get(CHALLENGE_HEADER.title()) or ""
    return value.strip().lower() == CHALLENGE_VALUE


def host_of(url):
    """The lowercased host a URL names, or an empty string."""
    return (urlsplit(url).hostname or "").lower()


def is_robots(url):
    """Whether a URL is a site's robots.txt."""
    return urlsplit(url).path.lower() == "/robots.txt"


### Sessions ###

def browser_session():
    """
    A session that opens its connections the way a browser does.

    The session speaks the same `get(url, headers=, timeout=)` as a
    requests session and answers with the same `status_code`, `headers`,
    `text`, `content`, `url`, and `raise_for_status()`, which is all the
    fetch layer reads. Headers given per request win over the profile's
    own, so the crawler's User-Agent is what the server sees.

    Returns:
        A curl_cffi session impersonating BROWSER_PROFILE.

    Raises:
        TransportUnavailable: if curl_cffi is not installed.
    """
    try:
        from curl_cffi import requests as browser_requests
    except ImportError as error:
        raise TransportUnavailable(
            f"the browser transport needs the {BROWSER_PACKAGE} package: pip install {BROWSER_PACKAGE}"
        ) from error
    return browser_requests.Session(impersonate=BROWSER_PROFILE)


class AutoSession:
    """
    A session that starts plain and switches to the browser handshake, per
    host, the first time a host answers a challenge.

    The switch is made once per host and kept, so the second and every
    later page of a challenged site costs one request rather than two.
    A host that was never challenged keeps the plain transport. Nothing
    from either session is written anywhere; cookies live and die with
    the sessions, and the fetch cache stores page text and validators only.
    """

    def __init__(self, plain=None, browser_factory=browser_session, progress=None,
                 delay_seconds=0.0, sleep=time.sleep):
        """
        Args:
            plain: the ordinary session; a requests.Session by default.
            browser_factory (Callable): builds the browser session on first
                need. Injected so tests never load the native library.
            progress (Callable[[str], None] | None): receives one line per
                host when its transport is decided.
            delay_seconds (float): the build's pause between requests,
                applied before a retry too, so a challenged site is not
                asked twice in quick succession.
            sleep (Callable[[float], None]): how the pause is taken.
        """
        self.plain = plain if plain is not None else requests.Session()
        self.browser_factory = browser_factory
        self.progress = progress or (lambda message: None)
        self.delay_seconds = delay_seconds
        self.sleep = sleep
        self.browser = None
        self.transport_by_host = {}
        self.unavailable_hosts = set()
        # Sources run in threads, so a host's transport is decided and
        # reported under a lock: two workers reaching one host at the same
        # moment would otherwise both announce it.
        self._lock = threading.Lock()

    def _browser(self):
        """The browser session, built on first use."""
        with self._lock:
            if self.browser is None:
                self.browser = self.browser_factory()
            return self.browser

    def get(self, url, **kwargs):
        """
        Fetches one URL over whichever transport its host has earned.

        Args:
            url (str): the address.
            **kwargs: passed to the underlying session's get, unchanged.

        Returns:
            The response from the transport that answered last. A challenge
            that the browser transport cannot be tried for is returned as
            it is, so the caller reports the refusal as usual.
        """
        return self._request("get", url, **kwargs)

    def post(self, url, **kwargs):
        """
        Sends one request with a body, the way get fetches, over whichever
        transport the host has earned. A listing that pages through a
        site's own interface asks this way, and the host's transport is
        decided by exactly the same rule.
        """
        return self._request("post", url, **kwargs)

    def _request(self, method, url, **kwargs):
        """One request by either method, with the per-host transport rule applied."""
        host = host_of(url)
        if self.transport_by_host.get(host) == TRANSPORT_BROWSER:
            return getattr(self._browser(), method)(url, **kwargs)

        response = getattr(self.plain, method)(url, **kwargs)
        if not is_challenge(response):
            # robots.txt is a static file the protection never challenges,
            # so its answer says nothing about how the host's pages will be
            # served and does not settle the host's transport.
            if not is_robots(url):
                self._settle(host, TRANSPORT_PLAIN, PLAIN_REPORT)
            return response

        try:
            browser = self._browser()
        except TransportUnavailable:
            with self._lock:
                if host not in self.unavailable_hosts:
                    self.unavailable_hosts.add(host)
                    self.progress(UNAVAILABLE_REPORT.format(host=host))
            return response

        if self.delay_seconds > 0:
            self.sleep(self.delay_seconds)
        retried = getattr(browser, method)(url, **kwargs)
        # The host keeps the browser transport even when the retry was
        # refused too: the plain transport is known not to work there.
        self._settle(host, TRANSPORT_BROWSER, BROWSER_REPORT)
        return retried

    def _settle(self, host, mode, report):
        """
        Records a host's transport and reports it, once. The plain
        transport is recorded only for a host with no decision yet; the
        browser transport replaces a plain decision, because a challenge
        after a plain answer means the plain transport stopped working.
        """
        with self._lock:
            current = self.transport_by_host.get(host)
            if current == mode or (mode == TRANSPORT_PLAIN and current is not None):
                return
            self.transport_by_host[host] = mode
            self.progress(report.format(host=host))

    def summary_lines(self):
        """
        One line per host that needed the browser transport, for the build
        summary, so the choice is on record at the end as well as in the log.
        """
        lines = [f"transport: {host} was served over the browser transport"
                 for host, mode in sorted(self.transport_by_host.items()) if mode == TRANSPORT_BROWSER]
        lines.extend(f"transport: {host} answered with a challenge the browser transport could not be tried for"
                     for host in sorted(self.unavailable_hosts))
        return lines

    def close(self):
        """Closes both sessions."""
        self.plain.close()
        if self.browser is not None:
            self.browser.close()


### Pacing ###

class HostPacer:
    """
    Keeps the requests to one host at least `delay_seconds` apart, however
    many threads are sending them.

    Politeness is a promise to a site rather than to a source. Sources run
    at the same time, and a crawl keeps several fetches in flight, so the
    pause between requests cannot live in any one of them: two sources
    reading one host would together send twice the rate the setting
    promises. Every request asks here first and waits its turn for that
    host alone. Hosts never wait for one another, and the request itself
    runs outside the wait, so several answers from one host may be in
    flight at once while their starts stay one delay apart.

    Args:
        delay_seconds (float): the least time between two request starts
            to the same host; 0 or less means no pacing at all.
        clock (Callable[[], float]): a monotonic clock, in seconds.
        sleep (Callable[[float], None]): how the wait is taken.
    """

    def __init__(self, delay_seconds=0.0, clock=time.monotonic, sleep=time.sleep):
        self.delay_seconds = float(delay_seconds or 0.0)
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._host_locks = {}
        self._next_start = {}

    def wait(self, host):
        """
        Blocks until a request to `host` may start, then claims that start.

        Args:
            host (str): the lowercased host name, or an empty string for an
                address without one, which is paced like any other host.
        """
        if self.delay_seconds <= 0:
            return
        with self._lock:
            host_lock = self._host_locks.setdefault(host, threading.Lock())
        with host_lock:
            pause = self._next_start.get(host, 0.0) - self.clock()
            if pause > 0:
                self.sleep(pause)
            self._next_start[host] = self.clock() + self.delay_seconds


class PacedSession:
    """
    A session that applies a HostPacer to every request before handing it
    to the session underneath.

    Every source in a build fetches through the one session the command
    line makes, so this is the one place a per-host rule reaches every
    request, robots.txt included. The wrapper answers the same `get`,
    `post`, `close`, and `summary_lines` the fetch layer and the command
    line use, and any other attribute is read from the session underneath.

    Args:
        session: the session that sends the requests.
        pacer (HostPacer): the per-host pacing rule.
    """

    def __init__(self, session, pacer):
        self.session = session
        self.pacer = pacer

    def get(self, url, **kwargs):
        """Fetches one URL once its host's turn has come."""
        self.pacer.wait(host_of(url))
        return self.session.get(url, **kwargs)

    def post(self, url, **kwargs):
        """Sends one request with a body once its host's turn has come."""
        self.pacer.wait(host_of(url))
        return self.session.post(url, **kwargs)

    def summary_lines(self):
        """The session's summary lines, or none when it keeps no summary."""
        if hasattr(self.session, "summary_lines"):
            return self.session.summary_lines()
        return []

    def close(self):
        """Closes the session underneath."""
        self.session.close()

    def __getattr__(self, name):
        # Reached only for attributes this wrapper does not define, so a
        # caller that inspects the session underneath still can.
        return getattr(self.session, name)


def make_session(mode=DEFAULT_TRANSPORT, progress=None, delay_seconds=0.0):
    """
    The session a build should fetch through, for one transport setting.

    Whatever the mode, the session paces requests per host: a host is
    asked at most once per `delay_seconds`, across every source and every
    worker in the build. See HostPacer.

    Args:
        mode (str): one of TRANSPORT_MODES.
        progress (Callable[[str], None] | None): where the per-host
            transport lines go.
        delay_seconds (float): the least time between two requests to
            the same host.

    Returns:
        PacedSession: a session with a requests-style `get`, `post`, and
        `close`, whose `session` attribute is the transport underneath.

    Raises:
        ValueError: for a mode that is not one of TRANSPORT_MODES.
        TransportUnavailable: for `browser` when curl_cffi is missing.
    """
    if mode == TRANSPORT_PLAIN:
        session = requests.Session()
    elif mode == TRANSPORT_BROWSER:
        session = browser_session()
    elif mode == TRANSPORT_AUTO:
        session = AutoSession(progress=progress, delay_seconds=delay_seconds)
    else:
        raise ValueError(f"transport must be one of {', '.join(TRANSPORT_MODES)}, not {mode!r}.")
    return PacedSession(session, HostPacer(delay_seconds))
