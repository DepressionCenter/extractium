/*
 * Summary: Tests for the Val Town search: the container fetched once and
 * kept in a fake blob store, revalidated with a conditional request,
 * served from the store when the host is down, keyword search against
 * the golden compendium, hybrid search through a fake embedding service,
 * the parsing of the shapes such services answer with, the address rule,
 * and the staging script that assembles the val folder.
 *
 * This file is part of Extractium™
 * examples/mcp/valtown/kb.test.js
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
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { loadContainer } from '../../../clients/js/extractium-client.js';
import { ConfigurationError } from '../shared/mcp-protocol.js';
import {
    checkedUrl,
    containerBytes,
    createValServer,
    httpEmbedder,
    keywordSearch,
    parseEmbedding,
    storeKeys,
} from './kb.js';
import { SOURCE_FILES, relocatedImports, stage } from './stage.js';

/* ### Fixtures ### */

const GOLDEN = new URL('../../../tests/golden/', import.meta.url);
const CONTAINER_BYTES = new Uint8Array(fs.readFileSync(new URL('contract-container.json', GOLDEN)));
const expectations = JSON.parse(fs.readFileSync(new URL('contract-query.json', GOLDEN), 'utf8'));
const container = loadContainer(CONTAINER_BYTES);

const INDEX_URL = 'https://example.org/kb/kb-index.json';
const EMBED_URL = 'https://embed.example.org/v1/vectors';

/** A blob store in memory, with the shape main.http.ts builds over Val Town's. */
function fakeStore() {
    const bytes = new Map();
    const json = new Map();
    return {
        bytes,
        json,
        async getBytes(key) { return bytes.get(key) ?? null; },
        async setBytes(key, value) { bytes.set(key, value); },
        async getJSON(key) { return json.get(key); },
        async setJSON(key, value) { json.set(key, value); },
    };
}

/**
 * A fetch that serves the golden container with validators, answers 304
 * to a matching conditional request, and answers embedding requests with
 * the recorded query vector. Every call is recorded.
 */
function fakeFetch(options = {}) {
    const calls = [];
    const fetchImpl = async (url, init = {}) => {
        calls.push({ url, init });
        if (options.down) throw new TypeError('fetch failed');
        if (url === EMBED_URL) {
            return new Response(JSON.stringify(options.embedShape ?? [expectations.queryVector]), {
                status: 200, headers: { 'content-type': 'application/json' },
            });
        }
        const headers = init.headers || {};
        if (headers['If-None-Match'] === '"v1"') return new Response(null, { status: 304 });
        return new Response(CONTAINER_BYTES, {
            status: 200,
            headers: { etag: '"v1"', 'last-modified': 'Mon, 05 Jan 2026 00:00:00 GMT' },
        });
    };
    return { fetchImpl, calls };
}

/** A settings reader over a plain object. */
const settings = (values) => (name) => values[name];

/* ### The address ### */

test('only an HTTPS address is accepted on a hosted runtime', () => {
    assert.equal(checkedUrl(INDEX_URL), INDEX_URL);
    assert.throws(() => checkedUrl('http://localhost:8000/kb-index.json'), ConfigurationError);
    assert.throws(() => checkedUrl('http://example.org/kb-index.json'), ConfigurationError);
    assert.throws(() => checkedUrl(undefined), ConfigurationError);
    assert.throws(() => checkedUrl('not a url'), ConfigurationError);
});

test('a hostile address cannot pick the blob key', async () => {
    const keys = await storeKeys('https://example.org/../../secret?x=y');

    assert.match(keys.bodyKey, /^extractium:index:[0-9a-f]{64}$/);
    assert.match(keys.metaKey, /^extractium:index:[0-9a-f]{64}:meta$/);
});

/* ### The store ### */

test('the first load downloads the container and keeps it with its validators', async () => {
    const store = fakeStore();
    const { fetchImpl, calls } = fakeFetch();

    const result = await containerBytes(INDEX_URL, store, { fetchImpl });

    assert.equal(result.fromStore, false);
    assert.equal(result.bytes.byteLength, CONTAINER_BYTES.byteLength);
    assert.equal(calls.length, 1);
    assert.equal(store.bytes.size, 1);
    assert.deepEqual(Array.from(store.json.values())[0], {
        etag: '"v1"', lastModified: 'Mon, 05 Jan 2026 00:00:00 GMT',
    });
});

test('an unchanged container is read from the store after one conditional request', async () => {
    const store = fakeStore();
    const { fetchImpl, calls } = fakeFetch();
    await containerBytes(INDEX_URL, store, { fetchImpl });

    const again = await containerBytes(INDEX_URL, store, { fetchImpl });

    assert.equal(again.fromStore, true);
    assert.equal(calls[1].init.headers['If-None-Match'], '"v1"');
});

test('a host that cannot be reached falls back to the stored copy, and fails when nothing is stored', async () => {
    const store = fakeStore();
    await containerBytes(INDEX_URL, store, fakeFetch());
    const messages = [];

    const offline = await containerBytes(INDEX_URL, store, { ...fakeFetch({ down: true }), log: (m) => messages.push(m) });
    assert.equal(offline.fromStore, true);
    assert.match(messages[0], /stored copy/);

    await assert.rejects(() => containerBytes(INDEX_URL, fakeStore(), fakeFetch({ down: true })), TypeError);
});

test('a store that refuses the copy does not fail the load', async () => {
    const store = fakeStore();
    store.setBytes = async () => { throw new Error('blob too large for this plan'); };
    const messages = [];

    const result = await containerBytes(INDEX_URL, store, { ...fakeFetch(), log: (m) => messages.push(m) });

    assert.equal(result.bytes.byteLength, CONTAINER_BYTES.byteLength);
    assert.match(messages[0], /blob store/);
});

/* ### Embedding ### */

test('the shapes embedding services answer with are all read', () => {
    const vector = [0.1, 0.2, 0.3];
    assert.deepEqual(parseEmbedding(vector), vector);
    assert.deepEqual(parseEmbedding([vector]), vector);
    assert.deepEqual(parseEmbedding({ data: [vector] }), vector);
    assert.deepEqual(parseEmbedding({ result: { data: [vector] } }), vector);
    assert.throws(() => parseEmbedding({ error: 'no' }), /vector of numbers/);
    assert.throws(() => parseEmbedding([]), /vector of numbers/);
    assert.throws(() => parseEmbedding(['a', 'b']), /vector of numbers/);
});

test('the embedder posts the text, carries the token as a bearer token only, and checks the width', async () => {
    const { fetchImpl, calls } = fakeFetch();
    const embed = httpEmbedder(EMBED_URL, 'EXAMPLE_TOKEN', 384, { fetchImpl });

    const vector = await embed('a question');

    assert.equal(vector.length, 384);
    assert.equal(calls[0].url, EMBED_URL);
    assert.equal(calls[0].init.headers.authorization, 'Bearer EXAMPLE_TOKEN');
    assert.deepEqual(JSON.parse(calls[0].init.body), { inputs: 'a question' });
    assert.doesNotMatch(calls[0].url, /EXAMPLE_TOKEN/);

    const narrow = httpEmbedder(EMBED_URL, undefined, 384, fakeFetch({ embedShape: [[1, 2, 3]] }));
    await assert.rejects(() => narrow('x'), /returned 3 values/);
});

/* ### Searching ### */

test('keyword search alone returns whole sections, best first, and never one twice', () => {
    const hits = keywordSearch(container, expectations.query, expectations.k);

    assert.ok(hits.length > 0 && hits.length <= expectations.k);
    const ids = hits.map((hit) => hit.parent.id);
    assert.equal(new Set(ids).size, ids.length);
    assert.deepEqual(keywordSearch(container, 'zzzz qqqq', 4), []);
});

test('a val with no embedding service answers from keywords, loading the index once', async () => {
    const store = fakeStore();
    const { fetchImpl, calls } = fakeFetch();
    const server = createValServer({
        readSetting: settings({ EXTRACTIUM_INDEX_URL: INDEX_URL }), store, fetchImpl, now: () => 0,
    });

    const call = { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'search_kb', arguments: { query: expectations.query } } };
    const first = await server.handle(call);
    const second = await server.handle(call);

    assert.equal(first.result.isError, false);
    assert.equal(first.result.structuredContent.index.name, 'Example Org');
    assert.ok(first.result.structuredContent.results.length > 0);
    assert.deepEqual(second.result, first.result);
    assert.equal(calls.filter((c) => c.url === INDEX_URL).length, 1);
});

test('a val with an embedding service runs the full hybrid search the clients run', async () => {
    const server = createValServer({
        readSetting: settings({
            EXTRACTIUM_INDEX_URL: INDEX_URL,
            EXTRACTIUM_EMBED_URL: EMBED_URL,
            EXTRACTIUM_EMBED_TOKEN: 'EXAMPLE_TOKEN',
        }),
        store: fakeStore(),
        ...fakeFetch(),
    });

    const answer = await server.handle({
        jsonrpc: '2.0', id: 1, method: 'tools/call',
        params: { name: 'search_kb', arguments: { query: expectations.query, k: expectations.k } },
    });

    const expected = expectations.relevantParentIds
        .map((id) => container.parents.find((parent) => parent.id === id).u);
    assert.deepEqual(answer.result.structuredContent.results.map((record) => record.url), expected);
});

test('a warm val revalidates the index after the interval and keeps answering when the host is down', async () => {
    let clock = 0;
    const store = fakeStore();
    const { fetchImpl, calls } = fakeFetch();
    let currentFetch = fetchImpl;
    const messages = [];
    const server = createValServer({
        readSetting: settings({ EXTRACTIUM_INDEX_URL: INDEX_URL }),
        store,
        fetchImpl: (...args) => currentFetch(...args),
        now: () => clock,
        log: (m) => messages.push(m),
    });
    const call = { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'search_kb', arguments: { query: expectations.query } } };

    await server.handle(call);
    clock = 11 * 60 * 1000;
    await server.handle(call);
    assert.equal(calls.length, 2, 'one download and one conditional request');

    clock = 22 * 60 * 1000;
    currentFetch = fakeFetch({ down: true }).fetchImpl;
    const answer = await server.handle(call);
    assert.equal(answer.result.isError, false);
    assert.match(messages.at(-1), /stored copy|copy in memory/);
});

test('a val with no index address says which setting is missing', async () => {
    const server = createValServer({ readSetting: settings({}), store: fakeStore(), ...fakeFetch() });

    const answer = await server.handle({
        jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'search_kb', arguments: { query: 'hours' } },
    });

    assert.equal(answer.result.isError, true);
    assert.match(answer.result.content[0].text, /EXTRACTIUM_INDEX_URL/);
});

/* ### Staging ### */

test('imports that leave the folder are pointed at the copies beside the entry point', () => {
    const source = 'import { a } from \'../shared/mcp-http.js\';\n'
        + 'import { b } from "../../../clients/js/extractium-client.js";\n'
        + 'import { c } from "./kb.js";\n'
        + 'import { d } from "https://esm.town/v/std/blob/main.ts";\n';

    assert.equal(relocatedImports(source), 'import { a } from \'./mcp-http.js\';\n'
        + 'import { b } from "./extractium-client.js";\n'
        + 'import { c } from "./kb.js";\n'
        + 'import { d } from "https://esm.town/v/std/blob/main.ts";\n');
});

test('the staged folder holds every file the val needs, and every relative import in it resolves', async () => {
    const target = fs.mkdtempSync(path.join(os.tmpdir(), 'extractium-val-'));
    try {
        const written = await stage(target);

        assert.deepEqual(written, SOURCE_FILES.map((relative) => path.basename(relative)));
        for (const name of written) {
            const source = fs.readFileSync(path.join(target, name), 'utf8');
            for (const match of source.matchAll(/from\s+['"](\.[^'"]+)['"]/g)) {
                const imported = path.join(target, match[1]);
                assert.ok(fs.existsSync(imported), `${name} imports ${match[1]}, which is not staged`);
            }
        }
    } finally {
        fs.rmSync(target, { recursive: true, force: true });
    }
});
