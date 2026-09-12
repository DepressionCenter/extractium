/*
 * Summary: Tests for the Streamable HTTP binding: a tool call round trip
 * over HTTP against the committed golden compendium, the statuses the
 * transport reserves, the refusal of every method but POST, the header
 * checks, the body cap, and the two optional gates.
 *
 * This file is part of Extractium™
 * examples/mcp/shared/mcp-http.test.js
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

import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import { loadContainer } from '../../../clients/js/extractium-client.js';
import { ERROR_HEADER_MISMATCH, allowedOrigins, handleMcpRequest, sameSecret } from './mcp-http.js';
import { SearchServer } from './mcp-protocol.js';
import { TOOL_DEFINITION } from './search-tool.js';

/* ### Fixtures ### */

const GOLDEN = new URL('../../../tests/golden/', import.meta.url);
const CONTAINER_PATH = new URL('contract-container.json', GOLDEN);
const expectations = JSON.parse(fs.readFileSync(new URL('contract-query.json', GOLDEN), 'utf8'));

const ENDPOINT = 'https://kb.example.org/mcp';
const MODERN_META = { 'io.modelcontextprotocol/protocolVersion': '2026-07-28' };

/** A server over the golden compendium, the recorded vector standing in for a model. */
function goldenServer() {
    return new SearchServer({
        serverName: 'test-server',
        serverVersion: '0.0.0',
        openSearch: async () => {
            const index = loadContainer(new Uint8Array(fs.readFileSync(CONTAINER_PATH)));
            return {
                name: index.name,
                builtAt: index.header.builtAt,
                search: (query, k) => index.search(query, () => expectations.queryVector, { k }),
            };
        },
    });
}

/** One POST to the endpoint with a JSON body and any extra headers. */
function post(body, headers = {}, url = ENDPOINT) {
    return new Request(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json', ...headers },
        body: typeof body === 'string' ? body : JSON.stringify(body),
    });
}

/** A request message with an id, the modern metadata included. */
function request(id, method, params = {}) {
    return { jsonrpc: '2.0', id, method, params: { ...params, _meta: MODERN_META } };
}

/* ### The round trip ### */

test('a tool call over HTTP returns the sections the client ranks for the recorded query', async () => {
    const answer = await handleMcpRequest(post(request(1, 'tools/call', {
        name: 'search_kb',
        arguments: { query: expectations.query, k: expectations.k },
    }), { 'MCP-Protocol-Version': '2026-07-28', 'Mcp-Method': 'tools/call', 'Mcp-Name': 'search_kb' }), goldenServer());

    assert.equal(answer.status, 200);
    assert.match(answer.headers.get('content-type'), /^application\/json/);
    const body = await answer.json();
    const index = loadContainer(new Uint8Array(fs.readFileSync(CONTAINER_PATH)));
    const expected = expectations.relevantParentIds
        .map((id) => index.parents.find((parent) => parent.id === id).u);
    assert.deepEqual(body.result.structuredContent.results.map((record) => record.url), expected);
    assert.equal(body.result.resultType, 'complete');
});

test('the tool list is served, and a legacy client gets its handshake', async () => {
    const list = await (await handleMcpRequest(post(request(1, 'tools/list')), goldenServer())).json();
    assert.deepEqual(list.result.tools, [TOOL_DEFINITION]);

    const legacy = await handleMcpRequest(post({
        jsonrpc: '2.0', id: 2, method: 'initialize', params: { protocolVersion: '2025-06-18' },
    }), goldenServer());
    assert.equal(legacy.status, 200);
    assert.equal((await legacy.json()).result.protocolVersion, '2025-06-18');
});

/* ### Statuses the transport reserves ### */

test('a notification is accepted with no body', async () => {
    const answer = await handleMcpRequest(post({ jsonrpc: '2.0', method: 'notifications/initialized' }), goldenServer());

    assert.equal(answer.status, 202);
    assert.equal(await answer.text(), '');
});

test('an unknown method is 404 with the JSON-RPC error a client tells apart from a missing endpoint', async () => {
    const answer = await handleMcpRequest(post(request(1, 'resources/list')), goldenServer());

    assert.equal(answer.status, 404);
    assert.equal((await answer.json()).error.code, -32601);
});

test('an unsupported revision is 400 with the list of supported ones', async () => {
    const answer = await handleMcpRequest(post({
        jsonrpc: '2.0', id: 1, method: 'tools/list',
        params: { _meta: { 'io.modelcontextprotocol/protocolVersion': '1900-01-01' } },
    }), goldenServer());

    assert.equal(answer.status, 400);
    const body = await answer.json();
    assert.equal(body.error.code, -32022);
    assert.ok(body.error.data.supported.includes('2026-07-28'));
});

test('a tool error is a 200 result the model reads, not an HTTP failure', async () => {
    const answer = await handleMcpRequest(post(request(1, 'tools/call', {
        name: 'search_kb', arguments: { query: '   ' },
    })), goldenServer());

    assert.equal(answer.status, 200);
    assert.equal((await answer.json()).result.isError, true);
});

test('a body that is not JSON is 400 with a parse error', async () => {
    const answer = await handleMcpRequest(post('{not json'), goldenServer());

    assert.equal(answer.status, 400);
    assert.equal((await answer.json()).error.code, -32700);
});

test('a batch, a response, and a bare value are all refused', async () => {
    for (const body of [[request(1, 'ping')], { jsonrpc: '2.0', id: 1, result: {} }, '42']) {
        const answer = await handleMcpRequest(post(body), goldenServer());
        assert.equal(answer.status, 400, JSON.stringify(body));
    }
});

/* ### Methods and paths ### */

test('GET and DELETE on the endpoint are 405, because there is no stream and no session', async () => {
    for (const method of ['GET', 'DELETE']) {
        const answer = await handleMcpRequest(new Request(ENDPOINT, { method }), goldenServer());
        assert.equal(answer.status, 405, method);
        assert.equal(answer.headers.get('allow'), 'POST');
    }
});

test('the root answers a browser with a line of text, and any other path is 404', async () => {
    const root = await handleMcpRequest(new Request('https://kb.example.org/'), goldenServer());
    assert.equal(root.status, 200);
    assert.match(await root.text(), /\/mcp/);

    const other = await handleMcpRequest(post(request(1, 'ping'), {}, 'https://kb.example.org/admin'), goldenServer());
    assert.equal(other.status, 404);
});

test('a body that is not JSON by content type is refused before it is read', async () => {
    const answer = await handleMcpRequest(new Request(ENDPOINT, {
        method: 'POST', headers: { 'content-type': 'text/plain' }, body: 'hello',
    }), goldenServer());

    assert.equal(answer.status, 415);
});

test('a body past the cap is refused', async () => {
    const huge = request(1, 'tools/call', { name: 'search_kb', arguments: { query: 'x'.repeat(70_000) } });
    const answer = await handleMcpRequest(post(huge), goldenServer());

    assert.equal(answer.status, 413);
});

/* ### Mirrored headers ### */

test('a mirrored header that disagrees with the body is a header mismatch', async () => {
    const cases = [
        { 'MCP-Protocol-Version': '2025-11-25' },
        { 'Mcp-Method': 'tools/list' },
        { 'Mcp-Name': 'other_tool' },
        { 'Mcp-Name': `=?base64?${Buffer.from('other_tool').toString('base64')}?=` },
    ];
    for (const headers of cases) {
        const answer = await handleMcpRequest(post(request(7, 'tools/call', {
            name: 'search_kb', arguments: { query: 'hours' },
        }), headers), goldenServer());
        assert.equal(answer.status, 400, JSON.stringify(headers));
        const body = await answer.json();
        assert.equal(body.error.code, ERROR_HEADER_MISMATCH);
        assert.equal(body.id, 7);
    }
});

test('a mirrored header that agrees, plain or Base64-wrapped, passes', async () => {
    const wrapped = `=?base64?${Buffer.from('search_kb').toString('base64')}?=`;
    const answer = await handleMcpRequest(post(request(1, 'tools/call', {
        name: 'search_kb', arguments: { query: expectations.query },
    }), { 'Mcp-Method': 'tools/call', 'Mcp-Name': wrapped }), goldenServer());

    assert.equal(answer.status, 200);
});

test('a session id from an older client is ignored rather than refused', async () => {
    const answer = await handleMcpRequest(post(request(1, 'ping'), { 'Mcp-Session-Id': 'abc' }), goldenServer());

    assert.equal(answer.status, 200);
    assert.equal(answer.headers.get('mcp-session-id'), null);
});

/* ### Gates ### */

test('with a bearer token configured, a request without the right one is 401', async () => {
    const options = { bearerToken: 'EXAMPLE_TOKEN' };
    const missing = await handleMcpRequest(post(request(1, 'ping')), goldenServer(), options);
    assert.equal(missing.status, 401);
    assert.equal(missing.headers.get('www-authenticate'), 'Bearer');

    const wrong = await handleMcpRequest(post(request(1, 'ping'), { authorization: 'Bearer EXAMPLE_TOKE' }), goldenServer(), options);
    assert.equal(wrong.status, 401);

    const right = await handleMcpRequest(post(request(1, 'ping'), { authorization: 'Bearer EXAMPLE_TOKEN' }), goldenServer(), options);
    assert.equal(right.status, 200);
});

test('secrets are compared whole, whatever their length', () => {
    assert.equal(sameSecret('abc', 'abc'), true);
    assert.equal(sameSecret('abc', 'abcd'), false);
    assert.equal(sameSecret('', 'a'), false);
    assert.equal(sameSecret('', ''), true);
});

test('with an origin allowlist, a browser origin off the list is 403 and a non-browser caller passes', async () => {
    const options = { allowedOrigins: allowedOrigins('https://assistant.example.org, https://Other.example.org') };
    const off = await handleMcpRequest(post(request(1, 'ping'), { origin: 'https://evil.example.net' }), goldenServer(), options);
    assert.equal(off.status, 403);

    const on = await handleMcpRequest(post(request(1, 'ping'), { origin: 'https://other.example.org' }), goldenServer(), options);
    assert.equal(on.status, 200);

    const none = await handleMcpRequest(post(request(1, 'ping')), goldenServer(), options);
    assert.equal(none.status, 200);
});

test('an empty allowlist setting means no origin check', () => {
    assert.equal(allowedOrigins(''), null);
    assert.equal(allowedOrigins(undefined), null);
    assert.equal(allowedOrigins(' , '), null);
});
