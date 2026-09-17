"""
Summary: Tests for the helpers every output adapter shares: which sections
are prose and which describe code, the one-record-per-page grouping, and
the rule for describing a page by its own summary, then its keywords,
then the opening of its text.

This file is part of Extractium™
tests/test_adapter_base.py

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

from extractium.adapters import base
from extractium.core.build import build_compendium
from extractium.core.models import CODE_CONTENT_TYPES, Document, Parent


def section(n, url, **overrides):
    """One synthetic section. Ids are sixteen hex digits, as the model requires."""
    fields = dict(id=f"{n:016x}", t=f"Page {n}", x=f"Opening words of page {n}.", u=url,
                  host="example.org", source_type="web", content_type="page",
                  source_label="Main Site")
    fields.update(overrides)
    return Parent(**fields)


# ---------------------------------------------------------------------------
# Prose and code
# ---------------------------------------------------------------------------

def test_code_records_are_not_prose():
    kept = base.prose_parents([
        section(1, "https://example.org/a"),
        section(2, "https://github.com/example/tool/blob/main/run.py",
                source_type="github", content_type="code_symbol"),
    ])
    assert [p.u for p in kept] == ["https://example.org/a"]


# ---------------------------------------------------------------------------
# One record per page
# ---------------------------------------------------------------------------

def test_a_page_is_one_record_however_many_sections_it_has():
    pages = base.page_records([
        section(1, "https://example.org/a"), section(2, "https://example.org/a"),
        section(3, "https://example.org/b"),
    ])
    assert [page["url"] for page in pages] == ["https://example.org/a", "https://example.org/b"]


def test_a_page_record_carries_what_an_index_needs_to_place_it():
    page = base.page_records([
        section(1, "https://example.org/a", categories=("Site", "News"), summary="  About A.  ",
                keywords=("sleep",)),
    ])[0]

    assert page == {
        "url": "https://example.org/a", "title": "Page 1", "source_label": "Main Site",
        "source_type": "web", "content_type": "page", "categories": ("Site", "News"),
        "text": "Opening words of page 1.", "summary": "About A.", "given_summary": "About A.",
        "keywords": ("sleep",), "own_keywords": ("sleep",),
    }


def test_no_sections_give_no_pages():
    assert base.page_records([]) == []


# ---------------------------------------------------------------------------
# Describing a page
# ---------------------------------------------------------------------------

def test_a_description_is_the_summary_then_the_keywords_then_an_excerpt():
    with_summary = base.page_records([section(1, "https://example.org/a", summary="What page A covers.")])[0]
    with_keywords = base.page_records([section(2, "https://example.org/b", keywords=("sleep", "wearables"))])[0]
    with_neither = base.page_records([section(3, "https://example.org/c")])[0]

    assert base.describe(with_summary) == "What page A covers."
    assert base.describe(with_keywords) == "Keywords: sleep, wearables."
    assert base.describe(with_neither) == "Opening words of page 3."


def test_a_long_summary_is_cut_at_a_word_boundary():
    page = base.page_records([section(1, "https://example.org/a", summary="word " * 200)])[0]
    described = base.describe(page)

    assert len(described) <= base.DESCRIPTION_CHARS + 3
    assert described.endswith("...")


def test_a_summary_shared_across_a_source_is_the_sites_and_not_the_pages():
    shared = "The latest news from Example Organization."
    parents = [section(n, f"https://example.org/{n}", summary=shared, keywords=("topic",))
               for n in range(1, 6)]
    pages = base.page_records(parents)

    assert all(page["summary"] == "" for page in pages)
    assert all(page["given_summary"] == shared for page in pages)
    assert base.describe(pages[0]) == "Keywords: topic."


def test_a_summary_a_few_pages_share_is_kept():
    shared = "A two-part guide."
    pages = base.page_records([section(n, f"https://example.org/{n}", summary=shared)
                               for n in range(1, base.SHARED_SUMMARY_PAGES + 1)])
    assert all(page["summary"] == shared for page in pages)


def test_the_same_summary_on_two_sources_is_counted_per_source():
    shared = "Example Organization."
    parents = [section(n, f"https://example.org/{n}", summary=shared,
                       source_label="Main Site" if n % 2 else "Other Site") for n in range(1, 7)]
    assert all(page["summary"] == shared for page in base.page_records(parents))


def test_keywords_named_prefers_shared_tags_over_the_sections_own_keywords():
    parent = section(1, "https://example.org/a", tags=("Guides", "sleep"), categories=("Guides",),
                     keywords=("caffeine",))

    assert base.keywords_named(parent) == ("sleep",)
    assert base.keywords_named(section(2, "https://example.org/b", tags=("Guides",), categories=("Guides",),
                                       keywords=("caffeine",))) == ("caffeine",)
    assert base.keywords_named(section(3, "https://example.org/c")) == ()


def test_keywords_a_whole_source_shares_give_way_to_the_pages_own():
    """
    A repository's topics are tags on every one of its files. They say
    what the repository is about and nothing about one file, so a file is
    described by the keywords found in its own text.
    """
    topics = ("Docs", "wearables", "sleep")
    parents = [section(n, f"https://example.org/{n}", tags=topics, categories=("Docs",),
                       keywords=(f"subject {n}",)) for n in range(1, 6)]
    pages = base.page_records(parents)

    assert [base.describe(page) for page in pages] == [f"Keywords: subject {n}." for n in range(1, 6)]


def test_shared_keywords_with_nothing_else_to_say_leave_the_excerpt():
    parents = [section(n, f"https://example.org/{n}", tags=("wearables",)) for n in range(1, 6)]
    assert base.describe(base.page_records(parents)[0]) == "Opening words of page 1."


# ---------------------------------------------------------------------------
# Dropping code records
# ---------------------------------------------------------------------------

PROSE = (
    "Sleep data from a wearable device is summarized nightly, and this page explains "
    "how the summary is produced and where the figures in it come from."
)
CODE = (
    "def summarize(nights): return sum(nights) / len(nights)  # the nightly mean, which "
    "is long enough here for the chunker to keep it as a section of its own."
)


def compendium_of(embedder, with_code):
    """Two prose pages, and one code record when asked for, built with the test embedder."""
    documents = [
        Document(url="https://example.org/a", title="Page A", content=PROSE,
                 source_type="web", content_type="text"),
        Document(url="https://example.org/b", title="Page B", content=PROSE.replace("Sleep", "Activity"),
                 source_type="web", content_type="text"),
    ]
    if with_code:
        documents.append(Document(
            url="https://github.com/example/tool/blob/main/run.py", title="run.py", content=CODE,
            source_type="github", content_type="code_file",
        ))
    return build_compendium(documents, name="Example Org", embedder=embedder,
                            built_at="2026-01-02T03:04:05Z")


def posting_count(compendium):
    """How many term and window pairs the keyword statistics hold."""
    return sum(len(entries) for entries in compendium.bm25["postings"].values())


def test_without_code_drops_code_sections_and_everything_derived_from_them(fake_embed_chunks_core):
    before = compendium_of(fake_embed_chunks_core, with_code=True)
    after = base.without_code(before)

    assert any(parent.content_type in CODE_CONTENT_TYPES for parent in before.parents)
    assert all(parent.content_type not in CODE_CONTENT_TYPES for parent in after.parents)
    assert len(after.children) < len(before.children)
    assert after.vectors.shape[0] == len(after.children)
    assert max(after.children.pid) == len(after.parents) - 1
    assert posting_count(after) < posting_count(before)


def test_without_code_returns_the_same_object_when_there_is_no_code(fake_embed_chunks_core):
    compendium = compendium_of(fake_embed_chunks_core, with_code=False)
    assert base.without_code(compendium) is compendium
