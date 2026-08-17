"""
Summary: Tests pinning extractium.core.chunk's parent/child (small-to-big)
chunking behavior: split_into_parents (headings vs. no headings, long-
section hard split), split_parent_into_children (fixed-step window,
overlap, forward-progress guarantee), and build_parent_and_child_chunks
(per-page local pid indices). Mirrors tests/test_chunking.py (which pins
the same behavior on the frozen reference script) against the real,
ported implementation, proving the port is behavior-identical.

This file is part of Extractium™
tests/test_core_chunking.py

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

from bs4 import BeautifulSoup

from extractium.core import chunk


def _soup_from_fixture(fixtures_dir, name):
    text = (fixtures_dir / name).read_text(encoding="utf-8")
    return BeautifulSoup(text, "html.parser")


# ---------------------------------------------------------------------------
# split_into_parents
# ---------------------------------------------------------------------------

def test_split_into_parents_no_headings_yields_single_parent(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "page_no_headings.html")
    url = "https://example.org/plain"
    node = chunk.extract_content(soup, url)
    title = chunk.get_title(soup, url)

    parents = chunk.split_into_parents(title, node, url)

    assert len(parents) == 1
    assert parents[0]["t"] == title
    assert "no h2 or h3 headings" in parents[0]["x"]
    assert parents[0]["weight"] == 1.0
    assert parents[0]["kind"] == "page"


def test_split_into_parents_with_headings_yields_one_parent_per_section(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "tdx_article.html")
    url = "https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1"
    node = chunk.extract_content(soup, url)
    title = chunk.get_title(soup, url)

    parents = chunk.split_into_parents(title, node, url)

    # No content precedes the first <h2> in the fixture, so the "before
    # first heading" chunk is empty and dropped (< CHUNK_MIN_CHARS) -- only
    # the two real sections survive.
    assert len(parents) == 2
    assert parents[0]["t"] == f"{title} -- Getting Started"
    assert "sleep-hygiene guidance" in parents[0]["x"]
    assert parents[1]["t"] == f"{title} -- Reducing Screen Time"
    assert "reducing screen time" in parents[1]["x"]
    assert all(p["kind"] == "kb" for p in parents)


def test_split_into_parents_hard_splits_long_section_without_newlines(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "page_long_section.html")
    url = "https://example.org/long-section"
    node = chunk.extract_content(soup, url)
    title = chunk.get_title(soup, url)

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
    return {"t": "T", "x": text, "u": "https://example.org/x", "host": "example.org", "kind": "page", "weight": 1.0}


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
    soup = _soup_from_fixture(fixtures_dir, "tdx_article.html")
    url = "https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1"
    node = chunk.extract_content(soup, url)
    title = chunk.get_title(soup, url)

    parents, children = chunk.build_parent_and_child_chunks(title, node, url)

    assert len(parents) == 2
    # Each parent here is short enough to yield exactly one child.
    assert len(children) == 2
    assert children[0]["pid"] == 0
    assert children[1]["pid"] == 1
    assert children[0]["t"] == parents[0]["t"]
    assert children[1]["t"] == parents[1]["t"]
