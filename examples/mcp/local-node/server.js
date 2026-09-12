/*
 * Summary: A local Model Context Protocol (MCP) server that lets an AI
 * assistant on this machine search a published Extractium compendium. It
 * speaks JSON-RPC over standard input and output, downloads and caches
 * the container from its published URL, embeds the query with
 * transformers.js using the model the container names, and exposes one
 * tool, `search_kb`, over the JavaScript client. The protocol itself,
 * both eras of it, lives in the shared core under ../shared/.
 *
 * This file is part of Extractium™
 * examples/mcp/local-node/server.js
 *
 * Author(s): Gabriel Mongefranco.
 * Created: 2026-09-11
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

import { createHash } from 'node:crypto';
import { createInterface } from 'node:readline';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

// The client is read from its place in this repository. The package is
// not published to a registry, so there is no module name to import; a
// copy of this folder elsewhere needs extractium-client.js beside it and
// this one line changed.
import { loadContainer } from '../../../clients/js/extractium-client.js';

import {
    ConfigurationError,
    SearchServer,
} from '../shared/mcp-protocol.js';
import {
    TOOL_DEFINITION,
    renderResults,
    resultRecords,
} from '../shared/search-tool.js';

// The pieces the tests and the Python suite look for by name.
export { ConfigurationError, TOOL_DEFINITION, renderResults, resultRecords };

/* ### Constants ### */

// Identity this server reports. It is self-reported and unverified, so it
// is for display and logging only.
const SERVER_NAME = 'extractium-local-node';
const SERVER_VERSION = '0.1.0';

// Where the container comes from. One of the two is required; the path
// wins when both are set, because a local file needs no network at all.
const INDEX_URL_ENV = 'EXTRACTIUM_INDEX_URL';
const INDEX_PATH_ENV = 'EXTRACTIUM_INDEX_PATH';
const CACHE_DIR_ENV = 'EXTRACTIUM_CACHE_DIR';

// Folder the downloaded container is kept in, under the user's home
// directory unless CACHE_DIR_ENV names another.
const CACHE_FOLDER_NAME = 'extractium-mcp';

// Download limits. The timeout keeps a stalled host from hanging the
// assistant, and the size cap keeps a hostile or misconfigured URL from
// filling memory: a real compendium of a large site is a few hundred
// megabytes at most.
const DOWNLOAD_TIMEOUT_MS = 60_000;
const MAX_INDEX_BYTES = 512 * 1024 * 1024;

// Addresses allowed to serve the container over plain HTTP. Everywhere
// else must use HTTPS, because an index fetched over an open connection
// can be replaced in transit by whatever an attacker wants the assistant
// to read.
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

// How transformers.js is asked for a sentence embedding. The pooling and
// normalization match what the build side does, so a query vector and a
// stored vector are comparable.
const EMBEDDING_OPTIONS = { pooling: 'cls', normalize: true };

/* ### Configuration ### */

/**
 * Folder the downloaded container is kept in.
 *
 * @param {Object} [environment] The environment to read.
 * @returns {string} The folder, which may not exist yet.
 */
export function cacheRoot(environment = process.env) {
    return environment[CACHE_DIR_ENV] || path.join(os.homedir(), '.cache', CACHE_FOLDER_NAME);
}

/**
 * Accepts a published container address, or refuses it.
 *
 * HTTPS is required, except on the loopback address, where a developer
 * serving a build locally has no certificate and no network to attack.
 *
 * @param {string} raw The address as configured.
 * @returns {string} The same address, once it has passed.
 * @throws {ConfigurationError} If the address is not an HTTPS URL, or an
 *     HTTP URL on the loopback address.
 */
export function checkedUrl(raw) {
    let parsed;
    try {
        parsed = new URL(raw);
    } catch {
        parsed = null;
    }
    const host = parsed ? parsed.hostname.toLowerCase() : '';
    if (parsed && parsed.protocol === 'https:' && host) return raw;
    if (parsed && parsed.protocol === 'http:' && LOOPBACK_HOSTS.has(host)) return raw;
    throw new ConfigurationError(
        `${INDEX_URL_ENV} must be an https:// address (http:// is allowed only on localhost); `
        + `${JSON.stringify(raw)} is not.`
    );
}

/**
 * Where one published address is cached.
 *
 * The file name is a digest of the address, never any part of the address
 * itself, so a URL holding path separators or a parent-directory step
 * cannot decide where the file lands.
 *
 * @param {string} url The published address.
 * @param {string} root The cache folder.
 * @returns {{bodyPath: string, metaPath: string}}
 */
export function cachePaths(url, root) {
    const digest = createHash('sha256').update(url, 'utf8').digest('hex');
    return {
        bodyPath: path.join(root, `${digest}.container`),
        metaPath: path.join(root, `${digest}.meta.json`),
    };
}

/* ### Container Loading ### */

/** The file's bytes, or null when it is not there. */
async function readIfPresent(filePath) {
    try {
        return new Uint8Array(await fs.readFile(filePath));
    } catch {
        return null;
    }
}

/**
 * The container for one published address, downloaded or from the cache.
 *
 * The request carries whatever validators the last download returned, so
 * an unchanged file costs one small round trip rather than a full
 * download. When the host cannot be reached and a copy is cached, the
 * cached copy is used and the failure is logged, so an assistant keeps
 * working offline.
 *
 * @param {string} url The published address, already checked.
 * @param {string} root The cache folder.
 * @param {{fetchImpl?: Function, log?: Function}} [options] Injection
 *     points for tests, and where to write progress.
 * @returns {Promise<Uint8Array>} The container.
 * @throws {Error} If the file cannot be fetched and nothing is cached.
 */
export async function containerBytes(url, root, options = {}) {
    const fetchImpl = options.fetchImpl || fetch;
    const log = options.log || (() => {});
    const { bodyPath, metaPath } = cachePaths(url, root);

    let validators = {};
    try {
        validators = JSON.parse(await fs.readFile(metaPath, 'utf8'));
    } catch {
        validators = {};
    }
    const cached = await readIfPresent(bodyPath);

    const headers = {};
    if (cached) {
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
        if (cached) {
            log(`could not reach the index host (${error.message}); using the cached copy.`);
            return cached;
        }
        throw error;
    }

    if (response.status === 304 && cached) {
        log('index unchanged since the last download; using the cached copy.');
        return cached;
    }
    if (!response.ok) {
        throw new Error(`the index host answered ${response.status} for the published address.`);
    }

    const body = new Uint8Array(await response.arrayBuffer());
    if (body.byteLength > MAX_INDEX_BYTES) {
        throw new Error(
            `the index is larger than the ${Math.floor(MAX_INDEX_BYTES / 1024 / 1024)} MB this `
            + 'server will read.'
        );
    }
    await fs.mkdir(root, { recursive: true });
    await fs.writeFile(bodyPath, body);
    await fs.writeFile(metaPath, JSON.stringify({
        etag: response.headers.get('etag'),
        lastModified: response.headers.get('last-modified'),
    }), 'utf8');
    return body;
}

/**
 * Loads the configured compendium and returns it ready to search.
 *
 * @param {Object} [environment] The environment to read.
 * @param {{fetchImpl?: Function, log?: Function}} [options] As above.
 * @returns {Promise<Object>} The loaded compendium.
 * @throws {ConfigurationError} If neither address nor path is configured,
 *     or the address is not one this server will fetch.
 * @throws {Error} If the file is not a readable compendium, or cannot be
 *     read or fetched.
 */
export async function indexFromEnvironment(environment = process.env, options = {}) {
    const log = options.log || (() => {});
    const localPath = environment[INDEX_PATH_ENV];
    if (localPath) {
        log(`reading the index from ${localPath}`);
        return loadContainer(new Uint8Array(await fs.readFile(localPath)));
    }
    const url = environment[INDEX_URL_ENV];
    if (!url) {
        throw new ConfigurationError(
            `set ${INDEX_URL_ENV} to the published index address, or ${INDEX_PATH_ENV} to a built `
            + 'index on this machine.'
        );
    }
    log(`reading the index from ${url}`);
    return loadContainer(await containerBytes(checkedUrl(url), cacheRoot(environment), options));
}

/**
 * An embedder for one model, loaded from transformers.js.
 *
 * The import happens here rather than at the top of the file so that
 * starting the server costs nothing: the package and the model, about
 * 130 MB the first time, are fetched only when a search actually runs.
 *
 * @param {string} modelName The model id the container names for browsers
 *     and other JavaScript runtimes.
 * @returns {Promise<(text: string) => Promise<ArrayLike<number>>>}
 */
export async function transformersEmbedder(modelName) {
    const { pipeline } = await import('@huggingface/transformers');
    const embedder = await pipeline('feature-extraction', modelName);
    return async (text) => (await embedder(text, EMBEDDING_OPTIONS)).data;
}

/* ### Server ### */

/**
 * The local server: the shared protocol core over a compendium read from
 * this machine or downloaded once, with queries embedded here.
 *
 * The compendium and the embedder are supplied as callables and are built
 * on the first search, so the server starts instantly and a machine that
 * never searches never downloads a model.
 */
export class KbServer extends SearchServer {
    /**
     * @param {{openIndex: () => Promise<Object>,
     *          openEmbedder: (index: Object) => Promise<Function>,
     *          log?: (message: string) => void}} options
     *     How to load the compendium and its embedder, and where to write
     *     progress. Never standard output, which carries protocol
     *     messages only.
     */
    constructor({ openIndex, openEmbedder, log }) {
        super({
            serverName: SERVER_NAME,
            serverVersion: SERVER_VERSION,
            log,
            openSearch: async () => {
                const index = await openIndex();
                const embedQuery = await openEmbedder(index);
                return {
                    name: index.name || '',
                    builtAt: (index.header && index.header.builtAt) || '',
                    search: (query, k) => index.search(query, embedQuery, { k }),
                };
            },
        });
    }
}

/* ### Running ### */

/**
 * Reads messages from one stream and writes answers to the other.
 *
 * Messages are one per line and never hold a newline, which is what the
 * standard-input transport specifies.
 *
 * @param {NodeJS.ReadableStream} input The client's messages.
 * @param {NodeJS.WritableStream} output Where answers go. Protocol
 *     messages only.
 * @param {KbServer} server What answers them.
 * @returns {Promise<number>} The process exit code.
 */
export async function serve(input, output, server) {
    const lines = createInterface({ input, crlfDelay: Infinity });
    for await (const line of lines) {
        const trimmed = line.trim();
        if (trimmed === '') continue;
        const answer = await server.handleLine(trimmed);
        if (answer === null) continue;
        output.write(`${JSON.stringify(answer)}\n`);
    }
    return 0;
}

/**
 * Starts the server on standard input and output.
 *
 * @param {Object} [environment] The environment to read.
 * @returns {Promise<number>} 0 on a clean shutdown, 2 when the
 *     environment does not say which index to search.
 */
export async function main(environment = process.env) {
    const log = (message) => process.stderr.write(`${SERVER_NAME}: ${message}\n`);

    if (!environment[INDEX_PATH_ENV] && !environment[INDEX_URL_ENV]) {
        log(`set ${INDEX_URL_ENV} to the published index address, or ${INDEX_PATH_ENV} to a built `
            + 'index on this machine.');
        return 2;
    }

    const server = new KbServer({
        openIndex: () => indexFromEnvironment(environment, { log }),
        openEmbedder: (index) => transformersEmbedder(index.embedding.browserModel
            || index.embedding.model),
        log,
    });
    log('ready; waiting for requests on standard input.');
    return serve(process.stdin, process.stdout, server);
}

// Runs only when this file is the program, so the tests can import it.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    main().then((code) => {
        process.exitCode = code;
    });
}
