/*
 * Summary: Tests for the Val Town push: the calls it makes to the platform
 * in order, the val found by name or created, each staged file created or
 * updated with the right type, the token carried in one header only, the
 * endpoint reported back, and the refusals a bad token or an oversized
 * file earn.
 *
 * This file is part of Extractium™
 * examples/mcp/valtown/push.test.js
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

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { ENTRY_FILE, PushError, push, putFile } from './push.js';
import { SOURCE_FILES } from './stage.js';

/* ### A fake platform ### */

const TOKEN = 'EXAMPLE_VALTOWN_TOKEN';
const VAL_ID = '11111111-2222-3333-4444-555555555555';

/**
 * Enough of the Val Town API to push against: an account, an optional
 * existing val, and a file store. Every call is recorded.
 */
function fakePlatform({ existingVal = false, existingFiles = [] } = {}) {
    const calls = [];
    const files = new Set(existingFiles);
    const fetchImpl = async (url, init) => {
        const { pathname, searchParams } = new URL(url);
        calls.push({ method: init.method, pathname, path: searchParams.get('path'), init });
        const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
        if (init.headers.authorization !== `Bearer ${TOKEN}`) return json(401, { message: 'bad token' });
        if (pathname === '/v2/me') return json(200, { id: 'u1', username: 'example' });
        if (pathname.startsWith('/v2/alias/vals/example/')) {
            return existingVal ? json(200, { id: VAL_ID }) : json(404, { message: 'not found' });
        }
        if (pathname === '/v2/vals' && init.method === 'POST') return json(201, { id: VAL_ID });
        if (pathname === `/v2/vals/${VAL_ID}/files`) {
            const name = searchParams.get('path');
            if (init.method === 'GET') return json(200, { data: files.has(name) ? [{ path: name }] : [] });
            const body = JSON.parse(init.body);
            if (init.method === 'POST' && files.has(name)) return json(409, { message: 'exists' });
            if (init.method === 'PUT' && !files.has(name)) return json(404, { message: 'missing' });
            files.add(name);
            const record = { path: name, type: body.type, links: {} };
            if (body.type === 'http') record.links.endpoint = 'https://example-kb.val.run';
            return json(init.method === 'POST' ? 201 : 200, record);
        }
        return json(404, { message: `no route ${pathname}` });
    };
    return { fetchImpl, calls, files };
}

function tempTarget() {
    return fs.mkdtempSync(path.join(os.tmpdir(), 'extractium-push-'));
}

/* ### Pushing ### */

test('a first push creates the val, creates every staged file, and reports the endpoint', async () => {
    const platform = fakePlatform();
    const target = tempTarget();
    try {
        const result = await push({ token: TOKEN, target, fetchImpl: platform.fetchImpl });

        assert.equal(result.valId, VAL_ID);
        assert.equal(result.endpoint, 'https://example-kb.val.run');
        assert.deepEqual(result.files, SOURCE_FILES.map((relative) => path.basename(relative)));
        assert.deepEqual([...platform.files].sort(), [...result.files].sort());
        const creates = platform.calls.filter((c) => c.method === 'POST' && c.pathname === '/v2/vals');
        assert.equal(creates.length, 1);
        assert.deepEqual(JSON.parse(creates[0].init.body), { name: 'extractium-kb-mcp', privacy: 'unlisted' });
        assert.equal(platform.calls.filter((c) => c.method === 'PUT').length, 0);
    } finally {
        fs.rmSync(target, { recursive: true, force: true });
    }
});

test('a later push finds the val by name and updates the files it already holds', async () => {
    const platform = fakePlatform({ existingVal: true, existingFiles: [ENTRY_FILE, 'kb.js'] });
    const target = tempTarget();
    try {
        await push({ token: TOKEN, target, fetchImpl: platform.fetchImpl, name: 'extractium-kb-mcp' });

        assert.equal(platform.calls.filter((c) => c.method === 'POST' && c.pathname === '/v2/vals').length, 0);
        const updated = platform.calls.filter((c) => c.method === 'PUT').map((c) => c.path).sort();
        assert.deepEqual(updated, ['kb.js', ENTRY_FILE].sort());
        assert.equal(platform.calls.filter((c) => c.method === 'POST' && c.path !== null).length, 4);
    } finally {
        fs.rmSync(target, { recursive: true, force: true });
    }
});

test('the entry point is an http val and every other file is a plain file', async () => {
    const platform = fakePlatform();
    const target = tempTarget();
    try {
        await push({ token: TOKEN, target, fetchImpl: platform.fetchImpl });

        for (const c of platform.calls.filter((call) => call.method === 'POST' && call.path !== null)) {
            const { type } = JSON.parse(c.init.body);
            assert.equal(type, c.path === ENTRY_FILE ? 'http' : 'file', c.path);
        }
    } finally {
        fs.rmSync(target, { recursive: true, force: true });
    }
});

test('the token travels in the authorization header and in no address or body', async () => {
    const platform = fakePlatform();
    const target = tempTarget();
    try {
        await push({ token: TOKEN, target, fetchImpl: platform.fetchImpl });

        for (const c of platform.calls) {
            assert.equal(c.init.headers.authorization, `Bearer ${TOKEN}`);
            assert.doesNotMatch(c.pathname, /EXAMPLE_VALTOWN_TOKEN/);
            assert.doesNotMatch(String(c.init.body || ''), /EXAMPLE_VALTOWN_TOKEN/);
        }
    } finally {
        fs.rmSync(target, { recursive: true, force: true });
    }
});

/* ### Refusals ### */

test('a refused token is a push error that says what the token needs', async () => {
    const platform = fakePlatform();
    const target = tempTarget();
    try {
        await assert.rejects(
            () => push({ token: 'WRONG', target, fetchImpl: platform.fetchImpl }),
            (error) => error instanceof PushError && /read and write on vals/.test(error.message)
        );
    } finally {
        fs.rmSync(target, { recursive: true, force: true });
    }
});

test('a file past the platform limit is refused before it is sent', async () => {
    const platform = fakePlatform({ existingVal: true });

    await assert.rejects(
        () => putFile(platform.fetchImpl, TOKEN, VAL_ID, 'big.js', 'x'.repeat(80_001)),
        (error) => error instanceof PushError && /80000 per file/.test(error.message)
    );
    assert.equal(platform.calls.length, 0);
});

test('a platform that cannot be reached is a push error, not a stack trace', async () => {
    const target = tempTarget();
    try {
        await assert.rejects(
            () => push({ token: TOKEN, target, fetchImpl: async () => { throw new TypeError('fetch failed'); } }),
            (error) => error instanceof PushError && /could not reach/.test(error.message)
        );
    } finally {
        fs.rmSync(target, { recursive: true, force: true });
    }
});
