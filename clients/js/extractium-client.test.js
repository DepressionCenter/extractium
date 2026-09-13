/*
 * Summary: Tests for the JavaScript compendium client. Covers each stage
 * of the search (tokenizing, cosine candidates, BM25 candidates, rank
 * fusion, the relevance cutoff, diversity selection, resolving a window
 * to its section), every refusal in the container format's reader
 * checklist, and the cross-language contract: the ranking recorded in
 * tests/golden/contract-query.json, which extractium/search.py must
 * produce from the same file. Run with `node --test clients/js`.
 *
 * This file is part of Extractium™
 * clients/js/extractium-client.test.js
 *
 * Author(s): Gabriel Mongefranco.
 * Created: 2026-09-08
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
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
    CANDIDATE_POOL,
    ContainerError,
    RRF_K,
    SCORE_MIN,
    SOURCE_CAP,
    bm25Candidates,
    diversify,
    inflateContainer,
    loadContainer,
    relevanceCutoff,
    rrfFuse,
    tokenize,
    vectorCandidates,
} from './extractium-client.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const GOLDEN = path.join(HERE, '..', '..', 'tests', 'golden');

/* ### Test Doubles ### */

/** A section record with the fields the client reads. */
function parent(id, fields = {}) {
    return {
        id,
        t: fields.t || `Section ${id}`,
        x: fields.x || 'Synthetic section text for the client tests.',
        u: fields.u || `https://example.org/${id}`,
        host: 'example.org',
        source_type: 'web',
        content_type: 'page',
        source_label: 'Example Website',
        categories: [],
        local: false,
        weight: fields.weight === undefined ? 1 : fields.weight,
    };
}

/**
 * Serializes a header and its vectors the way the container adapter does,
 * so the reader checks can be exercised without a Python build.
 */
function containerBytes(header, vectors, { dtype = 'float32', headerLength } = {}) {
    const headerBytes = new TextEncoder().encode(JSON.stringify(header));
    const body = dtype === 'int8' ? Int8Array.from(vectors) : Float32Array.from(vectors);
    const bytes = new Uint8Array(4 + headerBytes.length + body.byteLength);
    new DataView(bytes.buffer).setUint32(0, headerLength === undefined ? headerBytes.length : headerLength, true);
    bytes.set(headerBytes, 4);
    bytes.set(new Uint8Array(body.buffer, body.byteOffset, body.byteLength), 4 + headerBytes.length);
    return bytes;
}

/** A minimal but complete two-window container. */
function sampleHeader(overrides = {}) {
    return {
        format: 'extractium-compendium',
        v: 4,
        extractium: '0.1.0',
        builtAt: '2026-01-02T03:04:05Z',
        site: 'Example Org',
        sourceCount: 2,
        embedding: {
            model: 'BAAI/bge-small-en-v1.5',
            browserModel: 'Xenova/bge-small-en-v1.5',
            dims: 2,
            normalized: true,
            queryPrefix: 'Represent this sentence for searching relevant passages: ',
            passagePrefix: '',
            dtype: 'float32',
        },
        offsetUnit: 'utf16',
        parents: [parent('aaaaaaaaaaaaaaaa', { x: 'Alpha section text.' }), parent('bbbbbbbbbbbbbbbb')],
        children: { pid: [0, 1], start: [0, 0], end: [5, 5] },
        bm25: null,
        calibration: { mean: 0, std: 0, sampleSize: 0 },
        ...overrides,
    };
}

/* ### Tokenizing ### */

test('tokenize keeps runs of three or more letters or digits, lowercased', () => {
    assert.deepEqual(tokenize('Weekly BUILD of compendium v3 a an'), ['weekly', 'build', 'compendium']);
});

test('tokenize handles empty and missing text', () => {
    assert.deepEqual(tokenize(''), []);
    assert.deepEqual(tokenize(null), []);
});

/* ### Vector Candidates ### */

test('vectorCandidates ranks by cosine similarity, best first', () => {
    const vectors = Float32Array.from([1, 0, 0, 1, 0.7071, 0.7071]);

    const ranked = vectorCandidates([1, 0], vectors, 2);

    assert.deepEqual(ranked.map((entry) => entry.i), [0, 2, 1]);
    assert.ok(Math.abs(ranked[0].s - 1) < 1e-6);
});

test('vectorCandidates normalizes a query vector it is handed unnormalized', () => {
    const vectors = Float32Array.from([1, 0]);

    const [hit] = vectorCandidates([10, 0], vectors, 2);

    assert.ok(Math.abs(hit.s - 1) < 1e-6);
});

test('vectorCandidates keeps at most the pool size', () => {
    const vectors = new Float32Array(2 * (CANDIDATE_POOL + 5)).fill(1);

    assert.equal(vectorCandidates([1, 1], vectors, 2).length, CANDIDATE_POOL);
});

test('vectorCandidates breaks score ties on the child index', () => {
    const vectors = Float32Array.from([1, 0, 1, 0, 1, 0]);

    assert.deepEqual(vectorCandidates([1, 0], vectors, 2).map((entry) => entry.i), [0, 1, 2]);
});

/* ### Keyword Candidates ### */

const KEYWORD_STATS = {
    k: 1.2,
    b: 0.75,
    d: 0.5,
    avgDocLen: 10,
    docLen: [10, 10, 10],
    df: new Map([['crawler', 1], ['index', 3]]),
    postings: new Map([['crawler', [[2, 3]]], ['index', [[0, 1], [1, 1], [2, 1]]]]),
};

test('bm25Candidates scores only the windows a query term appears in', () => {
    const ranked = bm25Candidates(['crawler'], KEYWORD_STATS, 3);

    assert.deepEqual(ranked.map((entry) => entry.i), [2]);
    assert.ok(ranked[0].s > 0);
});

test('bm25Candidates gives a rare term more weight than a common one', () => {
    const [rare] = bm25Candidates(['crawler'], KEYWORD_STATS, 3);
    const [common] = bm25Candidates(['index'], KEYWORD_STATS, 3);

    assert.ok(rare.s > common.s);
});

test('bm25Candidates returns nothing without statistics or terms', () => {
    assert.deepEqual(bm25Candidates(['crawler'], null, 3), []);
    assert.deepEqual(bm25Candidates([], KEYWORD_STATS, 3), []);
});

/* ### Fusion ### */

test('rrfFuse scores by rank alone, not by the incoming scores', () => {
    const vectorList = [{ i: 7, s: 0.9 }, { i: 8, s: 0.8 }];
    const keywordList = [{ i: 8, s: 42 }, { i: 7, s: 0.1 }];

    const fused = rrfFuse([{ items: vectorList, listWeight: 0.5 }, { items: keywordList, listWeight: 0.5 }]);

    const expected = 0.5 * (RRF_K / (RRF_K + 1)) + 0.5 * (RRF_K / (RRF_K + 2));
    assert.equal(fused.length, 2);
    for (const entry of fused) assert.ok(Math.abs(entry.s - expected) < 1e-12);
});

test('rrfFuse applies the per-section weight after fusion', () => {
    const items = [{ i: 1, s: 0.9 }, { i: 2, s: 0.8 }];

    const fused = rrfFuse([{ items, listWeight: 1 }], (childIndex) => (childIndex === 2 ? 5 : 1));

    assert.deepEqual(fused.map((entry) => entry.i), [2, 1]);
});

/* ### Relevance Cutoff ### */

test('relevanceCutoff never drops below the absolute floor', () => {
    const candidates = [{ s: 0.1 }, { s: 0.2 }, { s: 0.3 }];

    assert.equal(relevanceCutoff(candidates, null), SCORE_MIN);
});

test('relevanceCutoff rises with the pool median', () => {
    const candidates = [{ s: 0.8 }, { s: 0.9 }, { s: 0.95 }];

    assert.ok(Math.abs(relevanceCutoff(candidates, null) - 0.93) < 1e-9);
});

test('relevanceCutoff uses the calibration statistics when they are stricter', () => {
    const candidates = [{ s: 0.5 }, { s: 0.5 }, { s: 0.5 }];

    assert.ok(Math.abs(relevanceCutoff(candidates, { mean: 0.7, std: 0.1 }) - 0.8) < 1e-9);
});

test('relevanceCutoff ignores calibration with no spread and falls back to the pool', () => {
    const candidates = [{ s: 0.5 }, { s: 0.5 }, { s: 0.5 }];

    assert.ok(Math.abs(relevanceCutoff(candidates, { mean: 0.9, std: 0 }) - 0.53) < 1e-9);
});

/* ### Diversity Selection ### */

test('diversify drops everything below the cutoff', () => {
    const candidates = [{ i: 0, s: 0.2 }, { i: 1, s: 0.1 }];
    const vectors = Float32Array.from([1, 0, 0, 1]);

    assert.deepEqual(diversify(candidates, vectors, 2, 4, () => 'one', false, null), []);
});

test('diversify returns the closest windows when the threshold is skipped', () => {
    const candidates = [{ i: 0, s: 0.2 }, { i: 1, s: 0.1 }];
    const vectors = Float32Array.from([1, 0, 0, 1]);

    const selected = diversify(candidates, vectors, 2, 4, (i) => String(i), true, null);

    assert.deepEqual(selected.map((entry) => entry.i), [0, 1]);
});

test('diversify caps how many windows one section contributes', () => {
    const candidates = [0, 1, 2, 3].map((i) => ({ i, s: 0.9 - i * 0.01 }));
    const vectors = Float32Array.from([1, 0, 1, 0, 0, 1, 0, 1]);
    const sections = ['one', 'one', 'one', 'two'];

    const selected = diversify(candidates, vectors, 2, 4, (i) => sections[i], true, null);

    assert.equal(selected.filter((entry) => sections[entry.i] === 'one').length, SOURCE_CAP);
    assert.ok(selected.some((entry) => sections[entry.i] === 'two'));
});

test('diversify prefers a different window over a near-copy of the one already chosen', () => {
    const candidates = [{ i: 0, s: 0.9 }, { i: 1, s: 0.89 }, { i: 2, s: 0.88 }];
    // Window 1 is a copy of window 0; window 2 points elsewhere.
    const vectors = Float32Array.from([1, 0, 1, 0, 0, 1]);
    const sections = ['one', 'two', 'three'];

    const selected = diversify(candidates, vectors, 2, 2, (i) => sections[i], true, null);

    assert.deepEqual(selected.map((entry) => entry.i), [0, 2]);
});

/* ### Reading a Container ### */

test('loadContainer reads a well-formed file', () => {
    const index = loadContainer(containerBytes(sampleHeader(), [1, 0, 0, 1]));

    assert.equal(index.name, 'Example Org');
    assert.equal(index.size, 2);
    assert.equal(index.dims, 2);
    assert.equal(index.queryPrefix, 'Represent this sentence for searching relevant passages: ');
});

test('loadContainer dequantizes int8 vectors with the header scale', () => {
    const header = sampleHeader();
    header.embedding.dtype = 'int8';
    header.embedding.scale = 127;

    const index = loadContainer(containerBytes(header, [127, 0, 0, 127], { dtype: 'int8' }));

    assert.ok(Math.abs(index.vectors[0] - 1) < 1e-6);
    assert.equal(index.vectors[1], 0);
});

test('loadContainer refuses a file too short to hold a header length', () => {
    assert.throws(() => loadContainer(new Uint8Array([1, 2])), ContainerError);
});

test('loadContainer refuses a header length that runs past the end of the file', () => {
    const bytes = containerBytes(sampleHeader(), [1, 0, 0, 1], { headerLength: 10 ** 6 });

    assert.throws(() => loadContainer(bytes), /runs past the end/);
});

test('loadContainer refuses a header that is not JSON', () => {
    const broken = new Uint8Array(4 + 3);
    new DataView(broken.buffer).setUint32(0, 3, true);
    broken.set(new TextEncoder().encode('{{{'), 4);

    assert.throws(() => loadContainer(broken), /not valid UTF-8 JSON/);
});

test('loadContainer refuses another tool output that happens to be JSON', () => {
    const bytes = containerBytes(sampleHeader({ format: 'some-other-tool' }), [1, 0, 0, 1]);

    assert.throws(() => loadContainer(bytes), /not an Extractium compendium/);
});

test('loadContainer refuses a container version it does not read', () => {
    const bytes = containerBytes(sampleHeader({ v: 2 }), [1, 0, 0, 1]);

    assert.throws(() => loadContainer(bytes), /is not supported/);
});

test('loadContainer refuses a file whose embedder is not the one asked for', () => {
    const bytes = containerBytes(sampleHeader(), [1, 0, 0, 1]);

    assert.throws(() => loadContainer(bytes, { model: 'other/model' }), /not comparable/);
    assert.throws(() => loadContainer(bytes, { dims: 384 }), /query .*embedder produces 384/s);
});

test('loadContainer refuses vector bytes that do not match the children', () => {
    const bytes = containerBytes(sampleHeader(), [1, 0]);

    assert.throws(() => loadContainer(bytes), /do not match 2 children/);
});

test('loadContainer refuses a window pointing outside the sections', () => {
    const header = sampleHeader();
    header.children.pid = [0, 9];

    assert.throws(() => loadContainer(containerBytes(header, [1, 0, 0, 1])), /outside the 2 sections/);
});

test('loadContainer refuses int8 vectors with no usable scale', () => {
    const header = sampleHeader();
    header.embedding.dtype = 'int8';

    assert.throws(
        () => loadContainer(containerBytes(header, [1, 0, 0, 1], { dtype: 'int8' })),
        /positive scale/
    );
});

test('loadContainer keeps a crawled page from polluting Object.prototype', () => {
    // Built through JSON.parse so "__proto__" is a real key, which is
    // how it would arrive from a crawled page that uses the word.
    const header = sampleHeader({
        bm25: JSON.parse(
            '{"k":1.2,"b":0.75,"d":0.5,"avgDocLen":3,"docLen":[3,3],'
            + '"df":{"__proto__":1},"postings":{"__proto__":[[0,1]]}}'
        ),
    });

    const index = loadContainer(containerBytes(header, [1, 0, 0, 1]));

    assert.equal({}.polluted, undefined);
    assert.equal(index.bm25.postings.get('__proto__')[0][0], 0);
});

/* ### Searching ### */

test('searchWithVector returns whole sections, not the matched window', async () => {
    const index = loadContainer(containerBytes(sampleHeader(), [1, 0, 0, 1]));

    const [hit] = index.searchWithVector('alpha', [1, 0], { noThreshold: true, k: 1 });

    assert.equal(hit.parent.id, 'aaaaaaaaaaaaaaaa');
    assert.equal(hit.parent.x, 'Alpha section text.');
    assert.equal(hit.windowText, 'Alpha');
    assert.equal(hit.childIndex, 0);
});

test('search adds the query prefix the file records before embedding', async () => {
    const index = loadContainer(containerBytes(sampleHeader(), [1, 0, 0, 1]));
    const seen = [];

    await index.search('how do I rebuild', (text) => { seen.push(text); return [1, 0]; }, { noThreshold: true });

    assert.deepEqual(seen, ['Represent this sentence for searching relevant passages: how do I rebuild']);
});

test('search returns nothing when no section clears the relevance cutoff', async () => {
    const header = sampleHeader();
    const index = loadContainer(containerBytes(header, [1, 0, 0, 1]));

    // A query pointing between the two windows scores 0.7071 against
    // both, so no candidate beats its own pool by the margin.
    const hits = await index.search('unrelated', () => [0.7071, 0.7071]);

    assert.deepEqual(hits, []);
});

/* ### Cross-Language Contract ### */

test('the ranking matches the one recorded for the Python client', () => {
    const container = fs.readFileSync(path.join(GOLDEN, 'contract-container.json'));
    const expected = JSON.parse(fs.readFileSync(path.join(GOLDEN, 'contract-query.json'), 'utf-8'));
    const index = loadContainer(new Uint8Array(container));

    const pool = index.candidates(expected.query, expected.queryVector);
    const closest = index.searchWithVector(
        expected.query, expected.queryVector, { k: expected.k, noThreshold: true }
    );
    const relevant = index.searchWithVector(expected.query, expected.queryVector, { k: expected.k });

    assert.deepEqual(
        pool.slice(0, expected.candidateChildren.length).map((entry) => entry.i),
        expected.candidateChildren
    );
    assert.deepEqual(closest.map((hit) => hit.parent.id), expected.closestParentIds);
    assert.deepEqual(relevant.map((hit) => hit.parent.id), expected.relevantParentIds);
});

test('the golden container carries the query prefix the contract expects', () => {
    const container = fs.readFileSync(path.join(GOLDEN, 'contract-container.json'));
    const expected = JSON.parse(fs.readFileSync(path.join(GOLDEN, 'contract-query.json'), 'utf-8'));

    assert.equal(loadContainer(new Uint8Array(container)).queryPrefix, expected.queryPrefix);
});

test('inflateContainer returns plain bytes untouched and inflates a gzip-compressed container', async () => {
    const { gzipSync } = await import('node:zlib');
    const plain = containerBytes(sampleHeader(), [1, 0, 0, 1]);
    assert.strictEqual(await inflateContainer(plain), plain);

    const packed = new Uint8Array(gzipSync(plain));
    const inflated = await inflateContainer(packed);
    assert.deepStrictEqual(Array.from(inflated), Array.from(plain));
    assert.strictEqual(loadContainer(inflated).size, 2);
});

test('loadContainer names the step a caller skipped when handed a compressed file', async () => {
    const { gzipSync } = await import('node:zlib');
    const packed = new Uint8Array(gzipSync(containerBytes(sampleHeader(), [1, 0, 0, 1])));
    assert.throws(() => loadContainer(packed), { name: 'ContainerError', message: /inflateContainer/ });
});

test('inflateContainer refuses bytes that begin like gzip but are not', async () => {
    await assert.rejects(inflateContainer(new Uint8Array([0x1f, 0x8b, 1, 2, 3, 4])), { name: 'ContainerError' });
});
