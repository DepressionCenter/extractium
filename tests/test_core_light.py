"""
Summary: Tests for the light compendium: one section per page holding the
page's description and keywords, no code records, nothing dropped for
being short or alike, and the same scoring fields as the full one.

This file is part of Extractium™
tests/test_core_light.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-17
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

from dataclasses import replace

from extractium.core import light
from extractium.core.build import build_compendium, utf16_slice
from extractium.core.models import CODE_CONTENT_TYPES, Document

BUILT_AT = "2026-01-02T03:04:05Z"

SECTION = (
    "Sleep data from a wearable device is summarized nightly, and this part of the page "
    "explains how the summary is produced and where the figures in it come from."
)


def page(url, title, text=SECTION, **fields):
    """One synthetic page. Web pages are the default; a test overrides what it is about."""
    fields.setdefault("source_type", "web")
    fields.setdefault("content_type", "text")
    return Document(url=url, title=title, content=text, **fields)


def built(embedder, documents, **enrichment):
    """
    A compendium of the documents, with the given enrichment fields set on
    every section, which is what a build's keyword step leaves behind.
    """
    compendium = build_compendium(documents, name="Example Org", embedder=embedder, built_at=BUILT_AT)
    if not enrichment:
        return compendium
    return replace(compendium, parents=tuple(replace(parent, **enrichment) for parent in compendium.parents))


# ---------------------------------------------------------------------------
# Light sections
# ---------------------------------------------------------------------------

def test_a_light_section_is_one_per_page_and_holds_the_description_and_keywords(fake_embed_chunks_core):
    two_sections = f"# Page A\n\n## First\n\n{SECTION}\n\n## Second\n\n{SECTION.replace('Sleep', 'Activity')}\n"
    compendium = built(
        fake_embed_chunks_core, [page("https://example.org/a.md", "Page A", two_sections)],
        summary="What page A covers.", keywords=("sleep", "wearables"),
    )
    assert len(compendium.parents) > 1

    (section,) = light.light_parents(compendium)

    assert section.u == "https://example.org/a.md"
    assert section.t == "Page A"
    assert section.x == "What page A covers.\n\nKeywords: sleep, wearables."
    assert section.keywords == ("sleep", "wearables")
    assert section.summary is None
    assert section.id == compendium.parents[0].id


def test_a_page_described_by_its_keywords_does_not_repeat_them(fake_embed_chunks_core):
    compendium = built(fake_embed_chunks_core, [page("https://example.org/a", "Page A")],
                       keywords=("sleep", "wearables"))
    assert light.light_parents(compendium)[0].x == "Keywords: sleep, wearables."


def test_a_page_from_a_local_source_stays_local(fake_embed_chunks_core):
    compendium = built(fake_embed_chunks_core, [
        page("local:notes/internal.txt", "Internal Notes", source_type="local", local=True),
    ])
    assert light.light_parents(compendium)[0].local is True


# ---------------------------------------------------------------------------
# The light compendium
# ---------------------------------------------------------------------------

def test_the_light_compendium_has_no_code_and_keeps_the_keywords(fake_embed_chunks_core):
    compendium = built(fake_embed_chunks_core, [
        page("https://example.org/a", "Page A"),
        page("https://github.com/example/tool/blob/main/run.py", "run.py",
             SECTION.replace("Sleep", "Code about sleep"), source_type="github", content_type="code_file"),
    ], keywords=("sleep",))

    result = light.build_light_compendium(compendium, embedder=fake_embed_chunks_core)

    assert all(parent.content_type not in CODE_CONTENT_TYPES for parent in result.parents)
    assert len(result.parents) < len(compendium.parents)
    assert all(parent.keywords == ("sleep",) for parent in result.parents)
    assert result.built_at == compendium.built_at
    assert result.name == compendium.name
    assert result.embedding == compendium.embedding


def test_short_and_identical_descriptions_each_keep_their_page(fake_embed_chunks_core):
    # "Keywords: sleep." is far shorter than the chunker's minimum section,
    # and both pages carry exactly the same words.
    compendium = built(fake_embed_chunks_core, [
        page("https://example.org/a", "Page A"),
        page("https://example.org/b", "Page B", SECTION.replace("nightly", "weekly")),
    ], keywords=("sleep",))

    result = light.build_light_compendium(compendium, embedder=fake_embed_chunks_core)

    assert [parent.u for parent in result.parents] == ["https://example.org/a", "https://example.org/b"]
    assert [parent.x for parent in result.parents] == ["Keywords: sleep.", "Keywords: sleep."]


def test_every_window_reads_back_out_of_its_section(fake_embed_chunks_core):
    # A summary with a character outside the Basic Multilingual Plane, and
    # enough keywords that the section is split into more than one window.
    compendium = built(
        fake_embed_chunks_core, [page("https://example.org/a", "Page A")],
        summary="Sleep \U0001F634 " + "and wearable devices " * 12,
        keywords=tuple(f"keyword number {n}" for n in range(12)),
    )

    result = light.build_light_compendium(compendium, embedder=fake_embed_chunks_core)

    assert len(result.children) > 1
    assert result.vectors.shape[0] == len(result.children)
    assert len(result.bm25["docLen"]) == len(result.children)
    for pid, start, end in zip(result.children.pid, result.children.start, result.children.end):
        window = utf16_slice(result.parents[pid].x, start, end)
        assert window and window == window.strip()


def test_float32_vectors_stay_float32(fake_embed_chunks_core):
    compendium = build_compendium([page("https://example.org/a", "Page A")], name="Example Org",
                                  embedder=fake_embed_chunks_core, built_at=BUILT_AT, float32_vecs=True)
    result = light.build_light_compendium(compendium, embedder=fake_embed_chunks_core)
    assert str(result.vectors.dtype) == "float32"


def test_a_build_of_code_alone_has_no_light_compendium(fake_embed_chunks_core):
    compendium = built(fake_embed_chunks_core, [
        page("https://github.com/example/tool/blob/main/run.py", "run.py",
             source_type="github", content_type="code_file"),
    ])
    assert light.build_light_compendium(compendium, embedder=fake_embed_chunks_core) is None


def test_the_light_compendium_measures_its_own_unrelated_figures_with_the_builds_probes(fake_embed_chunks_core):
    compendium = built(fake_embed_chunks_core, [
        page("https://example.org/a", "Page A"),
        page("https://example.org/b", "Page B", SECTION.replace("nightly", "weekly")),
    ], summary="What the page covers.")

    result = light.build_light_compendium(compendium, embedder=fake_embed_chunks_core)

    assert result.probe_vectors is compendium.probe_vectors
    assert result.calibration["unrelatedProbes"] == len(compendium.probe_vectors)
    # Measured against the light windows, not copied from the full ones.
    assert result.calibration["unrelatedMedian"] != compendium.calibration["unrelatedMedian"]
