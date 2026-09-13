/*
 * Summary: The search behind the Val Town example: fetches a published
 * Extractium container, keeps a copy in the val's blob store so a cold
 * start does not download it again, holds it in memory between requests,
 * and answers with keyword (BM25) search alone, or with the full hybrid
 * search when an embedding service is configured. Runtime-neutral: the
 * store, the fetch, and the settings are all handed in, which is what
 * lets the tests run it in Node against the golden compendium.
 *
 * This file is part of Extractium™
 * examples/mcp/valtown/kb.js
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
    bm25Candidates,
    diversify,
    inflateContainer,
    loadContainer,
    tokenize,
} from '../../../clients/js/extractium-client.js';
import { ConfigurationError, SearchServer } from '../shared/mcp-protocol.js';

/* ### Constants ### */

// Identity this server reports. It is self-reported and unverified, so it
// is for display and logging only.
export const SERVER_NAME = 'extractium-valtown';
const SERVER_VERSION = '0.1.0';

// The settings read from the val's environment.
export const INDEX_URL_SETTING = 'EXTRACTIUM_INDEX_URL';
export const EMBED_URL_SETTING = 'EXTRACTIUM_EMBED_URL';
export const EMBED_TOKEN_SETTING = 'EXTRACTIUM_EMBED_TOKEN';

// Blob keys are a fixed prefix plus a digest of the index address, never
// any part of the address itself, so a hostile address cannot pick the key.
const STORE_PREFIX = 'extractium:index:';

// Limits. The size cap keeps a misconfigured address from filling memory;
// the timeouts keep a stalled host from eating the val's one-minute
// budget; the revalidation interval is how stale an answer may be while
// the val stays warm.
const MAX_INDEX_BYTES = 256 * 1024 * 1024;
const DOWNLOAD_TIMEOUT_MS = 30_000;
const EMBED_TIMEOUT_MS = 20_000;
const REVALIDATE_AFTER_MS = 10 * 60 * 1000;

/* ### Settings ### */

/**
 * Accepts a published container address, or refuses it.
 *
 * Only HTTPS is accepted on a hosted runtime: there is no loopback
 * address a developer could be serving a build from.
 *
 * @param {string|undefined} raw The address as configured.
 * @returns {string} The same address, once it has passed.
 * @throws {ConfigurationError} If it is missing or not an HTTPS URL.
 */
export function checkedUrl(raw) {
    if (!raw) {
        throw new ConfigurationError(`set ${INDEX_URL_SETTING} to the published index address.`);
    }
    let parsed;
    try {
        parsed = new URL(raw);
    } catch {
        parsed = null;
    }
    if (parsed && parsed.protocol === 'https:' && parsed.hostname) return raw;
    throw new ConfigurationError(`${INDEX_URL_SETTING} must be an https:// address; ${JSON.stringify(raw)} is not.`);
}

/**
 * The blob keys one published address is stored under.
 *
 * @param {string} url The published address.
 * @returns {Promise<{bodyKey: string, metaKey: string}>}
 */
export async function storeKeys(url) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(url));
    const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
    return { bodyKey: `${STORE_PREFIX}${hex}`, metaKey: `${STORE_PREFIX}${hex}:meta` };
}

/* ### Container Loading ### */

/**
 * The container for one published address, downloaded or from the store.
 *
 * The request carries whatever validators the last download returned, so
 * an unchanged file costs one small round trip. When the host cannot be
 * reached and a copy is stored, the stored copy is used and the failure
 * is logged. A store that refuses the copy, because the plan's blob
 * limit is smaller than the file, is logged and does not fail the
 * answer: the file is still held in memory for as long as the val stays
 * warm.
 *
 * @param {string} url The published address, already checked.
 * @param {{getBytes: Function, setBytes: Function, getJSON: Function, setJSON: Function}} store
 *     The blob store.
 * @param {{fetchImpl?: Function, log?: Function}} [options] Injection
 *     points for tests, and where to write progress.
 * @returns {Promise<{bytes: Uint8Array, fromStore: boolean}>}
 * @throws {Error} If the file cannot be fetched and nothing is stored.
 */
export async function containerBytes(url, store, options = {}) {
    const fetchImpl = options.fetchImpl || fetch;
    const log = options.log || (() => {});
    const { bodyKey, metaKey } = await storeKeys(url);

    const validators = (await store.getJSON(metaKey)) || {};
    const stored = await store.getBytes(bodyKey);

    const headers = {};
    if (stored) {
        if (validators.etag) headers['If-None-Match'] = validators.etag;
        if (validators.lastModified) headers['If-Modified-Since'] = validators.lastModified;
    }

    let response;
    try {
        response = await fetchImpl(url, {
            headers,
            redirect: 'follow',
            signal: AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS),
        });
    } catch (error) {
        if (stored) {
            log(`could not reach the index host (${error.message}); using the stored copy.`);
            return { bytes: stored, fromStore: true };
        }
        throw error;
    }

    if (response.status === 304 && stored) {
        return { bytes: stored, fromStore: true };
    }
    if (!response.ok) {
        throw new Error(`the index host answered ${response.status} for the published address.`);
    }
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > MAX_INDEX_BYTES) {
        throw new Error(`the index is larger than the ${Math.floor(MAX_INDEX_BYTES / 1024 / 1024)} MB this server will read.`);
    }
    try {
        await store.setBytes(bodyKey, bytes);
        await store.setJSON(metaKey, {
            etag: response.headers.get('etag'),
            lastModified: response.headers.get('last-modified'),
        });
    } catch (error) {
        log(`the index could not be kept in the blob store (${error.message}); it will be downloaded again on the next cold start.`);
    }
    return { bytes, fromStore: false };
}

/* ### Embedding ### */

/**
 * The vector inside an embedding service's answer.
 *
 * Services differ in how they wrap one vector: a bare array, an array
 * holding one array per input, or an object carrying either under
 * `data` or `result.data`. All four are read; anything else is refused.
 *
 * @param {*} payload The parsed JSON answer.
 * @returns {number[]} The vector.
 * @throws {Error} If no vector of numbers is found.
 */
export function parseEmbedding(payload) {
    let candidate = payload;
    if (candidate && typeof candidate === 'object' && !Array.isArray(candidate)) {
        candidate = candidate.data ?? (candidate.result && candidate.result.data);
    }
    if (Array.isArray(candidate) && Array.isArray(candidate[0])) candidate = candidate[0];
    if (Array.isArray(candidate) && candidate.length && candidate.every((value) => typeof value === 'number')) {
        return candidate;
    }
    throw new Error('the embedding service did not answer with a vector of numbers.');
}

/**
 * An embedder that posts text to an HTTP service.
 *
 * The request body is `{"inputs": text}`, the shape the Hugging Face
 * inference endpoints take for feature extraction; the token, when set,
 * travels as a bearer token and nowhere else.
 *
 * @param {string} url The service address.
 * @param {string|undefined} token The bearer token, if the service needs one.
 * @param {number} dims The vector length the container expects.
 * @param {{fetchImpl?: Function}} [options] Injection point for tests.
 * @returns {(text: string) => Promise<number[]>}
 */
export function httpEmbedder(url, token, dims, options = {}) {
    const fetchImpl = options.fetchImpl || fetch;
    return async (text) => {
        const headers = { 'content-type': 'application/json' };
        if (token) headers.authorization = `Bearer ${token}`;
        const response = await fetchImpl(url, {
            method: 'POST',
            headers,
            body: JSON.stringify({ inputs: text }),
            signal: AbortSignal.timeout(EMBED_TIMEOUT_MS),
        });
        if (!response.ok) throw new Error(`the embedding service answered ${response.status}.`);
        const vector = parseEmbedding(await response.json());
        if (vector.length !== dims) {
            throw new Error(`the embedding service returned ${vector.length} values; the index has ${dims}-dimensional vectors.`);
        }
        return vector;
    };
}

/* ### Searching ### */

/**
 * Keyword search alone, for a runtime with no embedding model.
 *
 * The candidate pool is ranked by BM25 and weighted per section as the
 * hybrid search would weight it; diversity selection then runs over the
 * pool with the stored vectors, so near-copies of one paragraph still
 * cannot fill the answer. The relevance cutoff is skipped, because its
 * constants are on the cosine scale and a keyword score is not: having
 * matched at least one query term is the floor here.
 *
 * @param {Object} index The loaded compendium.
 * @param {string} query What was asked.
 * @param {number} k How many sections to return.
 * @returns {Array<Object>} The selected sections, best first.
 */
export function keywordSearch(index, query, k) {
    const pool = bm25Candidates(tokenize(query), index.bm25, index.size)
        .map((entry) => ({ i: entry.i, s: entry.s * index.weightOf(entry.i) }))
        .sort((a, b) => (b.s - a.s) || (a.i - b.i));
    const selected = diversify(pool, index.vectors, index.dims, k, index.sourceKeyOf, true);
    return selected.map((candidate) => index.hitOf(candidate));
}

/**
 * The server for one val.
 *
 * The container is loaded on the first search and kept in memory; while
 * the val stays warm it is revalidated against the published address at
 * most every ten minutes, so a new build is picked up without a restart
 * and an unchanged one costs nothing.
 *
 * @param {{readSetting: (name: string) => (string|undefined),
 *          store: Object, fetchImpl?: Function, log?: Function,
 *          now?: () => number}} options
 *     How to read the environment, the blob store, and injection points
 *     for tests.
 * @returns {SearchServer}
 */
export function createValServer({ readSetting, store, fetchImpl, log, now }) {
    const clock = now || Date.now;
    const logger = log || (() => {});
    let index = null;
    let loadedAt = 0;

    async function currentIndex() {
        if (index !== null && clock() - loadedAt < REVALIDATE_AFTER_MS) return index;
        const url = checkedUrl(readSetting(INDEX_URL_SETTING));
        try {
            const { bytes, fromStore } = await containerBytes(url, store, { fetchImpl, log: logger });
            if (index === null || !fromStore) {
                index = loadContainer(await inflateContainer(bytes));
                logger(`index loaded: ${index.size} windows from ${fromStore ? 'the store' : 'the published address'}.`);
            }
        } catch (error) {
            if (index === null) throw error;
            logger(`the index could not be revalidated (${error.message}); answering from the copy in memory.`);
        }
        loadedAt = clock();
        return index;
    }

    return new SearchServer({
        serverName: SERVER_NAME,
        serverVersion: SERVER_VERSION,
        log: logger,
        openSearch: async () => {
            const first = await currentIndex();
            const embedUrl = readSetting(EMBED_URL_SETTING);
            const embedQuery = embedUrl
                ? httpEmbedder(embedUrl, readSetting(EMBED_TOKEN_SETTING), first.dims, { fetchImpl })
                : null;
            return {
                get name() { return index ? index.name : ''; },
                get builtAt() { return index ? (index.header.builtAt || '') : ''; },
                async search(query, k) {
                    const current = await currentIndex();
                    if (embedQuery) return current.search(query, embedQuery, { k });
                    return keywordSearch(current, query, k);
                },
            };
        },
    });
}
