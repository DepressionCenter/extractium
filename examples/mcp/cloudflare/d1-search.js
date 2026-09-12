/*
 * Summary: The search behind the Cloudflare Worker: a published Extractium
 * compendium read from its SQLite output, imported into a D1 database.
 * Keyword (BM25) ranking runs inside the database, so the Worker never
 * parses the index and stays within the free plan's CPU budget; when the
 * Workers AI binding is present and serves the container's own embedding
 * model, the keyword candidates are re-ranked by vector similarity and
 * fused as the clients do. Kept apart from the entry module because the
 * Workers runtime accepts only handlers as that module's exports.
 *
 * This file is part of Extractium™
 * examples/mcp/cloudflare/d1-search.js
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
    CANDIDATE_POOL,
    CONTAINER_FORMAT,
    CONTAINER_VERSION,
    RRF_BM25_WEIGHT,
    RRF_VECTOR_WEIGHT,
    diversify,
    rrfFuse,
    tokenize,
} from '../../../clients/js/extractium-client.js';
import { SearchServer } from '../shared/mcp-protocol.js';

/* ### Constants ### */

// Identity this server reports. It is self-reported and unverified, so it
// is for display and logging only.
export const SERVER_NAME = 'extractium-cloudflare';
const SERVER_VERSION = '0.1.0';

// The Workers AI model that serves the same embeddings as the build. It
// is used only when the index was built with that model, which the meta
// table says; any other index gets keyword search alone.
export const WORKERS_AI_MODEL = '@cf/baai/bge-small-en-v1.5';
const WORKERS_AI_MODEL_TAIL = 'bge-small-en-v1.5';

// Most distinct query terms sent to the database. D1 binds at most a
// hundred parameters to one statement, and each term costs two.
export const MAX_QUERY_TERMS = 32;

// Width of the vectors this Worker will decode; anything else is refused
// rather than read wrongly.
const DTYPE_WIDTHS = { int8: 1, float32: 4 };

/* ### Meta ### */

/**
 * Everything a search needs to know about the index, read once.
 *
 * @param {D1Database} db The database binding.
 * @returns {Promise<Object>} The settings, with numbers converted.
 * @throws {Error} If the database does not hold an Extractium
 *     compendium of the version this Worker reads.
 */
export async function readMeta(db) {
    const { results } = await db.prepare('SELECT key, value FROM meta').all();
    const meta = new Map(results.map((row) => [row.key, row.value]));
    if (meta.get('format') !== CONTAINER_FORMAT) {
        throw new Error(`the database is not an Extractium compendium: format is ${JSON.stringify(meta.get('format'))}.`);
    }
    if (Number(meta.get('v')) !== CONTAINER_VERSION) {
        throw new Error(`compendium version ${JSON.stringify(meta.get('v'))} is not supported; this Worker reads version ${CONTAINER_VERSION}.`);
    }
    const dtype = meta.get('embedding.dtype');
    if (!Object.prototype.hasOwnProperty.call(DTYPE_WIDTHS, dtype)) {
        throw new Error(`unknown vector dtype ${JSON.stringify(dtype)}.`);
    }
    const count = await db.prepare('SELECT COUNT(*) AS n FROM children').first('n');
    return {
        name: meta.get('site') || '',
        builtAt: meta.get('builtAt') || '',
        childCount: Number(count) || 0,
        k: Number(meta.get('bm25.k')),
        b: Number(meta.get('bm25.b')),
        d: Number(meta.get('bm25.d')),
        avgDocLen: Number(meta.get('bm25.avgDocLen')) || 1,
        model: meta.get('embedding.model') || '',
        dims: Number(meta.get('embedding.dims')),
        dtype,
        scale: Number(meta.get('embedding.scale')),
        queryPrefix: meta.get('embedding.queryPrefix') || '',
        calibration: {
            mean: Number(meta.get('calibration.mean')),
            std: Number(meta.get('calibration.std')),
        },
    };
}

/**
 * Whether the Workers AI model can embed queries for this index.
 *
 * @param {Object} meta From readMeta.
 * @returns {boolean}
 */
export function embeddableByWorkersAi(meta) {
    return meta.model.toLowerCase().endsWith(WORKERS_AI_MODEL_TAIL) && meta.dims === 384;
}

/* ### Queries ### */

/**
 * The keyword candidate pool, scored inside the database.
 *
 * The formula is the one the clients use, with the inverse document
 * frequency computed here from each term's document count and handed to
 * the statement as a value, so the database does only arithmetic.
 *
 * @param {D1Database} db The database binding.
 * @param {Object} meta From readMeta.
 * @param {string[]} terms Query terms from `tokenize`.
 * @param {number} [poolSize] How many candidates to keep.
 * @returns {Promise<Array<{cid: number, s: number}>>} Best first.
 */
export async function keywordPool(db, meta, terms, poolSize = CANDIDATE_POOL) {
    const unique = Array.from(new Set(terms)).slice(0, MAX_QUERY_TERMS);
    if (!unique.length) return [];

    const placeholders = unique.map(() => '?').join(', ');
    const { results: known } = await db
        .prepare(`SELECT term, df FROM bm25_terms WHERE term IN (${placeholders})`)
        .bind(...unique)
        .all();
    if (!known.length) return [];

    const weighted = known.map((row) => {
        const df = Number(row.df);
        return [row.term, Math.log(1 + (meta.childCount - df + 0.5) / (df + 0.5))];
    });
    const values = weighted.map(() => '(?, ?)').join(', ');
    const sql = `WITH q(term, idf) AS (VALUES ${values})
        SELECT c.cid AS cid,
               SUM(q.idf * (? + p.tf * (? + 1.0)) / (p.tf + ? * (1.0 - ? + ? * c.doc_len / ?))) AS s
        FROM q
        JOIN bm25_postings p ON p.term = q.term
        JOIN children c ON c.cid = p.cid
        GROUP BY c.cid
        ORDER BY s DESC, c.cid ASC
        LIMIT ?`;
    const { results } = await db
        .prepare(sql)
        .bind(...weighted.flat(), meta.d, meta.k, meta.k, meta.b, meta.b, meta.avgDocLen, poolSize)
        .all();
    return results.map((row) => ({ cid: Number(row.cid), s: Number(row.s) }));
}

/**
 * The section behind each window in the pool.
 *
 * @param {D1Database} db The database binding.
 * @param {number[]} cids The windows.
 * @returns {Promise<Map<number, Object>>} Window id to section row.
 */
export async function sectionsFor(db, cids) {
    if (!cids.length) return new Map();
    const placeholders = cids.map(() => '?').join(', ');
    const { results } = await db
        .prepare(`SELECT c.cid AS cid, p.id AS id, p.t AS t, p.u AS u, p.x AS x, p.local AS local, p.weight AS weight
                  FROM children c JOIN parents p ON p.pid = c.pid
                  WHERE c.cid IN (${placeholders})`)
        .bind(...cids)
        .all();
    return new Map(results.map((row) => [Number(row.cid), row]));
}

/**
 * One stored vector, decoded to floats.
 *
 * D1 hands a BLOB back as an array of byte values; a SQLite driver hands
 * back a byte array. Both are read the same way.
 *
 * @param {ArrayLike<number>} raw The column value.
 * @param {Object} meta From readMeta.
 * @returns {Float32Array}
 */
export function decodeVector(raw, meta) {
    const bytes = Uint8Array.from(raw);
    if (bytes.byteLength !== meta.dims * DTYPE_WIDTHS[meta.dtype]) {
        throw new Error(`a stored vector holds ${bytes.byteLength} bytes; ${meta.dims} ${meta.dtype} values were expected.`);
    }
    if (meta.dtype === 'float32') return new Float32Array(bytes.buffer, 0, meta.dims);
    if (!(meta.scale > 0)) throw new Error('int8 vectors need a positive scale.');
    const quantized = new Int8Array(bytes.buffer, 0, meta.dims);
    const vector = new Float32Array(meta.dims);
    for (let position = 0; position < meta.dims; position += 1) vector[position] = quantized[position] / meta.scale;
    return vector;
}

/**
 * The stored vectors of the pool, flat, in pool order.
 *
 * @param {D1Database} db The database binding.
 * @param {Object} meta From readMeta.
 * @param {number[]} cids The windows, in the order the flat array follows.
 * @returns {Promise<Float32Array>}
 */
export async function vectorsFor(db, meta, cids) {
    const flat = new Float32Array(cids.length * meta.dims);
    if (!cids.length) return flat;
    const placeholders = cids.map(() => '?').join(', ');
    const { results } = await db
        .prepare(`SELECT cid, v FROM vectors WHERE cid IN (${placeholders})`)
        .bind(...cids)
        .all();
    const byCid = new Map(results.map((row) => [Number(row.cid), row.v]));
    cids.forEach((cid, position) => {
        const raw = byCid.get(cid);
        if (raw !== undefined) flat.set(decodeVector(raw, meta), position * meta.dims);
    });
    return flat;
}

/* ### Searching ### */

/** Cosine similarity of a unit query against one row of the flat pool vectors. */
function similarity(query, vectors, position, dims) {
    let dot = 0;
    for (let d = 0; d < dims; d += 1) dot += query[d] * vectors[position * dims + d];
    return dot;
}

/**
 * The search over one D1 database, with or without a query embedder.
 */
export class D1Search {
    /**
     * @param {D1Database} db The database binding.
     * @param {Object} meta From readMeta.
     * @param {((text: string) => Promise<ArrayLike<number>>)|null} embedQuery
     *     The embedder, or null for keyword search alone.
     */
    constructor(db, meta, embedQuery) {
        this.db = db;
        this.meta = meta;
        this.embedQuery = embedQuery;
        this.name = meta.name;
        this.builtAt = meta.builtAt;
    }

    /**
     * Searches and returns whole sections, best first.
     *
     * Keyword search picks the candidate pool. Without an embedder the
     * pool is weighted per section and passed through diversity
     * selection; with one, the pool is also ranked by cosine similarity
     * and the two rankings are fused by reciprocal rank, thresholded, and
     * diversified exactly as the clients do. A section that shares no
     * term with the query cannot appear either way; that is the trade
     * the database-side design makes.
     *
     * @param {string} query What was asked.
     * @param {number} k How many sections to return.
     * @returns {Promise<Array<{parent: Object}>>}
     */
    async search(query, k) {
        const pool = await keywordPool(this.db, this.meta, tokenize(query));
        if (!pool.length) return [];
        const cids = pool.map((entry) => entry.cid);
        const sections = await sectionsFor(this.db, cids);
        const weightOf = (position) => {
            const weight = Number(sections.get(cids[position])?.weight);
            return Number.isFinite(weight) ? weight : 1;
        };
        const sourceKeyOf = (position) => sections.get(cids[position])?.id || String(cids[position]);

        // Candidates are numbered by their position in the pool, so the
        // client's selection routines can index a flat vector array.
        const keywordRanked = pool.map((entry, position) => ({ i: position, s: entry.s }));

        let selected;
        let vectors = new Float32Array(0);
        let dims = 0;
        if (this.embedQuery === null) {
            const weighted = keywordRanked
                .map((entry) => ({ i: entry.i, s: entry.s * weightOf(entry.i) }))
                .sort((a, b) => (b.s - a.s) || (a.i - b.i));
            selected = diversify(weighted, vectors, dims, k, sourceKeyOf, true);
        } else {
            dims = this.meta.dims;
            vectors = await vectorsFor(this.db, this.meta, cids);
            const raw = Float32Array.from(await this.embedQuery(this.meta.queryPrefix + query));
            let norm = 0;
            for (let d = 0; d < dims; d += 1) norm += raw[d] * raw[d];
            norm = Math.sqrt(norm) || 1;
            const unit = raw.map((value) => value / norm);
            const vectorRanked = keywordRanked
                .map((entry) => ({ i: entry.i, s: similarity(unit, vectors, entry.i, dims) }))
                .sort((a, b) => (b.s - a.s) || (a.i - b.i));
            const fused = rrfFuse([
                { items: vectorRanked, listWeight: RRF_VECTOR_WEIGHT },
                { items: keywordRanked, listWeight: RRF_BM25_WEIGHT },
            ], weightOf);
            selected = diversify(fused, vectors, dims, k, sourceKeyOf, false, this.meta.calibration);
        }

        return selected.map((candidate) => {
            const row = sections.get(cids[candidate.i]);
            return { parent: { id: row.id, t: row.t, u: row.u, x: row.x, local: Boolean(Number(row.local)) } };
        });
    }
}

/**
 * The embedder over the Workers AI binding, or null when the binding is
 * absent or serves a different model than the index was built with.
 *
 * @param {Object|undefined} ai The `AI` binding.
 * @param {Object} meta From readMeta.
 * @param {Function} log Where to say why hybrid search is off.
 * @returns {((text: string) => Promise<number[]>)|null}
 */
export function workersAiEmbedder(ai, meta, log) {
    if (!ai) return null;
    if (!embeddableByWorkersAi(meta)) {
        log(`the index was built with ${JSON.stringify(meta.model)}, which Workers AI does not serve; using keyword search alone.`);
        return null;
    }
    return async (text) => {
        const answer = await ai.run(WORKERS_AI_MODEL, { text: [text], pooling: 'cls' });
        const vector = answer && answer.data && answer.data[0];
        if (!Array.isArray(vector) || vector.length !== meta.dims) {
            throw new Error('Workers AI did not return a vector of the expected width.');
        }
        return vector;
    };
}

/**
 * The server for one Worker environment.
 *
 * @param {{DB: D1Database, AI?: Object}} env The bindings.
 * @param {Function} [log] Where to write progress.
 * @returns {SearchServer}
 */
export function createWorkerServer(env, log = console.error) {
    return new SearchServer({
        serverName: SERVER_NAME,
        serverVersion: SERVER_VERSION,
        log,
        openSearch: async () => {
            const meta = await readMeta(env.DB);
            return new D1Search(env.DB, meta, workersAiEmbedder(env.AI, meta, log));
        },
    });
}
