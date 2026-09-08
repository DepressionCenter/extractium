"""
Summary: Tests for the core build step. Pins the scored result against the
frozen reference script's own pipeline over the same fixtures, checks the
order the steps run in (near-duplicate collapse before the keyword
statistics, parent compaction after it), and checks that a child's stored
offsets slice its window back out of its parent's text, including for
characters outside the Basic Multilingual Plane.

This file is part of Extractium™
tests/test_build.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
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

import numpy as np
import pytest
from bs4 import BeautifulSoup

from extractium.core import build
from extractium.core.models import Document
from extractium.sources.generic import GenericHandler


def document_from_fixture(fixtures_dir, name, url, **fields):
    """Reads a fixture the way a crawl would, through the generic handler."""
    soup = BeautifulSoup((fixtures_dir / name).read_text(encoding="utf-8"), "html.parser")
    extraction = GenericHandler().extract(soup, url)
    return Document(
        url=url,
        title=extraction.title,
        content=extraction.node,
        source_type=fields.pop("source_type", "web"),
        content_type=fields.pop("content_type", "page"),
        **fields,
    )


def text_document(text, url="https://example.org/notes.txt", title="Notes"):
    """A document whose content is plain text, which the chunker wraps itself."""
    return Document(url=url, title=title, content=text, source_type="web", content_type="text")


# ---------------------------------------------------------------------------
# Offsets
# ---------------------------------------------------------------------------

def test_utf16_length_counts_code_units_not_characters():
    assert build.utf16_length("plain") == 5
    # One emoji is a single Python character and two UTF-16 code units.
    assert build.utf16_length("a\U0001F600b") == 4


def test_utf16_slice_recovers_the_named_run_of_code_units():
    text = "a\U0001F600bc"
    assert build.utf16_slice(text, 0, 1) == "a"
    assert build.utf16_slice(text, 1, 3) == "\U0001F600"
    assert build.utf16_slice(text, 3, 5) == "bc"


def test_utc_now_is_an_iso_timestamp_ending_in_z():
    from extractium.core.models import UTC_TIMESTAMP_RE

    assert UTC_TIMESTAMP_RE.match(build.utc_now())


# ---------------------------------------------------------------------------
# Chunking documents into one corpus
# ---------------------------------------------------------------------------

def test_chunk_documents_offsets_each_pages_pids_into_the_shared_list(fixtures_dir):
    documents = [
        document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team"),
        document_from_fixture(fixtures_dir, "page_boilerplate_b.html", "https://example.org/project"),
    ]

    parents, children, site_name = build.chunk_documents(documents, lambda line: None)

    assert site_name == documents[0].title
    assert len(parents) == 4
    first_page = [c for c in children if c["u"] == "https://example.org/team"]
    second_page = [c for c in children if c["u"] == "https://example.org/project"]
    assert sorted(c["pid"] for c in first_page) == [0, 1]
    assert sorted(c["pid"] for c in second_page) == [2, 3]


def test_chunk_documents_matches_the_reference_crawls_parents_and_children(
    reference, fixtures_dir
):
    """
    The port deliberately differs from the frozen script only in the fields
    it adds (docs/architecture.md, decision 3). Every field the reference
    itself produces must still agree, page for page.
    """
    url = "https://example.org/team"
    document = document_from_fixture(fixtures_dir, "page_boilerplate_a.html", url)
    shared = ("t", "x", "u", "host", "weight")

    parents, children, _ = build.chunk_documents([document], lambda line: None)
    ref_parents, ref_children = reference.build_parent_and_child_chunks(
        document.title, document.content, url
    )

    assert [{k: p[k] for k in shared} for p in parents] == [
        {k: p[k] for k in shared} for p in ref_parents
    ]
    assert [{k: c[k] for k in shared + ("pid",)} for c in children] == [
        {k: c[k] for k in shared + ("pid",)} for c in ref_children
    ]


# ---------------------------------------------------------------------------
# build_compendium
# ---------------------------------------------------------------------------

def test_build_compendium_returns_none_when_nothing_is_indexable(fake_embed_chunks_core):
    assert build.build_compendium([], embedder=fake_embed_chunks_core) is None


def test_build_compendium_returns_none_when_every_document_is_too_short(fake_embed_chunks_core):
    # Below CHUNK_MIN_CHARS, so the chunker yields no parent at all.
    document = text_document("Too short.")
    assert build.build_compendium([document], embedder=fake_embed_chunks_core) is None


def test_build_compendium_produces_one_vector_row_per_child(fixtures_dir, fake_embed_chunks_core):
    documents = [
        document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team"),
        document_from_fixture(fixtures_dir, "page_boilerplate_b.html", "https://example.org/project"),
    ]

    compendium = build.build_compendium(documents, embedder=fake_embed_chunks_core)

    assert compendium.vectors.shape == (len(compendium.children), compendium.embedding.dims)
    assert compendium.vectors.dtype == np.int8
    assert compendium.embedding.dtype == "int8"
    assert compendium.embedding.scale == 127
    assert len(compendium.bm25["docLen"]) == len(compendium.children)


def test_build_compendium_collapses_the_shared_boilerplate_section(
    fixtures_dir, fake_embed_chunks_core
):
    """
    Both fixture pages carry the same disclaimer. Near-duplicate collapse
    keeps the first copy and drops the second, and compaction then removes
    the second page's now-childless section.
    """
    documents = [
        document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team"),
        document_from_fixture(fixtures_dir, "page_boilerplate_b.html", "https://example.org/project"),
    ]

    compendium = build.build_compendium(documents, embedder=fake_embed_chunks_core)

    headings = [parent.t for parent in compendium.parents]
    assert sum("Standard Disclaimer" in heading for heading in headings) == 1
    assert len(compendium.parents) == 3


def test_build_compendium_matches_the_reference_pipeline_on_the_same_fixtures(
    reference, fixtures_dir, fake_embed_chunks, fake_embed_chunks_core
):
    """
    The scored result -- surviving windows, keyword statistics, and
    calibration -- must equal what the frozen script computes for the same
    pages. Only the container's own shape differs.

    The two near-duplicate collapses agree here because the repetition in
    these fixtures is one disclaimer shared by two pages, which is what
    the step is for. They diverge on a page that repeats itself: the port
    keeps such passages and the frozen script discards them. See
    extractium.core.dedup.drop_near_duplicates.
    """
    urls = ("https://example.org/team", "https://example.org/project")
    names = ("page_boilerplate_a.html", "page_boilerplate_b.html")
    documents = [document_from_fixture(fixtures_dir, n, u) for n, u in zip(names, urls)]

    compendium = build.build_compendium(documents, embedder=fake_embed_chunks_core)

    ref_parents, ref_children = [], []
    for document in documents:
        page_parents, page_children = reference.build_parent_and_child_chunks(
            document.title, document.content, document.url
        )
        for child in page_children:
            child["pid"] += len(ref_parents)
        ref_parents.extend(page_parents)
        ref_children.extend(page_children)
    ref_vecs = fake_embed_chunks(ref_children)
    ref_children, ref_vecs, _ = reference.drop_near_duplicates(ref_children, ref_vecs)
    ref_parents, ref_children = reference.remap_parents_after_dedup(ref_parents, ref_children)

    assert [p.t for p in compendium.parents] == [p["t"] for p in ref_parents]
    assert [p.x for p in compendium.parents] == [p["x"] for p in ref_parents]
    assert list(compendium.children.pid) == [c["pid"] for c in ref_children]
    assert compendium.bm25 == reference.build_bm25_index(ref_children)
    assert compendium.calibration == reference.compute_calibration_stats(ref_vecs)
    assert compendium.vectors.tobytes() == reference.quantize_int8(ref_vecs).tobytes()


def test_build_compendium_child_offsets_slice_their_window_out_of_the_parent(
    fixtures_dir, fake_embed_chunks_core
):
    document = document_from_fixture(fixtures_dir, "page_long_section.html", "https://example.org/long")

    compendium = build.build_compendium([document], embedder=fake_embed_chunks_core)

    assert len(compendium.children) > 1
    for pid, start, end in zip(compendium.children.pid, compendium.children.start, compendium.children.end):
        window = build.utf16_slice(compendium.parents[pid].x, start, end)
        assert window.strip() == window
        assert window in compendium.parents[pid].x


def test_build_compendium_offsets_stay_correct_past_the_basic_multilingual_plane(
    fake_embed_chunks_core
):
    # An emoji before the text moves every later UTF-16 offset one unit
    # beyond its Python character position.
    body = "\U0001F600 " + ("Body sentence that is long enough to clear the minimum chunk size. " * 3)
    compendium = build.build_compendium([text_document(body)], embedder=fake_embed_chunks_core)

    parent = compendium.parents[compendium.children.pid[0]]
    start, end = compendium.children.start[0], compendium.children.end[0]
    assert build.utf16_slice(parent.x, start, end)
    assert end <= build.utf16_length(parent.x)


def test_build_compendium_float32_keeps_the_unquantized_vectors(fixtures_dir, fake_embed_chunks_core):
    document = document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team")

    compendium = build.build_compendium(
        [document], embedder=fake_embed_chunks_core, float32_vecs=True
    )

    assert compendium.vectors.dtype == np.float32
    assert compendium.embedding.dtype == "float32"
    assert compendium.embedding.scale is None


def test_build_compendium_names_the_index_after_the_first_page_unless_told_otherwise(
    fixtures_dir, fake_embed_chunks_core
):
    document = document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team")

    from_page = build.build_compendium([document], embedder=fake_embed_chunks_core)
    named = build.build_compendium([document], name="Example Org", embedder=fake_embed_chunks_core)

    assert from_page.name == document.title
    assert named.name == "Example Org"


def test_build_compendium_reports_each_stage_through_the_progress_callback(
    fixtures_dir, fake_embed_chunks_core
):
    document = document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team")
    lines = []

    build.build_compendium([document], embedder=fake_embed_chunks_core, progress=lines.append)

    assert any("section(s)" in line for line in lines)


def test_build_compendium_uses_the_build_time_it_is_given(fixtures_dir, fake_embed_chunks_core):
    document = document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team")

    compendium = build.build_compendium(
        [document], embedder=fake_embed_chunks_core, built_at="2026-01-02T03:04:05Z"
    )

    assert compendium.built_at == "2026-01-02T03:04:05Z"


def test_build_compendium_refuses_a_build_time_that_is_not_utc(fixtures_dir, fake_embed_chunks_core):
    document = document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team")

    with pytest.raises(ValueError, match="UTC"):
        build.build_compendium(
            [document], embedder=fake_embed_chunks_core, built_at="2026-01-02 03:04:05"
        )
