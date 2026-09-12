"""
Summary: Tests for the Python compendium client (extractium.search).
Covers each stage of the search (tokenizing, cosine candidates, BM25
candidates, rank fusion, the relevance cutoff, diversity selection,
resolving a window to its section) and every refusal in the container
format's reader checklist. The cross-language agreement with the
JavaScript client is tested in tests/test_search_contract.py.

This file is part of Extractium™
tests/test_search.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
Last Modified: 2026-09-12
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
import struct

import numpy as np
import pytest

from extractium.search import (
    CANDIDATE_POOL,
    RRF_K,
    SCORE_MIN,
    SOURCE_CAP,
    ContainerError,
    bm25_candidates,
    diversify,
    load_container,
    relevance_cutoff,
    rrf_fuse,
    tokenize,
    vector_candidates,
)


### Test Doubles ###

def parent_record(parent_id, **fields):
    """A section record with the fields the client reads."""
    return {
        "id": parent_id,
        "t": fields.get("t", f"Section {parent_id}"),
        "x": fields.get("x", "Synthetic section text for the client tests."),
        "u": fields.get("u", f"https://example.org/{parent_id}"),
        "host": "example.org",
        "source_type": "web",
        "content_type": "page",
        "categories": [],
        "local": False,
        "weight": fields.get("weight", 1.0),
    }


def sample_header(**overrides):
    """A minimal but complete two-window header."""
    header = {
        "format": "extractium-compendium",
        "v": 4,
        "extractium": "0.1.0",
        "builtAt": "2026-01-02T03:04:05Z",
        "site": "Example Org",
        "sourceCount": 2,
        "embedding": {
            "model": "BAAI/bge-small-en-v1.5",
            "browserModel": "Xenova/bge-small-en-v1.5",
            "dims": 2,
            "normalized": True,
            "queryPrefix": "Represent this sentence for searching relevant passages: ",
            "passagePrefix": "",
            "dtype": "float32",
        },
        "offsetUnit": "utf16",
        "parents": [
            parent_record("aaaaaaaaaaaaaaaa", x="Alpha section text."),
            parent_record("bbbbbbbbbbbbbbbb"),
        ],
        "children": {"pid": [0, 1], "start": [0, 0], "end": [5, 5]},
        "bm25": None,
        "calibration": {"mean": 0, "std": 0, "sampleSize": 0},
    }
    header.update(overrides)
    return header


def container_bytes(header, values, dtype="float32", header_length=None):
    """Serializes a header and its vectors the way the container adapter does."""
    encoded = json.dumps(header).encode("utf-8")
    vectors = np.asarray(values, dtype="<i1" if dtype == "int8" else "<f4").tobytes()
    length = len(encoded) if header_length is None else header_length
    return struct.pack("<I", length) + encoded + vectors


KEYWORD_STATS = {
    "k": 1.2,
    "b": 0.75,
    "d": 0.5,
    "avgDocLen": 10,
    "docLen": [10, 10, 10],
    "df": {"crawler": 1, "index": 3},
    "postings": {"crawler": [[2, 3]], "index": [[0, 1], [1, 1], [2, 1]]},
}


# ---------------------------------------------------------------------------
# Tokenizing
# ---------------------------------------------------------------------------

def test_tokenize_keeps_runs_of_three_or_more_letters_or_digits_lowercased():
    assert tokenize("Weekly BUILD of compendium v3 a an") == ["weekly", "build", "compendium"]


def test_tokenize_handles_empty_and_missing_text():
    assert tokenize("") == []
    assert tokenize(None) == []


# ---------------------------------------------------------------------------
# Vector candidates
# ---------------------------------------------------------------------------

def test_vector_candidates_ranks_by_cosine_similarity_best_first():
    vectors = np.array([[1, 0], [0, 1], [0.7071, 0.7071]], dtype=np.float32)

    ranked = vector_candidates([1, 0], vectors)

    assert [entry["i"] for entry in ranked] == [0, 2, 1]
    assert ranked[0]["s"] == pytest.approx(1.0, abs=1e-6)


def test_vector_candidates_normalizes_a_query_vector_it_is_handed_unnormalized():
    vectors = np.array([[1, 0]], dtype=np.float32)

    (hit,) = vector_candidates([10, 0], vectors)

    assert hit["s"] == pytest.approx(1.0, abs=1e-6)


def test_vector_candidates_keeps_at_most_the_pool_size():
    vectors = np.ones((CANDIDATE_POOL + 5, 2), dtype=np.float32)

    assert len(vector_candidates([1, 1], vectors)) == CANDIDATE_POOL


def test_vector_candidates_breaks_score_ties_on_the_child_index():
    vectors = np.array([[1, 0], [1, 0], [1, 0]], dtype=np.float32)

    assert [entry["i"] for entry in vector_candidates([1, 0], vectors)] == [0, 1, 2]


def test_vector_candidates_handles_an_empty_corpus():
    assert vector_candidates([1, 0], np.zeros((0, 2), dtype=np.float32)) == []


# ---------------------------------------------------------------------------
# Keyword candidates
# ---------------------------------------------------------------------------

def test_bm25_candidates_scores_only_the_windows_a_query_term_appears_in():
    ranked = bm25_candidates(["crawler"], KEYWORD_STATS, 3)

    assert [entry["i"] for entry in ranked] == [2]
    assert ranked[0]["s"] > 0


def test_bm25_candidates_gives_a_rare_term_more_weight_than_a_common_one():
    (rare,) = bm25_candidates(["crawler"], KEYWORD_STATS, 3)
    common = bm25_candidates(["index"], KEYWORD_STATS, 3)[0]

    assert rare["s"] > common["s"]


def test_bm25_candidates_returns_nothing_without_statistics_or_terms():
    assert bm25_candidates(["crawler"], None, 3) == []
    assert bm25_candidates([], KEYWORD_STATS, 3) == []


def test_bm25_candidates_ignores_a_term_the_corpus_does_not_have():
    assert bm25_candidates(["nonexistent"], KEYWORD_STATS, 3) == []


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

def test_rrf_fuse_scores_by_rank_alone_not_by_the_incoming_scores():
    vector_list = [{"i": 7, "s": 0.9}, {"i": 8, "s": 0.8}]
    keyword_list = [{"i": 8, "s": 42.0}, {"i": 7, "s": 0.1}]

    fused = rrf_fuse([(vector_list, 0.5), (keyword_list, 0.5)])

    expected = 0.5 * (RRF_K / (RRF_K + 1)) + 0.5 * (RRF_K / (RRF_K + 2))
    assert len(fused) == 2
    assert all(entry["s"] == pytest.approx(expected) for entry in fused)


def test_rrf_fuse_applies_the_per_section_weight_after_fusion():
    items = [{"i": 1, "s": 0.9}, {"i": 2, "s": 0.8}]

    fused = rrf_fuse([(items, 1.0)], lambda child: 5.0 if child == 2 else 1.0)

    assert [entry["i"] for entry in fused] == [2, 1]


# ---------------------------------------------------------------------------
# Relevance cutoff
# ---------------------------------------------------------------------------

def test_relevance_cutoff_never_drops_below_the_absolute_floor():
    assert relevance_cutoff([{"s": 0.1}, {"s": 0.2}, {"s": 0.3}]) == SCORE_MIN


def test_relevance_cutoff_rises_with_the_pool_median():
    assert relevance_cutoff([{"s": 0.8}, {"s": 0.9}, {"s": 0.95}]) == pytest.approx(0.93)


def test_relevance_cutoff_uses_the_calibration_statistics_when_they_are_stricter():
    candidates = [{"s": 0.5}, {"s": 0.5}, {"s": 0.5}]

    cutoff = relevance_cutoff(candidates, {"mean": 0.7, "std": 0.1})

    assert cutoff == pytest.approx(0.8)


def test_relevance_cutoff_ignores_calibration_with_no_spread():
    candidates = [{"s": 0.5}, {"s": 0.5}, {"s": 0.5}]

    assert relevance_cutoff(candidates, {"mean": 0.9, "std": 0}) == pytest.approx(0.53)


def test_relevance_cutoff_of_an_empty_pool_admits_nothing():
    assert relevance_cutoff([]) == float("-inf")


# ---------------------------------------------------------------------------
# Diversity selection
# ---------------------------------------------------------------------------

def test_diversify_drops_everything_below_the_cutoff():
    candidates = [{"i": 0, "s": 0.2}, {"i": 1, "s": 0.1}]
    vectors = np.array([[1, 0], [0, 1]], dtype=np.float32)

    assert diversify(candidates, vectors, 4, lambda child: "one") == []


def test_diversify_returns_the_closest_windows_when_the_threshold_is_skipped():
    candidates = [{"i": 0, "s": 0.2}, {"i": 1, "s": 0.1}]
    vectors = np.array([[1, 0], [0, 1]], dtype=np.float32)

    selected = diversify(candidates, vectors, 4, str, no_threshold=True)

    assert [entry["i"] for entry in selected] == [0, 1]


def test_diversify_caps_how_many_windows_one_section_contributes():
    candidates = [{"i": i, "s": 0.9 - i * 0.01} for i in range(4)]
    vectors = np.array([[1, 0], [1, 0], [0, 1], [0, 1]], dtype=np.float32)
    sections = ["one", "one", "one", "two"]

    selected = diversify(candidates, vectors, 4, lambda child: sections[child], no_threshold=True)

    assert sum(1 for entry in selected if sections[entry["i"]] == "one") == SOURCE_CAP
    assert any(sections[entry["i"]] == "two" for entry in selected)


def test_diversify_prefers_a_different_window_over_a_near_copy_of_the_one_already_chosen():
    candidates = [{"i": 0, "s": 0.9}, {"i": 1, "s": 0.89}, {"i": 2, "s": 0.88}]
    # Window 1 is a copy of window 0; window 2 points elsewhere.
    vectors = np.array([[1, 0], [1, 0], [0, 1]], dtype=np.float32)
    sections = ["one", "two", "three"]

    selected = diversify(candidates, vectors, 2, lambda child: sections[child], no_threshold=True)

    assert [entry["i"] for entry in selected] == [0, 2]


# ---------------------------------------------------------------------------
# Reading a container
# ---------------------------------------------------------------------------

def test_load_container_reads_a_well_formed_file():
    index = load_container(container_bytes(sample_header(), [[1, 0], [0, 1]]))

    assert index.name == "Example Org"
    assert len(index) == 2
    assert index.query_prefix == "Represent this sentence for searching relevant passages: "


def test_load_container_reads_a_file_from_a_path(tmp_path):
    path = tmp_path / "compendium.json"
    path.write_bytes(container_bytes(sample_header(), [[1, 0], [0, 1]]))

    assert len(load_container(path)) == 2


def test_load_container_dequantizes_int8_vectors_with_the_header_scale():
    header = sample_header()
    header["embedding"]["dtype"] = "int8"
    header["embedding"]["scale"] = 127

    index = load_container(container_bytes(header, [[127, 0], [0, 127]], dtype="int8"))

    assert index.vectors[0][0] == pytest.approx(1.0, abs=1e-6)
    assert index.vectors[0][1] == 0


def test_load_container_refuses_a_file_too_short_to_hold_a_header_length():
    with pytest.raises(ContainerError, match="too short"):
        load_container(b"\x01\x02")


def test_load_container_refuses_a_header_length_past_the_end_of_the_file():
    data = container_bytes(sample_header(), [[1, 0], [0, 1]], header_length=10 ** 6)

    with pytest.raises(ContainerError, match="runs past the end"):
        load_container(data)


def test_load_container_refuses_a_header_that_is_not_json():
    with pytest.raises(ContainerError, match="not valid UTF-8 JSON"):
        load_container(struct.pack("<I", 3) + b"{{{")


def test_load_container_refuses_another_tool_output_that_happens_to_be_json():
    data = container_bytes(sample_header(format="some-other-tool"), [[1, 0], [0, 1]])

    with pytest.raises(ContainerError, match="not an Extractium compendium"):
        load_container(data)


def test_load_container_refuses_a_container_version_it_does_not_read():
    data = container_bytes(sample_header(v=2), [[1, 0], [0, 1]])

    with pytest.raises(ContainerError, match="not supported"):
        load_container(data)


def test_load_container_refuses_a_file_whose_embedder_is_not_the_one_asked_for():
    data = container_bytes(sample_header(), [[1, 0], [0, 1]])

    with pytest.raises(ContainerError, match="not comparable"):
        load_container(data, model="other/model")
    with pytest.raises(ContainerError, match="produces 384"):
        load_container(data, dims=384)


def test_load_container_refuses_vector_bytes_that_do_not_match_the_children():
    data = container_bytes(sample_header(), [[1, 0]])

    with pytest.raises(ContainerError, match="do not match 2 children"):
        load_container(data)


def test_load_container_refuses_a_window_pointing_outside_the_sections():
    header = sample_header()
    header["children"]["pid"] = [0, 9]

    with pytest.raises(ContainerError, match="outside the 2 sections"):
        load_container(container_bytes(header, [[1, 0], [0, 1]]))


def test_load_container_refuses_int8_vectors_with_no_usable_scale():
    header = sample_header()
    header["embedding"]["dtype"] = "int8"

    with pytest.raises(ContainerError, match="positive scale"):
        load_container(container_bytes(header, [[1, 0], [0, 1]], dtype="int8"))


def test_load_container_refuses_a_header_missing_a_field_the_search_needs():
    header = sample_header()
    del header["children"]

    with pytest.raises(ContainerError, match="missing the 'children' field"):
        load_container(container_bytes(header, []))


# ---------------------------------------------------------------------------
# Searching
# ---------------------------------------------------------------------------

def test_search_returns_whole_sections_not_the_matched_window():
    index = load_container(container_bytes(sample_header(), [[1, 0], [0, 1]]))

    (hit,) = index.search("alpha", lambda text: [1, 0], k=1, no_threshold=True)

    assert hit.parent["id"] == "aaaaaaaaaaaaaaaa"
    assert hit.parent["x"] == "Alpha section text."
    assert hit.window_text == "Alpha"
    assert hit.child_index == 0


def test_search_adds_the_query_prefix_the_file_records_before_embedding():
    index = load_container(container_bytes(sample_header(), [[1, 0], [0, 1]]))
    seen = []

    def embed(text):
        seen.append(text)
        return [1, 0]

    index.search("how do I rebuild", embed, no_threshold=True)

    assert seen == [
        "Represent this sentence for searching relevant passages: how do I rebuild"
    ]


def test_search_returns_nothing_when_no_section_clears_the_relevance_cutoff():
    index = load_container(container_bytes(sample_header(), [[1, 0], [0, 1]]))

    # A query pointing between the two windows scores 0.7071 against both,
    # so no candidate beats its own pool by the margin.
    assert index.search("unrelated", lambda text: [0.7071, 0.7071]) == []


def test_search_applies_the_per_section_weight_without_keyword_statistics():
    header = sample_header()
    header["parents"][1]["weight"] = 5.0
    index = load_container(container_bytes(header, [[1, 0], [0.9, 0.4359]]))

    hits = index.search("either", lambda text: [1, 0], k=2, no_threshold=True)

    assert [hit.parent["id"] for hit in hits] == ["bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa"]


def test_window_text_falls_back_to_the_whole_section_without_offsets():
    header = sample_header()
    header["children"] = {"pid": [0, 1]}
    index = load_container(container_bytes(header, [[1, 0], [0, 1]]))

    (hit,) = index.search("alpha", lambda text: [1, 0], k=1, no_threshold=True)

    assert hit.window_text == "Alpha section text."
    assert hit.start is None


def test_window_text_slices_in_utf16_code_units_like_a_browser_does():
    header = sample_header()
    # An emoji is two UTF-16 code units, so a client that counted Python
    # characters would cut the following word in half.
    header["parents"][0]["x"] = "🚀 launch notes"
    header["children"] = {"pid": [0, 1], "start": [3, 0], "end": [9, 5]}
    index = load_container(container_bytes(header, [[1, 0], [0, 1]]))

    (hit,) = index.search("launch", lambda text: [1, 0], k=1, no_threshold=True)

    assert hit.window_text == "launch"
