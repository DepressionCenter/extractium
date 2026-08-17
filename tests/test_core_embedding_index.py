"""
Summary: Tests pinning the ported embedding/index-assembly functions:
extractium.core.bm25.tokenize/build_bm25_index, extractium.core.embed.
quantize_int8, extractium.core.dedup.drop_near_duplicates/
remap_parents_after_dedup, and extractium.core.calibration.
compute_calibration_stats (seeded RNG -- pinned against the same committed
golden snapshot the reference-script version uses). Mirrors the
non-build_index parts of tests/test_embedding_index.py (which pins the
same behavior on the frozen reference script) against the real, ported
implementation, proving the port is behavior-identical. build_index()
itself is not ported in this step (it will live in a future adapter, not
extractium.core) and embed_chunks() itself is never invoked with the real
SentenceTransformer -- this file uses the deterministic
fake_embed_chunks_core fixture from conftest.py instead.

This file is part of Extractium™
tests/test_core_embedding_index.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-08-17
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

import json
from collections import Counter

import numpy as np

from extractium.core import bm25, calibration, dedup, embed


# ---------------------------------------------------------------------------
# tokenize
# ---------------------------------------------------------------------------

def test_tokenize_lowercases_and_drops_short_or_non_alnum_runs():
    tokens = bm25.tokenize("Hello World! foo_bar 123 ab")
    assert tokens == ["hello", "world", "foo", "bar", "123"]


# ---------------------------------------------------------------------------
# build_bm25_index
# ---------------------------------------------------------------------------

def test_build_bm25_index_matches_manual_aggregation_over_tokenize():
    children = [
        {"t": "Sleep", "x": "sleep hygiene tips for better sleep"},
        {"t": "Screen", "x": "reduce screen time before bed"},
    ]
    result = bm25.build_bm25_index(children)

    assert result["k"] == bm25.BM25_K1
    assert result["b"] == bm25.BM25_B
    assert result["d"] == bm25.BM25_D

    expected_doc_len = []
    expected_df = {}
    expected_postings = {}
    for i, c in enumerate(children):
        tokens = bm25.tokenize((c.get("t") or "") + " " + c["x"])
        expected_doc_len.append(len(tokens))
        for term, tf in Counter(tokens).items():
            expected_df[term] = expected_df.get(term, 0) + 1
            expected_postings.setdefault(term, []).append([i, tf])

    assert result["docLen"] == expected_doc_len
    assert result["df"] == expected_df
    assert result["postings"] == expected_postings
    assert result["avgDocLen"] == sum(expected_doc_len) / len(expected_doc_len)


# ---------------------------------------------------------------------------
# quantize_int8
# ---------------------------------------------------------------------------

def test_quantize_int8_rounds_scales_and_clips():
    vecs = np.array([[0.5, -0.5, 1.5, -1.5, 0.004]], dtype=np.float32)
    result = embed.quantize_int8(vecs)
    scale = embed.INT8_SCALE

    assert result.dtype == np.int8
    expected = np.clip(np.round(vecs * scale), -scale, scale).astype(np.int8)
    assert (result == expected).all()
    assert int(result[0, 2]) == scale   # 1.5 * 127 clipped to +127
    assert int(result[0, 3]) == -scale  # -1.5 * 127 clipped to -127


# ---------------------------------------------------------------------------
# drop_near_duplicates / remap_parents_after_dedup
# ---------------------------------------------------------------------------

def test_drop_near_duplicates_collapses_identical_text_keeps_first_occurrence(
    fake_embed_chunks_core
):
    children = [
        {"t": "A", "x": "unique content one", "pid": 0},
        {"t": "B", "x": "shared boilerplate text", "pid": 1},
        {"t": "C", "x": "unique content two", "pid": 2},
        {"t": "D", "x": "shared boilerplate text", "pid": 3},  # duplicate of index 1
    ]
    vecs = fake_embed_chunks_core(children)

    kept_chunks, kept_vecs, dropped = dedup.drop_near_duplicates(children, vecs)

    assert dropped == 1
    assert [c["pid"] for c in kept_chunks] == [0, 1, 2]
    assert kept_vecs.shape[0] == 3


def test_drop_near_duplicates_empty_input():
    kept_chunks, kept_vecs, dropped = dedup.drop_near_duplicates([], np.zeros((0, embed.DIMS)))
    assert kept_chunks == []
    assert dropped == 0


def test_remap_parents_after_dedup_compacts_orphaned_parents():
    parents = [{"t": "P0"}, {"t": "P1"}, {"t": "P2"}]
    # No surviving child references parent 1 (e.g. it was entirely
    # boilerplate and got dropped by drop_near_duplicates) -> it's orphaned.
    children = [{"pid": 0, "x": "a"}, {"pid": 2, "x": "b"}]

    new_parents, new_children = dedup.remap_parents_after_dedup(parents, children)

    assert new_parents == [{"t": "P0"}, {"t": "P2"}]
    assert [c["pid"] for c in new_children] == [0, 1]


# ---------------------------------------------------------------------------
# compute_calibration_stats -- seeded RNG, pinned against a golden snapshot
# ---------------------------------------------------------------------------

def test_compute_calibration_stats_matches_golden_snapshot(fake_embed_chunks_core, golden_dir):
    texts = [f"synthetic calibration fixture sentence number {i}" for i in range(8)]
    chunks = [{"x": t} for t in texts]
    vecs = fake_embed_chunks_core(chunks)

    stats = calibration.compute_calibration_stats(vecs)

    expected = json.loads((golden_dir / "calibration_stats.json").read_text(encoding="utf-8"))
    assert stats["sampleSize"] == expected["sampleSize"]
    assert stats["mean"] == pytest_approx(expected["mean"])
    assert stats["std"] == pytest_approx(expected["std"])


def test_compute_calibration_stats_fewer_than_two_vecs_returns_zeros():
    stats = calibration.compute_calibration_stats(np.zeros((1, embed.DIMS), dtype=np.float32))
    assert stats == {"mean": 0.0, "std": 0.0, "sampleSize": 0}


def pytest_approx(value, tol=1e-12):
    """Small local helper so this module doesn't need a pytest import just
    for approx() -- exact-value characterization still allows for the last
    bit or two of float round-trip noise through JSON."""
    class _Approx:
        def __eq__(self, other):
            return abs(other - value) <= tol
    return _Approx()
