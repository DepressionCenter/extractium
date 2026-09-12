/*
 * Summary: The Val Town entry point of the hosted search server. Wires
 * the val's blob store and environment into the runtime-neutral search
 * in kb.js and serves the Model Context Protocol endpoint at /mcp over
 * the shared HTTP binding. This file runs on Val Town only; the tests
 * exercise kb.js directly.
 *
 * This file is part of Extractium™
 * examples/mcp/valtown/main.http.ts
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

// The val-scoped blob store: keys are private to this val.
import { blob } from "https://esm.town/v/std/blob/main.ts";

// These two are copied beside this file by push.py; see the README.
import { createValServer } from "./kb.js";
import {
    ALLOWED_ORIGINS_SETTING,
    BEARER_TOKEN_SETTING,
    allowedOrigins,
    handleMcpRequest,
} from "./mcp-http.js";

/* ### Wiring ### */

// The store kb.js expects, over Val Town's blob module. A missing key is
// null here rather than an exception, which is the shape a cache wants.
const store = {
    async getBytes(key: string): Promise<Uint8Array | null> {
        try {
            const response = await blob.get(key);
            return new Uint8Array(await response.arrayBuffer());
        } catch {
            return null;
        }
    },
    setBytes: (key: string, bytes: Uint8Array) => blob.set(key, bytes),
    getJSON: (key: string) => blob.getJSON(key),
    setJSON: (key: string, value: unknown) => blob.setJSON(key, value),
};

const readSetting = (name: string) => Deno.env.get(name);

// One server per warm val, so the index stays loaded between requests.
const server = createValServer({ readSetting, store, log: console.error });

/* ### Handler ### */

export default async function (request: Request): Promise<Response> {
    return handleMcpRequest(request, server, {
        bearerToken: readSetting(BEARER_TOKEN_SETTING),
        allowedOrigins: allowedOrigins(readSetting(ALLOWED_ORIGINS_SETTING)),
    });
}
