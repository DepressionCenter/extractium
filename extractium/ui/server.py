"""
Summary: The local page behind `extractium ui`. A threaded HTTP server
from the standard library, bound to the loopback address on a free
port, that serves the page's own files from an allowlist inside the
package, answers the page's small API for reading and writing the
settings file, mounts the Model Context Protocol endpoint at /mcp over
the compendium the settings file names, and serves the output folder
under /dist/. The address it opens carries a random session token that
every API request must present; every request must name the server's
own address as its Host, and every write must come from the page's own
origin, so a page from any other site, or a name that points at this
machine, cannot reach it. It quits on its own when no page has checked
in for ten minutes, when the page asks it to, or on Ctrl+C.

This file is part of Extractium™
extractium/ui/server.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-28
Last Modified: 2026-09-28
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
__date__ = "2026-09-28"

import hmac
import json
import pathlib
import secrets
import shutil
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from extractium import __version__
from extractium.adapters.container import full_container_file_name
from extractium.config import ConfigError, load_config
from extractium.mcp.http import DEFAULT_MCP_PATH, MAX_BODY_BYTES, handle_http_request
from extractium.mcp.server import ConfigurationError, KbServer, sentence_transformer_embedder
from extractium.search import load_container
from extractium.ui import settings as settings_module

### Constants ###

# The one address the server listens on. Nothing here is reachable from
# another computer, and the page relies on that.
HOST = "127.0.0.1"

# How long the server waits for a page to check in before it quits, so a
# closed tab does not leave a process running for days. The page checks
# in every PING_INTERVAL_SECONDS while it is open.
IDLE_SECONDS = 600
PING_INTERVAL_SECONDS = 30

# The header the page sends the session token in, and how many random
# bytes the token holds.
TOKEN_HEADER = "X-Extractium-Token"
TOKEN_BYTES = 32

# Largest body the page's API reads. A settings file is a few kilobytes;
# anything far past this is not one. A refused body up to the drain
# ceiling is read and thrown away before the refusal is sent, so the
# sender reads the answer instead of a dropped connection; past the
# ceiling the connection is closed unread.
MAX_API_BODY_BYTES = 1_000_000
DRAIN_CEILING_BYTES = 16 * 1024 * 1024

# The default settings file, and what the page shows beside a setting
# it cannot explain itself.
DEFAULT_CONFIG = "config.yaml"
DOCS_URL = "https://github.com/DepressionCenter/extractium/blob/main/docs/how-to/use-the-local-page.md"

# The exit code of a page that could not start, matching the build
# command's code for a bad configuration.
EXIT_OK = 0
EXIT_CONFIG = 2

# The page's own files, served only by these names and only from this
# folder. Nothing else in the package is reachable over HTTP.
STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}
STATIC_PREFIX = "/static/"

# Where the output folder is served, for the search page and Field
# Station AI, and where the search tool answers.
DIST_PREFIX = "/dist/"
MCP_PATH = DEFAULT_MCP_PATH

# Content types for files served from the output folder, by ending.
# Anything else is served as plain bytes.
DIST_CONTENT_TYPES = {
    ".json": "application/json; charset=utf-8",
    ".gz": "application/gzip",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
}
DEFAULT_CONTENT_TYPE = "application/octet-stream"

# Headers every answer carries. The page loads nothing from anywhere but
# itself, may not be framed, and sends no referrer.
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; font-src 'self'; form-action 'none'; base-uri 'none'; "
    "frame-ancestors 'none'"
)

JSON_CONTENT_TYPE = "application/json; charset=utf-8"


### The Server ###

class PageServer(ThreadingHTTPServer):
    """
    The server behind the local page.

    Args:
        config_path (str | pathlib.Path): the settings file the page
            reads and writes; it need not exist yet.
        port (int): the port to listen on; 0 takes a free one.
        idle_seconds (float): how long to wait for a page to check in
            before quitting.
        token (str | None): the session token; a random one when None.
        log (Callable[[str], None] | None): where a line about a refused
            request or a stop goes. Nothing when None.
        open_embedder (Callable | None): builds the query embedder for a
            loaded compendium; the installed model when None.

    Raises:
        OSError: if the port cannot be bound.
    """

    daemon_threads = True

    def __init__(self, config_path, port=0, idle_seconds=IDLE_SECONDS, token=None, log=None,
                 open_embedder=None):
        super().__init__((HOST, port), PageHandler)
        self.config_path = pathlib.Path(config_path)
        self.token = token or secrets.token_urlsafe(TOKEN_BYTES)
        self.idle_seconds = idle_seconds
        self.log = log or (lambda message: None)
        self._last_seen = time.monotonic()
        self._stop_watching = threading.Event()
        self.stopped_for = None
        self.mcp = KbServer(
            open_index=self.open_index,
            open_embedder=open_embedder or (lambda index: sentence_transformer_embedder(index.embedding["model"])),
            log=self.log,
        )

    def handle_error(self, request, client_address):
        """
        Says in one line when a request failed inside the server.

        A browser or client that drops a kept-alive connection while the
        server waits for its next request is ordinary and is not
        reported. Anything else is named without a traceback, because
        the person at the terminal is not the one to read it.
        """
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionError, TimeoutError)):
            return
        self.log(f"extractium ui: a request failed ({type(error).__name__}: {error}).")

    ### Addresses ###

    @property
    def port(self):
        """The port the server listens on."""
        return self.server_address[1]

    @property
    def address(self):
        """The one Host value accepted: the address the server listens on."""
        return f"{HOST}:{self.port}"

    @property
    def origin(self):
        """The one Origin a write may come from: the page's own."""
        return f"http://{self.address}"

    @property
    def page_url(self):
        """The address to open: the page, with the session token in the fragment."""
        return f"{self.origin}/#token={self.token}"

    ### Checks ###

    def token_matches(self, presented):
        """Whether a presented token is this session's, compared in constant time."""
        if not isinstance(presented, str):
            return False
        return hmac.compare_digest(presented.encode("utf-8"), self.token.encode("utf-8"))

    def host_matches(self, host):
        """Whether a Host header names this server and nothing else."""
        return isinstance(host, str) and host.strip().lower() == self.address

    def origin_matches(self, origin):
        """Whether an Origin header is the page's own."""
        return isinstance(origin, str) and origin.strip().lower() == self.origin

    ### Idle Watch ###

    def touch(self):
        """Records that a page is still open."""
        self._last_seen = time.monotonic()

    def idle_for(self):
        """Seconds since a page last checked in."""
        return time.monotonic() - self._last_seen

    def serve(self):
        """
        Answers requests until the server is asked to stop.

        The idle watch runs beside it and stops the server when no page
        has checked in for `idle_seconds`. A Ctrl+C stops it too and is
        raised on to the caller.
        """
        watcher = threading.Thread(target=self._watch_idle, name="extractium-ui-idle", daemon=True)
        watcher.start()
        try:
            self.serve_forever(poll_interval=0.5)
        finally:
            self._stop_watching.set()
            self.server_close()

    def _watch_idle(self):
        while not self._stop_watching.wait(min(1.0, max(self.idle_seconds / 4, 0.05))):
            if self.idle_for() > self.idle_seconds:
                self.stop("no page has checked in for a while")
                return

    def stop(self, reason):
        """
        Stops the server from any thread, once, and says why.

        Args:
            reason (str): what stopped it, for the log line.
        """
        if self.stopped_for is not None:
            return
        self.stopped_for = reason
        self.log(f"extractium ui: stopping ({reason}).")
        # shutdown() waits for the serving loop to end, so it runs on a
        # thread of its own rather than on a thread that loop is serving.
        threading.Thread(target=self.shutdown, name="extractium-ui-stop", daemon=True).start()

    ### The Settings And The Compendium ###

    def config(self):
        """The loaded settings, or None when the file is missing or refused."""
        try:
            return load_config(self.config_path)
        except ConfigError:
            return None

    def out_dir(self):
        """The output folder the settings name, resolved, or None."""
        config = self.config()
        if config is None:
            return None
        return pathlib.Path(config.out_dir).resolve()

    def compendium_path(self):
        """
        The compendium file the search tool serves: the full container
        when the last build wrote one, else the light one.

        Raises:
            ConfigurationError: when the settings file is missing or
                refused, writes no container, or no build has run yet.
        """
        config = self.config()
        if config is None:
            raise ConfigurationError("the settings file is missing or cannot be loaded.")
        entry = next((output for output in config.outputs if output.type == "container"), None)
        if entry is None:
            raise ConfigurationError("the settings file writes no container output to search.")
        out_dir = pathlib.Path(config.out_dir)
        light = out_dir / entry.options["file"]
        candidates = [out_dir / full_container_file_name(entry.options["file"]), light]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise ConfigurationError("no compendium has been built yet; run a build first.")

    def open_index(self):
        """Loads the compendium for the search tool. TODO: reload it after a build writes a new one."""
        path = self.compendium_path()
        self.log(f"extractium ui: reading the compendium from {path}")
        return load_container(path)

    def state(self):
        """What the page needs to know about this server and the settings file."""
        exists = self.config_path.is_file()
        error = None
        out_dir = None
        compendium = None
        if exists:
            try:
                config = load_config(self.config_path)
            except ConfigError as problem:
                error = str(problem)
            else:
                out_dir = str(pathlib.Path(config.out_dir).resolve())
                try:
                    compendium = self.compendium_path().name
                except ConfigurationError:
                    compendium = None
        return {
            "version": __version__,
            "settingsFile": str(self.config_path),
            "settingsFolder": str(self.config_path.resolve().parent),
            "settingsExists": exists,
            "settingsError": error,
            "outDir": out_dir,
            "compendium": compendium,
            "mcpPath": MCP_PATH,
            "pingSeconds": PING_INTERVAL_SECONDS,
            "idleSeconds": self.idle_seconds,
            "docsUrl": DOCS_URL,
        }


### The Handler ###

class PageHandler(BaseHTTPRequestHandler):
    """Answers one request to the page's server."""

    protocol_version = "HTTP/1.1"
    server_version = f"Extractium/{__version__}"
    sys_version = ""

    ### Entry Points ###

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_HEAD(self):
        self._route("HEAD")

    def _route(self, method):
        """
        Sends every request where it belongs, after the Host check.

        The Host check comes first, before any body is read: a request
        that reached this port through a name other than the server's
        own address came from a page that resolved that name to this
        machine, which is the one way a page elsewhere could reach a
        server on the loopback address.
        """
        if not self.server.host_matches(self.headers.get("Host")):
            self.close_connection = True
            self._send_text(403, "This server answers its own address only.\n")
            return
        path = urllib.parse.urlsplit(self.path).path
        if path == "/" and method in ("GET", "HEAD"):
            self._send_static("index.html", head=(method == "HEAD"))
        elif path.startswith(STATIC_PREFIX) and method in ("GET", "HEAD"):
            self._send_static(path[len(STATIC_PREFIX):], head=(method == "HEAD"))
        elif path == MCP_PATH:
            self._answer_mcp(method)
        elif path.startswith(DIST_PREFIX) and method in ("GET", "HEAD"):
            self._send_dist(path[len(DIST_PREFIX):], head=(method == "HEAD"))
        elif path.startswith("/api/"):
            self._answer_api(method, path)
        else:
            self._send_text(404, "Not found.\n")

    ### The Page's Files ###

    def _send_static(self, name, head=False):
        """One of the page's own files, by its allowlisted name, or 404."""
        content_type = STATIC_FILES.get(name)
        if content_type is None:
            self._send_text(404, "Not found.\n")
            return
        try:
            body = (STATIC_DIR / name).read_bytes()
        except OSError:
            self._send_text(404, "Not found.\n")
            return
        extra = {"Content-Security-Policy": CONTENT_SECURITY_POLICY} if name.endswith(".html") else {}
        self._send(200, content_type, body, extra, head=head)

    ### The Output Folder ###

    def _send_dist(self, relative, head=False):
        """
        One file from the output folder, or 404.

        The requested path is resolved against the folder, and anything
        whose real location is outside the folder is refused, so `..`
        and a link out of the tree both answer 404.
        """
        out_dir = self.server.out_dir()
        relative = urllib.parse.unquote(relative)
        if out_dir is None or not relative or "\\" in relative:
            self._send_text(404, "Not found.\n")
            return
        # A drive letter or a bare part could name a place outside the
        # folder before the real location is checked, so both are refused
        # as written rather than resolved.
        parts = relative.split("/")
        if any(part in ("", ".", "..") or ":" in part for part in parts):
            self._send_text(404, "Not found.\n")
            return
        target = out_dir.joinpath(*parts)
        try:
            resolved = target.resolve()
            inside = resolved.is_relative_to(out_dir)
        except (OSError, ValueError):
            inside = False
        if not inside or not resolved.is_file():
            self._send_text(404, "Not found.\n")
            return
        content_type = DIST_CONTENT_TYPES.get(resolved.suffix.lower(), DEFAULT_CONTENT_TYPE)
        try:
            size = resolved.stat().st_size
            with open(resolved, "rb") as handle:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                for name, value in SECURITY_HEADERS.items():
                    self.send_header(name, value)
                self.end_headers()
                if not head:
                    shutil.copyfileobj(handle, self.wfile)
        except OSError:
            self.close_connection = True

    ### The Search Tool ###

    def _answer_mcp(self, method):
        """
        The Model Context Protocol endpoint, through the stateless
        binding. A browser page may call it from the page's own origin
        only; a client that sends no Origin is not a browser and passes.
        """
        body = b""
        if method == "POST":
            body = self._read_body(MAX_BODY_BYTES + 1)
            if body is None:
                return
        answer = handle_http_request(
            method, self.path, dict(self.headers.items()), body, self.server.mcp,
            path=MCP_PATH, origins=frozenset({self.server.origin}),
        )
        self.send_response(answer.status)
        for name, value in answer.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(answer.body)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(answer.body)

    ### The Page's API ###

    def _answer_api(self, method, path):
        """
        The page's own calls. Every one needs the session token, and a
        write needs the page's own origin as well.
        """
        if not self.server.token_matches(self.headers.get(TOKEN_HEADER)):
            self.close_connection = True
            self._send_json(401, {"error": "This page has no session token. Open the address the "
                                           "terminal printed."})
            return
        if method == "POST" and not self.server.origin_matches(self.headers.get("Origin")):
            self.close_connection = True
            self._send_json(403, {"error": "A write must come from the page itself."})
            return
        self.server.touch()

        # A write's body is read whole before it is answered, whatever
        # the route does with it, so nothing is left on a kept-alive
        # connection to be mistaken for the next request.
        payload = None
        if method == "POST":
            payload = self._read_json()
            if payload is None:
                return

        if method == "GET" and path == "/api/ping":
            self._send_json(200, {"ok": True, "idleSeconds": self.server.idle_seconds})
        elif method == "GET" and path == "/api/state":
            self._send_json(200, self.server.state())
        elif method == "GET" and path == "/api/settings":
            self._send_json(200, self._settings_payload())
        elif method == "POST" and path == "/api/settings":
            self._save_settings(payload)
        elif method == "POST" and path == "/api/welcome":
            self._write_first_settings(payload)
        elif method == "POST" and path == "/api/quit":
            self._send_json(200, {"ok": True})
            self.server.stop("the page asked to quit")
        else:
            self._send_json(404, {"error": "Not found."})

    def _settings_payload(self):
        """The settings file as the page shows it, with the form's description."""
        state = settings_module.settings_state(self.server.config_path)
        return {**state, "schema": settings_module.schema(), "state": self.server.state()}

    def _save_settings(self, payload):
        """Writes the settings file from the form or from its text."""
        path = self.server.config_path
        try:
            if isinstance(payload.get("text"), str):
                text = payload["text"]
                kept = settings_module.save_text(path, text)
            elif isinstance(payload.get("form"), dict):
                text, kept = settings_module.save_form(path, payload["form"])
            else:
                self._send_json(400, {"error": "Send the settings as text or as a form."})
                return
        except settings_module.SettingsError as error:
            self._send_json(400, {"error": str(error)})
            return
        except OSError as error:
            self._send_json(500, {"error": f"the settings file could not be written ({error.strerror or error})."})
            return
        self._send_json(200, {"ok": True, "text": text, "kept": str(kept) if kept else None,
                              **self._settings_payload()})

    def _write_first_settings(self, payload):
        """Writes the welcome screen's first settings file."""
        path = self.server.config_path
        if path.exists():
            self._send_json(409, {"error": f"{path} already exists. Change it on the settings page instead."})
            return
        try:
            settings_module.write_first_settings(payload, path)
        except settings_module.SettingsError as error:
            self._send_json(400, {"error": str(error)})
            return
        except OSError as error:
            self._send_json(500, {"error": f"the settings file could not be written ({error.strerror or error})."})
            return
        self._send_json(200, {"ok": True, "path": str(path), **self._settings_payload()})

    ### Reading And Writing ###

    def _read_body(self, limit):
        """
        The request body, or None once a refusal has been sent.

        The body must declare its length and stay under the limit; a
        body past it is refused without being read.
        """
        declared = self.headers.get("Content-Length")
        if declared is None or not declared.strip().isdigit():
            self.close_connection = True
            self._send_json(411, {"error": "The request must declare its length."})
            return None
        length = int(declared)
        if length > limit:
            if length <= DRAIN_CEILING_BYTES:
                self._discard(length)
            else:
                self.close_connection = True
            self._send_json(413, {"error": f"The body is larger than the {limit} bytes accepted."})
            return None
        return self.rfile.read(length)

    def _discard(self, length):
        """Reads and drops a body of the given length, a chunk at a time."""
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)

    def _read_json(self):
        """The request body parsed as a JSON object, or None once a refusal has been sent."""
        body = self._read_body(MAX_API_BODY_BYTES)
        if body is None:
            return None
        if not body.strip():
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._send_json(400, {"error": "The body is not valid JSON."})
            return None
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "The body must be a JSON object."})
            return None
        return payload

    def _send(self, status, content_type, body, extra_headers=None, head=False):
        """One complete answer, with the headers every answer carries."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _send_text(self, status, text):
        self._send(status, "text/plain; charset=utf-8", text.encode("utf-8"))

    def _send_json(self, status, payload):
        self._send(status, JSON_CONTENT_TYPE, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    ### Logging ###

    def log_request(self, code="-", size="-"):
        """Only a refused or failed request is logged; the page's routine calls are not."""
        try:
            status = int(code)
        except (TypeError, ValueError):
            status = 0
        if status >= 400:
            self.server.log(f"extractium ui: {self.command} {urllib.parse.urlsplit(self.path).path} -> {status}")

    def log_error(self, format, *args):
        self.server.log("extractium ui: " + (format % args))

    def log_message(self, format, *args):
        return None


### Running ###

def run_ui(args, open_browser=None, say=print, err=None):
    """
    Runs the `ui` command: starts the server, prints its address, opens
    the browser unless told not to, and serves until stopped.

    Args:
        args (argparse.Namespace): the parsed `ui` arguments: `config`,
            `port`, and `no_browser`.
        open_browser (Callable[[str], bool] | None): opens an address in
            the browser; the standard library's when None.
        say (Callable[[str], None]): prints one line to the person.
        err (Callable[[str], None] | None): prints one line of log or
            error text; standard error outside tests.

    Returns:
        int: 0 when the server ran and stopped, 2 when it could not
        start.
    """
    err = err or (lambda line: print(line, file=sys.stderr, flush=True))
    open_browser = open_browser or webbrowser.open
    try:
        server = PageServer(args.config, port=args.port or 0, log=err)
    except OSError as error:
        err(f"extractium ui: the page could not listen on port {args.port or 'any'} ({error}).")
        return EXIT_CONFIG
    say(f"The Extractium page is at {server.page_url}")
    say("Keep this window open. Press Ctrl+C here, or Quit on the page, to stop it.")
    if not args.no_browser:
        try:
            opened = open_browser(server.page_url)
        except Exception as error:
            opened = False
            err(f"extractium ui: the browser could not be opened ({error}).")
        if not opened:
            say("Open that address in your browser.")
    try:
        server.serve()
    except KeyboardInterrupt:
        server.stopped_for = server.stopped_for or "stopped at your request"
        server.server_close()
    say("The page has stopped.")
    return EXIT_OK
