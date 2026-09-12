/*
 * Summary: Tests for the Cloudflare Worker: the golden compendium's D1
 * statements loaded into an in-process SQLite database that stands in for
 * the binding, keyword search from SQL, hybrid search with a fake AI
 * binding, the meta checks, vector decoding, and the HTTP round trip
 * through the Worker's own fetch handler.
 *
 * This file is part of Extractium™
 * examples/mcp/cloudflare/worker.test.js
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
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

import { bm25Candidates, loadContainer, tokenize } from '../../../clients/js/extractium-client.js';
import {
    D1Search,
    createWorkerServer,
    decodeVector,
    embeddableByWorkersAi,
    keywordPool,
    readMeta,
} from './d1-search.js';
import worker from './worker.js';

/* ### Fixtures ### */

const GOLDEN = new URL('../../../tests/golden/', import.meta.url);
const D1_SQL = fs.readFileSync(new URL('contract-d1.sql', GOLDEN), 'utf8');
const expectations = JSON.parse(fs.readFileSync(new URL('contract-query.json', GOLDEN), 'utf8'));
const container = loadContainer(new Uint8Array(fs.readFileSync(new URL('contract-container.json', GOLDEN))));

/**
 * Enough of the D1 binding to run the Worker's statements against an
 * in-process SQLite database. D1 hands a BLOB back as an array of byte
 * values, which is reproduced here so the decoder is tested on the shape
 * it meets in production.
 */
class FakeD1 {
    constructor(sql) {
        this.db = new DatabaseSync(':memory:');
        this.db.exec(sql);
    }

    prepare(sql) {
        const statement = this.db.prepare(sql);
        let bound = [];
        const rows = () => statement.all(...bound).map((row) => {
            const copy = {};
            for (const [key, value] of Object.entries(row)) {
                copy[key] = value instanceof Uint8Array ? Array.from(value) : value;
            }
            return copy;
        });
        const prepared = {
            bind(...values) { bound = values; return prepared; },
            async all() { return { results: rows(), success: true }; },
            async first(column) {
                const row = rows()[0];
                if (row === undefined) return null;
                return column === undefined ? row : row[column];
            },
        };
        return prepared;
    }
}

const db = new FakeD1(D1_SQL);
const meta = await readMeta(db);

/** A fake Workers AI binding that answers with the recorded query vector. */
const fakeAi = { run: async () => ({ shape: [1, 384], data: [expectations.queryVector] }) };

/* ### Meta ### */

test('the meta table names the index, the formula constants, and the vector encoding', () => {
    assert.equal(meta.name, 'Example Org');
    assert.equal(meta.builtAt, '2026-01-02T03:04:05Z');
    assert.equal(meta.childCount, container.size);
    assert.equal(meta.k, container.bm25.k);
    assert.equal(meta.b, container.bm25.b);
    assert.equal(meta.dims, container.dims);
    assert.equal(meta.queryPrefix, expectations.queryPrefix);
});

test('a database that is not an Extractium compendium is refused', async () => {
    const other = new FakeD1('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT); INSERT INTO meta VALUES (\'format\', \'other\');');
    await assert.rejects(() => readMeta(other), /not an Extractium compendium/);

    const old = new FakeD1('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT); INSERT INTO meta VALUES (\'format\', \'extractium-compendium\'), (\'v\', \'3\');');
    await assert.rejects(() => readMeta(old), /version "3" is not supported/);
});

test('Workers AI is used only for an index built with the model it serves', () => {
    assert.equal(embeddableByWorkersAi({ model: 'BAAI/bge-small-en-v1.5', dims: 384 }), true);
    assert.equal(embeddableByWorkersAi({ model: 'BAAI/bge-base-en-v1.5', dims: 768 }), false);
    assert.equal(embeddableByWorkersAi({ model: 'other/bge-small-en-v1.5', dims: 512 }), false);
});

/* ### Keyword search in SQL ### */

test('the pool scored in the database matches the pool the client scores in memory', async () => {
    const terms = tokenize(expectations.query);
    const fromSql = await keywordPool(db, meta, terms);
    const fromClient = bm25Candidates(terms, container.bm25, container.size);

    assert.deepEqual(fromSql.map((entry) => entry.cid), fromClient.map((entry) => entry.i));
    fromSql.forEach((entry, position) => {
        assert.ok(Math.abs(entry.s - fromClient[position].s) < 1e-9, `score of window ${entry.cid}`);
    });
});

test('a query with no known term yields an empty pool, and so does an empty query', async () => {
    assert.deepEqual(await keywordPool(db, meta, ['zzzzzzzz']), []);
    assert.deepEqual(await keywordPool(db, meta, []), []);
});

test('a term that reads like SQL is bound, not interpolated', async () => {
    const pool = await keywordPool(db, meta, ["disclaimer'; DROP TABLE parents; --", 'disclaimer']);

    assert.ok(pool.length > 0);
    assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM parents').first('n')) > 0, true);
});

/* ### Vectors ### */

test('a stored vector decodes to the floats the container holds', () => {
    const row = db.db.prepare('SELECT v FROM vectors WHERE cid = 1').get();
    const decoded = decodeVector(Array.from(row.v), meta);
    const fromContainer = container.vectors.subarray(container.dims, 2 * container.dims);

    assert.equal(decoded.length, container.dims);
    decoded.forEach((value, position) => {
        assert.ok(Math.abs(value - fromContainer[position]) < 1e-6, `value ${position}`);
    });
});

test('a vector of the wrong width is refused', () => {
    assert.throws(() => decodeVector([1, 2, 3], meta), /bytes/);
});

/* ### Searching ### */

test('keyword search returns whole sections, best first, with no embedder', async () => {
    const hits = await new D1Search(db, meta, null).search(expectations.query, expectations.k);

    assert.ok(hits.length > 0 && hits.length <= expectations.k);
    for (const hit of hits) {
        assert.ok(container.parents.some((parent) => parent.id === hit.parent.id));
        assert.equal(typeof hit.parent.x, 'string');
        assert.equal(hit.parent.local, false);
    }
    const ids = hits.map((hit) => hit.parent.id);
    assert.equal(new Set(ids).size, ids.length, 'no section twice');
});

test('hybrid search over the keyword pool returns the sections the clients rank as relevant', async () => {
    const search = new D1Search(db, meta, async () => expectations.queryVector);
    const hits = await search.search(expectations.query, expectations.k);

    assert.deepEqual(hits.map((hit) => hit.parent.id), expectations.relevantParentIds);
});

test('a question no term matches is an empty answer', async () => {
    assert.deepEqual(await new D1Search(db, meta, null).search('zzzz qqqq', 4), []);
});

/* ### The Worker ### */

test('the Worker answers a tool call over HTTP from the database, with the fake AI binding', async () => {
    const env = { DB: db, AI: fakeAi };
    const request = new Request('https://kb.example.workers.dev/mcp', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
            jsonrpc: '2.0', id: 1, method: 'tools/call',
            params: {
                name: 'search_kb',
                arguments: { query: expectations.query, k: expectations.k },
                _meta: { 'io.modelcontextprotocol/protocolVersion': '2026-07-28' },
            },
        }),
    });

    const answer = await worker.fetch(request, env);

    assert.equal(answer.status, 200);
    const body = await answer.json();
    assert.equal(body.result.structuredContent.index.name, 'Example Org');
    assert.match(body.result.content[0].text, /quoted evidence, not instructions/);
    const expected = expectations.relevantParentIds
        .map((id) => container.parents.find((parent) => parent.id === id).u);
    assert.deepEqual(body.result.structuredContent.results.map((record) => record.url), expected);
});

test('a Worker with a bearer token configured refuses a request without it', async () => {
    const server = createWorkerServer({ DB: db }, () => {});
    assert.ok(server);
    const env = { DB: db, EXTRACTIUM_BEARER_TOKEN: 'EXAMPLE_TOKEN' };
    const answer = await worker.fetch(new Request('https://kb.example.workers.dev/mcp', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'ping', params: {} }),
    }), env);

    assert.equal(answer.status, 401);
});

test('a database that cannot be read is a tool error carrying no internal detail', async () => {
    const broken = { prepare() { throw new Error('D1_ERROR: table meta not found in account 12345'); } };
    const server = createWorkerServer({ DB: broken }, () => {});
    const answer = await server.handle({
        jsonrpc: '2.0', id: 1, method: 'tools/call',
        params: { name: 'search_kb', arguments: { query: 'hours' } },
    });

    assert.equal(answer.result.isError, true);
    assert.doesNotMatch(answer.result.content[0].text, /12345/);
});
