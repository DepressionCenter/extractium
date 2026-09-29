"""
Summary: Tests for the Streamable HTTP binding in extractium.mcp.http: a
tool call round trip over one POST against the committed golden
compendium that answers the same as the standard-input path, the
statuses the transport reserves, the refusal of every method but POST,
the header checks, the body cap, and the two optional gates.

This file is part of Extractium™
tests/test_mcp_http.py

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

import base64
import io
import json

import pytest

from extractium.mcp import http as binding
from extractium.mcp import server as server_module
from extractium.search import load_container
from tests.contract_fixture import CONTAINER_FILE, QUERY_FILE

MODERN_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}


### Fixtures ###

@pytest.fixture
def expectations(golden_dir):
    return json.loads((golden_dir / QUERY_FILE).read_text(encoding="utf-8"))


@pytest.fixture
def golden_index(golden_dir):
    return load_container(golden_dir / CONTAINER_FILE)


@pytest.fixture
def golden_server(golden_index, expectations):
    """A server over the golden compendium, the recorded vector standing in for a model."""
    return server_module.KbServer(
        open_index=lambda: golden_index,
        open_embedder=lambda index: (lambda text: expectations["queryVector"]),
    )


def request(request_id, method, params=None):
    """A request message with an id, the modern metadata included."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": {**(params or {}), "_meta": MODERN_META}}


def post(server, body, headers=None, target="/mcp", **options):
    """One POST to the endpoint with a JSON body and any extra headers."""
    raw = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
    return binding.handle_http_request(
        "POST", target, {"Content-Type": "application/json", **(headers or {})}, raw, server, **options
    )


def wrapped(value):
    """A header value in the Base64 wrapper a client uses for text it cannot send plain."""
    return f"=?base64?{base64.b64encode(value.encode('utf-8')).decode('ascii')}?="


### The round trip ###

def test_a_tool_call_over_http_returns_the_sections_the_client_ranks_for_the_recorded_query(
    golden_server, golden_index, expectations
):
    answer = post(golden_server, request(1, "tools/call", {
        "name": "search_kb", "arguments": {"query": expectations["query"], "k": expectations["k"]},
    }), {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": "search_kb"})

    assert answer.status == 200
    assert answer.headers["content-type"].startswith("application/json")
    body = answer.json()
    by_id = {parent["id"]: parent["u"] for parent in golden_index.parents}
    assert [record["url"] for record in body["result"]["structuredContent"]["results"]] == [
        by_id[parent_id] for parent_id in expectations["relevantParentIds"]
    ]
    assert body["result"]["resultType"] == "complete"


def test_the_http_path_and_the_standard_input_path_give_the_same_answer(golden_server, expectations):
    message = request(1, "tools/call", {"name": "search_kb", "arguments": {"query": expectations["query"]}})
    stream_out = io.StringIO()
    server_module.serve(io.StringIO(json.dumps(message) + "\n"), stream_out, golden_server)

    over_http = post(golden_server, message).json()

    assert over_http == json.loads(stream_out.getvalue())


def test_the_tool_list_is_served_and_a_legacy_client_gets_its_handshake(golden_server):
    listed = post(golden_server, request(1, "tools/list")).json()
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["search_kb"]

    legacy = post(golden_server, {
        "jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "2025-06-18"},
    })
    assert legacy.status == 200
    assert legacy.json()["result"]["protocolVersion"] == "2025-06-18"


### Statuses the transport reserves ###

def test_a_notification_is_accepted_with_no_body(golden_server):
    answer = post(golden_server, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    assert answer.status == 202
    assert answer.body == b""


def test_an_unknown_method_is_404_with_the_error_a_client_tells_apart_from_a_missing_endpoint(golden_server):
    answer = post(golden_server, request(1, "resources/list"))

    assert answer.status == 404
    assert answer.json()["error"]["code"] == -32601


def test_an_unsupported_revision_is_400_with_the_list_of_supported_ones(golden_server):
    answer = post(golden_server, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "1900-01-01"}},
    })

    assert answer.status == 400
    body = answer.json()
    assert body["error"]["code"] == -32022
    assert "2026-07-28" in body["error"]["data"]["supported"]


def test_a_tool_error_is_a_200_result_the_model_reads_not_an_http_failure(golden_server):
    answer = post(golden_server, request(1, "tools/call", {"name": "search_kb", "arguments": {"query": "   "}}))

    assert answer.status == 200
    assert answer.json()["result"]["isError"] is True


def test_a_body_that_is_not_json_is_400_with_a_parse_error(golden_server):
    answer = post(golden_server, "{not json")

    assert answer.status == 400
    assert answer.json()["error"]["code"] == -32700


@pytest.mark.parametrize("body", [
    [{"jsonrpc": "2.0", "id": 1, "method": "ping"}],
    {"jsonrpc": "2.0", "id": 1, "result": {}},
    "42",
    {"id": 1, "method": "ping"},
])
def test_a_batch_a_response_a_bare_value_and_a_message_without_the_version_are_refused(golden_server, body):
    answer = post(golden_server, body)

    assert answer.status == 400
    assert answer.json()["error"]["code"] == -32600


### Methods and paths ###

@pytest.mark.parametrize("method", ["GET", "DELETE", "PUT"])
def test_every_method_but_post_is_405_because_there_is_no_stream_and_no_session(golden_server, method):
    answer = binding.handle_http_request(method, "/mcp", {}, b"", golden_server)

    assert answer.status == 405
    assert answer.headers["allow"] == "POST"


def test_the_root_answers_a_browser_with_a_line_of_text_and_any_other_path_is_404(golden_server):
    root = binding.handle_http_request("GET", "/", {}, b"", golden_server)
    assert root.status == 200
    assert "/mcp" in root.body.decode("utf-8")

    other = post(golden_server, request(1, "ping"), target="/admin")
    assert other.status == 404


def test_the_endpoint_path_and_the_root_text_follow_the_caller(golden_server):
    answer = post(golden_server, request(1, "ping"), target="/tool?client=1", path="/tool")
    assert answer.status == 200

    root = binding.handle_http_request("GET", "/", {}, b"", golden_server, description="Hello.\n")
    assert root.body == b"Hello.\n"


def test_a_body_that_is_not_json_by_content_type_is_refused_before_it_is_read(golden_server):
    answer = binding.handle_http_request(
        "POST", "/mcp", {"content-type": "text/plain"}, b"hello", golden_server
    )

    assert answer.status == 415


def test_a_body_past_the_cap_is_refused_whether_declared_or_read(golden_server):
    huge = request(1, "tools/call", {"name": "search_kb", "arguments": {"query": "x" * 70_000}})
    assert post(golden_server, huge).status == 413

    declared = post(golden_server, request(1, "ping"), {"Content-Length": str(binding.MAX_BODY_BYTES + 1)})
    assert declared.status == 413


def test_the_body_cap_follows_the_caller(golden_server):
    answer = post(golden_server, request(1, "ping"), max_body_bytes=8)

    assert answer.status == 413


### Mirrored headers ###

@pytest.mark.parametrize("headers", [
    {"MCP-Protocol-Version": "2025-11-25"},
    {"Mcp-Method": "tools/list"},
    {"Mcp-Name": "other_tool"},
    {"Mcp-Name": wrapped("other_tool")},
])
def test_a_mirrored_header_that_disagrees_with_the_body_is_a_header_mismatch(golden_server, headers):
    answer = post(golden_server, request(7, "tools/call", {
        "name": "search_kb", "arguments": {"query": "hours"},
    }), headers)

    assert answer.status == 400
    body = answer.json()
    assert body["error"]["code"] == binding.ERROR_HEADER_MISMATCH
    assert body["id"] == 7


def test_a_mirrored_header_that_agrees_plain_or_wrapped_passes(golden_server, expectations):
    answer = post(golden_server, request(1, "tools/call", {
        "name": "search_kb", "arguments": {"query": expectations["query"]},
    }), {"Mcp-Method": "tools/call", "Mcp-Name": wrapped("search_kb")})

    assert answer.status == 200


def test_a_wrapped_header_that_is_not_valid_is_read_as_absent():
    assert binding.decoded_header("=?base64?!!!?=") is None
    assert binding.decoded_header(None) is None
    assert binding.decoded_header("plain") == "plain"


def test_a_session_id_from_an_older_client_is_ignored_rather_than_refused(golden_server):
    answer = post(golden_server, request(1, "ping"), {"Mcp-Session-Id": "abc"})

    assert answer.status == 200
    assert "mcp-session-id" not in answer.headers


### Gates ###

def test_with_a_bearer_token_configured_a_request_without_the_right_one_is_401(golden_server):
    options = {"bearer_token": "EXAMPLE_TOKEN"}
    missing = post(golden_server, request(1, "ping"), **options)
    assert missing.status == 401
    assert missing.headers["www-authenticate"] == "Bearer"

    wrong = post(golden_server, request(1, "ping"), {"Authorization": "Bearer EXAMPLE_TOKE"}, **options)
    assert wrong.status == 401

    right = post(golden_server, request(1, "ping"), {"Authorization": "Bearer EXAMPLE_TOKEN"}, **options)
    assert right.status == 200


def test_secrets_are_compared_whole_whatever_their_length():
    assert binding.same_secret("abc", "abc") is True
    assert binding.same_secret("abc", "abcd") is False
    assert binding.same_secret("", "a") is False
    assert binding.same_secret("", "") is True


def test_with_an_origin_allowlist_a_browser_origin_off_the_list_is_403_and_a_non_browser_caller_passes(
    golden_server
):
    origins = binding.allowed_origins("https://assistant.example.org, https://Other.example.org")
    off = post(golden_server, request(1, "ping"), {"Origin": "https://evil.example.net"}, origins=origins)
    assert off.status == 403

    on = post(golden_server, request(1, "ping"), {"Origin": "https://other.example.org"}, origins=origins)
    assert on.status == 200

    none = post(golden_server, request(1, "ping"), origins=origins)
    assert none.status == 200


def test_an_empty_allowlist_setting_means_no_origin_check():
    assert binding.allowed_origins("") is None
    assert binding.allowed_origins(None) is None
    assert binding.allowed_origins(" , ") is None
