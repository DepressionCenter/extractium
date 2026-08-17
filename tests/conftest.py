"""
Summary: Shared pytest fixtures for extractium's characterization test
suite: a safe (no-network) import of the vendored reference module, fake
HTTP session/response test doubles, a deterministic embed_chunks stand-in,
and cache-directory isolation.

This file is part of Extractium™
tests/conftest.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Notes: See README file for documentation and full license information.
"""

# Copyright © 2026 The Regents of the University of Michigan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>.

__author__ = "Gabriel Mongefranco, University of Michigan."
__copyright__ = "Copyright (C) 2026 The Regents of the University of Michigan"
__license__ = "GPLv3 or later"
__date__ = "2026-08-17"

import hashlib
import importlib
import pathlib
from unittest import mock

import numpy as np
import pytest
import requests
from requests.structures import CaseInsensitiveDict


@pytest.fixture(autouse=True, scope="session")
def _no_pip_installs_during_tests():
    """
    The vendored reference module (tests/reference/build_kb_index_reference.py)
    calls _ensure("typing_extensions", upgrade=True) at import time, which
    unconditionally shells out to `pip install --upgrade` regardless of
    whether the package is already installed (upgrade=True skips the
    "already importable" short-circuit entirely). Patching
    subprocess.check_call for the whole test session keeps that import --
    and any other accidental subprocess call -- from ever touching the
    network, so this suite runs offline in CI.
    """
    with mock.patch("subprocess.check_call"):
        yield


@pytest.fixture(scope="session")
def reference():
    """
    Imports the frozen reference script once per session, with the
    session-wide subprocess patch above already active. Test modules must
    request this fixture rather than importing
    tests.reference.build_kb_index_reference directly at module level, so
    the import can never happen before the patch is in place.
    """
    return importlib.import_module("tests.reference.build_kb_index_reference")


class FakeResponse:
    """
    Minimal stand-in for requests.Response, covering only what
    fetch()/_store_fetched_page() read: status_code, headers, text, and
    raise_for_status().
    """

    def __init__(self, status_code=200, headers=None, text=""):
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(headers or {})
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    """
    Stand-in for requests.Session, scripted per URL. `responses` maps a URL
    to either one FakeResponse (returned on every call to that URL) or a
    list of FakeResponse objects (popped in call order, letting a test
    script e.g. a 200-then-304 sequence against the same URL). Every call is
    recorded in .calls so tests can assert exactly which headers fetch()
    sent -- in particular, that If-None-Match/If-Modified-Since were sent
    verbatim from the stored cache entry.
    """

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": dict(headers or {}), "timeout": timeout})
        entry = self.responses[url]
        if isinstance(entry, list):
            return entry.pop(0)
        return entry


@pytest.fixture
def fake_session_factory():
    """Returns the FakeSession class so tests can build one per-scenario."""
    return FakeSession


@pytest.fixture
def fake_embed_chunks(reference):
    """
    Deterministic stand-in for the real embed_chunks (which loads a live
    SentenceTransformer -- never run in tests). Hashes each chunk's body
    text (`x`) to seed a normal vector, then L2-normalizes it, so identical
    body text always yields the identical unit vector (cosine similarity
    1.0), with no network access or model weights required. Keyed on `x`
    alone (not the `t` heading prefix the real embedder also folds in):
    two chunks with the same body text under different section headings
    are exactly the boilerplate-collapse scenario drop_near_duplicates
    exists for, and a real semantic embedding would still rate them near
    -identical despite a differing heading -- this fake reproduces that
    outcome deterministically instead of requiring a real model.
    """

    def _embed(chunks):
        dims = reference.DIMS
        vecs = np.zeros((len(chunks), dims), dtype=np.float32)
        for i, c in enumerate(chunks):
            key = c["x"]
            seed = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            v = rng.normal(size=dims).astype(np.float32)
            vecs[i] = v / np.linalg.norm(v)
        return vecs.astype(np.float32)

    return _embed


@pytest.fixture
def isolated_cache(reference, tmp_path, monkeypatch):
    """
    Redirects the reference module's cache-path constants to a per-test
    tmp_path, so cache tests never write into the real repository tree.
    Returns the tmp cache directory path.
    """
    cache_dir = tmp_path / ".kb_cache"
    monkeypatch.setattr(reference, "CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(reference, "CACHE_META_PATH", str(cache_dir / "meta.json"))
    monkeypatch.setattr(reference, "CACHE_PAGES_DIR", str(cache_dir / "pages"))
    return cache_dir


@pytest.fixture
def patch_crawl_session(reference, monkeypatch):
    """
    crawl() does not accept a session parameter -- it always constructs its
    own `session = requests.Session()` internally. This fixture returns a
    function that redirects that construction to return a given FakeSession
    instead, so crawl() can be exercised end-to-end without ever touching a
    real network. reference.requests is the same module object as the
    global `requests` package (crawl()'s `import requests` binds it), so
    patching reference.requests.Session patches it there too -- contained
    to this test by monkeypatch's automatic teardown.
    """

    def _patch(fake_session):
        monkeypatch.setattr(reference.requests, "Session", lambda: fake_session)

    return _patch


@pytest.fixture
def fixtures_dir():
    """Path to tests/fixtures/, for tests that read synthetic HTML/MD/TXT."""
    return pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def golden_dir():
    """Path to tests/golden/, for tests that read committed expected-output snapshots."""
    return pathlib.Path(__file__).parent / "golden"


@pytest.fixture
def isolated_core_cache(tmp_path, monkeypatch):
    """
    Redirects extractium.core.cache's cache-path constants to a per-test
    tmp_path, so tests exercising the real (non-reference) cache/fetch
    modules never write into the real repository tree. Mirrors
    isolated_cache, but targets the real extractium.core.cache module
    object -- extractium.core.fetch reaches these constants via a
    qualified `cache.<NAME>` attribute lookup, so patching them here is
    visible to fetch's functions too. Returns the tmp cache directory path.
    """
    from extractium.core import cache

    cache_dir = tmp_path / ".kb_cache"
    monkeypatch.setattr(cache, "CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(cache, "CACHE_META_PATH", str(cache_dir / "meta.json"))
    monkeypatch.setattr(cache, "CACHE_PAGES_DIR", str(cache_dir / "pages"))
    return cache_dir


@pytest.fixture
def fake_embed_chunks_core():
    """
    Deterministic stand-in for extractium.core.embed.embed_chunks (which
    loads a live SentenceTransformer -- never run in tests). Identical
    construction to fake_embed_chunks, but sized off
    extractium.core.embed.DIMS instead of the reference module's DIMS --
    the two are equal (384), so golden snapshots pinned against one apply
    to the other unchanged.
    """
    from extractium.core.embed import DIMS

    def _embed(chunks):
        dims = DIMS
        vecs = np.zeros((len(chunks), dims), dtype=np.float32)
        for i, c in enumerate(chunks):
            key = c["x"]
            seed = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            v = rng.normal(size=dims).astype(np.float32)
            vecs[i] = v / np.linalg.norm(v)
        return vecs.astype(np.float32)

    return _embed
