"""
Summary: Tests for the llms.txt adapter. Pins both generated files against
committed snapshots, checks that the index names each page once however
many sections it contributed, checks the grouping and the excerpt rule,
and checks that local content stays out unless the output opted in.

This file is part of Extractium™
tests/test_adapter_llmstxt.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
Last Modified: 2026-09-09
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

import dataclasses

from extractium.adapters import llmstxt
from extractium.adapters.llmstxt import LlmsTxtAdapter
from tests.test_adapter_container import (
    FIXED_BUILT_AT,
    mixed_compendium,
    sample_compendium,
)
from tests.test_build import document_from_fixture

from extractium.core import build


def two_website_compendium(fixtures_dir, embedder, second_label="Peer Program"):
    """
    Two pages from two sources that are both websites, so only the label
    separates them.

    Args:
        fixtures_dir (pathlib.Path): the tests/fixtures folder.
        embedder (Callable): the deterministic test embedder.
        second_label (str): label for the second source. Passing the first
            source's label proves two sources can share one heading.
    """
    documents = [
        dataclasses.replace(
            document_from_fixture(
                fixtures_dir, "page_boilerplate_a.html", "https://example.org/team"
            ),
            source_label="Main Website",
        ),
        dataclasses.replace(
            document_from_fixture(
                fixtures_dir, "page_boilerplate_b.html", "https://peer.example.org/about"
            ),
            source_label=second_label,
        ),
    ]
    return build.build_compendium(
        documents, name="Example Org", embedder=embedder, built_at=FIXED_BUILT_AT
    )


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def test_page_title_drops_the_section_part_of_a_heading():
    assert llmstxt.page_title("Team Directory -- Members") == "Team Directory"
    assert llmstxt.page_title("Team Directory") == "Team Directory"


def test_excerpt_collapses_whitespace_and_cuts_at_a_word_boundary():
    assert llmstxt.excerpt("one\n  two\tthree") == "one two three"

    cut = llmstxt.excerpt("alpha bravo charlie delta", limit=12)

    assert cut == "alpha bravo..."
    assert " ." not in cut


def test_excerpt_leaves_short_text_alone():
    assert llmstxt.excerpt("short enough") == "short enough"


def test_link_escapes_a_title_that_would_end_the_link_early():
    assert llmstxt.link("Guide [draft]", "https://example.org/g") == (
        "[Guide \\[draft\\]](https://example.org/g)"
    )


def test_link_encodes_url_characters_that_would_end_the_link_early():
    assert llmstxt.link("Guide", "https://example.org/a(b)c d") == (
        "[Guide](https://example.org/a%28b%29c%20d)"
    )


def test_link_leaves_an_ordinary_title_and_url_alone():
    assert llmstxt.link("Guide", "https://example.org/g") == "[Guide](https://example.org/g)"


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def test_index_file_matches_the_committed_snapshot(fixtures_dir, golden_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    assert llmstxt.render_index(compendium) == (golden_dir / "llms.txt").read_text(encoding="utf-8")


def test_full_file_matches_the_committed_snapshot(fixtures_dir, golden_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    assert llmstxt.render_full(compendium) == (golden_dir / "llms-full.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_index_names_each_page_once_however_many_sections_it_contributed(
    fixtures_dir, fake_embed_chunks_core
):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    body = llmstxt.render_index(compendium)

    assert len(compendium.parents) == 3
    assert body.count("https://example.org/team)") == 1
    assert body.count("https://example.org/project)") == 1


# ---------------------------------------------------------------------------
# Orientation for a reader arriving with no context
# ---------------------------------------------------------------------------

def test_source_hosts_are_listed_once_in_first_appearance_order(
    fixtures_dir, fake_embed_chunks_core
):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    assert llmstxt.source_hosts(compendium.parents) == ("example.org",)


def test_source_hosts_skip_local_files_which_have_none(fixtures_dir, fake_embed_chunks_core):
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)

    assert "" not in llmstxt.source_hosts(compendium.parents)


def test_name_sites_counts_the_ones_past_the_limit_instead_of_listing_them():
    assert llmstxt.name_sites(()) == ""
    assert llmstxt.name_sites(("a.edu",)) == "a.edu"
    assert llmstxt.name_sites(("a.edu", "b.org")) == "a.edu and b.org"
    assert llmstxt.name_sites(("a.edu", "b.org", "c.gov")) == "a.edu, b.org and c.gov"
    assert llmstxt.name_sites(("a.edu", "b.org", "c.gov", "d.net")) == (
        "a.edu, b.org, c.gov and 1 other site"
    )
    assert llmstxt.name_sites(("a.edu", "b.org", "c.gov", "d.net", "e.io")) == (
        "a.edu, b.org, c.gov and 2 other sites"
    )


def test_count_of_reads_correctly_in_either_number():
    assert llmstxt.count_of(1, "page") == "1 page"
    assert llmstxt.count_of(2, "page") == "2 pages"
    assert llmstxt.count_of(0, "page") == "0 pages"


def test_summary_says_what_the_knowledge_base_is_where_it_came_from_and_when(
    fixtures_dir, fake_embed_chunks_core
):
    """
    A model arriving at this file cold needs the blockquote to explain the
    rest of it, which is what the llms.txt convention reserves it for.
    """
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    line = llmstxt.summary(compendium, page_count=2)

    assert line.startswith("> ")
    assert "knowledge base of 3 sections" in line
    assert "drawn from 2 pages on example.org" in line
    assert compendium.built_at in line
    # The heading directly above already carries the name.
    assert not line.startswith(f"> {compendium.name}")


def test_index_explains_that_it_is_an_index_and_points_at_the_full_text(
    fixtures_dir, fake_embed_chunks_core
):
    body = llmstxt.render_index(sample_compendium(fixtures_dir, fake_embed_chunks_core))

    assert "This file is an index, not the content itself." in body
    assert "llms-full.txt" in body


def test_full_file_explains_that_it_is_the_content_and_points_at_the_index(
    fixtures_dir, fake_embed_chunks_core
):
    body = llmstxt.render_full(sample_compendium(fixtures_dir, fake_embed_chunks_core))

    assert "This file holds the complete text of every page indexed" in body
    assert "llms.txt, written alongside this file" in body


def test_the_orientation_uses_no_headings_of_its_own(fixtures_dir, fake_embed_chunks_core):
    """
    The llms.txt convention allows free-form prose between the summary and
    the link sections but no headings there, because a heading starts a new
    section for a parser reading the file (https://llmstxt.org/).
    """
    for body in (llmstxt.render_index(sample_compendium(fixtures_dir, fake_embed_chunks_core)),
                 llmstxt.render_full(sample_compendium(fixtures_dir, fake_embed_chunks_core))):
        before_sections = body.split("\n## ", 1)[0]
        headings = [line for line in before_sections.splitlines() if line.startswith("#")]
        assert headings == ["# Example Org"]


def test_index_starts_with_one_heading_and_a_summary(fixtures_dir, fake_embed_chunks_core):
    body = llmstxt.render_index(sample_compendium(fixtures_dir, fake_embed_chunks_core))

    lines = body.splitlines()
    assert lines[0] == "# Example Org"
    assert lines[2].startswith("> ")
    assert body.count("\n# ") == 0  # exactly one first-level heading


def test_index_groups_pages_under_the_name_of_the_source_they_came_from(
    fixtures_dir, fake_embed_chunks_core
):
    """
    The renderers describe whatever compendium they are handed; the
    local-content guardrail runs once in write() and hands them the
    filtered result. Both sources are present here because this renders
    the unfiltered build directly.
    """
    body = llmstxt.render_index(mixed_compendium(fixtures_dir, fake_embed_chunks_core))

    assert "## Website" in body
    assert "## Local Files" in body
    assert body.index("## Website") < body.index("## Local Files")


def test_index_heads_only_the_sources_that_contributed_a_page(
    fixtures_dir, fake_embed_chunks_core
):
    body = llmstxt.render_index(sample_compendium(fixtures_dir, fake_embed_chunks_core))

    assert "## Website" in body
    assert "## Local Files" not in body


def test_index_tells_two_sources_of_the_same_kind_apart(fixtures_dir, fake_embed_chunks_core):
    """
    The reason a label exists. Both of these are web sources, so grouping
    by source_type would pile them under one heading and a reader could
    not tell the main site from the program microsite.
    """
    compendium = two_website_compendium(fixtures_dir, fake_embed_chunks_core)

    body = llmstxt.render_index(compendium)

    assert "## Main Website" in body
    assert "## Peer Program" in body
    assert body.index("## Main Website") < body.index("## Peer Program")


def test_index_orders_its_sections_the_way_the_sources_were_listed(
    fixtures_dir, fake_embed_chunks_core
):
    """First appearance, which is configuration order, not alphabetical."""
    compendium = two_website_compendium(fixtures_dir, fake_embed_chunks_core)

    assert llmstxt.labels_in_order(
        llmstxt.pages_in_order(compendium.parents)
    ) == ["Main Website", "Peer Program"]


def test_index_keeps_two_sources_sharing_a_label_in_one_section(
    fixtures_dir, fake_embed_chunks_core
):
    """
    Two sibling collections of one repository are one place to a person
    looking for an answer, so one label means one heading.
    """
    compendium = two_website_compendium(
        fixtures_dir, fake_embed_chunks_core, second_label="Main Website"
    )

    body = llmstxt.render_index(compendium)

    assert body.count("## Main Website") == 1


def test_full_file_gives_every_section_its_own_heading_and_source_line(
    fixtures_dir, fake_embed_chunks_core
):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    body = llmstxt.render_full(compendium)

    for parent in compendium.parents:
        assert f"## {parent.t}" in body
        assert parent.x in body
    assert body.count("Source: ") == len(compendium.parents)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def test_write_produces_both_files(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    paths = LlmsTxtAdapter().write(compendium, tmp_path, {})

    assert [p.name for p in paths] == ["llms.txt", "llms-full.txt"]
    assert all(p.read_text(encoding="utf-8").endswith("\n") for p in paths)


def test_write_keeps_local_content_out_unless_the_output_opted_in(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)

    excluded = LlmsTxtAdapter().write(compendium, tmp_path / "public", {"include_local": False})
    included = LlmsTxtAdapter().write(compendium, tmp_path / "private", {"include_local": True})

    for path in excluded:
        assert "Internal note" not in path.read_text(encoding="utf-8")
        assert "local:" not in path.read_text(encoding="utf-8")
    assert any("Internal note" in path.read_text(encoding="utf-8") for path in included)
