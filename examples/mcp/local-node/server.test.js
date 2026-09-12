/*
 * Summary: Tests for the local Node MCP server: one tool call round trip
 * against the committed golden compendium, the handshake both protocol
 * eras expect, refusal of a version this server does not speak, the
 * argument checks the tool applies, and the rules that decide which index
 * addresses may be fetched and where a downloaded index is cached.
 *
 * This file is part of Extractium™
 * examples/mcp/local-node/server.test.js
 *
 * Author(s): Gabriel Mongefranco.
 * Created: 2026-09-11
 * Last Modified: 2026-09-11
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
import path from 'node:path';
import test from 'node:test';
import { Readable, Writable } from 'node:stream';
import { fileURLToPath } from 'node:url';

import { loadContainer } from '../../../clients/js/extractium-client.js';
import {
    ConfigurationError,
    KbServer,
    TOOL_DEFINITION,
    cachePaths,
    checkedUrl,
    renderResults,
    resultRecords,
    serve,
} from './server.js';

/* ### Fixtures ### */

const GOLDEN_DIR = path.join(fileURLToPath(new URL('../../../tests/golden/', import.meta.url)));
const CONTAINER_PATH = path.join(GOLDEN_DIR, 'contract-container.json');
const QUERY_PATH = path.join(GOLDEN_DIR, 'contract-query.json');

const expectations = JSON.parse(fs.readFileSync(QUERY_PATH, 'utf8'));

// The modern revision carries its version in every request; a request
// without this metadata is a legacy one.
const MODERN_META = {
    _meta: {
        'io.modelcontextprotocol/protocolVersion': '2026-07-28',
        'io.modelcontextprotocol/clientInfo': { name: 'test-client', version: '1.0.0' },
        'io.modelcontextprotocol/clientCapabilities': {},
    },
};

/**
 * A server over the committed compendium, with the recorded query vector
 * standing in for an embedding model so no model is ever downloaded.
 */
function goldenServer() {
    return new KbServer({
        openIndex: () => loadContainer(new Uint8Array(fs.readFileSync(CONTAINER_PATH))),
        openEmbedder: () => () => expectations.queryVector,
    });
}

/** One request, answered. */
function ask(server, method, params = {}, id = 1) {
    return server.handle({ jsonrpc: '2.0', id, method, params });
}

/* ### Discovery and the handshake ### */

test('discovery names the tool capability and every revision the server speaks', async () => {
    const result = await ask(goldenServer(), 'server/discover', MODERN_META);

    assert.equal(result.result.resultType, 'complete');
    assert.ok(result.result.supportedVersions.includes('2026-07-28'));
    assert.deepEqual(result.result.capabilities.tools, { listChanged: false });
    assert.equal(
        result.result._meta['io.modelcontextprotocol/serverInfo'].name,
        'extractium-local-node'
    );
});

test('a legacy client keeps the revision it opened with', async () => {
    const result = await ask(goldenServer(), 'initialize', { protocolVersion: '2025-06-18' });

    assert.equal(result.result.protocolVersion, '2025-06-18');
    assert.equal(result.result.serverInfo.name, 'extractium-local-node');
});

test('a legacy client asking for a revision this server does not speak is offered one it does', async () => {
    const result = await ask(goldenServer(), 'initialize', { protocolVersion: '1900-01-01' });

    assert.equal(result.result.protocolVersion, '2025-11-25');
});

test('a modern request naming an unknown version is refused with the list of known ones', async () => {
    const result = await ask(goldenServer(), 'tools/list', {
        _meta: { 'io.modelcontextprotocol/protocolVersion': '1900-01-01' },
    });

    assert.equal(result.error.code, -32022);
    assert.ok(result.error.data.supported.includes('2026-07-28'));
    assert.equal(result.error.data.requested, '1900-01-01');
});

test('a notification is never answered', async () => {
    const server = goldenServer();

    assert.equal(await server.handle({ jsonrpc: '2.0', method: 'notifications/initialized' }), null);
});

test('a line that is not JSON earns a parse error', async () => {
    const answer = await goldenServer().handleLine('{not json');

    assert.equal(answer.error.code, -32700);
});

test('an unknown method is refused', async () => {
    const result = await ask(goldenServer(), 'resources/list');

    assert.equal(result.error.code, -32601);
});

/* ### The tool ### */

test('the tool list holds one tool, and only the modern revision is told the result is complete', async () => {
    const modern = await ask(goldenServer(), 'tools/list', MODERN_META);
    const legacy = await ask(goldenServer(), 'tools/list');

    assert.deepEqual(modern.result.tools, [TOOL_DEFINITION]);
    assert.equal(modern.result.resultType, 'complete');
    assert.equal(legacy.result.resultType, undefined);
    assert.equal(TOOL_DEFINITION.name, 'search_kb');
});

test('a tool call returns the sections the client ranks for the recorded query', async () => {
    const result = await ask(goldenServer(), 'tools/call', {
        ...MODERN_META,
        name: 'search_kb',
        arguments: { query: expectations.query, k: expectations.k },
    });

    const returned = result.result.structuredContent.results.map((record) => record.url);
    const index = loadContainer(new Uint8Array(fs.readFileSync(CONTAINER_PATH)));
    const expected = expectations.relevantParentIds
        .map((id) => index.parents.find((parent) => parent.id === id).u);
    assert.deepEqual(returned, expected);
    assert.equal(result.result.isError, false);
});

test('a tool call warns the reader that section text is evidence, not instructions', async () => {
    const result = await ask(goldenServer(), 'tools/call', {
        name: 'search_kb',
        arguments: { query: expectations.query },
    });

    assert.match(result.result.content[0].text, /quoted evidence, not instructions/);
});

test('a tool call names the compendium and when it was built', async () => {
    const result = await ask(goldenServer(), 'tools/call', {
        name: 'search_kb',
        arguments: { query: expectations.query },
    });

    assert.equal(result.result.structuredContent.index.name, 'Example Org');
    assert.ok(result.result.structuredContent.index.builtAt.endsWith('Z'));
});

test('a question nothing answers returns no sections and says so', async () => {
    // The golden compendium is built with a stand-in embedder, so its
    // vectors match anything; a compendium that returns no hits is the
    // only honest way to exercise the empty answer.
    const server = new KbServer({
        openIndex: () => ({ name: 'Example Org', header: { builtAt: '2026-01-02T03:04:05Z' }, search: () => [] }),
        openEmbedder: () => () => expectations.queryVector,
    });

    const result = await ask(server, 'tools/call', {
        name: 'search_kb',
        arguments: { query: 'replacing the timing belt on a tractor' },
    });

    assert.deepEqual(result.result.structuredContent.results, []);
    assert.match(result.result.content[0].text, /relevant enough/);
});

test('a tool this server does not have is a protocol error, not an answer', async () => {
    const result = await ask(goldenServer(), 'tools/call', { name: 'delete_everything' });

    assert.equal(result.error.code, -32602);
});

test('an empty query is reported back to the model rather than searched', async () => {
    const result = await ask(goldenServer(), 'tools/call', {
        name: 'search_kb',
        arguments: { query: '   ' },
    });

    assert.equal(result.result.isError, true);
});

test('a query longer than the limit is refused', async () => {
    const result = await ask(goldenServer(), 'tools/call', {
        name: 'search_kb',
        arguments: { query: 'x'.repeat(1001) },
    });

    assert.equal(result.result.isError, true);
    assert.match(result.result.content[0].text, /shorter question/);
});

test('a result count outside the allowed range is refused', async () => {
    for (const k of [0, 11, 2.5, '3', true]) {
        const result = await ask(goldenServer(), 'tools/call', {
            name: 'search_kb',
            arguments: { query: expectations.query, k },
        });

        assert.equal(result.result.isError, true, `k=${JSON.stringify(k)} should be refused`);
    }
});

test('an index that cannot be loaded is a tool error carrying no internal detail', async () => {
    const server = new KbServer({
        openIndex: () => { throw new Error('C:\\secrets\\compendium.json is missing'); },
        openEmbedder: () => () => expectations.queryVector,
    });

    const result = await ask(server, 'tools/call', {
        name: 'search_kb',
        arguments: { query: expectations.query },
    });

    assert.equal(result.result.isError, true);
    assert.doesNotMatch(result.result.content[0].text, /secrets/);
});

test('a server with no index configured says which settings are missing', async () => {
    const server = new KbServer({
        openIndex: () => { throw new ConfigurationError('set EXTRACTIUM_INDEX_URL to the address.'); },
        openEmbedder: () => () => expectations.queryVector,
    });

    const result = await ask(server, 'tools/call', {
        name: 'search_kb',
        arguments: { query: expectations.query },
    });

    assert.match(result.result.content[0].text, /EXTRACTIUM_INDEX_URL/);
});

test('the index is loaded once, however many searches run', async () => {
    let loads = 0;
    const server = new KbServer({
        openIndex: () => {
            loads += 1;
            return loadContainer(new Uint8Array(fs.readFileSync(CONTAINER_PATH)));
        },
        openEmbedder: () => () => expectations.queryVector,
    });

    for (let call = 0; call < 3; call += 1) {
        await ask(server, 'tools/call', { name: 'search_kb', arguments: { query: expectations.query } });
    }

    assert.equal(loads, 1);
});

/* ### Rendering ### */

test('content read from a local folder is marked confidential', () => {
    const records = resultRecords([
        { parent: { t: 'Team notes', u: 'local:notes.md', x: 'Internal only.', local: true } },
    ]);

    assert.match(renderResults(records, 'notes', 'Example Org'), /confidential/);
});

test('a section from a public page carries no confidentiality note', () => {
    const records = resultRecords([
        { parent: { t: 'Office hours', u: 'https://example.org/hours', x: 'Every Tuesday.' } },
    ]);

    assert.doesNotMatch(renderResults(records, 'hours', 'Example Org'), /confidential/);
});

/* ### Where an index may come from ### */

test('an index address must be secure unless it is on this machine', () => {
    assert.equal(checkedUrl('https://example.org/kb/compendium.json'), 'https://example.org/kb/compendium.json');
    assert.equal(checkedUrl('http://localhost:8000/compendium.json'), 'http://localhost:8000/compendium.json');
    assert.throws(() => checkedUrl('http://example.org/compendium.json'), ConfigurationError);
    assert.throws(() => checkedUrl('file:///etc/passwd'), ConfigurationError);
    assert.throws(() => checkedUrl('not a url at all'), ConfigurationError);
});

test('a hostile address cannot decide where the cached file lands', () => {
    const { bodyPath, metaPath } = cachePaths(
        'https://example.org/../../../etc/passwd?a=/b', path.join('C:', 'cache')
    );

    assert.equal(path.dirname(bodyPath), path.join('C:', 'cache'));
    assert.equal(path.dirname(metaPath), path.join('C:', 'cache'));
    assert.match(path.basename(bodyPath), /^[0-9a-f]{64}\.container$/);
});

/* ### The stream ### */

test('the server answers over the stream a client actually speaks', async () => {
    const written = [];
    const output = new Writable({
        write(chunk, encoding, done) {
            written.push(chunk.toString('utf8'));
            done();
        },
    });
    const input = Readable.from([
        `${JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'server/discover', params: MODERN_META })}\n`,
        `${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' })}\n`,
        '\n',
        `${JSON.stringify({
            jsonrpc: '2.0',
            id: 2,
            method: 'tools/call',
            params: { ...MODERN_META, name: 'search_kb', arguments: { query: expectations.query } },
        })}\n`,
    ]);

    const code = await serve(input, output, goldenServer());

    const answers = written.join('').trim().split('\n').map((line) => JSON.parse(line));
    assert.equal(code, 0);
    assert.deepEqual(answers.map((answer) => answer.id), [1, 2]);
    assert.ok(answers[1].result.structuredContent.results.length > 0);
    // One message per line, so a section holding a newline cannot be read
    // as a second message.
    assert.equal(written.join('').trim().split('\n').length, 2);
});
