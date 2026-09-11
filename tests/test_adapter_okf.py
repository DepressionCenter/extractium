"""
Summary: Tests for the Open Knowledge Format adapter. Checks the front
matter of every concept file against the fields the format asks for,
checks that a page split into several sections stays one concept, checks
the two reserved files, checks that file names built from untrusted titles
stay inside the bundle, checks that the same content written from three
different kinds of source produces the same structure, and checks that
local content stays out unless the output opted in.

This file is part of Extractium™
tests/test_adapter_okf.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-11
Last Modified: 2026-09-11
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
__date__ = "2026-09-11"

import pathlib
import re

import pytest
import yaml

from extractium.adapters import okf
from extractium.adapters.okf import OkfAdapter
from extractium.core import build
from extractium.core.models import Document
from tests.test_adapter_container import (
    FIXED_BUILT_AT,
    mixed_compendium,
    sample_compendium,
)

# One long block of text, so the chunker keeps a document as a section of
# its own rather than dropping it for being too short.
BODY = (
    "The team keeps office hours every week, and the notes from each session are "
    "posted the following morning so that anyone who could not attend can still "
    "follow what was decided and what is still open."
)


# A second block of text, different enough from the first that neither
# page is taken for a copy of the other.
RELEASE_BODY = (
    "Every release is announced here, with the date it went out, what changed in "
    "it, and who to ask when something looks wrong. Older announcements stay on "
    "the page so that a reader can follow how a feature reached its current shape."
)


def bundle_of(compendium, out_dir, options=None):
    """
    Writes a bundle and returns its folder.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        out_dir (pathlib.Path): the folder the build writes under.
        options (dict | None): the output's options.

    Returns:
        pathlib.Path: the bundle folder inside out_dir.
    """
    OkfAdapter().write(compendium, out_dir, options or {})
    return out_dir / okf.BUNDLE_DIR


def concept_files(folder):
    """Every concept file in a bundle, sorted, with the two reserved files left out."""
    reserved = {okf.INDEX_FILE, okf.LOG_FILE}
    return sorted(p for p in folder.rglob("*.md") if p.name not in reserved)


def front_matter_of(path):
    """The parsed front matter of one Markdown file, and the body after it."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} has no front matter"
    block, _, body = text[4:].partition("\n---\n")
    return yaml.safe_load(block), body


def one_page_compendium(embedder, **fields):
    """A single plain-text page, with whatever record fields a test needs."""
    document = Document(
        url=fields.pop("url", "https://example.org/office-hours"),
        title=fields.pop("title", "Office Hours"),
        content=fields.pop("content", BODY),
        source_type=fields.pop("source_type", "web"),
        content_type=fields.pop("content_type", "page"),
        **fields,
    )
    return build.build_compendium(
        [document], name="Example Org", embedder=embedder, built_at=FIXED_BUILT_AT
    )


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------

def test_every_concept_file_carries_the_fields_the_format_asks_for(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    folder = bundle_of(sample_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path)

    files = concept_files(folder)
    assert files
    for path in files:
        fields, _ = front_matter_of(path)
        assert list(fields) == [
            "type", "title", "description", "resource", "tags", "generated", "sources",
        ]


def test_the_one_required_field_is_never_empty(tmp_path, fixtures_dir, fake_embed_chunks_core):
    """
    A bundle is conformant only if every concept document carries a
    non-empty `type`, so this is the check that decides whether a reader
    accepts the folder at all.
    """
    folder = bundle_of(sample_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path)

    for path in concept_files(folder):
        fields, _ = front_matter_of(path)
        assert isinstance(fields["type"], str) and fields["type"].strip()


def test_the_type_names_the_kind_of_document_the_record_holds(tmp_path, fake_embed_chunks_core):
    compendium = one_page_compendium(fake_embed_chunks_core, content_type="readme")

    folder = bundle_of(compendium, tmp_path)

    fields, _ = front_matter_of(concept_files(folder)[0])
    assert fields["type"] == "Project README"


def test_a_content_type_this_adapter_has_no_name_for_still_gets_one():
    assert okf.concept_type("something_a_plugin_invented") == okf.DEFAULT_CONCEPT_TYPE


def test_the_resource_is_the_address_the_page_was_read_from(tmp_path, fake_embed_chunks_core):
    compendium = one_page_compendium(fake_embed_chunks_core)

    folder = bundle_of(compendium, tmp_path)

    fields, _ = front_matter_of(concept_files(folder)[0])
    assert fields["resource"] == "https://example.org/office-hours"
    assert fields["sources"] == [{"resource": "https://example.org/office-hours",
                                 "title": "Office Hours"}]


def test_the_build_records_which_tool_wrote_the_concept_and_when(
    tmp_path, fake_embed_chunks_core
):
    folder = bundle_of(one_page_compendium(fake_embed_chunks_core), tmp_path)

    fields, _ = front_matter_of(concept_files(folder)[0])
    assert fields["generated"]["by"] == okf.PRODUCER
    assert re.match(r"^extractium/\d", fields["generated"]["by"])
    assert fields["generated"]["at"] == FIXED_BUILT_AT


def test_tags_name_the_source_the_kind_and_the_categories(tmp_path, fake_embed_chunks_core):
    compendium = one_page_compendium(
        fake_embed_chunks_core, source_label="Staff Handbook", categories=("Policies", "Leave"),
    )

    folder = bundle_of(compendium, tmp_path)

    fields, _ = front_matter_of(concept_files(folder)[0])
    assert fields["tags"] == ["Staff Handbook", "Web Page", "Policies", "Leave"]


def test_a_tag_that_repeats_another_is_written_once():
    page = {
        "source_label": "Web Page",
        "content_type": "page",
        "categories": ("Web Page", "", "Leave"),
    }

    assert okf.tags_for(page) == ["Web Page", "Leave"]


def test_a_title_that_would_break_the_front_matter_is_still_read_back(
    tmp_path, fake_embed_chunks_core
):
    """
    Page titles come from sites nobody here controls. A title holding a
    colon, a quotation mark, or a line that looks like the end of the
    block has to be quoted by the writer, or the file stops parsing and
    the text after it is read as front matter.
    """
    hostile = 'Notes: "quoted", and --- a fence\nplus: a second line'
    compendium = one_page_compendium(fake_embed_chunks_core, title=hostile)

    folder = bundle_of(compendium, tmp_path)

    fields, body = front_matter_of(concept_files(folder)[0])
    assert fields["title"] == hostile
    assert "plus" not in fields
    assert BODY[:40] in body


# ---------------------------------------------------------------------------
# Concept bodies
# ---------------------------------------------------------------------------

def test_a_page_split_into_several_sections_is_one_concept_file(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)
    pages = {parent.u for parent in compendium.parents}
    assert len(compendium.parents) >= len(pages)

    folder = bundle_of(compendium, tmp_path)

    assert len(concept_files(folder)) == len(pages)


def test_every_section_of_a_page_reaches_its_concept_file(tmp_path, fake_embed_chunks_core):
    compendium = one_page_compendium(fake_embed_chunks_core)

    folder = bundle_of(compendium, tmp_path)

    body = concept_files(folder)[0].read_text(encoding="utf-8")
    for parent in compendium.parents:
        assert parent.x in body


def test_a_concept_file_opens_with_its_title_and_its_address(tmp_path, fake_embed_chunks_core):
    folder = bundle_of(one_page_compendium(fake_embed_chunks_core), tmp_path)

    _, body = front_matter_of(concept_files(folder)[0])
    assert body.lstrip().startswith("# Office Hours")
    assert "https://example.org/office-hours" in body


def test_a_page_that_stayed_one_section_repeats_no_heading(tmp_path, fake_embed_chunks_core):
    compendium = one_page_compendium(fake_embed_chunks_core)
    assert len(compendium.parents) == 1

    folder = bundle_of(compendium, tmp_path)

    _, body = front_matter_of(concept_files(folder)[0])
    assert "## Office Hours" not in body
    assert BODY in body


def test_sections_are_written_as_real_headings(tmp_path, fixtures_dir, fake_embed_chunks_core):
    """
    Structure has to be carried by headings rather than by bold text, so
    that a screen reader and a Markdown viewer both see the sections.
    """
    folder = bundle_of(sample_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path)

    _, body = front_matter_of(concept_files(folder)[0])
    assert re.search(r"^## \S", body, re.M)


# ---------------------------------------------------------------------------
# File names
# ---------------------------------------------------------------------------

def test_a_title_becomes_a_plain_name():
    assert okf.safe_name("Office Hours & Notes") == "office-hours-notes"


def test_a_title_that_looks_like_a_path_cannot_climb_out_of_the_bundle():
    for hostile in ("../../etc/passwd", "..\\..\\windows\\system32", "/absolute/path", "a/b"):
        name = okf.safe_name(hostile)
        assert "/" not in name and "\\" not in name and ".." not in name


def test_a_name_the_operating_system_reserves_is_changed():
    assert okf.safe_name("CON") == "con-"
    assert okf.safe_name("Index") == "index-"


def test_a_title_with_nothing_a_file_name_can_use_falls_back():
    assert okf.safe_name("日本語") == okf.FALLBACK_NAME


def test_a_very_long_title_is_cut_to_a_usable_length():
    name = okf.safe_name("word " * 60)

    assert len(name) <= okf.MAX_NAME_CHARS
    assert not name.endswith("-")


def test_two_pages_with_the_same_title_are_two_files(tmp_path, fake_embed_chunks_core):
    documents = [
        Document(url=f"https://example.org/{slug}", title="Office Hours",
                 content=f"{BODY} This one belongs to team {slug}, and its text differs "
                         f"enough that neither page is taken for a copy of the other.",
                 source_type="web", content_type="page")
        for slug in ("team-a", "team-b")
    ]
    compendium = build.build_compendium(
        documents, name="Example Org", embedder=fake_embed_chunks_core, built_at=FIXED_BUILT_AT
    )

    folder = bundle_of(compendium, tmp_path)

    assert len(concept_files(folder)) == 2


def test_the_same_corpus_is_written_to_the_same_names_every_run():
    pages = [
        {"url": "https://example.org/a", "title": "Office Hours", "source_label": "Handbook"},
        {"url": "https://example.org/b", "title": "Office Hours", "source_label": "Handbook"},
    ]

    assert okf.bundle_paths(pages) == okf.bundle_paths(pages)
    assert len(set(okf.bundle_paths(pages))) == 2


def test_pages_that_share_a_title_are_told_apart_by_their_address():
    """
    A documentation site often gives every page the same first heading,
    which would otherwise name every file, and every link, the same thing.
    """
    pages = [
        {"url": "local:architecture.md", "title": "Extractium", "source_label": "Docs"},
        {"url": "local:data-flow.md", "title": "Extractium", "source_label": "Docs"},
    ]

    assert okf.display_titles(pages) == [
        "Extractium (architecture.md)", "Extractium (data-flow.md)",
    ]
    assert okf.bundle_paths(pages) == [
        "docs/extractium-architecture-md-411a6842.md",
        "docs/extractium-data-flow-md-5ca1559c.md",
    ]


def test_a_shared_title_is_told_apart_in_the_file_as_well(tmp_path, fake_embed_chunks_core):
    """A file opened on its own has to say which page it is, not only which site."""
    documents = [
        Document(url="https://example.org/office-hours", title="Example Org", content=BODY,
                 source_type="web", content_type="page"),
        Document(url="https://example.org/release-notes", title="Example Org",
                 content=RELEASE_BODY, source_type="web", content_type="page"),
    ]
    compendium = build.build_compendium(
        documents, name="Example Org", embedder=fake_embed_chunks_core, built_at=FIXED_BUILT_AT
    )

    folder = bundle_of(compendium, tmp_path)

    titles = {front_matter_of(path)[0]["title"] for path in concept_files(folder)}
    assert titles == {"Example Org (office-hours)", "Example Org (release-notes)"}


def test_a_title_nothing_else_shares_is_left_alone():
    pages = [
        {"url": "https://example.org/a", "title": "Office Hours", "source_label": "Docs"},
        {"url": "https://example.org/b", "title": "Release Notes", "source_label": "Docs"},
    ]

    assert okf.display_titles(pages) == ["Office Hours", "Release Notes"]


@pytest.mark.parametrize("url, tail", [
    ("https://example.org/team/office-hours", "office-hours"),
    ("https://example.org/team/", "team"),
    ("https://example.org", "example.org"),
    ("local:notes/internal.txt", "internal.txt"),
    ("https://example.org/a.py#L10-L20", "a.py"),
    ("https://example.org/search?q=hours", "search"),
])
def test_the_end_of_an_address_is_the_part_a_person_recognizes(url, tail):
    assert okf.address_tail(url) == tail


def test_concepts_are_filed_under_the_name_of_their_source(tmp_path, fake_embed_chunks_core):
    compendium = one_page_compendium(fake_embed_chunks_core, source_label="Staff Handbook")

    folder = bundle_of(compendium, tmp_path)

    assert concept_files(folder)[0].parent.name == "staff-handbook"


# ---------------------------------------------------------------------------
# The reserved files
# ---------------------------------------------------------------------------

def test_the_index_declares_the_version_of_the_format(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    folder = bundle_of(sample_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path)

    fields, _ = front_matter_of(folder / okf.INDEX_FILE)
    assert fields == {"okf_version": okf.OKF_VERSION}


def test_every_index_link_points_at_a_file_that_exists(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    folder = bundle_of(sample_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path)

    _, body = front_matter_of(folder / okf.INDEX_FILE)
    targets = re.findall(r"^\* \[[^\]]*\]\(([^)]+)\)", body, re.M)
    assert len(targets) == len(concept_files(folder))
    for target in targets:
        assert (folder / target).exists()


def test_the_index_groups_concepts_under_the_name_of_each_source(
    tmp_path, fake_embed_chunks_core
):
    documents = [
        Document(url="https://example.org/a", title="Office Hours", content=BODY,
                 source_type="web", content_type="page", source_label="Staff Handbook"),
        Document(url="https://example.org/b", title="Release Notes",
                 content="Every release is announced here, with the date it went out, what "
                         "changed in it, and who to ask when something looks wrong.",
                 source_type="web", content_type="page", source_label="Peer Program"),
    ]
    compendium = build.build_compendium(
        documents, name="Example Org", embedder=fake_embed_chunks_core, built_at=FIXED_BUILT_AT
    )

    folder = bundle_of(compendium, tmp_path)

    _, body = front_matter_of(folder / okf.INDEX_FILE)
    assert "## Staff Handbook" in body
    assert "## Peer Program" in body
    assert body.index("## Staff Handbook") < body.index("## Peer Program")


def test_the_log_records_the_build_under_a_dated_heading(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    folder = bundle_of(sample_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path)

    body = (folder / okf.LOG_FILE).read_text(encoding="utf-8")
    assert body.startswith(f"# {okf.LOG_HEADING}\n")
    assert re.search(r"^## \d{4}-\d{2}-\d{2}$", body, re.M)
    assert FIXED_BUILT_AT[:10] in body


def test_the_log_carries_no_front_matter(tmp_path, fixtures_dir, fake_embed_chunks_core):
    """The format allows front matter on the root index alone."""
    folder = bundle_of(sample_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path)

    assert not (folder / okf.LOG_FILE).read_text(encoding="utf-8").startswith("---")


# ---------------------------------------------------------------------------
# The same shape whatever the source was
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source_type, content_type, url", [
    ("kb", "article", "https://example.edu/TDClient/000/ExampleOrg/KB/ArticleDet?ID=1"),
    ("github", "code_file", "https://github.com/example-org/example/blob/main/src/app.py"),
    ("repository", "text", "https://repository.example.edu/handle/9999.1/1001"),
    ("web", "page", "https://example.org/office-hours"),
])
def test_a_bundle_has_the_same_structure_whatever_kind_of_source_it_came_from(
    tmp_path, fake_embed_chunks_core, source_type, content_type, url
):
    """
    The format is a serialization of whatever the build produced. A
    bundle written from a help-desk portal, a code repository, a
    scholarly repository, and a plain website must differ in content
    alone, never in shape.
    """
    compendium = one_page_compendium(
        fake_embed_chunks_core, source_type=source_type, content_type=content_type, url=url,
    )

    folder = bundle_of(compendium, tmp_path / source_type)

    assert (folder / okf.INDEX_FILE).exists()
    assert (folder / okf.LOG_FILE).exists()
    fields, body = front_matter_of(concept_files(folder)[0])
    assert list(fields) == [
        "type", "title", "description", "resource", "tags", "generated", "sources",
    ]
    assert body.lstrip().startswith("# Office Hours")


def test_the_adapter_names_no_particular_source():
    """
    A named source in this file would be the start of a format shaped
    around one of them, which is the mistake this output exists to avoid.
    """
    text = pathlib.Path(okf.__file__).read_text(encoding="utf-8")
    # The addresses in the header and the license line name where this
    # adapter and the format it writes are published, which says nothing
    # about where the content came from.
    lowered = re.sub(r"https?://\S+", "", text).lower()
    for name in ("github", "teamdynamix", "tdx", "dspace", "youtube", "deep blue"):
        assert name not in lowered
    assert "source_type" not in lowered


# ---------------------------------------------------------------------------
# The local-content guardrail
# ---------------------------------------------------------------------------

def test_local_content_stays_out_unless_the_output_asked_for_it(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)

    folder = bundle_of(compendium, tmp_path)

    written = "\n".join(p.read_text(encoding="utf-8") for p in folder.rglob("*.md"))
    assert "local:" not in written
    assert "Internal Notes" not in written


def test_local_content_is_written_when_the_output_opted_in(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)

    folder = bundle_of(compendium, tmp_path, {"include_local": True})

    written = "\n".join(p.read_text(encoding="utf-8") for p in folder.rglob("*.md"))
    assert "local:notes/internal.txt" in written


# ---------------------------------------------------------------------------
# Writing the folder
# ---------------------------------------------------------------------------

def test_the_adapter_returns_the_reserved_files_first(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    written = OkfAdapter().write(compendium, tmp_path, {})

    assert written[0].name == okf.INDEX_FILE
    assert written[1].name == okf.LOG_FILE
    assert all(path.exists() for path in written)
    assert len(written) == 2 + len({parent.u for parent in compendium.parents})


def test_a_second_run_over_the_same_folder_writes_the_same_files(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    """A rerun has to be safe to repeat: the same build cannot leave two copies of a page."""
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    first = OkfAdapter().write(compendium, tmp_path, {})
    second = OkfAdapter().write(compendium, tmp_path, {})

    assert first == second
    assert len(concept_files(tmp_path / okf.BUNDLE_DIR)) == len(first) - 2


def test_a_bundle_with_nothing_in_it_still_opens(tmp_path, fixtures_dir, fake_embed_chunks_core):
    """
    Every parent can be dropped by the guardrail, which leaves a folder
    with no concepts. The two reserved files still have to be readable.
    """
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)
    only_local = build.build_compendium(
        [Document(url="local:notes/internal.txt", title="Internal Notes", content=BODY,
                  source_type="local", content_type="text", local=True)],
        name="Example Org", embedder=fake_embed_chunks_core, built_at=compendium.built_at,
    )

    folder = bundle_of(only_local, tmp_path)

    assert concept_files(folder) == []
    fields, _ = front_matter_of(folder / okf.INDEX_FILE)
    assert fields == {"okf_version": okf.OKF_VERSION}
    assert "0 concepts" in (folder / okf.LOG_FILE).read_text(encoding="utf-8")
