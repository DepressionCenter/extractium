"""
Summary: Characterization tests pinning the current behavior of
build-kb-index.py's embedding/index-assembly functions: drop_near_duplicates,
remap_parents_after_dedup, quantize_int8, tokenize, build_bm25_index,
compute_calibration_stats (seeded RNG -- pinned against a committed golden
snapshot), and build_index's binary container framing (4-byte LE header
length + JSON header + payload bytes -- also pinned against a golden
snapshot). embed_chunks itself is never invoked with the real
SentenceTransformer; every test here uses the deterministic
fake_embed_chunks fixture from conftest.py instead.

This file is part of Extractium™
tests/test_embedding_index.py

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

import json
import struct
from collections import Counter

import numpy as np


# ---------------------------------------------------------------------------
# tokenize
# ---------------------------------------------------------------------------

def test_tokenize_lowercases_and_drops_short_or_non_alnum_runs(reference):
    tokens = reference.tokenize("Hello World! foo_bar 123 ab")
    assert tokens == ["hello", "world", "foo", "bar", "123"]


# ---------------------------------------------------------------------------
# build_bm25_index
# ---------------------------------------------------------------------------

def test_build_bm25_index_matches_manual_aggregation_over_tokenize(reference):
    children = [
        {"t": "Sleep", "x": "sleep hygiene tips for better sleep"},
        {"t": "Screen", "x": "reduce screen time before bed"},
    ]
    result = reference.build_bm25_index(children)

    assert result["k"] == reference.BM25_K1
    assert result["b"] == reference.BM25_B
    assert result["d"] == reference.BM25_D

    expected_doc_len = []
    expected_df = {}
    expected_postings = {}
    for i, c in enumerate(children):
        tokens = reference.tokenize((c.get("t") or "") + " " + c["x"])
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

def test_quantize_int8_rounds_scales_and_clips(reference):
    vecs = np.array([[0.5, -0.5, 1.5, -1.5, 0.004]], dtype=np.float32)
    result = reference.quantize_int8(vecs)
    scale = reference.INT8_SCALE

    assert result.dtype == np.int8
    expected = np.clip(np.round(vecs * scale), -scale, scale).astype(np.int8)
    assert (result == expected).all()
    assert int(result[0, 2]) == scale   # 1.5 * 127 clipped to +127
    assert int(result[0, 3]) == -scale  # -1.5 * 127 clipped to -127


# ---------------------------------------------------------------------------
# drop_near_duplicates / remap_parents_after_dedup
# ---------------------------------------------------------------------------

def test_drop_near_duplicates_collapses_identical_text_keeps_first_occurrence(
    reference, fake_embed_chunks
):
    children = [
        {"t": "A", "x": "unique content one", "pid": 0},
        {"t": "B", "x": "shared boilerplate text", "pid": 1},
        {"t": "C", "x": "unique content two", "pid": 2},
        {"t": "D", "x": "shared boilerplate text", "pid": 3},  # duplicate of index 1
    ]
    vecs = fake_embed_chunks(children)

    kept_chunks, kept_vecs, dropped = reference.drop_near_duplicates(children, vecs)

    assert dropped == 1
    assert [c["pid"] for c in kept_chunks] == [0, 1, 2]
    assert kept_vecs.shape[0] == 3


def test_drop_near_duplicates_empty_input(reference):
    kept_chunks, kept_vecs, dropped = reference.drop_near_duplicates([], np.zeros((0, reference.DIMS)))
    assert kept_chunks == []
    assert dropped == 0


def test_remap_parents_after_dedup_compacts_orphaned_parents(reference):
    parents = [{"t": "P0"}, {"t": "P1"}, {"t": "P2"}]
    # No surviving child references parent 1 (e.g. it was entirely
    # boilerplate and got dropped by drop_near_duplicates) -> it's orphaned.
    children = [{"pid": 0, "x": "a"}, {"pid": 2, "x": "b"}]

    new_parents, new_children = reference.remap_parents_after_dedup(parents, children)

    assert new_parents == [{"t": "P0"}, {"t": "P2"}]
    assert [c["pid"] for c in new_children] == [0, 1]


# ---------------------------------------------------------------------------
# compute_calibration_stats -- seeded RNG, pinned against a golden snapshot
# ---------------------------------------------------------------------------

def test_compute_calibration_stats_matches_golden_snapshot(reference, fake_embed_chunks, golden_dir):
    texts = [f"synthetic calibration fixture sentence number {i}" for i in range(8)]
    chunks = [{"x": t} for t in texts]
    vecs = fake_embed_chunks(chunks)

    stats = reference.compute_calibration_stats(vecs)

    expected = json.loads((golden_dir / "calibration_stats.json").read_text(encoding="utf-8"))
    assert stats["sampleSize"] == expected["sampleSize"]
    assert stats["mean"] == pytest_approx(expected["mean"])
    assert stats["std"] == pytest_approx(expected["std"])


def test_compute_calibration_stats_fewer_than_two_vecs_returns_zeros(reference):
    stats = reference.compute_calibration_stats(np.zeros((1, reference.DIMS), dtype=np.float32))
    assert stats == {"mean": 0.0, "std": 0.0, "sampleSize": 0}


def pytest_approx(value, tol=1e-12):
    """Small local helper so this module doesn't need a pytest import just
    for approx() -- exact-value characterization still allows for the last
    bit or two of float round-trip noise through JSON."""
    class _Approx:
        def __eq__(self, other):
            return abs(other - value) <= tol
    return _Approx()


# ---------------------------------------------------------------------------
# build_index -- binary container framing, pinned against a golden snapshot
# ---------------------------------------------------------------------------

def _synthetic_parents_and_children():
    parents = [
        {"t": "Doc -- Section One", "x": "content one text", "u": "https://example.org/a",
         "host": "example.org", "kind": "page", "weight": 1.0},
        {"t": "Doc -- Section Two", "x": "content two text", "u": "https://example.org/a",
         "host": "example.org", "kind": "page", "weight": 1.0},
    ]
    children = [
        {**parents[0], "pid": 0},
        {**parents[1], "pid": 1},
    ]
    return parents, children


def _read_container(path):
    with open(path, "rb") as f:
        buf = f.read()
    header_len = struct.unpack("<I", buf[:4])[0]
    header = json.loads(buf[4:4 + header_len].decode("utf-8"))
    payload = buf[4 + header_len:]
    return header, payload


def test_build_index_int8_container_matches_golden_header(
    reference, fake_embed_chunks, golden_dir, tmp_path, monkeypatch
):
    monkeypatch.setattr(reference, "embed_chunks", fake_embed_chunks)
    parents, children = _synthetic_parents_and_children()
    out_path = tmp_path / "index.bin"

    reference.build_index(parents, children, "Test Site", str(out_path), float32_vecs=False)

    header, payload = _read_container(out_path)
    built_at = header.pop("builtAt")
    assert built_at.endswith("Z")  # ISO8601 UTC, per build_index's own formatting

    expected = json.loads((golden_dir / "binary_container_header.json").read_text(encoding="utf-8"))
    assert header == expected
    assert len(payload) == len(children) * reference.DIMS * 1  # int8 == 1 byte/component


def test_build_index_float32_variant_has_no_quantization_fields(
    reference, fake_embed_chunks, tmp_path, monkeypatch
):
    monkeypatch.setattr(reference, "embed_chunks", fake_embed_chunks)
    parents, children = _synthetic_parents_and_children()
    out_path = tmp_path / "index_f32.bin"

    reference.build_index(parents, children, "Test Site", str(out_path), float32_vecs=True)

    header, payload = _read_container(out_path)
    assert "vecsQ" not in header
    assert "vecsScale" not in header
    assert len(payload) == len(children) * reference.DIMS * 4  # float32 == 4 bytes/component


def test_build_index_no_children_writes_nothing(reference, tmp_path, capsys):
    out_path = tmp_path / "index.bin"
    reference.build_index([], [], "Empty Site", str(out_path))
    assert not out_path.exists()
    assert "No chunks" in capsys.readouterr().out
