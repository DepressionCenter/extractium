/*
 * Summary: The JavaScript client for a version 3 compendium: reads the
 * binary container back, checks it against the reader checklist, and runs
 * the hybrid search over it -- cosine similarity, BM25, reciprocal rank
 * fusion, a corpus-relative relevance threshold, diversity selection, and
 * resolution of each matched window to the section that contains it. One
 * file, no dependencies, no build step: it runs in a browser, in Node, and
 * on an edge runtime. The caller supplies the query embedder, so this file
 * never loads a model. extractium/search.py implements the same algorithm
 * with the same constants. See docs/container-format.md and
 * docs/how-to/search-a-compendium.md.
 *
 * This file is part of Extractium™
 * clients/js/extractium-client.js
 *
 * Author(s): Gabriel Mongefranco.
 * Created: 2026-09-08
 * Last Modified: 2026-09-08
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

/* ### Constants ### */

// The only container this reader accepts. Both values are checked before
// anything else is read, so a file of some other shape that happens to
// carry a .json name is refused rather than half-parsed.
export const CONTAINER_FORMAT = 'extractium-compendium';
export const CONTAINER_VERSION = 3;

// Width in bytes of one stored vector component, by container dtype.
const DTYPE_WIDTHS = { int8: 1, float32: 4 };

// Query tokens are runs of three or more ASCII letters or digits, in
// lowercase. This MUST stay identical to the build-side rule in
// extractium/core/bm25.py: postings built under one tokenization cannot
// be looked up under another, and the failure is silent -- keyword
// matching simply stops working.
const TOKEN_RE = /[a-z0-9]{3,}/g;

// Absolute similarity floor. Below this, a window is never relevant no
// matter how it compares with the rest of the pool. The value suits
// bge-small-en-v1.5, whose cosine similarities run high even for
// unrelated text; a different embedding model needs it retuned.
export const SCORE_MIN = 0.44;

// A hit must also beat the median of its own candidate pool by this
// much. Self-relative, so it keeps working on a corpus whose absolute
// scores sit somewhere else entirely.
export const SCORE_MARGIN = 0.03;

// How far above the corpus calibration mean, in standard deviations, a
// score must sit to count as relevant. Used only when the file carries
// calibration statistics.
export const ZSCORE_MARGIN = 1.0;

// Raw candidates pulled per query, before thresholding and diversity.
export const CANDIDATE_POOL = 50;

// How many of those candidates the diversity pass considers.
export const MMR_POOL_CAP = 20;

// Relevance against variety in the diversity pass. 1.0 would be pure
// relevance, which lets several near-copies of one page fill the answer.
export const MMR_LAMBDA = 0.7;

// Most windows kept from any one section, so a long article cannot take
// every slot.
export const SOURCE_CAP = 2;

// Sections returned per search when the caller names no other number.
export const TOP_K = 4;

// Reciprocal rank fusion. 60 is the constant from the literature, and
// the two weights are the trust split between the vector list and the
// keyword list. Fusion uses rank alone, never the raw scores, which is
// what makes a cosine list and a BM25 list comparable without
// normalizing either.
export const RRF_K = 60;
export const RRF_VECTOR_WEIGHT = 0.5;
export const RRF_BM25_WEIGHT = 0.5;

/** Thrown when a file is not a readable version 3 compendium. */
export class ContainerError extends Error {
    constructor(message) {
        super(message);
        this.name = 'ContainerError';
    }
}

/* ### Container Reader ### */

/**
 * Splits the raw bytes into the parsed header and the vector bytes.
 *
 * @param {Uint8Array} bytes The whole file.
 * @returns {{header: Object, vectorBytes: Uint8Array}}
 * @throws {ContainerError} If the file is too short, the header length
 *     runs past the end of the file, or the header is not JSON.
 */
function readHeader(bytes) {
    if (bytes.byteLength < 4) {
        throw new ContainerError('file is too short to hold a container header length.');
    }
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const headerLength = view.getUint32(0, true);
    if (4 + headerLength > bytes.byteLength) {
        throw new ContainerError(
            `header length (${headerLength}) runs past the end of the file (${bytes.byteLength} bytes).`
        );
    }
    let header;
    try {
        const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(4, 4 + headerLength));
        header = JSON.parse(text);
    } catch (error) {
        throw new ContainerError(`header is not valid UTF-8 JSON: ${error.message}`);
    }
    if (!header || typeof header !== 'object' || Array.isArray(header)) {
        throw new ContainerError('header must be a JSON object.');
    }
    return { header, vectorBytes: bytes.subarray(4 + headerLength) };
}

/**
 * Reads the vector bytes into one flat Float32Array of childCount x dims
 * values, in child order.
 *
 * int8 vectors are divided by the header's scale to recover the floats
 * they were quantized from. The bytes are copied into a fresh buffer
 * first: they start at an offset that is not guaranteed to be a multiple
 * of four, and most runtimes refuse to view a 32-bit array there.
 *
 * @param {Object} header The parsed container header.
 * @param {Uint8Array} vectorBytes Everything after the header.
 * @returns {Float32Array}
 * @throws {ContainerError} If the dtype is unknown, the scale is missing,
 *     or the byte count does not match the children.
 */
function readVectors(header, vectorBytes) {
    const embedding = header.embedding;
    const dtype = embedding.dtype;
    if (!Object.prototype.hasOwnProperty.call(DTYPE_WIDTHS, dtype)) {
        throw new ContainerError(`unknown vector dtype ${JSON.stringify(dtype)}.`);
    }
    const dims = embedding.dims;
    const childCount = header.children.pid.length;
    const expected = childCount * dims * DTYPE_WIDTHS[dtype];
    if (vectorBytes.byteLength !== expected) {
        throw new ContainerError(
            `vector bytes (${vectorBytes.byteLength}) do not match ${childCount} children `
            + `x ${dims} dims x ${DTYPE_WIDTHS[dtype]} bytes (${expected}).`
        );
    }
    const copy = new Uint8Array(vectorBytes.byteLength);
    copy.set(vectorBytes);
    if (dtype === 'float32') {
        return new Float32Array(copy.buffer);
    }
    const scale = embedding.scale;
    if (typeof scale !== 'number' || !(scale > 0)) {
        throw new ContainerError(`int8 vectors need a positive scale; got ${JSON.stringify(scale)}.`);
    }
    const quantized = new Int8Array(copy.buffer);
    const vectors = new Float32Array(quantized.length);
    for (let i = 0; i < quantized.length; i += 1) vectors[i] = quantized[i] / scale;
    return vectors;
}

/**
 * Loads the keyword statistics into Map objects.
 *
 * The keys are words taken from crawled pages, so a page containing
 * `__proto__` would pollute a prototype if they were loaded into a plain
 * object. A Map has no such problem.
 *
 * @param {Object|null} bm25 The container's `bm25` object, if any.
 * @returns {Object|null} The same statistics with Map-backed `df` and
 *     `postings`, or null when the file carries none.
 */
function readBm25(bm25) {
    if (!bm25 || !Array.isArray(bm25.docLen)) return null;
    return {
        k: Number.isFinite(bm25.k) ? bm25.k : 1.2,
        b: Number.isFinite(bm25.b) ? bm25.b : 0.75,
        d: Number.isFinite(bm25.d) ? bm25.d : 0.5,
        avgDocLen: Number.isFinite(bm25.avgDocLen) ? bm25.avgDocLen : 0,
        docLen: bm25.docLen,
        df: new Map(Object.entries(bm25.df || {})),
        postings: new Map(Object.entries(bm25.postings || {})),
    };
}

/* ### Scoring ### */

/**
 * Splits text into BM25 terms: lowercased runs of three or more ASCII
 * letters or digits.
 *
 * @param {string} text A query, or any text to match the build-side rule.
 * @returns {string[]} The terms, in the order they appear.
 */
export function tokenize(text) {
    return String(text || '').toLowerCase().match(TOKEN_RE) || [];
}

/** Cosine similarity of two rows of a flat vector array; both are unit length. */
function cosineSim(a, offsetA, b, offsetB, dims) {
    let dot = 0;
    for (let d = 0; d < dims; d += 1) dot += a[offsetA + d] * b[offsetB + d];
    return dot;
}

/** Sorts candidates best first, breaking ties on the child index so every client agrees. */
function sortCandidates(candidates) {
    candidates.sort((a, b) => (b.s - a.s) || (a.i - b.i));
    return candidates;
}

/**
 * Fuses ranked result lists by reciprocal rank.
 *
 * Each list must already be sorted best first. Only the position of a
 * candidate inside its own list counts, never its score, which is what
 * lets a cosine list and a BM25 list combine with no rescaling.
 *
 * @param {Array<{items: Array<{i: number}>, listWeight: number}>} rankedLists
 *     The lists to fuse and how much to trust each.
 * @param {(childIndex: number) => number} [weightOf] Per-child multiplier
 *     applied after fusion, used for the per-section `weight` field.
 * @returns {Array<{i: number, s: number}>} One entry per distinct child,
 *     best first.
 */
export function rrfFuse(rankedLists, weightOf) {
    const fused = new Map();
    for (const { items, listWeight } of rankedLists) {
        items.forEach((item, rank) => {
            const contribution = listWeight * (RRF_K / (RRF_K + rank + 1));
            const previous = fused.get(item.i);
            if (previous) previous.s += contribution;
            else fused.set(item.i, { i: item.i, s: contribution });
        });
    }
    const out = Array.from(fused.values());
    if (weightOf) for (const entry of out) entry.s *= weightOf(entry.i);
    return sortCandidates(out);
}

/**
 * Ranks every window by cosine similarity to the query.
 *
 * Stored vectors have unit length, so a dot product is the cosine
 * similarity. The query vector is normalized here rather than trusted,
 * because an embedder that skipped normalization would otherwise change
 * every score.
 *
 * @param {ArrayLike<number>} queryVector The embedded query.
 * @param {Float32Array} vectors The corpus vectors, flat, in child order.
 * @param {number} dims Vector length.
 * @param {number} [poolSize] How many candidates to keep.
 * @returns {Array<{i: number, s: number}>} Best first.
 */
export function vectorCandidates(queryVector, vectors, dims, poolSize = CANDIDATE_POOL) {
    const childCount = dims > 0 ? Math.floor(vectors.length / dims) : 0;
    if (!childCount) return [];
    const query = Float32Array.from(queryVector);
    let norm = 0;
    for (let d = 0; d < dims; d += 1) norm += query[d] * query[d];
    norm = Math.sqrt(norm);
    if (norm > 0) for (let d = 0; d < dims; d += 1) query[d] /= norm;

    const scored = new Array(childCount);
    for (let i = 0; i < childCount; i += 1) {
        scored[i] = { i, s: cosineSim(query, 0, vectors, i * dims, dims) };
    }
    return sortCandidates(scored).slice(0, poolSize);
}

/**
 * Ranks windows by keyword match, walking only the postings lists of
 * terms the query actually contains. The cost follows the query, not the
 * size of the corpus, which is what makes this practical to run in a
 * browser on every keystroke.
 *
 * The formula and its constants come from the file itself, so an index
 * rebuilt with different tuning needs no client change.
 *
 * @param {Iterable<string>} terms Query terms from `tokenize`.
 * @param {Object|null} bm25 The keyword statistics, Map-backed.
 * @param {number} childCount Number of windows in the corpus.
 * @param {number} [poolSize] How many candidates to keep.
 * @returns {Array<{i: number, s: number}>} Best first.
 */
export function bm25Candidates(terms, bm25, childCount, poolSize = CANDIDATE_POOL) {
    const unique = new Set(terms || []);
    if (!bm25 || !unique.size) return [];
    const { k, b, d, avgDocLen, docLen, df, postings } = bm25;
    const average = avgDocLen || 1;
    const scores = new Map();
    for (const term of unique) {
        const posting = postings.get(term);
        if (!posting) continue;
        const docFreq = df.get(term) || posting.length;
        const idf = Math.log(1 + (childCount - docFreq + 0.5) / (docFreq + 0.5));
        for (const [childIndex, termFrequency] of posting) {
            const length = docLen[childIndex] || 0;
            const denominator = termFrequency + k * (1 - b + (b * length) / average);
            if (!denominator) continue;
            const gain = (idf * (d + termFrequency * (k + 1))) / denominator;
            scores.set(childIndex, (scores.get(childIndex) || 0) + gain);
        }
    }
    const out = [];
    for (const [i, s] of scores) out.push({ i, s });
    return sortCandidates(out).slice(0, poolSize);
}

/**
 * The score a candidate must reach to count as relevant.
 *
 * Three tests, whichever is strictest: an absolute floor, the median of
 * this query's own candidate pool plus a margin, and, when the file
 * carries calibration statistics, a fixed number of standard deviations
 * above the corpus mean. The relative test is the one that survives a
 * change of corpus or embedding model; the other two are safety nets.
 *
 * Note that once vector and keyword results have been fused, a
 * candidate's score is a fused rank score rather than a cosine
 * similarity, so the two absolute tests are approximations on that scale.
 * The relative test is unaffected, because it moves with the pool.
 *
 * @param {Array<{s: number}>} candidates The scored candidate pool.
 * @param {Object} [calibration] The container's calibration object.
 * @returns {number} The cutoff, or -Infinity for an empty pool.
 */
export function relevanceCutoff(candidates, calibration) {
    if (!candidates.length) return -Infinity;
    const scores = candidates.map((candidate) => candidate.s).sort((a, b) => a - b);
    const median = scores[Math.floor(scores.length / 2)];
    let cutoff = Math.max(SCORE_MIN, median + SCORE_MARGIN);
    if (calibration && calibration.std) {
        cutoff = Math.max(cutoff, calibration.mean + ZSCORE_MARGIN * calibration.std);
    }
    return cutoff;
}

/**
 * Picks the windows to return: relevant, varied, and spread across
 * sections.
 *
 * Runs in three passes. First the relevance cutoff drops weak candidates.
 * Then a greedy maximal-marginal-relevance pass prefers a candidate that
 * is both similar to the query and unlike what is already chosen, so
 * several near-copies of one paragraph cannot fill the answer. Finally a
 * per-section cap keeps one long article from taking every slot.
 *
 * @param {Array<{i: number, s: number}>} candidates Scored, best first.
 * @param {Float32Array} vectors The corpus vectors, flat.
 * @param {number} dims Vector length.
 * @param {number} k How many windows to select.
 * @param {(childIndex: number) => string} sourceKeyOf Identity of the
 *     section a child belongs to, for the per-section cap.
 * @param {boolean} [noThreshold] Skip the relevance cutoff.
 * @param {Object} [calibration] The container's calibration object.
 * @returns {Array<{i: number, s: number}>} The selection, in the order chosen.
 */
export function diversify(candidates, vectors, dims, k, sourceKeyOf, noThreshold, calibration) {
    if (!candidates.length) return [];
    let surviving = candidates;
    if (!noThreshold) {
        const cutoff = relevanceCutoff(candidates, calibration);
        surviving = candidates.filter((candidate) => candidate.s >= cutoff);
    }
    if (!surviving.length) return [];

    const remaining = surviving.slice(0, MMR_POOL_CAP);
    const selected = [];
    const sourceCounts = new Map();
    while (selected.length < k && remaining.length) {
        let bestPosition = -1;
        let bestScore = -Infinity;
        for (let position = 0; position < remaining.length; position += 1) {
            const candidate = remaining[position];
            const key = sourceKeyOf(candidate.i);
            if ((sourceCounts.get(key) || 0) >= SOURCE_CAP) continue;
            let highestSimilarity = 0;
            for (const chosen of selected) {
                const similarity = cosineSim(vectors, candidate.i * dims, vectors, chosen.i * dims, dims);
                if (similarity > highestSimilarity) highestSimilarity = similarity;
            }
            const mmr = MMR_LAMBDA * candidate.s - (1 - MMR_LAMBDA) * highestSimilarity;
            if (mmr > bestScore) {
                bestScore = mmr;
                bestPosition = position;
            }
        }
        if (bestPosition === -1) break; // every remaining candidate is already at its section cap
        const chosen = remaining.splice(bestPosition, 1)[0];
        selected.push(chosen);
        const key = sourceKeyOf(chosen.i);
        sourceCounts.set(key, (sourceCounts.get(key) || 0) + 1);
    }
    return selected;
}

/* ### Index ### */

/**
 * One compendium, loaded and ready to search.
 *
 * Build one with `loadContainer`. The object holds the parsed header, the
 * dequantized vectors, and the keyword statistics; it never fetches
 * anything and never loads an embedding model.
 */
export class SearchIndex {
    /**
     * @param {Object} header The parsed container header.
     * @param {Float32Array} vectors The corpus vectors, flat, in child order.
     */
    constructor(header, vectors) {
        this.header = header;
        this.vectors = vectors;
        this.parents = header.parents;
        this.children = header.children;
        this.embedding = header.embedding;
        this.dims = header.embedding.dims;
        this.bm25 = readBm25(header.bm25);
        this.calibration = header.calibration || null;
        this.sourceKeyOf = this.sourceKeyOf.bind(this);
        this.weightOf = this.weightOf.bind(this);
    }

    /** Display name of the knowledge base. */
    get name() {
        return this.header.site || '';
    }

    /**
     * Text the embedding model expects in front of a search query. The
     * model this format ships with was trained for asymmetric search: the
     * prefix goes on queries only, never on indexed text.
     */
    get queryPrefix() {
        return this.embedding.queryPrefix || '';
    }

    /** Number of search windows in the corpus. */
    get size() {
        return this.children.pid.length;
    }

    /**
     * The section a window belongs to.
     *
     * @param {number} childIndex Position in the child columns.
     * @returns {Object} The section record.
     */
    parentOf(childIndex) {
        return this.parents[this.children.pid[childIndex]];
    }

    /**
     * Identity used by the per-section cap. The section's stable id, so
     * two windows of the same section share it and two sections of one
     * long page do not.
     *
     * @param {number} childIndex Position in the child columns.
     * @returns {string}
     */
    sourceKeyOf(childIndex) {
        const parent = this.parentOf(childIndex);
        return parent.id || `${parent.u || ''}#${this.children.pid[childIndex]}`;
    }

    /**
     * The per-section weight, applied after fusion. Defaults to 1.
     *
     * @param {number} childIndex Position in the child columns.
     * @returns {number}
     */
    weightOf(childIndex) {
        const weight = this.parentOf(childIndex).weight;
        return Number.isFinite(weight) ? weight : 1;
    }

    /**
     * The scored candidate pool for one query, before thresholding and
     * diversity selection.
     *
     * Vector and keyword results are fused by reciprocal rank when the
     * file carries keyword statistics and the query has terms that appear
     * in them. Otherwise the vector ranking stands alone. Either way the
     * per-section weight is applied, so a weighted source does not
     * quietly lose its weight on a query with no keyword matches.
     *
     * @param {string} query The query text, for keyword matching.
     * @param {ArrayLike<number>} queryVector The embedded query.
     * @param {number} [poolSize] How many candidates to keep.
     * @returns {Array<{i: number, s: number}>} Best first.
     */
    candidates(query, queryVector, poolSize = CANDIDATE_POOL) {
        const vectorRanked = vectorCandidates(queryVector, this.vectors, this.dims, poolSize);
        const terms = this.bm25 ? tokenize(query) : [];
        const keywordRanked = bm25Candidates(terms, this.bm25, this.size, poolSize);
        if (!keywordRanked.length) {
            return sortCandidates(
                vectorRanked.map((entry) => ({ i: entry.i, s: entry.s * this.weightOf(entry.i) }))
            );
        }
        return rrfFuse(
            [
                { items: vectorRanked, listWeight: RRF_VECTOR_WEIGHT },
                { items: keywordRanked, listWeight: RRF_BM25_WEIGHT },
            ],
            this.weightOf
        );
    }

    /**
     * Searches with a query vector the caller has already embedded.
     *
     * Small windows are searched and whole sections are returned, so a
     * match is precise but the text handed to a reader or a language
     * model still has enough context to answer from.
     *
     * @param {string} query The query text, for keyword matching.
     * @param {ArrayLike<number>} queryVector The embedded query, made
     *     from `queryPrefix + query`.
     * @param {{k?: number, noThreshold?: boolean}} [options] How many
     *     sections to return, and whether to return the closest sections
     *     even when none clears the relevance cutoff.
     * @returns {Array<Object>} The selected sections, best first.
     */
    searchWithVector(query, queryVector, options = {}) {
        const k = options.k || TOP_K;
        const pool = this.candidates(query, queryVector);
        const selected = diversify(
            pool, this.vectors, this.dims, k, this.sourceKeyOf, !!options.noThreshold, this.calibration
        );
        return selected.map((candidate) => this.hitOf(candidate));
    }

    /**
     * Searches the compendium and returns whole sections.
     *
     * @param {string} query What the user asked, unprefixed. The query
     *     prefix this file records is added before embedding.
     * @param {(text: string) => (ArrayLike<number>|Promise<ArrayLike<number>>)} embedQuery
     *     Embeds one string with the model named in the file's `embedding`
     *     object. Called once per search.
     * @param {{k?: number, noThreshold?: boolean}} [options] As above.
     * @returns {Promise<Array<Object>>} The selected sections, best first.
     */
    async search(query, embedQuery, options = {}) {
        const queryVector = await embedQuery(this.queryPrefix + query);
        return this.searchWithVector(query, queryVector, options);
    }

    /**
     * Resolves one selected window to the section that contains it.
     *
     * @param {{i: number, s: number}} candidate The selected window.
     * @returns {{parent: Object, score: number, childIndex: number,
     *     start: (number|null), end: (number|null), windowText: string}}
     */
    hitOf(candidate) {
        const childIndex = candidate.i;
        const parent = this.parentOf(childIndex);
        const starts = this.children.start || [];
        const ends = this.children.end || [];
        const start = childIndex < starts.length ? starts[childIndex] : null;
        const end = childIndex < ends.length ? ends[childIndex] : null;
        const text = parent.x || '';
        return {
            parent,
            score: candidate.s,
            childIndex,
            start,
            end,
            // Offsets are UTF-16 code units, which is how a JavaScript
            // string indexes, so a plain slice is already correct.
            windowText: (start === null || end === null) ? text : text.slice(start, end),
        };
    }
}

/* ### Loading ### */

/**
 * Reads a version 3 container and returns an index ready to search.
 *
 * Every check in the container format's reader checklist runs here, so a
 * truncated, altered, or foreign file is refused with a message that
 * names the problem instead of failing somewhere deep in a search.
 *
 * @param {ArrayBuffer|Uint8Array} source The file's bytes.
 * @param {{model?: string, dims?: number}} [expected] The Hugging Face
 *     model id and vector length of the embedder that will embed queries.
 *     When given, a file built with another model or width is refused,
 *     because vectors from two models are not comparable.
 * @returns {SearchIndex} The loaded compendium.
 * @throws {ContainerError} If the file is not a readable version 3
 *     compendium, or does not match the embedder named above.
 */
export function loadContainer(source, expected = {}) {
    const bytes = source instanceof Uint8Array ? source : new Uint8Array(source);
    const { header, vectorBytes } = readHeader(bytes);

    if (header.format !== CONTAINER_FORMAT) {
        throw new ContainerError(`not an Extractium compendium: format is ${JSON.stringify(header.format)}.`);
    }
    if (header.v !== CONTAINER_VERSION) {
        throw new ContainerError(
            `container version ${JSON.stringify(header.v)} is not supported; this client reads `
            + `version ${CONTAINER_VERSION}.`
        );
    }
    for (const required of ['embedding', 'parents', 'children']) {
        if (!(required in header)) throw new ContainerError(`header is missing the "${required}" field.`);
    }
    if (!Array.isArray(header.children.pid)) {
        throw new ContainerError('children columns are missing "pid".');
    }
    if (expected.model !== undefined && header.embedding.model !== expected.model) {
        throw new ContainerError(
            `file was built with ${JSON.stringify(header.embedding.model)}, but queries will be `
            + `embedded with ${JSON.stringify(expected.model)}; the vectors are not comparable.`
        );
    }
    if (expected.dims !== undefined && header.embedding.dims !== expected.dims) {
        throw new ContainerError(
            `file has ${JSON.stringify(header.embedding.dims)}-dimensional vectors, but the query `
            + `embedder produces ${expected.dims}.`
        );
    }
    const parentCount = header.parents.length;
    header.children.pid.forEach((pid, position) => {
        if (!Number.isInteger(pid) || pid < 0 || pid >= parentCount) {
            throw new ContainerError(
                `child ${position} points at section ${JSON.stringify(pid)}, outside the ${parentCount} sections.`
            );
        }
    });

    return new SearchIndex(header, readVectors(header, vectorBytes));
}
