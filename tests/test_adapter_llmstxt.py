"""
Summary: Tests for the llms.txt adapter. Pins the generated index tree
against committed snapshots, checks that the root file lists sources and
each source's file lists its pages once with a description, checks the
repository ordering, the split past the entry cap, and that code records
appear nowhere, checks that a stale file this tool wrote is removed and
nobody else's is, and checks that local content stays out unless the
output opted in.

This file is part of Extractium™
tests/test_adapter_llmstxt.py

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

import dataclasses

from extractium.adapters import base, llmstxt
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
    assert base.page_title("Team Directory -- Members") == "Team Directory"
    assert base.page_title("Team Directory") == "Team Directory"


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
    assert "compendium of 3 sections" in line
    assert "drawn from 2 pages on example.org" in line
    assert compendium.built_at in line
    # The heading directly above already carries the name.
    assert not line.startswith(f"> {compendium.name}")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

def a_parent(**fields):
    """One section with every required field, plus whatever the test sets."""
    from extractium.core.models import Parent

    values = {
        "id": "0123456789abcdef", "t": "Page -- Section", "x": "Some text.",
        "u": "https://example.org/page", "host": "example.org", "source_type": "web",
        "content_type": "page", "source_label": "Website",
    }
    values.update(fields)
    return Parent(**values)


def with_enrichment(compendium, **fields):
    """The same compendium with every section carrying the given enrichment fields."""
    parents = tuple(dataclasses.replace(parent, **fields) for parent in compendium.parents)
    return dataclasses.replace(compendium, parents=parents)


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def test_the_tree_matches_the_committed_snapshots(fixtures_dir, golden_dir, fake_embed_chunks_core):
    tree = llmstxt.render_tree(sample_compendium(fixtures_dir, fake_embed_chunks_core))

    for path, body in tree.items():
        assert body == (golden_dir / path).read_text(encoding="utf-8"), path
    committed = {"llms.txt"} | {
        file.relative_to(golden_dir).as_posix() for file in (golden_dir / "llms").rglob("*.txt")
    }
    assert committed == set(tree)


# ---------------------------------------------------------------------------
# A real build's sections
# ---------------------------------------------------------------------------

def test_a_source_file_names_each_page_once_however_many_sections_it_contributed(
    fixtures_dir, fake_embed_chunks_core
):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    body = llmstxt.render_tree(compendium)["llms/website.txt"]

    assert len(compendium.parents) == 3
    assert body.count("https://example.org/team)") == 1
    assert body.count("https://example.org/project)") == 1


def test_the_root_file_starts_with_one_heading_and_a_summary(fixtures_dir, fake_embed_chunks_core):
    body = llmstxt.render_tree(sample_compendium(fixtures_dir, fake_embed_chunks_core))["llms.txt"]

    lines = body.splitlines()
    assert lines[0] == "# Example Org"
    assert lines[2].startswith("> ")
    assert body.count("\n# ") == 0  # exactly one first-level heading
    assert "This file is an index of the sources" in body


def test_the_renderer_lists_whatever_sources_it_is_handed(fixtures_dir, fake_embed_chunks_core):
    """
    The renderer describes whatever compendium it is handed; the
    local-content guardrail runs once in write() and hands it the
    filtered result. Both sources are present here because this renders
    the unfiltered build directly.
    """
    tree = llmstxt.render_tree(mixed_compendium(fixtures_dir, fake_embed_chunks_core))

    assert list(tree) == ["llms.txt", "llms/website.txt", "llms/local-files.txt"]


def test_two_sources_of_the_same_kind_are_told_apart(fixtures_dir, fake_embed_chunks_core):
    """
    The reason a label exists. Both of these are web sources, so listing
    by source type would make them one entry and a reader could not tell
    the main site from the program microsite.
    """
    tree = llmstxt.render_tree(two_website_compendium(fixtures_dir, fake_embed_chunks_core))

    assert list(tree) == ["llms.txt", "llms/main-website.txt", "llms/peer-program.txt"]
    assert "https://peer.example.org/about" in tree["llms/peer-program.txt"]
    assert "https://peer.example.org/about" not in tree["llms/main-website.txt"]


def test_two_sources_sharing_a_label_are_one_entry_and_one_file(fixtures_dir, fake_embed_chunks_core):
    """
    Two sibling collections of one repository are one place to a person
    looking for an answer, so one label means one entry.
    """
    compendium = two_website_compendium(fixtures_dir, fake_embed_chunks_core, second_label="Main Website")

    tree = llmstxt.render_tree(compendium)

    assert list(tree) == ["llms.txt", "llms/main-website.txt"]
    assert tree["llms.txt"].count("[Main Website]") == 1
    assert "https://peer.example.org/about" in tree["llms/main-website.txt"]


# ---------------------------------------------------------------------------
# The index tree
# ---------------------------------------------------------------------------

SOURCES = (
    {"label": "Main Site", "type": "web", "home_url": "https://example.org/", "description": "Programs and events."},
    {"label": "Source Code", "type": "github_api", "home_url": "https://github.com/example", "description": ""},
)


def section(n, url, **overrides):
    """One synthetic section. Ids are sixteen hex digits, as the model requires."""
    from extractium.core.models import Parent

    fields = dict(id=f"{n:016x}", t=f"Page {n}", x=f"Opening words of page {n}.", u=url,
                  host="example.org", source_type="web", content_type="page",
                  source_label="Main Site")
    fields.update(overrides)
    return Parent(**fields)


def github(n, path, repository="tool", content_type="text", **overrides):
    """One section of a file in a repository, categorized the way the GitHub source does it."""
    folders = tuple(path.split("/")[:-1])
    fields = dict(host="github.com", source_type="github", content_type=content_type,
                  source_label="Source Code", t=f"example/{repository}: {path}",
                  categories=("example", repository) + folders)
    fields.update(overrides)
    return section(n, f"https://github.com/example/{repository}/blob/main/{path}", **fields)


def tree_of(parents, sources=SOURCES):
    """The rendered tree for a stand-in compendium; the renderer reads only these three fields."""
    from types import SimpleNamespace

    compendium = SimpleNamespace(name="Example Library", built_at="2026-01-02T03:04:05Z", parents=tuple(parents))
    return llmstxt.render_tree(compendium, sources)


def entries_of(body):
    return [line for line in body.splitlines() if line.startswith("- ")]


def test_the_root_file_lists_sources_and_not_pages():
    tree = tree_of([section(1, "https://example.org/a", keywords=("sleep",)),
                    github(2, "README.md", content_type="readme")])
    root = tree["llms.txt"]

    assert ("- [Main Site](https://example.org/): Programs and events. "
            "Index of its pages: [llms/main-site.txt](llms/main-site.txt).") in root
    assert "https://example.org/a" not in root
    assert "Keywords:" not in root
    assert list(tree) == ["llms.txt", "llms/main-site.txt", "llms/source-code.txt"]


def test_the_root_file_orders_sources_the_way_the_settings_file_does():
    parents = [github(1, "README.md", content_type="readme"), section(2, "https://example.org/a")]
    root = tree_of(parents)["llms.txt"]
    assert root.index("[Main Site]") < root.index("[Source Code]")


def test_a_source_that_contributed_no_page_is_not_listed():
    tree = tree_of([section(1, "https://example.org/a")])
    assert "Source Code" not in tree["llms.txt"]
    assert list(tree) == ["llms.txt", "llms/main-site.txt"]


def test_a_source_without_a_description_is_described_by_the_page_it_starts_at():
    sources = ({"label": "Main Site", "type": "web", "home_url": "https://example.org", "description": ""},)
    tree = tree_of([section(1, "https://example.org/", summary="Everything about Example Organization."),
                    section(2, "https://example.org/a")], sources)
    assert "- [Main Site](https://example.org): Everything about Example Organization. Index" in tree["llms.txt"]


def test_a_source_with_nothing_said_about_it_is_described_by_a_count():
    sources = ({"label": "Main Site", "type": "web", "home_url": "https://example.org/", "description": ""},)
    tree = tree_of([section(1, "https://example.org/a"), section(2, "https://example.org/b")], sources)
    assert "- [Main Site](https://example.org/): 2 pages from example.org. Index" in tree["llms.txt"]


def test_a_source_with_no_home_address_links_to_its_own_index():
    tree = tree_of([section(1, "local:notes/a.md", host="", source_type="local", content_type="text",
                            source_label="Notes", local=True)], sources=())
    assert "- [Notes](llms/notes.txt): 1 file." in tree["llms.txt"]


def test_a_source_file_lists_each_page_with_its_description():
    tree = tree_of([section(1, "https://example.org/a", summary="What page A covers.")])
    body = tree["llms/main-site.txt"]

    assert "- [Page 1](https://example.org/a): What page A covers." in body
    assert "[llms.txt](../llms.txt)" in body


def test_keywords_describe_only_a_page_with_no_summary_of_its_own():
    tree = tree_of([section(1, "https://example.org/a", summary="What page A covers.", keywords=("sleep",)),
                    section(2, "https://example.org/b", keywords=("sleep", "wearables"))])
    entries = entries_of(tree["llms/main-site.txt"])

    assert entries == ["- [Page 1](https://example.org/a): What page A covers.",
                       "- [Page 2](https://example.org/b): Keywords: sleep, wearables."]


def test_code_records_are_listed_nowhere():
    tree = tree_of([github(1, "README.md", content_type="readme"),
                    github(2, "run.py", content_type="code_file"),
                    github(3, "run.py", content_type="code_symbol"),
                    github(4, "pyproject.toml", content_type="manifest"),
                    github(5, "map", content_type="repo_map")])
    everything = "\n".join(tree.values())

    assert "run.py" not in everything and "pyproject.toml" not in everything
    assert all("Source code is not listed here." in body for body in tree.values())


def test_a_repository_lists_its_readme_then_root_files_then_docs_then_the_rest():
    tree = tree_of([github(1, "src/notes/design.md"), github(2, "docs/usage.md"),
                    github(3, "CONTRIBUTING.md"), github(4, "Guide/start.md"),
                    github(5, "README.md", content_type="readme", summary="A tool that does one thing.")])
    body = tree["llms/source-code.txt"]
    order = [body.index(name) for name in ("(https://github.com/example/tool)", "[README.md]",
                                           "[CONTRIBUTING.md]", "[docs/usage.md]", "[Guide/start.md]",
                                           "[src/notes/design.md]")]

    assert order == sorted(order)
    assert "## example/tool" in body
    assert "- [example/tool](https://github.com/example/tool): A tool that does one thing." in body


def test_a_repository_that_says_nothing_about_itself_says_so():
    body = tree_of([github(1, "NOTES.md")])["llms/source-code.txt"]
    assert "- [example/tool](https://github.com/example/tool): No description." in body


def test_a_label_shared_by_a_website_and_a_repository_source_lists_both():
    parents = [section(1, "https://example.org/a", source_label="Source Code"),
               github(2, "README.md", content_type="readme")]
    body = tree_of(parents)["llms/source-code.txt"]

    assert body.index("## Source Code") < body.index("## example/tool")
    assert "https://example.org/a" in body


def test_a_source_over_the_cap_splits_by_category(monkeypatch):
    monkeypatch.setattr(llmstxt, "MAX_ENTRIES_PER_FILE", 2)
    parents = [section(n, f"https://example.org/{group}/{n}", categories=("Site", group))
               for n, group in enumerate(("news", "news", "events"), start=1)]
    tree = tree_of(parents)

    assert "- [news](main-site/news.txt): 2 pages." in tree["llms/main-site.txt"]
    assert "https://example.org/news/1" not in tree["llms/main-site.txt"]
    assert "https://example.org/news/1" in tree["llms/main-site/news.txt"]
    assert "https://example.org/events/3" in tree["llms/main-site/events.txt"]
    assert "[main-site.txt](../main-site.txt)" in tree["llms/main-site/news.txt"]
    assert "[llms.txt](../../llms.txt)" in tree["llms/main-site/news.txt"]


def test_a_page_with_no_category_groups_by_the_first_folder_of_its_address(monkeypatch):
    monkeypatch.setattr(llmstxt, "MAX_ENTRIES_PER_FILE", 2)
    parents = [section(1, "https://example.org/news/one"), section(2, "https://example.org/news/two"),
               section(3, "https://example.org/about")]
    tree = tree_of(parents)

    assert "https://example.org/news/two" in tree["llms/main-site/news.txt"]
    assert "https://example.org/about" in tree["llms/main-site/top-level-pages.txt"]


def test_a_repository_source_over_the_cap_gives_each_repository_a_file(monkeypatch):
    monkeypatch.setattr(llmstxt, "MAX_ENTRIES_PER_FILE", 3)
    parents = [github(1, "README.md", content_type="readme", summary="First tool."),
               github(2, "docs/a.md"), github(3, "README.md", repository="other", content_type="readme"),
               github(4, "docs/b.md", repository="other")]
    tree = tree_of(parents)

    assert ("- [example/tool](https://github.com/example/tool): First tool. "
            "Index of its files: [source-code/tool.txt](source-code/tool.txt).") in tree["llms/source-code.txt"]
    assert "docs/a.md" not in tree["llms/source-code.txt"]
    assert "[docs/a.md]" in tree["llms/source-code/tool.txt"]
    assert "[docs/b.md]" in tree["llms/source-code/other.txt"]


def test_a_group_over_the_cap_continues_in_a_numbered_file(monkeypatch):
    monkeypatch.setattr(llmstxt, "MAX_ENTRIES_PER_FILE", 2)
    parents = [section(n, f"https://example.org/news/{n}", categories=("Site", "news")) for n in range(1, 4)]
    tree = tree_of(parents)

    assert "llms/main-site/news-2.txt" in tree
    assert "- [Continued in news-2.txt](news-2.txt)" in tree["llms/main-site/news.txt"]
    assert "https://example.org/news/3" in tree["llms/main-site/news-2.txt"]


def test_a_continuation_file_never_takes_the_name_of_another_group(monkeypatch):
    monkeypatch.setattr(llmstxt, "MAX_ENTRIES_PER_FILE", 2)
    parents = [section(n, f"https://example.org/x/{n}", categories=("Site", "news")) for n in range(1, 4)]
    parents += [section(9, "https://example.org/x/9", categories=("Site", "news 2"))]
    tree = tree_of(parents)

    assert "https://example.org/x/9" in tree["llms/main-site/news-2.txt"]
    assert "https://example.org/x/3" in tree["llms/main-site/news-3.txt"]
    assert "- [news 2](main-site/news-2.txt): 1 page." in tree["llms/main-site.txt"]


def test_no_file_holds_more_entries_than_the_cap(monkeypatch):
    monkeypatch.setattr(llmstxt, "MAX_ENTRIES_PER_FILE", 3)
    parents = [section(n, f"https://example.org/{n % 4}/{n}", categories=("Site", str(n % 4))) for n in range(1, 30)]
    tree = tree_of(parents)

    for path, body in tree.items():
        assert len(entries_of(body)) <= 3 + 1, path    # one more for a "Continued in" entry
    listed = "\n".join(tree.values())
    assert all(f"https://example.org/{n % 4}/{n})" in listed for n in range(1, 30))


def test_every_link_between_index_files_points_at_a_file_in_the_tree(monkeypatch):
    import posixpath
    import re

    monkeypatch.setattr(llmstxt, "MAX_ENTRIES_PER_FILE", 2)
    parents = [section(n, f"https://example.org/{n % 3}/{n}", categories=("Site", str(n % 3))) for n in range(1, 12)]
    parents += [github(20 + n, f"docs/{n}.md") for n in range(1, 5)]
    tree = tree_of(parents)

    for path, body in tree.items():
        for target in re.findall(r"\]\(([^)]+\.txt)\)", body):
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
            assert resolved in tree, f"{path} links to {target}"


def test_a_label_cannot_name_a_path_outside_the_folder():
    parents = [section(1, "https://example.org/a", source_label="../../etc/passwd"),
               section(2, "https://example.org/b", source_label="***")]
    tree = tree_of(parents, sources=())

    assert list(tree) == ["llms.txt", "llms/etc-passwd.txt", "llms/source-2.txt"]


def test_two_labels_that_reduce_to_one_name_get_numbered_files():
    parents = [section(1, "https://example.org/a", source_label="Main Site"),
               section(2, "https://example.org/b", source_label="main site!")]
    assert list(tree_of(parents, sources=())) == ["llms.txt", "llms/main-site.txt", "llms/main-site-2.txt"]


def test_the_orientation_of_every_file_uses_no_headings_of_its_own(monkeypatch):
    """The llms.txt convention allows nothing but paragraphs between the summary and the first H2."""
    monkeypatch.setattr(llmstxt, "MAX_ENTRIES_PER_FILE", 2)
    parents = [section(n, f"https://example.org/news/{n}") for n in range(1, 4)]
    for body in tree_of(parents).values():
        lines = body.splitlines()
        assert lines[0].startswith("# ") and lines[2].startswith("> ")
        first_section = next(i for i, line in enumerate(lines) if line.startswith("## "))
        assert not any(line.startswith("#") for line in lines[1:first_section])
        assert llmstxt.LICENSE_LINE in lines[:first_section]


# ---------------------------------------------------------------------------
# Writing the tree
# ---------------------------------------------------------------------------

def test_write_produces_the_tree_and_no_full_file(tmp_path, fixtures_dir, fake_embed_chunks_core):
    adapter = LlmsTxtAdapter()
    written = adapter.write(sample_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path,
                            {"include_local": False})

    names = [path.relative_to(tmp_path).as_posix() for path in written]
    assert names[0] == "llms.txt"
    assert all(name.startswith("llms/") for name in names[1:]) and len(names) >= 2
    assert not (tmp_path / "llms-full.txt").exists()
    assert adapter.pruned == ()


def test_a_file_this_tool_wrote_is_removed_and_a_strangers_is_kept(tmp_path, fixtures_dir, fake_embed_chunks_core):
    (tmp_path / "llms-full.txt").write_text(f"# Old\n\n{llmstxt.LICENSE_LINE}\n", encoding="utf-8")
    (tmp_path / "llms" / "gone-source").mkdir(parents=True)
    (tmp_path / "llms" / "gone-source.txt").write_text(f"# Old\n\n{llmstxt.LICENSE_LINE}\n", encoding="utf-8")
    (tmp_path / "llms" / "gone-source" / "news.txt").write_text(f"# Old\n\n{llmstxt.LICENSE_LINE}\n", encoding="utf-8")
    (tmp_path / "llms" / "notes.txt").write_text("Written by a person.\n", encoding="utf-8")

    adapter = LlmsTxtAdapter()
    adapter.write(sample_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path, {"include_local": False})

    assert not (tmp_path / "llms-full.txt").exists()
    assert not (tmp_path / "llms" / "gone-source.txt").exists()
    assert not (tmp_path / "llms" / "gone-source").exists()
    assert (tmp_path / "llms" / "notes.txt").read_text(encoding="utf-8") == "Written by a person.\n"
    assert {path.name for path in adapter.pruned} == {"llms-full.txt", "gone-source.txt", "news.txt"}


def test_a_full_file_somebody_else_wrote_is_left_alone(tmp_path, fixtures_dir, fake_embed_chunks_core):
    (tmp_path / "llms-full.txt").write_text("My own notes.\n", encoding="utf-8")

    LlmsTxtAdapter().write(sample_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path,
                           {"include_local": False})

    assert (tmp_path / "llms-full.txt").read_text(encoding="utf-8") == "My own notes.\n"


def test_writing_twice_leaves_the_same_files(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)
    adapter = LlmsTxtAdapter()
    first = adapter.write(compendium, tmp_path, {"include_local": False})
    second = adapter.write(compendium, tmp_path, {"include_local": False})

    assert first == second and adapter.pruned == ()
    assert all(path.exists() for path in second)
