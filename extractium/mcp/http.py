"""
Summary: The Streamable HTTP binding of the Model Context Protocol over
the search server in extractium.mcp.server, in its stateless form: one
POST carries one JSON-RPC message and is answered with one JSON object.
There is no session, no server-sent event stream, and nothing kept
between calls, the same choice the hosted JavaScript examples made, so
a local page can mount it on one path with plain request handling. It
also holds the two gates such an endpoint may want, a bearer token and
an origin allowlist, checked before any message is read.

This file is part of Extractium™
extractium/mcp/http.py

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
import binascii
import dataclasses
import hmac
import json
import re

from extractium.mcp.server import (
    ERROR_INVALID_REQUEST,
    ERROR_METHOD_NOT_FOUND,
    ERROR_PARSE,
    ERROR_UNSUPPORTED_VERSION,
    JSONRPC_VERSION,
    PROTOCOL_VERSION_KEY,
)

### Constants ###

# The path the protocol endpoint answers on. Everything else is a short
# text page or a 404, so a person opening the address in a browser sees
# what the service is rather than an error.
DEFAULT_MCP_PATH = "/mcp"

# Largest request body read. A protocol message is a question and a few
# fields of metadata; anything past this is not one.
MAX_BODY_BYTES = 64 * 1024

# The protocol's "the HTTP headers disagree with the body" error.
ERROR_HEADER_MISMATCH = -32020

# Headers the transport mirrors from the body, and the one that names the
# revision. Header names are compared without regard to case.
PROTOCOL_VERSION_HEADER = "mcp-protocol-version"
METHOD_HEADER = "mcp-method"
NAME_HEADER = "mcp-name"

# A header value the client could not send as plain text arrives in this
# wrapper, Base64 inside.
BASE64_PREFIX = "=?base64?"
BASE64_SUFFIX = "?="

# What a browser sees at the root when the caller gives no other text.
DEFAULT_DESCRIPTION = (
    "An Extractium compendium search server. The Model Context Protocol endpoint is {path}.\n"
)

JSON_CONTENT_TYPE = "application/json; charset=utf-8"
TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"

_BEARER_RE = re.compile(r"^Bearer\s+(\S+)\s*$", re.IGNORECASE)


### Responses ###

@dataclasses.dataclass(frozen=True)
class HttpResponse:
    """
    One HTTP answer, ready for whatever server writes it out.

    Attributes:
        status (int): the HTTP status code.
        headers (dict[str, str]): response headers, names in lower case.
        body (bytes): the body, empty for a status with none.
    """

    status: int
    headers: dict
    body: bytes

    def json(self):
        """The body parsed as JSON, for a caller that knows it is one."""
        return json.loads(self.body.decode("utf-8"))


def _text(status, text, extra_headers=None):
    """A plain-text answer."""
    headers = {"content-type": TEXT_CONTENT_TYPE, **(extra_headers or {})}
    return HttpResponse(status, headers, text.encode("utf-8"))


def _json(status, payload, extra_headers=None):
    """A JSON answer."""
    headers = {"content-type": JSON_CONTENT_TYPE, **(extra_headers or {})}
    return HttpResponse(status, headers, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _refusal(status, code, message, extra_headers=None):
    """A JSON-RPC error with no id, as the transport's own refusals carry."""
    return _json(status, {"jsonrpc": JSONRPC_VERSION, "id": None, "error": {"code": code, "message": message}},
                 extra_headers)


def status_for(answer):
    """
    The HTTP status one JSON-RPC answer travels with.

    The transport reserves two statuses for errors a client must tell
    apart from an application error: an unknown method is 404, so a
    client can distinguish it from a server that never hosted this
    endpoint, and an unsupported revision is 400, so a client falls back
    to the handshake era. A message that was not a request is 400 too.
    Every other answer, error or not, is 200.

    Args:
        answer (dict): the JSON-RPC message the server produced.

    Returns:
        int: the status code.
    """
    error = answer.get("error")
    if not error:
        return 200
    if error.get("code") == ERROR_METHOD_NOT_FOUND:
        return 404
    if error.get("code") in (ERROR_UNSUPPORTED_VERSION, ERROR_PARSE, ERROR_INVALID_REQUEST):
        return 400
    return 200


### Header Checks ###

def _lowered(headers):
    """The request headers keyed by lower-case name, whatever mapping came in."""
    return {str(name).lower(): value for name, value in headers.items()}


def decoded_header(value):
    """
    A mirrored header's value, decoded when the client wrapped it.

    Args:
        value (str | None): the header as received.

    Returns:
        str | None: the plain value, or None when it was absent or the
        wrapper did not hold valid UTF-8.
    """
    if value is None:
        return None
    if not (value.startswith(BASE64_PREFIX) and value.endswith(BASE64_SUFFIX)):
        return value
    encoded = value[len(BASE64_PREFIX):len(value) - len(BASE64_SUFFIX)]
    try:
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, ValueError):
        return None


def header_mismatch(headers, message):
    """
    The mismatch between the mirrored headers and the body, if any.

    A header that is present must agree with the body, because a
    gateway in front of this server may route on the header while this
    server acts on the body. A header that is absent is allowed, so
    clients written against the older revisions, which had no such
    headers, are still served.

    Args:
        headers (Mapping[str, str]): the request headers, any case.
        message (dict): the parsed body.

    Returns:
        str | None: what disagrees, or None.
    """
    headers = _lowered(headers)
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    body_version = meta.get(PROTOCOL_VERSION_KEY)
    header_version = headers.get(PROTOCOL_VERSION_HEADER)
    if header_version is not None and isinstance(body_version, str) and header_version != body_version:
        return (f"MCP-Protocol-Version header {header_version!r} does not match the body's "
                f"{body_version!r}")
    header_method = decoded_header(headers.get(METHOD_HEADER))
    if header_method is not None and header_method != message.get("method"):
        return f"Mcp-Method header {header_method!r} does not match the body's {message.get('method')!r}"
    header_name = decoded_header(headers.get(NAME_HEADER))
    if header_name is not None and message.get("method") == "tools/call" and header_name != params.get("name"):
        return f"Mcp-Name header {header_name!r} does not match the body's {params.get('name')!r}"
    return None


### Gates ###

def same_secret(presented, expected):
    """
    Whether two secrets are the same, in time that does not depend on
    where they first differ.

    Args:
        presented (str): what the request carried.
        expected (str): what the setting holds.

    Returns:
        bool
    """
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def presented_token(headers):
    """
    The bearer token a request presented, or None.

    Args:
        headers (Mapping[str, str]): the request headers, any case.

    Returns:
        str | None
    """
    value = _lowered(headers).get("authorization")
    if not value:
        return None
    match = _BEARER_RE.match(value)
    return match.group(1) if match else None


def allowed_origins(setting):
    """
    The origins a setting names, or None when the setting is empty.

    Args:
        setting (str | None): comma-separated origins, such as
            `https://assistant.example.org, https://other.example.org`.

    Returns:
        frozenset[str] | None: the origins in lower case, or None for no
        origin check at all.
    """
    if not setting:
        return None
    origins = frozenset(origin.strip().lower() for origin in setting.split(",") if origin.strip())
    return origins or None


### The Endpoint ###

def handle_http_request(method, target, headers, body, server, path=DEFAULT_MCP_PATH,
                        bearer_token=None, origins=None, max_body_bytes=MAX_BODY_BYTES,
                        description=None):
    """
    Answers one HTTP request to the protocol endpoint.

    Args:
        method (str): the HTTP method, any case.
        target (str): the request path, with or without a query string.
        headers (Mapping[str, str]): the request headers, any case.
        body (bytes): the request body as read. A caller that reads at
            most `max_body_bytes + 1` bytes lets the cap below refuse a
            larger body without holding it.
        server (extractium.mcp.server.KbServer): what answers messages.
        path (str): where the endpoint lives.
        bearer_token (str | None): a token every request must carry.
        origins (frozenset[str] | None): the browser origins allowed to
            call the endpoint, from `allowed_origins`; None checks none.
        max_body_bytes (int): the body cap.
        description (str | None): the text a browser sees at the root.

    Returns:
        HttpResponse: the answer.
    """
    method = method.upper()
    headers = _lowered(headers)
    request_path = target.split("?", 1)[0]

    if request_path == "/" and method == "GET":
        return _text(200, description or DEFAULT_DESCRIPTION.format(path=path))
    if request_path != path:
        return _text(404, "Not found.\n")

    # A browser page may only call this endpoint from an origin the
    # operator named. A request with no Origin header is not from a
    # browser page and passes; a request with one that is not listed is
    # refused, which is what stops a page on another site from using a
    # visitor's browser to reach here.
    origin = headers.get("origin")
    if origins is not None and origin is not None and origin.lower() not in origins:
        return _refusal(403, ERROR_INVALID_REQUEST, "This origin may not call this server.")

    if bearer_token:
        token = presented_token(headers)
        if token is None or not same_secret(token, bearer_token):
            return _refusal(401, ERROR_INVALID_REQUEST, "A bearer token is required.",
                            {"www-authenticate": "Bearer"})

    # The current revision has no GET stream and no session to end, so
    # the two methods older clients used for those are refused outright.
    if method != "POST":
        return _text(405, "Only POST is accepted here.\n", {"allow": "POST"})

    content_type = (headers.get("content-type") or "").lower()
    if not content_type.startswith("application/json"):
        return _refusal(415, ERROR_INVALID_REQUEST, "The body must be application/json.")

    too_large = f"The body is larger than the {max_body_bytes} bytes accepted."
    declared = headers.get("content-length")
    if declared is not None and declared.strip().isdigit() and int(declared) > max_body_bytes:
        return _refusal(413, ERROR_INVALID_REQUEST, too_large)
    if len(body) > max_body_bytes:
        return _refusal(413, ERROR_INVALID_REQUEST, too_large)

    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _refusal(400, ERROR_PARSE, "message is not valid JSON.")
    if not isinstance(message, dict):
        return _refusal(400, ERROR_INVALID_REQUEST,
                        "The body must be one JSON-RPC request or notification.")
    if "result" in message or "error" in message:
        return _refusal(400, ERROR_INVALID_REQUEST, "A client does not send responses to this endpoint.")
    if message.get("jsonrpc") != JSONRPC_VERSION:
        return _refusal(400, ERROR_INVALID_REQUEST, "message is not a JSON-RPC 2.0 request.")

    mismatch = header_mismatch(headers, message)
    if mismatch is not None:
        return _json(400, {
            "jsonrpc": JSONRPC_VERSION,
            "id": message.get("id"),
            "error": {"code": ERROR_HEADER_MISMATCH, "message": f"Header mismatch: {mismatch}"},
        })

    answer = server.handle(message)
    if answer is None:
        return HttpResponse(202, {}, b"")
    return _json(status_for(answer), answer)
