/*
 * Summary: The Streamable HTTP binding of the Model Context Protocol, over
 * the shared search server, for a hosted runtime that speaks the web's
 * Request and Response objects. One endpoint accepts POST; each request
 * is answered as one JSON object; there is no session, no server-sent
 * event stream, and nothing to keep between calls. Also holds the two
 * gates a public endpoint may want: an optional bearer token and an
 * optional origin allowlist.
 *
 * This file is part of Extractium™
 * examples/mcp/shared/mcp-http.js
 *
 * Author(s): Gabriel Mongefranco.
 * Created: 2026-09-12
 * Last Modified: 2026-09-12
 * Notes: See README file for documentation and full license information.
 *
 * Copyright © 2026 The Regents of the University of Michigan
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import {
    ERROR_INVALID_REQUEST,
    ERROR_METHOD_NOT_FOUND,
    ERROR_PARSE,
    ERROR_UNSUPPORTED_VERSION,
    errorMessage,
    requestedVersion,
} from './mcp-protocol.js';

/* ### Constants ### */

// The path the protocol endpoint answers on. Everything else is a short
// text page or a 404, so a person opening the address in a browser sees
// what the service is rather than an error.
export const DEFAULT_MCP_PATH = '/mcp';

// Largest request body read. A protocol message is a question and a few
// fields of metadata; anything past this is not one.
export const MAX_BODY_BYTES = 64 * 1024;

// The protocol's "the HTTP headers disagree with the body" error.
export const ERROR_HEADER_MISMATCH = -32020;

// Headers the transport mirrors from the body, and the one that names
// the revision. All are compared case-insensitively by the platform.
const PROTOCOL_VERSION_HEADER = 'MCP-Protocol-Version';
const METHOD_HEADER = 'Mcp-Method';
const NAME_HEADER = 'Mcp-Name';

// A header value the client could not send as plain text arrives in this
// wrapper, Base64 inside.
const BASE64_PREFIX = '=?base64?';
const BASE64_SUFFIX = '?=';

// Names of the settings the gates read.
export const BEARER_TOKEN_SETTING = 'EXTRACTIUM_BEARER_TOKEN';
export const ALLOWED_ORIGINS_SETTING = 'EXTRACTIUM_ALLOWED_ORIGINS';

const JSON_HEADERS = { 'content-type': 'application/json; charset=utf-8' };
const TEXT_HEADERS = { 'content-type': 'text/plain; charset=utf-8' };

/* ### Responses ### */

/** A JSON body with one status. */
function jsonResponse(status, body, extraHeaders = {}) {
    return new Response(JSON.stringify(body), { status, headers: { ...JSON_HEADERS, ...extraHeaders } });
}

/** A JSON-RPC error with no id, as the transport's own refusals carry. */
function refusal(status, code, message, extraHeaders = {}) {
    return jsonResponse(status, errorMessage(null, code, message), extraHeaders);
}

/**
 * The HTTP status one JSON-RPC answer travels with.
 *
 * The transport reserves two statuses for errors a client must tell apart
 * from an application error: an unknown method is 404, so a client can
 * distinguish it from a legacy server that never hosted this endpoint,
 * and an unsupported revision is 400, so a client falls back to the
 * handshake era. Every other answer, error or not, is 200.
 */
function statusFor(answer) {
    if (!answer.error) return 200;
    if (answer.error.code === ERROR_METHOD_NOT_FOUND) return 404;
    if (answer.error.code === ERROR_UNSUPPORTED_VERSION) return 400;
    if (answer.error.code === ERROR_PARSE || answer.error.code === ERROR_INVALID_REQUEST) return 400;
    return 200;
}

/* ### Header Checks ### */

/** A mirrored header's value, decoded when the client wrapped it. */
function decodedHeader(value) {
    if (value === null) return null;
    if (!value.startsWith(BASE64_PREFIX) || !value.endsWith(BASE64_SUFFIX)) return value;
    const encoded = value.slice(BASE64_PREFIX.length, value.length - BASE64_SUFFIX.length);
    try {
        return new TextDecoder('utf-8', { fatal: true })
            .decode(Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0)));
    } catch {
        return null;
    }
}

/**
 * The mismatch between the mirrored headers and the body, if any.
 *
 * A header that is present must agree with the body, because a gateway
 * in front of this server may route on the header while this server
 * acts on the body. A header that is absent is allowed, so that clients
 * written against the older revisions, which had no such headers, are
 * still served.
 *
 * @param {Headers} headers The request headers.
 * @param {Object} message The parsed body.
 * @returns {string|null} What disagrees, or null.
 */
export function headerMismatch(headers, message) {
    const params = (message.params && typeof message.params === 'object') ? message.params : {};
    const bodyVersion = requestedVersion(params);
    const headerVersion = headers.get(PROTOCOL_VERSION_HEADER);
    if (headerVersion !== null && bodyVersion !== null && headerVersion !== bodyVersion) {
        return `${PROTOCOL_VERSION_HEADER} header ${JSON.stringify(headerVersion)} does not match `
            + `the body's ${JSON.stringify(bodyVersion)}`;
    }
    const headerMethod = decodedHeader(headers.get(METHOD_HEADER));
    if (headerMethod !== null && headerMethod !== message.method) {
        return `${METHOD_HEADER} header ${JSON.stringify(headerMethod)} does not match the body's `
            + `${JSON.stringify(message.method)}`;
    }
    const headerName = decodedHeader(headers.get(NAME_HEADER));
    if (headerName !== null && message.method === 'tools/call' && headerName !== params.name) {
        return `${NAME_HEADER} header ${JSON.stringify(headerName)} does not match the body's `
            + `${JSON.stringify(params.name)}`;
    }
    return null;
}

/* ### Gates ### */

/**
 * Whether two secrets are the same, in time that does not depend on
 * where they first differ.
 *
 * @param {string} presented What the request carried.
 * @param {string} expected What the setting holds.
 * @returns {boolean}
 */
export function sameSecret(presented, expected) {
    const a = new TextEncoder().encode(presented);
    const b = new TextEncoder().encode(expected);
    let difference = a.length ^ b.length;
    const length = Math.max(a.length, b.length);
    for (let position = 0; position < length; position += 1) {
        difference |= (a[position] ?? 0) ^ (b[position] ?? 0);
    }
    return difference === 0;
}

/**
 * The bearer token a request presented, or null.
 *
 * @param {Headers} headers The request headers.
 * @returns {string|null}
 */
function presentedToken(headers) {
    const value = headers.get('authorization');
    if (!value) return null;
    const match = /^Bearer\s+(\S+)\s*$/i.exec(value);
    return match ? match[1] : null;
}

/**
 * The origins a setting names, or null when the setting is empty.
 *
 * @param {string|undefined} setting Comma-separated origins, such as
 *     `https://assistant.example.org, https://other.example.org`.
 * @returns {Set<string>|null}
 */
export function allowedOrigins(setting) {
    if (!setting) return null;
    const origins = setting.split(',').map((origin) => origin.trim().toLowerCase())
        .filter((origin) => origin !== '');
    return origins.length ? new Set(origins) : null;
}

/* ### The Endpoint ### */

/**
 * Answers one HTTP request to the protocol endpoint.
 *
 * @param {Request} request The incoming request.
 * @param {import('./mcp-protocol.js').SearchServer} server What answers
 *     protocol messages.
 * @param {{path?: string, bearerToken?: string, allowedOrigins?: Set<string>|null,
 *          maxBodyBytes?: number, description?: string}} [options]
 *     Where the endpoint lives, the optional token every request must
 *     carry, the optional set of browser origins allowed to call it, the
 *     body cap, and the text a browser sees at the root.
 * @returns {Promise<Response>}
 */
export async function handleMcpRequest(request, server, options = {}) {
    const path = options.path || DEFAULT_MCP_PATH;
    const url = new URL(request.url);

    if (url.pathname === '/' && request.method === 'GET') {
        const text = options.description
            || `An Extractium knowledge-base search server. The Model Context Protocol endpoint is ${path}.\n`;
        return new Response(text, { status: 200, headers: TEXT_HEADERS });
    }
    if (url.pathname !== path) {
        return new Response('Not found.\n', { status: 404, headers: TEXT_HEADERS });
    }

    // A browser page may only call this endpoint from an origin the
    // operator named. A request with no Origin header is not from a
    // browser page and passes; a request with one that is not listed is
    // refused, which is what stops a page on another site from using a
    // visitor's browser to reach here.
    const origin = request.headers.get('origin');
    if (options.allowedOrigins && origin !== null
        && !options.allowedOrigins.has(origin.toLowerCase())) {
        return refusal(403, ERROR_INVALID_REQUEST, 'This origin may not call this server.');
    }

    if (options.bearerToken) {
        const token = presentedToken(request.headers);
        if (token === null || !sameSecret(token, options.bearerToken)) {
            return refusal(401, ERROR_INVALID_REQUEST, 'A bearer token is required.', {
                'www-authenticate': 'Bearer',
            });
        }
    }

    // The current revision has no GET stream and no session to end, so
    // the two methods older clients used for those are refused outright.
    if (request.method !== 'POST') {
        return new Response('Only POST is accepted here.\n', {
            status: 405,
            headers: { ...TEXT_HEADERS, allow: 'POST' },
        });
    }

    const contentType = (request.headers.get('content-type') || '').toLowerCase();
    if (!contentType.startsWith('application/json')) {
        return refusal(415, ERROR_INVALID_REQUEST, 'The body must be application/json.');
    }

    const maxBytes = options.maxBodyBytes || MAX_BODY_BYTES;
    const declared = Number(request.headers.get('content-length'));
    if (Number.isFinite(declared) && declared > maxBytes) {
        return refusal(413, ERROR_INVALID_REQUEST, `The body is larger than the ${maxBytes} bytes accepted.`);
    }
    const body = new Uint8Array(await request.arrayBuffer());
    if (body.byteLength > maxBytes) {
        return refusal(413, ERROR_INVALID_REQUEST, `The body is larger than the ${maxBytes} bytes accepted.`);
    }

    let message;
    try {
        message = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body));
    } catch {
        return refusal(400, ERROR_PARSE, 'message is not valid JSON.');
    }
    if (message === null || typeof message !== 'object' || Array.isArray(message)) {
        return refusal(400, ERROR_INVALID_REQUEST, 'The body must be one JSON-RPC request or notification.');
    }
    if ('result' in message || 'error' in message) {
        return refusal(400, ERROR_INVALID_REQUEST, 'A client does not send responses to this endpoint.');
    }

    const mismatch = headerMismatch(request.headers, message);
    if (mismatch !== null) {
        return jsonResponse(400, errorMessage(message.id ?? null, ERROR_HEADER_MISMATCH, `Header mismatch: ${mismatch}`));
    }

    const answer = await server.handle(message);
    if (answer === null) return new Response(null, { status: 202 });
    return jsonResponse(statusFor(answer), answer);
}
