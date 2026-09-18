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
Last Modified: 2026-09-17
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

import json
import struct

import numpy as np
import pytest

from extractium.search import (
    CANDIDATE_POOL,
    COSINE_MIN,
    COSINE_MIN_HIGHEST,
    COSINE_MIN_LOWEST,
    RRF_K,
    SCORE_MIN,
    SCORE_PLACES,
    SOURCE_CAP,
    ContainerError,
    attach_cosines,
    bm25_candidates,
    diversify,
    load_container,
    relevance_cutoff,
    relevance_floor,
    round_score,
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
        "extractium": "0.2",
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


def test_vector_candidates_rounds_to_the_shared_precision():
    vectors = np.array([[0.6, 0.8]], dtype=np.float32)

    (hit,) = vector_candidates([0.28, 0.96], vectors)

    assert hit["s"] == round(hit["s"], SCORE_PLACES)


def test_two_windows_scoring_closer_than_the_precision_tie_and_order_by_index():
    """
    Two near-copies of one page score a hair apart, and the hair is
    smaller than the difference between two clients adding up the same
    products. Rounding puts them on one score so the child index, which
    every client agrees on, decides their order.
    """
    dims = 384
    first = np.linspace(0.01, 1.0, dims).astype(np.float32)
    first /= np.linalg.norm(first)
    second = first.copy()
    second[7] += 3e-7
    second /= np.linalg.norm(second)
    vectors = np.array([second, first], dtype=np.float32)

    ranked = vector_candidates(first, vectors)

    assert ranked[0]["s"] == ranked[1]["s"]
    assert [entry["i"] for entry in ranked] == [0, 1]


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


def test_bm25_candidates_round_to_the_shared_precision():
    ranked = bm25_candidates(["crawler", "index"], KEYWORD_STATS, 3)

    assert ranked
    assert all(entry["s"] == round(entry["s"], SCORE_PLACES) for entry in ranked)


# ---------------------------------------------------------------------------
# Shared precision
# ---------------------------------------------------------------------------

def test_round_score_keeps_the_places_every_client_shares():
    assert round_score(0.1234564999) == 0.123456
    assert round_score(0.12345678) == 0.123457
    assert round_score(2) == 2.0


def test_round_score_leaves_a_score_that_is_already_that_short_alone():
    assert round_score(0.5) == 0.5
    assert round_score(0.0) == 0.0


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

def test_rrf_fuse_scores_by_rank_alone_not_by_the_incoming_scores():
    vector_list = [{"i": 7, "s": 0.9}, {"i": 8, "s": 0.8}]
    keyword_list = [{"i": 8, "s": 42.0}, {"i": 7, "s": 0.1}]

    fused = rrf_fuse([(vector_list, 0.5), (keyword_list, 0.5)])

    expected = round_score(0.5 * (RRF_K / (RRF_K + 1)) + 0.5 * (RRF_K / (RRF_K + 2)))
    assert len(fused) == 2
    assert all(entry["s"] == expected for entry in fused)


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


def test_relevance_cutoff_of_an_empty_pool_admits_nothing():
    assert relevance_cutoff([]) == float("-inf")


# ---------------------------------------------------------------------------
# The cosine floor
# ---------------------------------------------------------------------------

def test_attach_cosines_records_the_raw_cosine_whatever_the_ranking_score_is():
    vectors = np.asarray([[1, 0], [0, 1], [0.6, 0.8]], dtype=np.float32)
    candidates = [{"i": 2, "s": 0.98}, {"i": 0, "s": 0.49}]

    attach_cosines(candidates, [2, 0], vectors)     # not unit length: normalized before use

    assert [candidate["cos"] for candidate in candidates] == pytest.approx([0.6, 1.0])
    assert [candidate["s"] for candidate in candidates] == [0.98, 0.49]
    assert all(candidate["cos"] == round(candidate["cos"], SCORE_PLACES) for candidate in candidates)


# Five unit vectors and a pool whose median ranking score is low, so the
# pool's own cutoff sits at SCORE_MIN and only the cosine floor decides
# between the two candidates that rank well.
FLOOR_VECTORS = np.eye(5, dtype=np.float32)


def floor_pool(first_cosine, second_cosine):
    weak = [{"i": i, "s": score, "cos": 0.9} for i, score in ((2, 0.3), (3, 0.2), (4, 0.1))]
    return [{"i": 0, "s": 0.98, "cos": first_cosine}, {"i": 1, "s": 0.90, "cos": second_cosine}] + weak


def test_a_candidate_under_the_cosine_floor_is_dropped_however_well_it_ranks():
    selected = diversify(floor_pool(COSINE_MIN - 0.01, COSINE_MIN), FLOOR_VECTORS, 4, str)

    assert [candidate["i"] for candidate in selected] == [1]


def test_a_candidate_that_carries_no_cosine_is_judged_on_its_ranking_score_alone():
    pool = floor_pool(0.1, 0.1)
    del pool[0]["cos"]

    selected = diversify(pool, FLOOR_VECTORS, 4, str)

    assert [candidate["i"] for candidate in selected] == [0]


def test_a_caller_may_set_its_own_cosine_floor():
    pool = floor_pool(0.60, 0.50)

    assert diversify(pool, FLOOR_VECTORS, 4, str) == []
    assert [c["i"] for c in diversify(pool, FLOOR_VECTORS, 4, str, cosine_min=0.55)] == [0]
    # An older caller passed the file's calibration object in this place.
    assert diversify(pool, FLOOR_VECTORS, 4, str, False, {"mean": 0.1, "std": 0.1}) == []
    assert diversify(pool, FLOOR_VECTORS, 4, str, False, None) == []


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


# ---------------------------------------------------------------------------
# A floor measured for the file
# ---------------------------------------------------------------------------

def unrelated(median, spread, probes=64):
    return {"mean": 0.93, "std": 0.05, "sampleSize": 500,
            "unrelatedMedian": median, "unrelatedSpread": spread, "unrelatedProbes": probes}


def test_a_file_with_the_unrelated_figures_sets_its_own_floor():
    assert relevance_floor(unrelated(0.618, 0.048)) == pytest.approx(0.690)
    assert relevance_floor(unrelated(0.565, 0.046)) == pytest.approx(0.634)


def test_a_file_without_usable_figures_gets_the_fixed_floor():
    assert relevance_floor(None) == COSINE_MIN
    assert relevance_floor({"mean": 0.93, "std": 0.05, "sampleSize": 500}) == COSINE_MIN
    assert relevance_floor(unrelated(0.6, 0.04, probes=3)) == COSINE_MIN          # too few probes to trust
    assert relevance_floor(unrelated("0.6", 0.04)) == COSINE_MIN                  # not a number
    assert relevance_floor(unrelated(float("nan"), 0.04)) == COSINE_MIN
    assert relevance_floor(unrelated(0.6, -0.04)) == COSINE_MIN
    assert relevance_floor(unrelated(True, 0.04)) == COSINE_MIN


def test_a_floor_read_from_a_file_stays_inside_a_sane_range():
    assert relevance_floor(unrelated(0.05, 0.04)) == COSINE_MIN_LOWEST       # random test vectors
    assert relevance_floor(unrelated(0.95, 0.10)) == COSINE_MIN_HIGHEST      # every probe on topic


def test_search_uses_the_floor_the_file_carries():
    header = sample_header(calibration=unrelated(0.47, 0.04))                # floor 0.53
    header["parents"].append(parent_record("cccccccccccccccc"))
    header["children"] = {"pid": [0, 1, 2], "start": [0, 0, 0], "end": [5, 5, 5]}
    index = load_container(container_bytes(header, [[1, 0], [0.6, 0.8], [0, 1]]))

    assert index.cosine_min == pytest.approx(0.53)
    # 0.6 from the first window: under the fixed 0.67, over this file's floor.
    hits = index.search("anything", lambda text: [0.6, -0.8], k=1)
    assert [hit.parent["id"] for hit in hits] == ["aaaaaaaaaaaaaaaa"]


def test_the_files_calibration_figures_never_hide_a_close_match():
    """
    The calibration figures say how similar the windows are to each other.
    In a large or repetitive corpus that is about 0.93, which no query
    reaches, so a cutoff built on them once rejected every hit.
    """
    header = sample_header(bm25=KEYWORD_STATS, calibration={"mean": 0.93, "std": 0.047, "sampleSize": 500})
    header["parents"].append(parent_record("cccccccccccccccc"))
    header["children"] = {"pid": [0, 1, 2], "start": [0, 0, 0], "end": [5, 5, 5]}
    index = load_container(container_bytes(header, [[1, 0], [0, 1], [0.8, 0.6]]))

    # 0.8 from the third window, which also holds the query's one rare word.
    hits = index.search("crawler", lambda text: [1, 0], k=1)

    assert [hit.parent["id"] for hit in hits] == ["cccccccccccccccc"]
    assert hits[0].cosine == pytest.approx(0.8)


def test_an_unrelated_query_gets_nothing_even_when_keywords_rank_a_window_first():
    header = sample_header(bm25=KEYWORD_STATS)
    header["parents"].append(parent_record("cccccccccccccccc"))
    header["children"] = {"pid": [0, 1, 2], "start": [0, 0, 0], "end": [5, 5, 5]}
    index = load_container(container_bytes(header, [[1, 0], [0.8, 0.6], [0.6, 0.8]]))

    # The query is at most 0.28 from any window, far under the floor, although
    # "crawler" puts the third window first in the keyword list and the
    # fused ranking score of every window is high.
    pool = index.candidates("crawler index", [-0.6, 0.8])
    assert max(candidate["s"] for candidate in pool) > SCORE_MIN
    assert index.search("crawler index", lambda text: [-0.6, 0.8]) == []
    assert index.search("crawler index", lambda text: [-0.6, 0.8], no_threshold=True) != []


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


def test_load_container_inflates_a_gzip_compressed_file(tmp_path):
    import gzip

    raw = container_bytes(sample_header(), [[1, 0], [0, 1]])
    path = tmp_path / "compendium.json.gz"
    path.write_bytes(gzip.compress(raw))

    assert len(load_container(path)) == 2
    assert len(load_container(gzip.compress(raw))) == 2


def test_load_container_refuses_bytes_that_begin_like_gzip_but_are_not():
    with pytest.raises(ContainerError, match="cannot be inflated"):
        load_container(b"\x1f\x8b" + b"not a gzip stream at all")
