"""
Summary: Tests pinning extractium.core.chunk's parent/child (small-to-big)
chunking behavior: split_into_parents (headings vs. no headings, long-
section hard split), split_parent_into_children (fixed-step window,
overlap, forward-progress guarantee), build_parent_and_child_chunks
(per-page local pid indices), the stable parent identifiers, and
chunk_document. Mirrors tests/test_chunking.py (which pins the same
behavior on the frozen reference script) against the real, ported
implementation. The port matches the reference on every field the
reference has; the id and metadata fields are additions the reference
never had (docs/architecture.md, decision 3).

This file is part of Extractium™
tests/test_core_chunking.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-04
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
__date__ = "2026-09-04"

from bs4 import BeautifulSoup

from extractium.core import chunk
from extractium.core.models import Document
from extractium.sources.generic import GenericHandler
from extractium.sources.tdx import TdxHandler


def _soup_from_fixture(fixtures_dir, name):
    text = (fixtures_dir / name).read_text(encoding="utf-8")
    return BeautifulSoup(text, "html.parser")


def _extract(fixtures_dir, name, url):
    """Reads a fixture the way the crawl would: through the handler that claims its URL."""
    soup = _soup_from_fixture(fixtures_dir, name)
    handler = TdxHandler() if TdxHandler().matches(url) else GenericHandler()
    return handler.extract(soup, url)


# ---------------------------------------------------------------------------
# split_into_parents
# ---------------------------------------------------------------------------

def test_split_into_parents_no_headings_yields_single_parent(fixtures_dir):
    url = "https://example.org/plain"
    extraction = _extract(fixtures_dir, "page_no_headings.html", url)
    node, title = extraction.node, extraction.title

    parents = chunk.split_into_parents(title, node, url)

    assert len(parents) == 1
    assert parents[0]["t"] == title
    assert "no h2 or h3 headings" in parents[0]["x"]
    assert parents[0]["weight"] == 1.0
    assert parents[0]["id"] == chunk.parent_id(url, title, 0)


def test_split_into_parents_with_headings_yields_one_parent_per_section(fixtures_dir):
    url = "https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1"
    extraction = _extract(fixtures_dir, "tdx_article.html", url)
    node, title = extraction.node, extraction.title

    parents = chunk.split_into_parents(title, node, url)

    # No content precedes the first <h2> in the fixture, so the "before
    # first heading" chunk is empty and dropped (< CHUNK_MIN_CHARS) -- only
    # the two real sections survive.
    assert len(parents) == 2
    assert parents[0]["t"] == f"{title} -- Getting Started"
    assert "sleep-hygiene guidance" in parents[0]["x"]
    assert parents[1]["t"] == f"{title} -- Reducing Screen Time"
    assert "reducing screen time" in parents[1]["x"]
    assert [p["id"] for p in parents] == [chunk.parent_id(url, p["t"], 0) for p in parents]


def test_split_into_parents_hard_splits_long_section_without_newlines(fixtures_dir):
    url = "https://example.org/long-section"
    extraction = _extract(fixtures_dir, "page_long_section.html", url)
    node, title = extraction.node, extraction.title

    parents = chunk.split_into_parents(title, node, url)

    assert len(parents) == 3
    assert all(len(p["x"]) <= chunk.CHUNK_MAX_CHARS for p in parents)
    # The source paragraph has no embedded newline, so
    # text.rfind("\n", 0, CHUNK_MAX_CHARS) always finds nothing and the
    # code falls back to a hard cut at exactly CHUNK_MAX_CHARS for every
    # chunk except the final remainder.
    assert len(parents[0]["x"]) == chunk.CHUNK_MAX_CHARS
    assert len(parents[1]["x"]) == chunk.CHUNK_MAX_CHARS
    assert len(parents[2]["x"]) < chunk.CHUNK_MAX_CHARS


# ---------------------------------------------------------------------------
# split_parent_into_children
# ---------------------------------------------------------------------------

def _make_parent(text):
    return {"id": "0" * 16, "t": "T", "x": text, "u": "https://example.org/x", "host": "example.org", "weight": 1.0}


def test_split_parent_into_children_short_parent_is_single_child():
    parent = _make_parent("Short body text well under the child chunk threshold.")
    children = chunk.split_parent_into_children(parent)
    assert children == [dict(parent)]


def test_split_parent_into_children_window_stepping_and_overlap():
    # A digit-repeating pattern makes every position content-identifiable,
    # so the overlap assertion below checks actual shared content, not
    # just shared length.
    text = "".join(str(i % 10) for i in range(1000))
    parent = _make_parent(text)

    children = chunk.split_parent_into_children(parent)

    step = max(
        chunk.CHILD_CHUNK_MAX_CHARS - chunk.CHILD_OVERLAP_CHARS,
        chunk.CHILD_CHUNK_MIN_CHARS,
    )
    assert step == 297  # max(350 - 53, 60)

    # Starts at 0, 297, 594, 891; the last window's end clamps to n=1000.
    assert len(children) == 4
    assert all(len(c["x"]) <= chunk.CHILD_CHUNK_MAX_CHARS for c in children)
    assert len(children[0]["x"]) == chunk.CHILD_CHUNK_MAX_CHARS
    assert len(children[-1]["x"]) == 1000 - 891  # final, shorter window

    # Overlap: the tail of window i is the head of window i+1, exactly
    # CHILD_OVERLAP_CHARS (53) characters wide.
    for i in range(len(children) - 1):
        overlap = chunk.CHILD_OVERLAP_CHARS
        assert children[i]["x"][-overlap:] == children[i + 1]["x"][:overlap]


def test_split_parent_into_children_guarantees_forward_progress():
    # A pathological case with a newline landing right at the start of
    # every window would make text.rfind("\n", start, end) return `start`
    # itself were the step tied to `cut` -- the fixed step must still make
    # progress every iteration regardless.
    text = ("\n" + "x" * 400) * 3
    parent = _make_parent(text)
    children = chunk.split_parent_into_children(parent)
    assert len(children) >= 1
    assert all(len(c["x"]) > 0 for c in children)


# ---------------------------------------------------------------------------
# build_parent_and_child_chunks
# ---------------------------------------------------------------------------

def test_build_parent_and_child_chunks_assigns_local_pid_indices(fixtures_dir):
    url = "https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1"
    extraction = _extract(fixtures_dir, "tdx_article.html", url)
    node, title = extraction.node, extraction.title

    parents, children = chunk.build_parent_and_child_chunks(title, node, url)

    assert len(parents) == 2
    # Each parent here is short enough to yield exactly one child.
    assert len(children) == 2
    assert children[0]["pid"] == 0
    assert children[1]["pid"] == 1
    assert children[0]["t"] == parents[0]["t"]
    assert children[1]["t"] == parents[1]["t"]


# ---------------------------------------------------------------------------
# Stable parent identifiers (docs/extractium-spec.md section 3.3)
# ---------------------------------------------------------------------------

def test_parent_id_is_sixteen_lowercase_hex_characters():
    identifier = chunk.parent_id("https://example.org/x", "Page -- Section", 0)
    assert len(identifier) == chunk.PARENT_ID_HEX_CHARS == 16
    assert identifier == identifier.lower()
    int(identifier, 16)  # every character is hexadecimal


def test_parent_id_is_stable_across_runs_and_changes_with_each_input():
    base = chunk.parent_id("https://example.org/x", "Heading", 0)
    assert chunk.parent_id("https://example.org/x", "Heading", 0) == base
    assert chunk.parent_id("https://example.org/y", "Heading", 0) != base
    assert chunk.parent_id("https://example.org/x", "Other", 0) != base
    assert chunk.parent_id("https://example.org/x", "Heading", 1) != base


def test_parent_id_ignores_trailing_slash_and_fragment_in_the_url():
    base = chunk.parent_id("https://example.org/x", "Heading", 0)
    assert chunk.parent_id("https://example.org/x/", "Heading", 0) == base
    assert chunk.parent_id("https://example.org/x#top", "Heading", 0) == base


def test_child_id_is_derived_from_the_parent_id():
    assert chunk.child_id("0123456789abcdef", 2) == "0123456789abcdef-2"


def test_split_sections_sharing_a_heading_get_distinct_ids(fixtures_dir):
    url = "https://example.org/long-section"
    extraction = _extract(fixtures_dir, "page_long_section.html", url)
    parents = chunk.split_into_parents(extraction.title, extraction.node, url)

    assert len(parents) == 3
    assert len({p["t"] for p in parents}) == 1        # one heading, cut three times
    assert len({p["id"] for p in parents}) == 3       # three distinct ids
    assert [p["id"] for p in parents] == [chunk.parent_id(url, parents[0]["t"], i) for i in range(3)]


def test_ids_are_identical_across_two_chunking_runs(fixtures_dir):
    url = "https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1"
    first = _extract(fixtures_dir, "tdx_article.html", url)
    second = _extract(fixtures_dir, "tdx_article.html", url)
    ids_first = [p["id"] for p in chunk.split_into_parents(first.title, first.node, url)]
    ids_second = [p["id"] for p in chunk.split_into_parents(second.title, second.node, url)]
    assert ids_first == ids_second


def test_children_carry_their_parent_id(fixtures_dir):
    url = "https://example.org/long-section"
    extraction = _extract(fixtures_dir, "page_long_section.html", url)
    parents, children = chunk.build_parent_and_child_chunks(extraction.title, extraction.node, url)
    assert all(c["id"] == parents[c["pid"]]["id"] for c in children)


# ---------------------------------------------------------------------------
# chunk_document
# ---------------------------------------------------------------------------

def test_chunk_document_stamps_document_metadata_on_parents_and_children(fixtures_dir):
    url = "https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1"
    extraction = _extract(fixtures_dir, "tdx_article.html", url)
    document = Document(
        url=url, title=extraction.title, content=extraction.node,
        source_type="kb", content_type="article", categories=("Knowledge Base", "Sleep"), weight=2.0,
    )

    parents, children = chunk.chunk_document(document)

    assert len(parents) == 2 and len(children) == 2
    for record in parents + children:
        assert record["source_type"] == "kb"
        assert record["content_type"] == "article"
        assert record["categories"] == ("Knowledge Base", "Sleep")
        assert record["local"] is False
        assert record["weight"] == 2.0
        assert record["host"] == "teamdynamix.umich.edu"
    assert [c["pid"] for c in children] == [0, 1]


def test_chunk_document_matches_build_parent_and_child_chunks_on_shared_fields(fixtures_dir):
    url = "https://example.org/plain"
    extraction = _extract(fixtures_dir, "page_no_headings.html", url)
    document = Document(url=url, title=extraction.title, content=extraction.node,
                        source_type="web", content_type="page")
    shared = ("id", "t", "x", "u", "host", "weight")

    parents, children = chunk.chunk_document(document)
    ref_parents, ref_children = chunk.build_parent_and_child_chunks(extraction.title, extraction.node, url)

    assert [{k: p[k] for k in shared} for p in parents] == ref_parents
    assert [{k: c[k] for k in shared + ("pid",)} for c in children] == ref_children


def test_chunk_document_wraps_plain_text_content():
    text = "Plain text content long enough to clear the sixty character minimum chunk size threshold.\n"
    document = Document(url="local:notes/readme.txt", title="Readme", content=text,
                        source_type="local", content_type="text", local=True)

    parents, children = chunk.chunk_document(document)

    assert len(parents) == 1
    assert parents[0]["x"].startswith("Plain text content")
    assert parents[0]["host"] == ""            # a local: URL has no host
    assert parents[0]["local"] is True
    assert children[0]["pid"] == 0


def test_chunk_document_renders_markdown_content_headings_as_sections():
    text = (
        "# Notes\n\nIntro paragraph long enough to clear the minimum chunk size threshold for a parent.\n\n"
        "## First\n\nFirst section body, also long enough to clear the minimum chunk size threshold.\n"
    )
    document = Document(url="local:notes/guide.md", title="Guide", content=text,
                        source_type="local", content_type="text", local=True)

    parents, _ = chunk.chunk_document(document)

    assert [p["t"] for p in parents] == ["Guide", "Guide -- First"]
