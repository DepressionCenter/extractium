/*
 * Summary: A one-shot runner that ranks a corpus with the JavaScript
 * client's vector search and prints the result as JSON. It exists so a
 * Python test can put the same vectors and the same query through both
 * clients and check that they agree, which no test written in one
 * language alone can do. Reads a JSON file holding `vectors` (flat, in
 * child order), `dims`, and `query`; writes `[[childIndex, score], ...]`
 * to standard output.
 *
 * This file is part of Extractium™
 * tests/reference/rank_vectors.mjs
 *
 * Author(s): Gabriel Mongefranco.
 * Created: 2026-09-18
 * Last Modified: 2026-09-18
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

import fs from 'node:fs';

import { vectorCandidates } from '../../clients/js/extractium-client.js';

const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ranked = vectorCandidates(
    Float32Array.from(input.query),
    Float32Array.from(input.vectors),
    input.dims,
    input.vectors.length / input.dims,
);
process.stdout.write(JSON.stringify(ranked.map((entry) => [entry.i, entry.s])));
