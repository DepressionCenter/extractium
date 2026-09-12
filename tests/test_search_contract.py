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

from extractium.search import load_container
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
def test_javascript_client_passes_its_own_suite_including_the_contract():
    result = subprocess.run(
        ["node", "--test", "clients/js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=NODE_TEST_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0, result.stdout + result.stderr
