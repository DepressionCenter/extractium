"""
Summary: The cross-language contract. Rebuilds the committed compendium
in tests/golden/ and checks it has not drifted, checks that the Python
client reproduces the ranking recorded beside it, and runs the Node test
suite for the JavaScript client so both clients are held to the same
ranking for the same file and the same query vector.

This file is part of Extractium™
tests/test_search_contract.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
Last Modified: 2026-09-08
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
__date__ = "2026-09-08"

import json
import pathlib
import shutil
import subprocess

import numpy as np
import pytest

from extractium.search import load_container, vector_candidates
from tests.contract_fixture import (
    CONTAINER_FILE,
    QUERY_FILE,
    build_contract_compendium,
    write_contract_container,
    write_contract_files,
)

# The repository root, from which the Node client and its tests are run.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# How long the Node test run may take before it is treated as a failure.
NODE_TEST_TIMEOUT_SECONDS = 300


@pytest.fixture
def expectations(golden_dir):
    """The committed query, query vector, and rankings."""
    return json.loads((golden_dir / QUERY_FILE).read_text(encoding="utf-8"))


@pytest.fixture
def golden_index(golden_dir):
    """The committed contract container, loaded by the Python client."""
    return load_container(golden_dir / CONTAINER_FILE)


# ---------------------------------------------------------------------------
# The committed files
# ---------------------------------------------------------------------------

def test_the_committed_container_still_matches_a_fresh_build(
    fixtures_dir, golden_dir, fake_embed_chunks_core, tmp_path
):
    compendium = build_contract_compendium(fixtures_dir, fake_embed_chunks_core)

    rebuilt = write_contract_container(compendium, tmp_path)

    assert rebuilt.read_bytes() == (golden_dir / CONTAINER_FILE).read_bytes()


def test_the_committed_rankings_still_match_a_fresh_build(
    fixtures_dir, golden_dir, fake_embed_chunks_core, tmp_path, expectations
):
    _, query_path = write_contract_files(fixtures_dir, fake_embed_chunks_core, tmp_path)

    assert json.loads(query_path.read_text(encoding="utf-8")) == expectations


# ---------------------------------------------------------------------------
# The Python client against the contract
# ---------------------------------------------------------------------------

def test_python_client_reproduces_the_recorded_candidate_pool(golden_index, expectations):
    pool = golden_index.candidates(expectations["query"], expectations["queryVector"])

    recorded = expectations["candidateChildren"]
    assert [entry["i"] for entry in pool[:len(recorded)]] == recorded


def test_python_client_reproduces_the_recorded_closest_sections(golden_index, expectations):
    hits = golden_index.search(
        expectations["query"],
        lambda text: expectations["queryVector"],
        k=expectations["k"],
        no_threshold=True,
    )

    assert [hit.parent["id"] for hit in hits] == expectations["closestParentIds"]


def test_python_client_reproduces_the_recorded_relevant_sections(golden_index, expectations):
    hits = golden_index.search(
        expectations["query"], lambda text: expectations["queryVector"], k=expectations["k"]
    )

    assert [hit.parent["id"] for hit in hits] == expectations["relevantParentIds"]


def test_the_contract_query_vector_is_one_the_file_could_have_produced(golden_index, expectations):
    vector = np.asarray(expectations["queryVector"], dtype=np.float32)

    assert vector.shape == (golden_index.embedding["dims"],)
    assert float(np.linalg.norm(vector)) == pytest.approx(1.0, abs=1e-5)


def test_the_contract_corpus_spans_several_sections_and_pages(golden_index, expectations):
    ids = expectations["closestParentIds"]

    assert len(set(ids)) == len(ids)  # the per-section cap left no section twice
    assert len({parent["u"] for parent in golden_index.parents}) > 1


# ---------------------------------------------------------------------------
# The JavaScript client against the same contract
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed on this machine")
def test_both_clients_rank_near_copies_of_one_page_the_same_way(tmp_path):
    """
    The two clients add up the same 384 products differently, so their
    scores for one window sit a hair apart. Windows closer together than
    that hair, which is what near-copies of a page produce, once came
    back in a different order from each client. Both round every score to
    the same precision now, so both must return one order and one set of
    scores.
    """
    rng = np.random.default_rng(3)
    dims = 384
    distinct = rng.standard_normal((30, dims)).astype(np.float32)
    distinct /= np.linalg.norm(distinct, axis=1, keepdims=True)

    rows = []
    for row in distinct:
        rows.append(row)
        for _ in range(4):
            twin = row.copy()
            twin[rng.integers(0, dims, size=3)] += rng.standard_normal(3).astype(np.float32) * 3e-7
            rows.append((twin / np.linalg.norm(twin)).astype(np.float32))
    vectors = np.asarray(rows, dtype=np.float32)
    query = distinct[0]

    handoff = tmp_path / "corpus.json"
    handoff.write_text(json.dumps({
        "vectors": vectors.reshape(-1).tolist(),
        "dims": dims,
        "query": query.tolist(),
    }), encoding="utf-8")
    result = subprocess.run(
        ["node", "tests/reference/rank_vectors.mjs", str(handoff)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=NODE_TEST_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    from_python = [[entry["i"], entry["s"]] for entry in vector_candidates(query, vectors, len(rows))]
    assert from_python == json.loads(result.stdout)


def test_javascript_client_passes_its_own_suite_including_the_contract():
    result = subprocess.run(
        ["node", "--test", "clients/js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=NODE_TEST_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0, result.stdout + result.stderr
