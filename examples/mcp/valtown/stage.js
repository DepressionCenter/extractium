/*
 * Summary: Assembles the folder that is pushed to Val Town. A val holds
 * only its own files, so the JavaScript client and the shared protocol
 * modules this example imports from elsewhere in the repository are
 * copied beside the entry point, and the import lines are rewritten to
 * point at the copies. Run it before `vt push`; run it again after any
 * of the source files change.
 *
 * This file is part of Extractium™
 * examples/mcp/valtown/stage.js
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
import { fileURLToPath } from 'node:url';

/* ### Constants ### */

const HERE = path.dirname(fileURLToPath(import.meta.url));

// Where the assembled val lands. Not committed: it is a build product.
export const DEFAULT_TARGET = path.join(HERE, 'val');

// Every file the val needs, relative to this folder. The entry point and
// the search live here; the rest are copied from where they are kept.
export const SOURCE_FILES = [
    'main.http.ts',
    'kb.js',
    '../shared/mcp-protocol.js',
    '../shared/mcp-http.js',
    '../shared/search-tool.js',
    '../../../clients/js/extractium-client.js',
];

// A relative import that leaves the folder, such as
// `'../shared/mcp-http.js'` or `'../../../clients/js/extractium-client.js'`.
// Only the file name survives, because every file lands in one folder.
const OUTSIDE_IMPORT = /(from\s+|import\s+)(['"])(?:\.\.\/)+(?:[^'"]*\/)?([^'"\/]+)\2/g;

/* ### Staging ### */

/**
 * The same source with every import that left the folder pointed at the
 * copy beside it.
 *
 * @param {string} source A JavaScript or TypeScript module.
 * @returns {string}
 */
export function relocatedImports(source) {
    return source.replace(OUTSIDE_IMPORT, (_match, keyword, quote, name) => `${keyword}${quote}./${name}${quote}`);
}

/**
 * Writes the val folder.
 *
 * @param {string} [target] Where to write; created if missing.
 * @returns {Promise<string[]>} The files written, by name.
 */
export async function stage(target = DEFAULT_TARGET) {
    await fs.mkdir(target, { recursive: true });
    const written = [];
    for (const relative of SOURCE_FILES) {
        const name = path.basename(relative);
        const source = await fs.readFile(path.join(HERE, relative), 'utf8');
        await fs.writeFile(path.join(target, name), relocatedImports(source), 'utf8');
        written.push(name);
    }
    return written;
}

// Runs only when this file is the program, so the tests can import it.
if (process.argv[1] && import.meta.url === new URL(`file:///${process.argv[1].replace(/\\/g, '/')}`).href) {
    stage(process.argv[2]).then((written) => {
        process.stdout.write(`staged ${written.length} files under ${process.argv[2] || DEFAULT_TARGET}:\n`);
        for (const name of written) process.stdout.write(`  ${name}\n`);
    });
}
