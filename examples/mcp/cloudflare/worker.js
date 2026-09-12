/*
 * Summary: The Cloudflare Worker entry point of the hosted search server:
 * one Model Context Protocol tool, `search_kb`, over a compendium held in
 * a D1 database, served at /mcp through the shared HTTP binding. The
 * search itself is in d1-search.js; this module exports the handler and
 * nothing else, which is what the Workers runtime requires of it.
 *
 * This file is part of Extractium™
 * examples/mcp/cloudflare/worker.js
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
    ALLOWED_ORIGINS_SETTING,
    BEARER_TOKEN_SETTING,
    allowedOrigins,
    handleMcpRequest,
} from '../shared/mcp-http.js';
import { createWorkerServer } from './d1-search.js';

/* ### Entry Point ### */

// One server per isolate, so the meta table is read once and kept.
let cachedServer = null;

export default {
    /**
     * Answers one request.
     *
     * @param {Request} request The incoming request.
     * @param {{DB: D1Database, AI?: Object, EXTRACTIUM_BEARER_TOKEN?: string,
     *          EXTRACTIUM_ALLOWED_ORIGINS?: string}} env The bindings and settings.
     * @returns {Promise<Response>}
     */
    async fetch(request, env) {
        if (cachedServer === null) cachedServer = createWorkerServer(env);
        return handleMcpRequest(request, cachedServer, {
            bearerToken: env[BEARER_TOKEN_SETTING],
            allowedOrigins: allowedOrigins(env[ALLOWED_ORIGINS_SETTING]),
        });
    },
};
