"""
Summary: Tests for the keyword step: how a section's candidates are
ranked by its own vector, how a page's tags are drawn from what its
sections share, what the store remembers between builds, and that the
candidate extractor itself, when installed, proposes phrases and not
function words. Every embedder here is a fake, and no test reaches the
network.

This file is part of Extractium™
tests/test_core_keywords.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-15
Last Modified: 2026-09-15
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

import importlib.util

import numpy as np
import pytest

from extractium.core import keywords
from extractium.core.keywords import KeywordPass

BUILT_AT = "2026-01-02T03:04:05Z"
EARLIER = "2025-12-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def unit(*components):
    """A unit vector in a small space, so similarities are easy to reason about."""
    vector = np.array(components, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def section(number, text, url="https://example.org/page", categories=(), source_type="web"):
    """One chunked section as the build holds it before the records are made."""
    return {
        "id": f"{number:016x}",
        "t": "Page -- Section",
        "x": text,
        "u": url,
        "host": "example.org",
        "source_type": source_type,
        "content_type": "page",
        "source_label": "Website",
        "categories": tuple(categories),
        "local": False,
        "weight": 1.0,
    }


def windows_for(sections, vectors):
    """One window per section, carrying the vector the test chose for it."""
    children = [{"pid": position, "x": s["x"], "start": 0, "end": len(s["x"])} for position, s in enumerate(sections)]
    return children, np.array(vectors, dtype=np.float32)


class PhraseEmbedder:
    """Embeds each phrase to the vector the test assigned it, and records the calls."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, chunks):
        self.calls.append([c["x"] for c in chunks])
        return np.array([self.table[c["x"]] for c in chunks], dtype=np.float32)


class MemoryStore:
    """A store that lives in the test, in place of the cache folder."""

    def __init__(self, document=None):
        self.document = document or {}
        self.saved = None

    def load(self):
        return self.document

    def save(self, document):
        self.saved = document


def constant_candidates(*phrases):
    """A candidate extractor that proposes the same phrases for every text, counting calls."""
    calls = []

    def candidates(text):
        calls.append(text)
        return list(phrases)

    candidates.calls = calls
    return candidates


# ---------------------------------------------------------------------------
# Section vectors and ranking
# ---------------------------------------------------------------------------

def test_section_vectors_average_a_sections_windows_back_to_unit_length():
    children = [{"pid": 0}, {"pid": 0}, {"pid": 1}]
    vecs = np.array([unit(1, 0), unit(0, 1), unit(0, 1)], dtype=np.float32)

    vectors = keywords.section_vectors(2, children, vecs)

    assert vectors.shape == (2, 2)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert np.allclose(vectors[0], unit(1, 1))
    assert np.allclose(vectors[1], unit(0, 1))


def test_section_vectors_give_a_section_with_no_window_a_zero_row_not_an_error():
    vectors = keywords.section_vectors(2, [{"pid": 1}], np.array([unit(1, 0)]))

    assert np.allclose(vectors[0], 0)


def test_rank_by_similarity_puts_the_closest_phrase_first():
    phrase_vectors = {"often": unit(0, 1), "subject": unit(1, 0), "near": unit(1, 1)}

    ranked = keywords.rank_by_similarity(["often", "near", "subject"], unit(1, 0), phrase_vectors)

    assert ranked == ["subject", "near", "often"]


def test_rank_by_similarity_breaks_ties_in_the_extractors_order():
    phrase_vectors = {"first": unit(0, 1), "second": unit(0, 1)}

    assert keywords.rank_by_similarity(["first", "second"], unit(1, 0), phrase_vectors) == ["first", "second"]
    assert keywords.rank_by_similarity(["second", "first"], unit(1, 0), phrase_vectors) == ["second", "first"]


def test_distinct_phrases_skip_a_phrase_inside_or_around_one_already_kept():
    ranked = ["Mobile Tech FAQs", "Tech FAQs", "text messages", "mobile tech faqs today", "wearables"]

    assert keywords.distinct_phrases(ranked, 5) == ["Mobile Tech FAQs", "text messages", "wearables"]


def test_distinct_phrases_stop_at_the_limit_and_keep_the_order_given():
    assert keywords.distinct_phrases(["c", "a", "b"], 2) == ["c", "a"]
    assert keywords.distinct_phrases([], 3) == []
    assert keywords.distinct_phrases(["", "  ", "one"], 3) == ["one"]


# ---------------------------------------------------------------------------
# Page tags
# ---------------------------------------------------------------------------

def test_page_tags_are_the_categories_then_the_keywords_at_least_half_the_sections_share():
    sections = [
        {"categories": ("Guides", "Sleep"), "keywords": ("sleep hygiene", "bedtime", "caffeine")},
        {"categories": ("Guides", "Sleep"), "keywords": ("sleep hygiene", "screens", "bedtime")},
        {"categories": ("Guides", "Sleep"), "keywords": ("sleep hygiene", "naps")},
    ]

    assert keywords.page_tags(sections) == ("Guides", "Sleep", "sleep hygiene", "bedtime")


def test_page_tags_order_shared_keywords_by_how_many_sections_share_them_then_first_seen():
    sections = [
        {"categories": (), "keywords": ("alpha", "beta")},
        {"categories": (), "keywords": ("beta", "alpha")},
        {"categories": (), "keywords": ("beta", "gamma")},
        {"categories": (), "keywords": ("gamma",)},
    ]

    assert keywords.page_tags(sections) == ("beta", "alpha", "gamma")


def test_page_tags_compare_without_regard_to_case_and_keep_the_first_spelling():
    sections = [
        {"categories": ("Depression",), "keywords": ("depression", "Peer Support")},
        {"categories": ("Depression",), "keywords": ("peer support",)},
    ]

    assert keywords.page_tags(sections) == ("Depression", "Peer Support")


def test_a_one_section_page_is_tagged_with_its_categories_and_every_keyword():
    sections = [{"categories": ("Events",), "keywords": ("open house", "campus tour")}]

    assert keywords.page_tags(sections) == ("Events", "open house", "campus tour")


def test_a_page_whose_sections_share_nothing_keeps_only_its_categories():
    sections = [
        {"categories": ("Mixed",), "keywords": ("one",)},
        {"categories": ("Mixed",), "keywords": ("two",)},
        {"categories": ("Mixed",), "keywords": ("three",)},
    ]

    assert keywords.page_tags(sections) == ("Mixed",)


def test_page_tags_stop_at_the_limit_after_the_categories():
    sections = [{"categories": ("A", "B"), "keywords": tuple(f"k{n}" for n in range(12))}]

    assert keywords.page_tags(sections, limit=3) == ("A", "B", "k0", "k1", "k2")


def test_page_tags_drop_blank_categories_and_a_keyword_repeated_within_one_section():
    sections = [{"categories": (" ", "Real "), "keywords": ("twice", "twice", "once")}]

    assert keywords.page_tags(sections) == ("Real", "twice", "once")


def test_tag_pages_groups_a_videos_moments_as_one_page():
    sections = [
        section(1, "a", url="https://www.youtube.com/watch?v=abcdefghijk&t=0s", source_type="youtube"),
        section(2, "b", url="https://www.youtube.com/watch?v=abcdefghijk&t=90s", source_type="youtube"),
        section(3, "c", url="https://example.org/other"),
    ]
    sections[0]["keywords"] = ("talk", "sleep")
    sections[1]["keywords"] = ("sleep", "screens")
    sections[2]["keywords"] = ("other",)

    pages = keywords.tag_pages(sections)

    assert pages == 2
    assert sections[0]["tags"] == sections[1]["tags"] == ("sleep", "talk", "screens")
    assert sections[2]["tags"] == ("other",)


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def test_the_pass_names_each_section_with_the_candidates_closest_to_its_vector():
    sections = [
        section(1, "About sleep.", categories=("Health",)),
        section(2, "About budgets.", url="https://example.org/budgets"),
    ]
    children, vecs = windows_for(sections, [unit(1, 0), unit(0, 1)])
    embedder = PhraseEmbedder({
        "sleep": unit(1, 0), "deep sleep": unit(1, 0), "money": unit(0, 1), "tuesday": unit(1, 1),
    })
    # "deep sleep" contains "sleep", so once "sleep" is chosen it is passed over.
    candidates = constant_candidates("tuesday", "money", "sleep", "deep sleep")
    store = MemoryStore()
    lines = []

    KeywordPass(store.load, store.save, candidates=candidates, per_section=2).run(
        sections, children, vecs, embedder, BUILT_AT, lines.append
    )

    assert sections[0]["keywords"] == ("sleep", "tuesday")
    assert sections[1]["keywords"] == ("money", "tuesday")
    assert sections[0]["tags"] == ("Health", "sleep", "tuesday")
    assert all(s["enriched_at"] == BUILT_AT and s["enrich_ver"] == keywords.PASS_VERSION for s in sections)
    # Every candidate phrase of the build is embedded in one call, once each.
    assert embedder.calls == [["deep sleep", "money", "sleep", "tuesday"]]
    assert candidates.calls == ["About sleep.", "About budgets."]
    assert lines[-1] == "Named 2 section(s) with keywords, 2 of them afresh, and tagged 2 page(s)."


def test_the_pass_stores_what_it_found_keyed_by_section_and_text_digest():
    sections = [section(1, "About sleep.")]
    children, vecs = windows_for(sections, [unit(1, 0)])
    store = MemoryStore()

    KeywordPass(store.load, store.save, candidates=constant_candidates("sleep")).run(
        sections, children, vecs, PhraseEmbedder({"sleep": unit(1, 0)}), BUILT_AT, lambda line: None
    )

    assert store.saved == {
        "version": keywords.PASS_VERSION,
        "sections": {
            sections[0]["id"]: {
                "hash": keywords.text_digest("About sleep."),
                "keywords": ["sleep"],
                "enriched_at": BUILT_AT,
            }
        },
    }


def test_the_pass_reuses_a_stored_result_for_unchanged_text_and_keeps_its_time():
    sections = [section(1, "About sleep.")]
    children, vecs = windows_for(sections, [unit(1, 0)])
    store = MemoryStore({
        "version": keywords.PASS_VERSION,
        "sections": {sections[0]["id"]: {
            "hash": keywords.text_digest("About sleep."), "keywords": ["stored"], "enriched_at": EARLIER,
        }},
    })
    candidates = constant_candidates("fresh")
    embedder = PhraseEmbedder({})
    lines = []

    KeywordPass(store.load, store.save, candidates=candidates).run(
        sections, children, vecs, embedder, BUILT_AT, lines.append
    )

    assert sections[0]["keywords"] == ("stored",)
    assert sections[0]["enriched_at"] == EARLIER
    assert sections[0]["enrich_ver"] == keywords.PASS_VERSION
    assert candidates.calls == []
    assert embedder.calls == []
    assert lines == ["Named 1 section(s) with keywords, 0 of them afresh, and tagged 1 page(s)."]


def test_the_pass_names_a_section_afresh_when_its_text_changed_under_the_same_id():
    sections = [section(1, "About sleep, revised.")]
    children, vecs = windows_for(sections, [unit(1, 0)])
    store = MemoryStore({
        "version": keywords.PASS_VERSION,
        "sections": {sections[0]["id"]: {
            "hash": keywords.text_digest("About sleep."), "keywords": ["stored"], "enriched_at": EARLIER,
        }},
    })

    KeywordPass(store.load, store.save, candidates=constant_candidates("fresh")).run(
        sections, children, vecs, PhraseEmbedder({"fresh": unit(1, 0)}), BUILT_AT, lambda line: None
    )

    assert sections[0]["keywords"] == ("fresh",)
    assert sections[0]["enriched_at"] == BUILT_AT


def test_the_pass_ignores_a_store_written_by_another_version_of_itself():
    sections = [section(1, "About sleep.")]
    children, vecs = windows_for(sections, [unit(1, 0)])
    store = MemoryStore({
        "version": "keywords-0",
        "sections": {sections[0]["id"]: {
            "hash": keywords.text_digest("About sleep."), "keywords": ["stale"], "enriched_at": EARLIER,
        }},
    })

    KeywordPass(store.load, store.save, candidates=constant_candidates("fresh")).run(
        sections, children, vecs, PhraseEmbedder({"fresh": unit(1, 0)}), BUILT_AT, lambda line: None
    )

    assert sections[0]["keywords"] == ("fresh",)
    assert store.saved["version"] == keywords.PASS_VERSION


def test_the_pass_drops_stored_sections_this_build_no_longer_has():
    sections = [section(1, "About sleep.")]
    children, vecs = windows_for(sections, [unit(1, 0)])
    store = MemoryStore({
        "version": keywords.PASS_VERSION,
        "sections": {
            sections[0]["id"]: {"hash": keywords.text_digest("About sleep."), "keywords": ["stored"], "enriched_at": EARLIER},
            "ffffffffffffffff": {"hash": "0" * 16, "keywords": ["gone"], "enriched_at": EARLIER},
        },
    })

    KeywordPass(store.load, store.save, candidates=constant_candidates()).run(
        sections, children, vecs, PhraseEmbedder({}), BUILT_AT, lambda line: None
    )

    assert list(store.saved["sections"]) == [sections[0]["id"]]


def test_a_section_with_no_candidate_is_named_with_an_empty_list_and_no_embedding_call():
    sections = [section(1, "Hi.")]
    children, vecs = windows_for(sections, [unit(1, 0)])
    embedder = PhraseEmbedder({})
    store = MemoryStore()

    KeywordPass(store.load, store.save, candidates=constant_candidates()).run(
        sections, children, vecs, embedder, BUILT_AT, lambda line: None
    )

    assert sections[0]["keywords"] == ()
    assert sections[0]["tags"] == ()
    assert embedder.calls == []


def test_a_store_that_is_not_a_document_is_treated_as_empty():
    sections = [section(1, "About sleep.")]
    children, vecs = windows_for(sections, [unit(1, 0)])
    store = MemoryStore({"sections": "not a mapping"})

    KeywordPass(store.load, store.save, candidates=constant_candidates("fresh")).run(
        sections, children, vecs, PhraseEmbedder({"fresh": unit(1, 0)}), BUILT_AT, lambda line: None
    )

    assert sections[0]["keywords"] == ("fresh",)


def test_text_digest_is_sixteen_hexadecimal_characters_of_the_texts_hash():
    digest = keywords.text_digest("About sleep.")

    assert len(digest) == keywords.TEXT_DIGEST_CHARS == 16
    assert int(digest, 16) >= 0
    assert digest != keywords.text_digest("About sleep")


# ---------------------------------------------------------------------------
# The extractor library
# ---------------------------------------------------------------------------

def test_keyword_library_available_reports_a_missing_library(monkeypatch):
    monkeypatch.setattr(keywords.importlib.util, "find_spec", lambda name: None)

    assert keywords.keyword_library_available() is False


def test_keyword_library_available_reports_an_installed_library(monkeypatch):
    monkeypatch.setattr(keywords.importlib.util, "find_spec", lambda name: object())

    assert keywords.keyword_library_available() is True


def test_keyword_library_available_agrees_with_the_interpreter():
    assert keywords.keyword_library_available() == (importlib.util.find_spec("yake") is not None)


SYNTHETIC_SECTION = (
    "Peer-to-peer depression awareness is a program for high school students. "
    "Students learn to recognize depression in classmates and to reach out for help. "
    "The program was developed at an example university, and schools across the "
    "state take part in it each year."
)

STOPWORDS_AT_AN_EDGE = {"the", "a", "an", "and", "for", "to", "in", "of", "is", "at", "it", "each"}


def test_candidate_phrases_propose_short_phrases_from_the_text_with_no_function_word_at_an_edge():
    pytest.importorskip("yake")

    candidates = keywords.candidate_phrases(SYNTHETIC_SECTION)

    assert candidates
    assert len(candidates) <= keywords.CANDIDATES_PER_SECTION
    assert all(1 <= len(phrase.split()) <= keywords.MAX_PHRASE_WORDS for phrase in candidates)
    assert all(phrase.lower() in SYNTHETIC_SECTION.lower() for phrase in candidates)
    assert all(
        phrase.split()[0].lower() not in STOPWORDS_AT_AN_EDGE
        and phrase.split()[-1].lower() not in STOPWORDS_AT_AN_EDGE
        for phrase in candidates
    )
    assert any("depression" in phrase.lower() for phrase in candidates)


def test_candidate_phrases_are_the_same_for_the_same_text():
    pytest.importorskip("yake")

    assert keywords.candidate_phrases(SYNTHETIC_SECTION) == keywords.candidate_phrases(SYNTHETIC_SECTION)


def test_candidate_phrases_of_an_empty_or_tiny_text_are_none():
    pytest.importorskip("yake")

    assert keywords.candidate_phrases("") == []
    assert keywords.candidate_phrases("Hello.") == []


def test_candidate_phrases_honor_the_limit():
    pytest.importorskip("yake")

    assert len(keywords.candidate_phrases(SYNTHETIC_SECTION, limit=3)) <= 3
