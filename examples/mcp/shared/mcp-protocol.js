/*
 * Summary: The Model Context Protocol core every Extractium example server
 * shares: JSON-RPC framing, both eras of the protocol (the stateless
 * revision that names its version in each request, and the older
 * `initialize` handshake), discovery, the tool list, and the dispatch of
 * `tools/call` to one search. Transport is somebody else's job: the local
 * servers feed it lines from standard input, and the hosted ones feed it
 * the body of an HTTP request.
 *
 * This file is part of Extractium™
 * examples/mcp/shared/mcp-protocol.js
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
    INSTRUCTIONS,
    TOOL_DEFINITION,
    TOOL_NAME,
    checkedArguments,
    searchResult,
    textResult,
} from './search-tool.js';

/* ### Constants ### */

// Protocol revisions. The modern revision carries the version, the client
// identity, and the client capabilities in each request's `_meta`; the
// legacy revisions open with an `initialize` handshake instead. Answering
// both is what lets one server work with old and new clients alike.
export const MODERN_VERSION = '2026-07-28';
export const LEGACY_VERSIONS = ['2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05'];
export const SUPPORTED_VERSIONS = [MODERN_VERSION, ...LEGACY_VERSIONS];

// Reserved `_meta` keys. The protocol requires this prefix on them.
const META_PREFIX = 'io.modelcontextprotocol/';
export const PROTOCOL_VERSION_KEY = `${META_PREFIX}protocolVersion`;
const SERVER_INFO_KEY = `${META_PREFIX}serverInfo`;

// JSON-RPC framing and the error codes these servers return. -32022 is
// the protocol's own "unsupported protocol version"; the rest are
// JSON-RPC's.
export const JSONRPC_VERSION = '2.0';
export const ERROR_PARSE = -32700;
export const ERROR_INVALID_REQUEST = -32600;
export const ERROR_METHOD_NOT_FOUND = -32601;
export const ERROR_INVALID_PARAMS = -32602;
export const ERROR_UNSUPPORTED_VERSION = -32022;

/** Thrown when the environment does not say which container to search. */
export class ConfigurationError extends Error {
    constructor(message) {
        super(message);
        this.name = 'ConfigurationError';
    }
}

/* ### Messages ### */

/** One JSON-RPC result message. */
export function response(id, result) {
    return { jsonrpc: JSONRPC_VERSION, id, result };
}

/** One JSON-RPC error message. */
export function errorMessage(id, code, message, data) {
    const error = { code, message };
    if (data !== undefined) error.data = data;
    return { jsonrpc: JSONRPC_VERSION, id, error };
}

/** The protocol version a modern request declares, or null. */
export function requestedVersion(params) {
    const meta = params._meta;
    if (meta === null || typeof meta !== 'object') return null;
    const version = meta[PROTOCOL_VERSION_KEY];
    return typeof version === 'string' ? version : null;
}

/**
 * Marks a result complete, which only the modern revision expects. A
 * legacy client is given the plain result it was written against.
 */
function complete(payload, modern) {
    return modern ? { resultType: 'complete', ...payload } : payload;
}

/**
 * The JSON-RPC error a malformed `tools/call` earns, or null when the
 * request is well formed enough for the tool to judge its arguments.
 */
function refusedCall(id, params) {
    if (params.name !== TOOL_NAME) {
        return errorMessage(id, ERROR_INVALID_PARAMS, `Unknown tool: ${params.name}`);
    }
    const args = params.arguments;
    if (args !== undefined && (typeof args !== 'object' || args === null || Array.isArray(args))) {
        return errorMessage(id, ERROR_INVALID_PARAMS, 'arguments must be an object.');
    }
    return null;
}

/* ### Server ### */

/**
 * Answers MCP requests for one compendium.
 *
 * The search is supplied as a callable and opened on the first call, so a
 * server starts instantly and one that is never asked anything never
 * loads an index.
 */
export class SearchServer {
    /**
     * @param {{serverName: string, serverVersion: string,
     *          openSearch: () => Promise<{name: string, builtAt: string,
     *              search: (query: string, k: number) => Promise<Array<Object>>}>,
     *          log?: (message: string) => void}} options
     *     What this server calls itself, how to open the search, and where
     *     to write progress. Never a protocol stream.
     */
    constructor({ serverName, serverVersion, openSearch, log }) {
        this.serverName = serverName;
        this.serverVersion = serverVersion;
        this.openSearch = openSearch;
        this.log = log || (() => {});
        this.searcher = null;
    }

    /* ### Request Handling ### */

    /**
     * Answers one message given as text.
     *
     * @param {string} text One JSON-RPC message.
     * @returns {Promise<Object|null>} The message to send back, or null
     *     for a notification, which is never answered.
     */
    async handleLine(text) {
        let message;
        try {
            message = JSON.parse(text);
        } catch {
            return errorMessage(null, ERROR_PARSE, 'message is not valid JSON.');
        }
        return this.handle(message);
    }

    /**
     * Answers one parsed message.
     *
     * @param {*} message The JSON-RPC request or notification.
     * @returns {Promise<Object|null>} The message to send back, or null.
     */
    async handle(message) {
        if (message === null || typeof message !== 'object' || Array.isArray(message)
            || message.jsonrpc !== JSONRPC_VERSION) {
            return errorMessage(null, ERROR_INVALID_REQUEST, 'message is not a JSON-RPC 2.0 request.');
        }
        const id = message.id ?? null;
        const params = message.params ?? {};
        if (typeof params !== 'object' || params === null || Array.isArray(params)) {
            return errorMessage(id, ERROR_INVALID_PARAMS, 'params must be an object.');
        }

        // A notification carries no id and is never answered, whatever it
        // asks for. Cancellation arrives this way, and nothing here runs
        // long enough to cancel.
        if (id === null) return null;

        const version = requestedVersion(params);
        if (version !== null && !SUPPORTED_VERSIONS.includes(version)) {
            return errorMessage(id, ERROR_UNSUPPORTED_VERSION, 'Unsupported protocol version', {
                supported: SUPPORTED_VERSIONS,
                requested: version,
            });
        }
        const modern = version !== null;

        switch (message.method) {
            case 'server/discover':
                return response(id, this.discover());
            case 'initialize':
                return response(id, this.initialize(params));
            case 'ping':
                return response(id, {});
            case 'tools/list':
                return response(id, complete({ tools: [TOOL_DEFINITION] }, modern));
            case 'tools/call': {
                const refusal = refusedCall(id, params);
                if (refusal) return refusal;
                return response(id, complete(await this.callTool(params), modern));
            }
            default:
                return errorMessage(id, ERROR_METHOD_NOT_FOUND, `Unknown method: ${message.method}`);
        }
    }

    /** What this server is and which revisions it answers. */
    discover() {
        return {
            resultType: 'complete',
            supportedVersions: SUPPORTED_VERSIONS,
            capabilities: { tools: { listChanged: false } },
            instructions: INSTRUCTIONS,
            _meta: { [SERVER_INFO_KEY]: { name: this.serverName, version: this.serverVersion } },
        };
    }

    /**
     * The handshake a legacy client opens with. The client's own version
     * is echoed when this server speaks it, so an older client keeps the
     * revision it was written against.
     */
    initialize(params) {
        const asked = params.protocolVersion;
        return {
            protocolVersion: LEGACY_VERSIONS.includes(asked) ? asked : LEGACY_VERSIONS[0],
            capabilities: { tools: { listChanged: false } },
            serverInfo: { name: this.serverName, version: this.serverVersion },
            instructions: INSTRUCTIONS,
        };
    }

    /* ### The Tool ### */

    /**
     * Runs the tool named in one `tools/call` request, once the request
     * itself has been accepted.
     *
     * @param {Object} params The request's parameters.
     * @returns {Promise<Object>} The tool result. A search that fails is
     *     a result carrying `isError`, so the model can read what went
     *     wrong and try again.
     */
    async callTool(params) {
        const checked = checkedArguments(params.arguments ?? {});
        if (checked.refusal) return checked.refusal;
        return this.search(checked.query, checked.k);
    }

    /** Searches the compendium and shapes the answer. */
    async search(query, k) {
        let searcher;
        try {
            searcher = await this.ready();
        } catch (error) {
            if (error instanceof ConfigurationError) {
                return textResult(`This server is not configured yet: ${error.message}`, undefined, true);
            }
            this.log(`preparing the search failed: ${error.message}`);
            return textResult(
                'The index or the embedding model could not be loaded. The server\'s log says '
                + 'which step failed.',
                undefined,
                true
            );
        }

        let hits;
        try {
            hits = await searcher.search(query, k);
        } catch (error) {
            this.log(`the search failed: ${error.message}`);
            return textResult(
                'The search could not be run. The server\'s log says which step failed.',
                undefined,
                true
            );
        }
        return searchResult(hits, query, searcher);
    }

    /** The search, opened once and kept. */
    async ready() {
        if (this.searcher === null) this.searcher = await this.openSearch();
        return this.searcher;
    }
}
