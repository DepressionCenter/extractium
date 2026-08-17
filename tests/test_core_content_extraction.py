"""
Summary: Tests pinning extractium.core.chunk's title/content-extraction
functions: get_title, normalise_page_title, extract_content (every host
branch), extract_links, chunk_kind, markdown_text_to_soup, and
derive_title_from_blob_path. Mirrors tests/test_content_extraction.py
(which pins the same behavior on the frozen reference script) against the
real, ported implementation, proving the port is behavior-identical. Uses
the synthetic fixtures in tests/fixtures/ -- no real URLs or content.

This file is part of Extractium™
tests/test_core_content_extraction.py

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
# TDX article branch
# ---------------------------------------------------------------------------

def test_tdx_article_title_strips_prefix_and_suffix(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "tdx_article.html")
    url = "https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1"
    assert chunk.get_title(soup, url) == "Sleep Hygiene Tips"


def test_tdx_article_content_selected_and_strip_tags_applied(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "tdx_article.html")
    url = "https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1"
    node = chunk.extract_content(soup, url)
    assert node is not None
    text = node.get_text(" ", strip=True)
    assert "Getting Started" in text
    assert "Synthetic breadcrumb" not in text  # <nav> stripped by STRIP_TAGS
    assert "Synthetic footer" not in text      # <footer> stripped by STRIP_TAGS


def test_tdx_article_chunk_kind_is_kb():
    url = "https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1"
    assert chunk.chunk_kind(url) == "kb"


# ---------------------------------------------------------------------------
# GitHub wiki branch
# ---------------------------------------------------------------------------

def test_github_wiki_content_selected_via_markdown_body(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "github_wiki.html")
    url = "https://github.com/example-org/example-repo/wiki/Setup-Guide"
    node = chunk.extract_content(soup, url)
    assert node is not None
    assert "Installation" in node.get_text(" ", strip=True)


def test_github_wiki_chunk_kind_is_code():
    url = "https://github.com/example-org/example-repo/wiki/Setup-Guide"
    assert chunk.chunk_kind(url) == "code"


# ---------------------------------------------------------------------------
# GitHub repo root branch -- no server-rendered content
# ---------------------------------------------------------------------------

def test_github_repo_root_extract_content_returns_none(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "github_repo_root.html")
    url = "https://github.com/example-org/example-repo"
    assert chunk.extract_content(soup, url) is None


# ---------------------------------------------------------------------------
# GitHub release-tag branch
# ---------------------------------------------------------------------------

def test_github_release_tag_content_selected_via_markdown_body(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "github_release_tag.html")
    url = "https://github.com/example-org/example-repo/releases/tag/v1.0.0"
    node = chunk.extract_content(soup, url)
    assert node is not None
    assert "Highlights" in node.get_text(" ", strip=True)


# ---------------------------------------------------------------------------
# Raw Markdown blob branch
# ---------------------------------------------------------------------------

def test_raw_markdown_file_renders_headings_code_and_table(fixtures_dir):
    raw_text = (fixtures_dir / "raw_markdown_file.md").read_text(encoding="utf-8")
    url = "https://github.com/example-org/example-repo/blob/main/docs/setup.md"
    soup = chunk.markdown_text_to_soup(raw_text, url)

    assert chunk.get_title(soup, url) == "Setup Notes"  # <h1> fallback

    node = chunk.extract_content(soup, url)
    assert node is not None
    assert node.find("table") is not None   # "tables" extension
    assert node.find("code") is not None    # "fenced_code" extension
    assert "Prerequisites" in node.get_text(" ", strip=True)


# ---------------------------------------------------------------------------
# Raw plain-text blob branch
# ---------------------------------------------------------------------------

def test_raw_plain_text_file_wrapped_in_pre_and_title_from_path(fixtures_dir):
    raw_text = (fixtures_dir / "raw_plain_text_file.txt").read_text(encoding="utf-8")
    url = "https://github.com/example-org/example-repo/blob/main/docs/release-notes.txt"
    soup = chunk.markdown_text_to_soup(raw_text, url)

    assert soup.find("pre") is not None
    # No <title>/<h1> in a <pre>-wrapped plain-text file -> falls back to
    # deriving a title from the blob path.
    assert chunk.get_title(soup, url) == "Release Notes"

    node = chunk.extract_content(soup, url)
    assert node is not None
    assert "synthetic plain-text fixture" in node.get_text(" ", strip=True)


def test_derive_title_from_blob_path():
    url = "https://github.com/example-org/example-repo/blob/main/docs/release-notes.txt"
    assert chunk.derive_title_from_blob_path(url) == "Release Notes"


# ---------------------------------------------------------------------------
# Generic/fallback branch (GENERIC_CONTENT_SELECTORS) -- surprising behavior
# ---------------------------------------------------------------------------

def test_generic_page_uses_generic_content_selectors_fallback(fixtures_dir):
    """
    SURPRISING BEHAVIOR, pinned as-is (see AGENTS.md section 4): despite
    the "generic" name, GENERIC_CONTENT_SELECTORS is never reached for a
    real "teamdynamix."-domain URL (those hit a hardcoded
    #divMainContent/#questionsContent branch instead -- see the TDX
    article test above). It is the fallback extractor for any non-git,
    non-teamdynamix page. (In the frozen reference this constant is named
    TDX_CONTENT_SELECTORS, a misnomer left in place there so the reference
    stays diff-clean against upstream; this port uses the accurate name.)
    """
    soup = _soup_from_fixture(fixtures_dir, "generic_page_with_main.html")
    url = "https://example.org/about"
    node = chunk.extract_content(soup, url)
    assert node is not None
    assert node.name == "main"
    assert "About" in node.get_text(" ", strip=True)


def test_generic_page_chunk_kind_is_page():
    assert chunk.chunk_kind("https://example.org/about") == "page"


# ---------------------------------------------------------------------------
# normalise_page_title
# ---------------------------------------------------------------------------

def test_normalise_page_title_strips_article_prefix_on_teamdynamix_url():
    title = chunk.normalise_page_title(
        "Article - Sleep Hygiene Tips", url="https://teamdynamix.umich.edu/TDClient/210/x"
    )
    assert title == "Sleep Hygiene Tips"


def test_normalise_page_title_strips_question_detail_prefix_on_teamdynamix_url():
    title = chunk.normalise_page_title(
        "Question Detail - Why is my VPN slow", url="https://teamdynamix.umich.edu/TDClient/210/x"
    )
    assert title == "Why is my VPN slow"


def test_normalise_page_title_leaves_non_teamdynamix_url_unchanged():
    title = chunk.normalise_page_title("Article - Sleep Hygiene Tips", url="https://example.org/x")
    assert title == "Article - Sleep Hygiene Tips"


# ---------------------------------------------------------------------------
# extract_links
# ---------------------------------------------------------------------------

def test_extract_links_resolves_relative_urls_and_normalises():
    soup = BeautifulSoup(
        '<a href="/kb/other">x</a><a href="https://x.org/page#frag">y</a>',
        "html.parser",
    )
    links = chunk.extract_links(soup, "https://example.org/kb/article")
    assert links == ["https://example.org/kb/other", "https://x.org/page"]
