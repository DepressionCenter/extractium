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
Last Modified: 2026-09-28
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
__date__ = "2026-09-17"

import functools
import json
from collections import Counter

import numpy as np
import pytest

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
    """
    A window's tokens are its section heading and its text. The page
    title is counted once per page, on the page's first window.
    """
    children = [
        {"t": "Sleep Guide -- Hygiene", "x": "sleep hygiene tips for better sleep", "u": "https://example.org/a"},
        {"t": "Sleep Guide -- Hygiene", "x": "keep the bedroom dark and cool", "u": "https://example.org/a"},
        {"t": "Sleep Guide -- Screens", "x": "reduce screen time before bed", "u": "https://example.org/a"},
        {"t": "Screens", "x": "another page about screens", "u": "https://example.org/b"},
    ]
    indexed = [
        "Sleep Guide Hygiene sleep hygiene tips for better sleep",
        "Hygiene keep the bedroom dark and cool",
        "Screens reduce screen time before bed",
        "Screens another page about screens",
    ]
    result = bm25.build_bm25_index(children)

    assert result["k"] == bm25.BM25_K1
    assert result["b"] == bm25.BM25_B
    assert result["d"] == bm25.BM25_D

    expected_doc_len = []
    expected_df = {}
    expected_postings = {}
    for i, text in enumerate(indexed):
        tokens = bm25.tokenize(text)
        expected_doc_len.append(len(tokens))
        for term, tf in Counter(tokens).items():
            expected_df[term] = expected_df.get(term, 0) + 1
            expected_postings.setdefault(term, []).append([i, tf])

    assert result["docLen"] == expected_doc_len
    assert result["df"] == expected_df
    assert result["postings"] == expected_postings
    assert result["avgDocLen"] == sum(expected_doc_len) / len(expected_doc_len)
    # "guide" is a title word: on the page's first window and nowhere else.
    assert result["postings"]["guide"] == [[0, 1]]


def test_the_page_title_is_indexed_once_per_page_and_the_section_heading_on_every_window():
    children = [
        {"t": "Alpha Page", "x": "text before the first heading", "u": "https://example.org/alpha"},
        {"t": "Alpha Page -- Details", "x": "more words here", "u": "https://example.org/alpha"},
        {"t": "Alpha Page", "x": "a second page with the same title", "u": "https://example.org/beta"},
    ]

    result = bm25.build_bm25_index(children)

    assert result["postings"]["alpha"] == [[0, 1], [2, 1]]
    assert result["postings"]["details"] == [[1, 1]]
    assert result["docLen"] == [7, 4, 8]


def test_a_window_without_an_address_counts_as_its_own_page():
    children = [{"t": "Title -- Part", "x": "one"}, {"t": "Title -- Part", "x": "two"}]

    result = bm25.build_bm25_index(children)

    assert result["postings"]["title"] == [[0, 1], [1, 1]]
    assert result["postings"]["part"] == [[0, 1], [1, 1]]


# ---------------------------------------------------------------------------
# quantize_int8
# ---------------------------------------------------------------------------

def test_embed_chunks_reports_progress_in_slices_and_returns_one_array(monkeypatch):
    """A hundred thousand windows on a CPU take an hour; one line for all of it reads as a hang."""
    class FakeModel:
        def __init__(self):
            self.batches = []

        def encode(self, texts, normalize_embeddings=True, batch_size=None, show_progress_bar=False):
            self.batches.append(len(texts))
            return np.ones((len(texts), embed.DIMS), dtype=np.float32)

    model = FakeModel()
    monkeypatch.setattr(embed, "_load_model", functools.lru_cache(maxsize=1)(lambda: model))
    monkeypatch.setattr(embed, "PROGRESS_EVERY", 3)
    lines = []

    vecs = embed.embed_chunks([{"t": "Page", "x": f"window {n}"} for n in range(7)], progress=lines.append)

    assert vecs.shape == (7, embed.DIMS) and vecs.dtype == np.float32
    assert model.batches == [3, 3, 1]
    assert "Embedding 7 chunk(s)..." in lines
    assert [line for line in lines if line.startswith("  embedded")] == [
        "  embedded 3 of 7 chunk(s); about a minute left",
        "  embedded 6 of 7 chunk(s); about a minute left",
    ]
    assert embed.embed_chunks([], progress=lines.append).shape == (0, embed.DIMS)


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
        {"t": "A", "x": "unique content one", "u": "https://example.org/a", "pid": 0},
        {"t": "B", "x": "shared boilerplate text", "u": "https://example.org/a", "pid": 1},
        {"t": "C", "x": "unique content two", "u": "https://example.org/b", "pid": 2},
        {"t": "D", "x": "shared boilerplate text", "u": "https://example.org/b", "pid": 3},
    ]
    vecs = fake_embed_chunks_core(children)

    kept_chunks, kept_vecs, dropped = dedup.drop_near_duplicates(children, vecs)

    assert dropped == 1
    assert [c["pid"] for c in kept_chunks] == [0, 1, 2]
    assert kept_vecs.shape[0] == 3


def test_drop_near_duplicates_leaves_a_pages_own_repetition_alone(fake_embed_chunks_core):
    """
    Collapsing across pages removes boilerplate; collapsing within one page
    removes an article's own passages, which is content loss rather than
    tidying (docs/extractium-spec.md section 3.2).
    """
    children = [
        {"t": "A", "x": "repeated passage text", "u": "https://example.org/a", "pid": 0},
        {"t": "A", "x": "repeated passage text", "u": "https://example.org/a", "pid": 1},
    ]
    vecs = fake_embed_chunks_core(children)

    kept_chunks, _, dropped = dedup.drop_near_duplicates(children, vecs)

    assert dropped == 0
    assert len(kept_chunks) == 2


def test_drop_near_duplicates_collapses_boilerplate_across_many_pages(fake_embed_chunks_core):
    children = [
        {"t": f"P{i}", "x": "shared footer disclaimer text", "u": f"https://example.org/{i}", "pid": i}
        for i in range(5)
    ]
    vecs = fake_embed_chunks_core(children)

    kept_chunks, _, dropped = dedup.drop_near_duplicates(children, vecs)

    assert dropped == 4
    assert [c["u"] for c in kept_chunks] == ["https://example.org/0"]


# ---------------------------------------------------------------------------
# downweight_repeated_sections
# ---------------------------------------------------------------------------

BIO = "Dr. Example writes about sleep, wearables, and study technology for the center."


def section(url, text, weight=1.0):
    return {"t": f"{url[-1].upper()} page -- About the Author", "x": text, "u": url, "weight": weight}


def test_a_section_repeated_on_three_pages_takes_the_repeated_weight():
    parents = [section(f"https://example.org/{n}", BIO) for n in "abc"]
    parents.append(section("https://example.org/d", "A section with words of its own."))

    changed, texts = dedup.downweight_repeated_sections(parents)

    assert (changed, texts) == (3, 1)
    assert [p["weight"] for p in parents] == [dedup.REPEATED_SECTION_WEIGHT] * 3 + [1.0]


def test_a_section_on_two_pages_is_not_repeated_enough():
    parents = [section(f"https://example.org/{n}", BIO) for n in "ab"]

    assert dedup.downweight_repeated_sections(parents) == (0, 0)
    assert all(p["weight"] == 1.0 for p in parents)


def test_a_pages_own_repetitions_count_as_one_page():
    parents = [section("https://example.org/a", BIO) for _ in range(3)]
    parents.append(section("https://example.org/a#part-2", BIO))

    assert dedup.downweight_repeated_sections(parents) == (0, 0)


def test_case_punctuation_and_spacing_do_not_tell_two_copies_apart():
    parents = [
        section("https://example.org/a", BIO),
        section("https://example.org/b", BIO.upper().replace(",", " ;")),
        section("https://example.org/c", "  " + BIO.replace(" ", "\n\n") + "\n"),
    ]

    assert dedup.downweight_repeated_sections(parents) == (3, 1)


def test_the_repeated_weight_is_assigned_once_and_never_raised():
    parents = [section(f"https://example.org/{n}", BIO) for n in "abc"]
    parents[0]["weight"] = 0.25

    assert dedup.downweight_repeated_sections(parents) == (2, 1)
    assert dedup.downweight_repeated_sections(parents) == (0, 0)
    assert [p["weight"] for p in parents] == [0.25, 0.5, 0.5]


def test_downweight_repeated_sections_empty_input():
    assert dedup.downweight_repeated_sections([]) == (0, 0)


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


# ---------------------------------------------------------------------------
# What an unrelated question scores
# ---------------------------------------------------------------------------

def _unit(rows):
    rows = np.asarray(rows, dtype=np.float32)
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def test_probe_chunks_are_queries_so_each_carries_the_query_prefix():
    chunks = calibration.probe_chunks("PREFIX: ")

    assert len(chunks) == len(calibration.UNRELATED_PROBES) == 64
    assert len(set(calibration.UNRELATED_PROBES)) == 64
    assert all(chunk["t"] == "" and chunk["x"].startswith("PREFIX: ") for chunk in chunks)
    assert chunks[0]["x"] == "PREFIX: " + calibration.UNRELATED_PROBES[0]


def test_unrelated_stats_are_the_median_and_scaled_spread_of_each_probes_best_score():
    windows = _unit([[1, 0], [0, 1]])
    # Best scores against the two windows: 1.0, 0.8, 0.8, and 0.7071.
    probes = _unit([[1, 0], [0.8, 0.6], [0.6, 0.8], [1, 1]])

    stats = calibration.unrelated_stats(windows, probes)

    assert stats["unrelatedProbes"] == 4
    assert stats["unrelatedMedian"] == pytest.approx(0.8)
    # Deviations from the median are 0.2, 0, 0, and 0.0929; their median is 0.04645.
    assert stats["unrelatedSpread"] == pytest.approx(0.04645 * calibration.MAD_TO_SIGMA, abs=1e-4)


def test_a_few_on_topic_probes_barely_move_the_figures():
    rng = np.random.default_rng(3)
    windows = _unit(rng.normal(size=(200, 16)))
    probes = _unit(rng.normal(size=(60, 16)))
    clean = calibration.unrelated_stats(windows, probes)

    # Six probes that match a window exactly, as a recipe question would on a cooking site.
    mixed = calibration.unrelated_stats(windows, np.vstack([probes, windows[:6]]))

    assert mixed["unrelatedMedian"] - clean["unrelatedMedian"] < 0.02
    assert mixed["unrelatedSpread"] - clean["unrelatedSpread"] < 0.02


def test_no_probes_or_no_windows_leave_the_figures_out():
    windows = _unit([[1, 0], [0, 1], [1, 1]])

    assert calibration.unrelated_stats(windows, None) == {}
    assert calibration.unrelated_stats(np.zeros((0, 2), dtype=np.float32), _unit([[1, 0]])) == {}
    assert set(calibration.compute_calibration_stats(windows)) == {"mean", "std", "sampleSize"}


def test_calibration_with_probes_carries_both_sets_of_figures():
    windows = _unit([[1, 0], [0, 1], [1, 1]])

    stats = calibration.compute_calibration_stats(windows, probe_vecs=_unit([[1, 0], [0, 1]]))

    assert stats["sampleSize"] == 3
    assert stats["unrelatedProbes"] == 2 and stats["unrelatedMedian"] == pytest.approx(1.0)
