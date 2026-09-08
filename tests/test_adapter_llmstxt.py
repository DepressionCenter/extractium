"""
Summary: Tests for the llms.txt adapter. Pins both generated files against
committed snapshots, checks that the index names each page once however
many sections it contributed, checks the grouping and the excerpt rule,
and checks that local content stays out unless the output opted in.

This file is part of Extractium™
tests/test_adapter_llmstxt.py

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

from extractium.adapters import llmstxt
from extractium.adapters.llmstxt import LlmsTxtAdapter
from tests.test_adapter_container import mixed_compendium, sample_compendium


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


def test_index_starts_with_one_heading_and_a_summary(fixtures_dir, fake_embed_chunks_core):
    body = llmstxt.render_index(sample_compendium(fixtures_dir, fake_embed_chunks_core))

    lines = body.splitlines()
    assert lines[0] == "# Example Org"
    assert lines[2].startswith("> ")
    assert body.count("\n# ") == 0  # exactly one first-level heading


def test_index_groups_pages_under_a_heading_for_their_kind_of_source(
    fixtures_dir, fake_embed_chunks_core
):
    """
    The renderers describe whatever compendium they are handed; the
    local-content guardrail runs once in write() and hands them the
    filtered result. Both source types are present here because this
    renders the unfiltered build directly.
    """
    body = llmstxt.render_index(mixed_compendium(fixtures_dir, fake_embed_chunks_core))

    assert "## Web pages" in body
    assert "## Local documents" in body
    assert body.index("## Web pages") < body.index("## Local documents")


def test_index_omits_a_heading_for_a_source_type_with_no_pages(
    fixtures_dir, fake_embed_chunks_core
):
    body = llmstxt.render_index(sample_compendium(fixtures_dir, fake_embed_chunks_core))

    assert "## Web pages" in body
    assert "## Knowledge base articles" not in body


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
