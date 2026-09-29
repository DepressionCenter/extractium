"""
Summary: Tests for the local page's server: it listens on the loopback
address only and answers it under both of its names; a request with
another Host, a write without the token
or from another origin, a path with `..`, and a file outside the
allowlist are all refused; the welcome screen writes a file the loader
accepts with the page's outputs on and refuses to replace one; a saved
form and a saved text round trip; the output folder is served under
/dist/ and nothing outside it; the search tool answers at /mcp; the
idle timer and the Quit button stop the server; and the `ui` command
prints the address, opens the browser unless told not to, and exits
when the page quits.

This file is part of Extractium™
tests/test_ui_server.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-28
Last Modified: 2026-09-29
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
__date__ = "2026-09-29"

import argparse
import http.client
import json
import shutil
import socket
import threading
import time

import pytest

from extractium import cli
from extractium.config import load_config
from extractium.search import load_container
from extractium.ui import server as ui
from tests.contract_fixture import CONTAINER_FILE, QUERY_FILE

MINIMAL = "sources:\n  - type: web\n    label: Docs\n    seed_url: https://example.edu/\n"
MODERN_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}

# A stand-in for the environment a person keeps their tokens in. None
# of it may ever reach the page.
PLANTED_SECRETS = {"GITHUB_TOKEN": "ghp_plantedsecret1234", "YOUTUBE_API_KEY": "AIzaPlantedSecret5678"}


### Fixtures ###

class Page:
    """A running server and a way to call it like a browser or a client would."""

    def __init__(self, server, thread):
        self.server = server
        self.thread = thread

    def call(self, method, path, body=None, headers=None, host=None, token=True, origin=True):
        """
        One request. By default it looks like the page's own: the right
        Host, the session token, and, on a write, the page's origin.
        """
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        sent = {"Host": host if host is not None else self.server.address}
        if token:
            sent[ui.TOKEN_HEADER] = self.server.token
        if origin and method == "POST":
            sent["Origin"] = self.server.origin
        if body is not None:
            body = json.dumps(body).encode("utf-8")
            sent["Content-Type"] = "application/json"
        sent.update(headers or {})
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, {name.lower(): value for name, value in response.getheaders()}, data

    def json(self, method, path, body=None, **options):
        status, _, data = self.call(method, path, body, **options)
        return status, json.loads(data.decode("utf-8"))

    def stopped(self, within=10):
        self.thread.join(within)
        return not self.thread.is_alive()


def start(server):
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    return Page(server, thread)


@pytest.fixture
def expectations(golden_dir):
    return json.loads((golden_dir / QUERY_FILE).read_text(encoding="utf-8"))


@pytest.fixture
def page(tmp_path, monkeypatch, expectations):
    """A server over an empty folder, with the recorded query vector standing in for a model."""
    monkeypatch.chdir(tmp_path)
    for name, value in PLANTED_SECRETS.items():
        monkeypatch.setenv(name, value)
    server = ui.PageServer(tmp_path / "config.yaml", idle_seconds=60,
                           open_embedder=lambda index: (lambda text: expectations["queryVector"]))
    running = start(server)
    yield running
    if running.thread.is_alive():
        server.stop("test finished")
        running.thread.join(10)


def ui_args(**values):
    given = {"config": "config.yaml", "port": 0, "no_browser": True}
    given.update(values)
    return argparse.Namespace(**given)


# ---------------------------------------------------------------------------
# Where it listens, and what it refuses
# ---------------------------------------------------------------------------

def test_the_server_binds_to_the_loopback_address_only(page):
    assert page.server.server_address[0] == "127.0.0.1"
    assert page.server.address == f"127.0.0.1:{page.server.port}"
    assert page.server.page_url == f"http://127.0.0.1:{page.server.port}/#token={page.server.token}"


def test_the_token_is_long_random_and_never_in_the_query_string(page):
    assert len(page.server.token) >= 40
    assert "?" not in page.server.page_url
    assert ui.PageServer(page.server.config_path).token != page.server.token


def test_the_page_is_served_with_a_content_security_policy(page):
    status, headers, body = page.call("GET", "/", token=False)

    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert "default-src 'none'" in headers["content-security-policy"]
    assert "script-src 'self'" in headers["content-security-policy"]
    assert headers["x-frame-options"] == "DENY"
    assert headers["cache-control"] == "no-store"
    assert b"<title>Extractium</title>" in body
    assert b"<script src=\"/static/app.js\">" in body


def test_the_pages_own_files_come_from_the_allowlist_and_nothing_else_is_served(page):
    assert page.call("GET", "/static/app.js", token=False)[0] == 200
    assert page.call("GET", "/static/style.css", token=False)[1]["content-type"].startswith("text/css")
    for path in ("/static/../server.py", "/static/%2e%2e/server.py", "/static/settings.py",
                 "/static/", "/static/app.js/../server.py", "/server.py", "/extractium/ui/server.py"):
        assert page.call("GET", path, token=False)[0] == 404, path


def test_a_request_with_another_host_is_refused_before_anything_else(page):
    for host in ("127.0.0.1", f"127.0.0.1:{page.server.port + 1}", f"localhost:{page.server.port + 1}",
                 f"evil.example:{page.server.port}", f"localhost.evil.example:{page.server.port}", ""):
        status, _, body = page.call("GET", "/api/state", host=host)
        assert status == 403, host
        assert b"own address" in body


def test_the_loopback_address_is_accepted_under_either_of_its_names(page):
    # The server binds the numeric address only; a person may still type localhost.
    assert page.server.server_address[0] == "127.0.0.1"
    assert page.call("GET", "/api/state", host=f"localhost:{page.server.port}")[0] == 200
    assert page.call("GET", "/api/state", host=f"LOCALHOST:{page.server.port}")[0] == 200
    status, body = page.json("POST", "/api/welcome", {"name": "x", "seed_url": "https://example.edu/"},
                             host=f"localhost:{page.server.port}",
                             headers={"Origin": f"http://localhost:{page.server.port}"})
    assert status == 200 and body["ok"]


def test_a_call_without_the_token_is_refused(page):
    assert page.call("GET", "/api/state", token=False)[0] == 401
    assert page.call("GET", "/api/settings", headers={ui.TOKEN_HEADER: "wrong"})[0] == 401
    assert page.call("POST", "/api/welcome", body={}, token=False)[0] == 401
    assert page.call("POST", "/api/quit", body={}, headers={ui.TOKEN_HEADER: page.server.token[:-1]})[0] == 401
    assert page.thread.is_alive()


def test_a_write_from_another_origin_or_from_none_is_refused(page):
    for origin in ("http://evil.example", f"http://localhost:{page.server.port + 1}", f"https://{page.server.address}",
                   f"http://localhost.evil.example:{page.server.port}"):
        status, body = page.json("POST", "/api/welcome", {"name": "x", "seed_url": "https://example.edu/"},
                                 headers={"Origin": origin})
        assert status == 403, origin
        assert "from the page itself" in body["error"]
    status, body = page.json("POST", "/api/welcome", {"name": "x", "seed_url": "https://example.edu/"}, origin=False)
    assert status == 403
    assert not (page.server.config_path).exists()


def test_a_read_needs_no_origin_and_a_write_with_the_pages_origin_passes(page):
    assert page.call("GET", "/api/state")[0] == 200
    status, body = page.json("POST", "/api/welcome", {"name": "x", "seed_url": "https://example.edu/"})
    assert status == 200 and body["ok"]


def test_an_unknown_path_and_an_oversized_body_are_refused(page):
    assert page.call("GET", "/nope", token=False)[0] == 404
    assert page.json("GET", "/api/nope")[0] == 404
    status, body = page.json("POST", "/api/settings", {"text": "x" * (ui.MAX_API_BODY_BYTES + 10)})
    assert status == 413
    assert page.json("POST", "/api/settings", {}, headers={"Content-Length": "abc"})[0] in (400, 411)


def test_no_token_from_the_environment_reaches_the_page(page):
    page.server.config_path.write_text(MINIMAL, encoding="utf-8")
    for path in ("/api/state", "/api/settings"):
        _, headers, body = page.call("GET", path)
        text = body.decode("utf-8")
        for secret in PLANTED_SECRETS.values():
            assert secret not in text, path
    assert page.server.token not in page.call("GET", "/api/settings")[2].decode("utf-8")


# ---------------------------------------------------------------------------
# The welcome screen and the settings
# ---------------------------------------------------------------------------

def test_the_state_says_whether_there_is_a_settings_file(page):
    status, state = page.json("GET", "/api/state")

    assert status == 200
    assert state["settingsExists"] is False and state["settingsError"] is None
    assert state["mcpPath"] == "/mcp" and state["pingSeconds"] == ui.PING_INTERVAL_SECONDS
    assert state["settingsFile"].endswith("config.yaml")


def test_the_welcome_screen_writes_a_file_the_loader_accepts_with_both_outputs_on(page, tmp_path):
    status, body = page.json("POST", "/api/welcome",
                             {"name": "My KB", "slug": "", "seed_url": "https://example.edu/docs/"})

    assert status == 200
    assert body["exists"] and body["error"] is None
    loaded = load_config(tmp_path / "config.yaml")
    assert loaded.name == "My KB" and loaded.slug == "my-kb"
    assert loaded.sources[0].options["seed_url"] == "https://example.edu/docs/"
    assert [output.type for output in loaded.outputs] == ["container", "llmstxt", "okf"]
    assert loaded.outputs[0].options["gzip"] is True
    assert body["state"]["settingsExists"] is True


def test_the_welcome_screen_refuses_to_replace_an_existing_file_and_a_bad_address(page, tmp_path):
    (tmp_path / "config.yaml").write_text("keep me\n", encoding="utf-8")

    status, body = page.json("POST", "/api/welcome", {"name": "x", "seed_url": "https://example.edu/"})
    assert status == 409 and "already exists" in body["error"]
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == "keep me\n"

    (tmp_path / "config.yaml").unlink()
    status, body = page.json("POST", "/api/welcome", {"name": "x", "seed_url": "not an address"})
    assert status == 400 and "must start with http" in body["error"]
    assert not (tmp_path / "config.yaml").exists()


def test_a_hostile_name_from_the_welcome_screen_stays_a_name(page, tmp_path):
    name = 'Evil: "name\nmax_pages: 1'

    status, _ = page.json("POST", "/api/welcome", {"name": name, "seed_url": "https://example.edu/"})

    assert status == 200
    loaded = load_config(tmp_path / "config.yaml")
    # The name is folded onto one line, as the terminal does, and none
    # of it becomes a setting.
    assert loaded.name == 'Evil: "name max_pages: 1' and loaded.max_pages != 1


def test_the_settings_call_gives_the_text_the_form_values_and_the_description(page, tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL, encoding="utf-8")

    status, body = page.json("GET", "/api/settings")

    assert status == 200
    assert body["text"] == MINIMAL
    assert body["values"]["sources"][0]["seed_urls"] == ["https://example.edu/"]
    assert {field["key"] for field in body["schema"]["globals"]} >= {"name", "slug", "max_pages", "rebuild"}
    assert body["state"]["settingsExists"] is True


def test_a_saved_form_round_trips_every_setting_and_keeps_the_previous_file(page, tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL, encoding="utf-8")
    _, body = page.json("GET", "/api/settings")
    form = body["values"]
    form["name"] = "Docs KB"
    form["max_pages"] = 25
    form["delay_seconds"] = 1
    form["rebuild"] = "incremental"
    form["sources"][0]["extra_crawl_exclude_patterns"] = ["/login", "/search\\?"]
    form["sources"].append({"type": "local", "label": "Notes", "path": "./notes", "read_documents": True})
    form["outputs"] = [{"type": "container", "full": False}, {"type": "okf", "include_local": True}]

    status, saved = page.json("POST", "/api/settings", {"form": form})

    assert status == 200, saved
    assert saved["kept"].endswith(".bak")
    loaded = load_config(tmp_path / "config.yaml")
    assert loaded.name == "Docs KB" and loaded.max_pages == 25 and loaded.delay_seconds == 1.0
    assert loaded.rebuild == "incremental"
    assert loaded.sources[0].options["extra_crawl_exclude_patterns"] == ("/login", "/search\\?")
    assert loaded.sources[1].type == "local" and loaded.sources[1].options["read_documents"] is True
    assert [(output.type, output.include_local) for output in loaded.outputs] == [("container", False), ("okf", True)]
    assert loaded.outputs[0].options["full"] is False
    # And reading it back gives the same form, so a second save changes nothing.
    _, again = page.json("GET", "/api/settings")
    assert again["values"] == saved["values"]
    status, twice = page.json("POST", "/api/settings", {"form": again["values"]})
    assert status == 200 and twice["text"] == saved["text"]


def test_a_form_value_the_loader_refuses_is_refused_with_its_message(page, tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL, encoding="utf-8")
    _, body = page.json("GET", "/api/settings")
    form = body["values"]
    form["max_pages"] = 0

    status, refused = page.json("POST", "/api/settings", {"form": form})

    assert status == 400
    assert "max_pages must be 1 or greater" in refused["error"]
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == MINIMAL
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["config.yaml"], "no kept copy for a refused save"


def test_the_files_text_is_saved_as_typed_and_refused_with_the_loaders_message(page, tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL, encoding="utf-8")
    typed = "# my comment\n" + MINIMAL + "max_pages: 9\n"

    status, saved = page.json("POST", "/api/settings", {"text": typed})
    assert status == 200 and saved["text"] == typed
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == typed
    assert load_config(tmp_path / "config.yaml").max_pages == 9

    status, refused = page.json("POST", "/api/settings", {"text": "sources: []\n"})
    assert status == 400 and "at least one source" in refused["error"]
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == typed

    assert page.json("POST", "/api/settings", {"neither": True})[0] == 400


# ---------------------------------------------------------------------------
# The output folder and the search tool
# ---------------------------------------------------------------------------

def test_the_output_folder_is_served_under_dist_and_nothing_outside_it(page, tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL, encoding="utf-8")
    (tmp_path / "dist" / "llms").mkdir(parents=True)
    (tmp_path / "dist" / "llms.txt").write_bytes(b"# Docs\n")
    (tmp_path / "dist" / "llms" / "docs.txt").write_bytes(b"- page\n")
    (tmp_path / "secret.txt").write_bytes(b"outside\n")

    status, headers, body = page.call("GET", "/dist/llms.txt", token=False)
    assert status == 200 and body == b"# Docs\n"
    assert headers["content-type"].startswith("text/plain")
    assert page.call("GET", "/dist/llms/docs.txt", token=False)[2] == b"- page\n"
    for path in ("/dist/../secret.txt", "/dist/%2e%2e/secret.txt", "/dist/llms/../../secret.txt",
                 "/dist//secret.txt", "/dist/", "/dist/llms", "/dist/llms/", "/dist/nope.txt",
                 "/dist/C:/secret.txt", "/dist/..%5Csecret.txt"):
        assert page.call("GET", path, token=False)[0] == 404, path


def test_the_output_folder_is_not_served_without_a_settings_file(page, tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "llms.txt").write_text("x", encoding="utf-8")

    assert page.call("GET", "/dist/llms.txt", token=False)[0] == 404


def test_the_search_tool_answers_at_mcp_from_the_built_compendium(page, tmp_path, golden_dir, expectations):
    (tmp_path / "config.yaml").write_text(
        MINIMAL + "outputs:\n  - type: container\n    file: contract.json\n", encoding="utf-8"
    )
    (tmp_path / "dist").mkdir()
    shutil.copy(golden_dir / CONTAINER_FILE, tmp_path / "dist" / "contract.json")

    listed = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": MODERN_META}}
    status, body = page.json("POST", "/mcp", listed, token=False, origin=False)
    assert status == 200 and body["result"]["tools"][0]["name"] == "search_kb"

    asked = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "search_kb", "arguments": {"query": expectations["query"], "k": expectations["k"]},
                        "_meta": MODERN_META}}
    status, body = page.json("POST", "/mcp", asked, token=False, origin=False)
    assert status == 200
    by_id = {parent["id"]: parent["u"] for parent in load_container(golden_dir / CONTAINER_FILE).parents}
    found = [result["url"] for result in body["result"]["structuredContent"]["results"]]
    assert found == [by_id[parent_id] for parent_id in expectations["relevantParentIds"]]


def test_the_search_tool_says_so_when_nothing_has_been_built(page, tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL, encoding="utf-8")
    asked = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "search_kb", "arguments": {"query": "anything"}, "_meta": MODERN_META}}

    status, body = page.json("POST", "/mcp", asked, token=False, origin=False)

    assert status == 200
    assert body["result"]["isError"] is True
    assert "no compendium has been built yet" in body["result"]["content"][0]["text"]


def test_the_search_tool_refuses_a_browser_page_from_another_origin_and_needs_no_token(page):
    listed = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": MODERN_META}}

    assert page.json("POST", "/mcp", listed, token=False, headers={"Origin": "http://evil.example"})[0] == 403
    assert page.json("POST", "/mcp", listed, token=False)[0] == 200
    assert page.call("GET", "/mcp", token=False)[0] == 405
    assert page.call("POST", "/mcp", body=listed, host="evil.example")[0] == 403


# ---------------------------------------------------------------------------
# Stopping
# ---------------------------------------------------------------------------

def test_the_idle_timer_stops_the_server_when_no_page_checks_in(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reasons = []
    server = ui.PageServer(tmp_path / "config.yaml", idle_seconds=0.3, log=reasons.append)

    running = start(server)

    assert running.stopped(within=10)
    assert "no page has checked in" in server.stopped_for
    assert any("stopping" in line for line in reasons)


def test_a_page_that_checks_in_keeps_the_server_running(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server = ui.PageServer(tmp_path / "config.yaml", idle_seconds=0.8)
    running = start(server)

    for _ in range(6):
        time.sleep(0.25)
        assert running.json("GET", "/api/ping")[0] == 200
    assert running.thread.is_alive(), "pings inside the idle window keep it up"

    assert running.stopped(within=10), "and it stops once they end"


def test_the_quit_button_stops_the_server(page):
    status, body = page.json("POST", "/api/quit", {})

    assert status == 200 and body["ok"]
    assert page.stopped()
    assert page.server.stopped_for == "the page asked to quit"


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def run_command(args, opened):
    """Runs the ui command on a thread and returns the lines it said plus the thread."""
    said = []
    thread = threading.Thread(
        target=lambda: said.append(("exit", ui.run_ui(args, open_browser=lambda url: opened.append(url) or True,
                                                     say=lambda line: said.append(("say", line)),
                                                     err=lambda line: said.append(("err", line))))),
        daemon=True,
    )
    thread.start()
    for _ in range(100):
        if any(kind == "say" and "page is at" in line for kind, line in said):
            break
        time.sleep(0.05)
    return said, thread


def address_from(said):
    line = next(line for kind, line in said if kind == "say" and "page is at" in line)
    url = line.split(" at ", 1)[1].strip()
    origin, token = url.split("/#token=")
    return origin, token


def test_the_command_prints_the_address_opens_the_browser_and_stops_when_the_page_quits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    opened = []

    said, thread = run_command(ui_args(no_browser=False), opened)

    origin, token = address_from(said)
    assert opened == [f"{origin}/#token={token}"]
    port = int(origin.rsplit(":", 1)[1])
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request("POST", "/api/quit", body=b"{}", headers={
        "Host": f"127.0.0.1:{port}", "Origin": origin, ui.TOKEN_HEADER: token, "Content-Type": "application/json",
    })
    assert connection.getresponse().status == 200
    thread.join(10)
    assert not thread.is_alive()
    assert ("exit", 0) in said
    assert any("has stopped" in line for kind, line in said if kind == "say")


def test_the_command_can_be_told_not_to_open_a_browser(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    opened = []

    said, thread = run_command(ui_args(no_browser=True), opened)

    origin, token = address_from(said)
    assert opened == []
    port = int(origin.rsplit(":", 1)[1])
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request("POST", "/api/quit", body=b"{}", headers={
        "Host": f"127.0.0.1:{port}", "Origin": origin, ui.TOKEN_HEADER: token, "Content-Type": "application/json",
    })
    assert connection.getresponse().status == 200
    thread.join(10)
    assert ("exit", 0) in said


def test_the_command_exits_two_when_the_port_is_taken(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen(1)
    port = taken.getsockname()[1]
    said = []
    try:
        code = ui.run_ui(ui_args(port=port), open_browser=lambda url: True,
                         say=lambda line: said.append(line), err=lambda line: said.append(line))
    finally:
        taken.close()

    assert code == 2
    assert any("could not listen" in line for line in said)


def test_the_command_line_knows_the_ui_command():
    parser = cli.build_parser()

    args = parser.parse_args(["ui", "--port", "8123", "--no-browser", "--config", "other.yaml"])

    assert args.handler is ui.run_ui
    assert (args.port, args.no_browser, args.config) == (8123, True, "other.yaml")
    assert parser.parse_args(["ui"]).config == ui.DEFAULT_CONFIG
