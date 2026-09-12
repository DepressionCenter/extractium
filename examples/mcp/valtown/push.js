/*
 * Summary: Pushes the staged val to Val Town through its REST API, with no
 * tool beyond Node. Finds or creates the val under the account the token
 * belongs to, then creates or updates each staged file, marking the entry
 * point as an HTTP val, and prints the endpoint address the platform
 * assigns. The token comes from the environment and travels in one
 * header; nothing else about the account is read or changed.
 *
 * This file is part of Extractium™
 * examples/mcp/valtown/push.js
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

import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

import { DEFAULT_TARGET, stage } from './stage.js';

/* ### Constants ### */

// The platform's API. Every call below is documented at
// https://docs.val.town/reference/api/ and in its OpenAPI description.
export const API_BASE = 'https://api.val.town';

// The setting the token is read from. Create one at
// https://www.val.town/settings/api with read and write on vals.
export const TOKEN_SETTING = 'VALTOWN_API_TOKEN';

// What the val is called unless the command line says otherwise, and how
// visible its source is. `unlisted` keeps the source off the public
// listing; the HTTP endpoint is reachable either way.
export const DEFAULT_VAL_NAME = 'extractium-kb-mcp';
export const DEFAULT_PRIVACY = 'unlisted';

// The file the platform runs on each request. Its `http` type is what
// gives the val an endpoint; every other file is a plain module.
export const ENTRY_FILE = 'main.http.ts';

// The platform's per-file size limit.
const MAX_FILE_CHARS = 80_000;

// Exit codes.
const EXIT_OK = 0;
const EXIT_NO_TOKEN = 2;
const EXIT_FAILED = 1;

/** Thrown when the platform answers something other than success. */
export class PushError extends Error {
    constructor(message) {
        super(message);
        this.name = 'PushError';
    }
}

/* ### API Calls ### */

/**
 * One call to the platform.
 *
 * @param {Function} fetchImpl The fetch to use.
 * @param {string} token The API token.
 * @param {string} method The HTTP method.
 * @param {string} route The path and query under the API base.
 * @param {Object} [body] JSON to send.
 * @returns {Promise<{status: number, json: any}>}
 * @throws {PushError} On a network failure or a 5xx answer.
 */
async function call(fetchImpl, token, method, route, body) {
    const init = {
        method,
        headers: { authorization: `Bearer ${token}`, accept: 'application/json' },
    };
    if (body !== undefined) {
        init.headers['content-type'] = 'application/json';
        init.body = JSON.stringify(body);
    }
    let response;
    try {
        response = await fetchImpl(`${API_BASE}${route}`, init);
    } catch (error) {
        throw new PushError(`could not reach ${API_BASE}: ${error.message}`);
    }
    if (response.status >= 500) {
        throw new PushError(`the platform answered ${response.status} for ${method} ${route}.`);
    }
    let json = null;
    try {
        json = await response.json();
    } catch {
        json = null;
    }
    return { status: response.status, json };
}

/** The answer's body, or a PushError naming the call when it was refused. */
function accepted(result, what) {
    if (result.status >= 200 && result.status < 300) return result.json;
    const detail = result.json && result.json.message ? `: ${result.json.message}` : '';
    throw new PushError(`${what} was refused with ${result.status}${detail}. A token needs read and write on vals.`);
}

/**
 * The id of the named val under the token's account, created if absent.
 *
 * @param {Function} fetchImpl The fetch to use.
 * @param {string} token The API token.
 * @param {string} name The val's name.
 * @param {string} privacy `public`, `unlisted`, or `private`.
 * @param {Function} log Where to report what happened.
 * @returns {Promise<string>} The val id.
 */
export async function findOrCreateVal(fetchImpl, token, name, privacy, log) {
    const me = accepted(await call(fetchImpl, token, 'GET', '/v2/me'), 'reading the account');
    const username = me.username;
    if (!username) throw new PushError('the account answer carried no username.');

    const existing = await call(fetchImpl, token, 'GET', `/v2/alias/vals/${encodeURIComponent(username)}/${encodeURIComponent(name)}`);
    if (existing.status === 200 && existing.json && existing.json.id) {
        log(`updating the val ${username}/${name}`);
        return existing.json.id;
    }
    if (existing.status !== 404) accepted(existing, 'looking the val up');

    const created = accepted(
        await call(fetchImpl, token, 'POST', '/v2/vals', { name, privacy }),
        'creating the val'
    );
    log(`created the val ${username}/${name}`);
    return created.id;
}

/**
 * Creates or updates one file in the val.
 *
 * @param {Function} fetchImpl The fetch to use.
 * @param {string} token The API token.
 * @param {string} valId The val.
 * @param {string} name The file name inside the val.
 * @param {string} content The file's text.
 * @returns {Promise<Object>} The platform's record of the file.
 */
export async function putFile(fetchImpl, token, valId, name, content) {
    if (content.length > MAX_FILE_CHARS) {
        throw new PushError(`${name} is ${content.length} characters; the platform accepts ${MAX_FILE_CHARS} per file.`);
    }
    const type = name === ENTRY_FILE ? 'http' : 'file';
    const route = `/v2/vals/${encodeURIComponent(valId)}/files?path=${encodeURIComponent(name)}`;
    const listed = await call(fetchImpl, token, 'GET', `${route}&limit=1`);
    const present = listed.status === 200 && listed.json && Array.isArray(listed.json.data)
        && listed.json.data.some((entry) => entry.path === name);
    const method = present ? 'PUT' : 'POST';
    return accepted(await call(fetchImpl, token, method, route, { content, type }), `writing ${name}`);
}

/* ### Pushing ### */

/**
 * Stages the val and pushes every file.
 *
 * @param {{token: string, name?: string, privacy?: string, target?: string,
 *          fetchImpl?: Function, log?: Function}} options
 *     The token, the val's name and source visibility, where to stage,
 *     and injection points for tests.
 * @returns {Promise<{valId: string, endpoint: string|null, files: string[]}>}
 * @throws {PushError} If the platform refuses any step.
 */
export async function push(options) {
    const fetchImpl = options.fetchImpl || fetch;
    const log = options.log || (() => {});
    const name = options.name || DEFAULT_VAL_NAME;
    const privacy = options.privacy || DEFAULT_PRIVACY;
    const target = options.target || DEFAULT_TARGET;

    const files = await stage(target);
    const valId = await findOrCreateVal(fetchImpl, options.token, name, privacy, log);

    let endpoint = null;
    for (const file of files) {
        const content = await fs.readFile(path.join(target, file), 'utf8');
        const record = await putFile(fetchImpl, options.token, valId, file, content);
        log(`wrote ${file}`);
        if (file === ENTRY_FILE && record && record.links && record.links.endpoint) {
            endpoint = record.links.endpoint;
        }
    }
    return { valId, endpoint, files };
}

/* ### Command Line ### */

/**
 * Pushes from the command line.
 *
 * Usage: `node push.js [val-name] [--privacy public|unlisted|private]`,
 * with `VALTOWN_API_TOKEN` in the environment.
 *
 * @param {string[]} argv Arguments after the script name.
 * @param {Object} [environment] The environment to read.
 * @returns {Promise<number>} The exit code.
 */
export async function main(argv, environment = process.env) {
    const log = (message) => process.stderr.write(`push: ${message}\n`);
    const token = environment[TOKEN_SETTING];
    if (!token) {
        log(`set ${TOKEN_SETTING} to a Val Town API token with read and write on vals.`);
        return EXIT_NO_TOKEN;
    }
    const positional = argv.filter((argument) => !argument.startsWith('--'));
    const privacyIndex = argv.indexOf('--privacy');
    const privacy = privacyIndex === -1 ? DEFAULT_PRIVACY : argv[privacyIndex + 1];
    const name = positional.find((argument, index) => argv[index - 1] !== '--privacy') || DEFAULT_VAL_NAME;

    try {
        const result = await push({ token, name, privacy, log });
        process.stdout.write(`pushed ${result.files.length} files to val ${result.valId}\n`);
        if (result.endpoint) {
            process.stdout.write(`endpoint: ${result.endpoint}\n`);
            process.stdout.write(`the MCP endpoint is ${result.endpoint.replace(/\/$/, '')}/mcp\n`);
        }
        process.stdout.write('set EXTRACTIUM_INDEX_URL in the val\'s environment variables before the first request.\n');
        return EXIT_OK;
    } catch (error) {
        if (error instanceof PushError) {
            log(error.message);
            return EXIT_FAILED;
        }
        throw error;
    }
}

// Runs only when this file is the program, so the tests can import it.
if (process.argv[1] && import.meta.url === new URL(`file:///${process.argv[1].replace(/\\/g, '/')}`).href) {
    main(process.argv.slice(2)).then((code) => {
        process.exitCode = code;
    });
}
