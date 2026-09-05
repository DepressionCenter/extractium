"""
Summary: Tests for the built-in site handlers (generic, tdx, github):
which URLs each one claims, the URL it requests and whether it expects
HTML, the title, content node, categories, and content type it reads
from each synthetic fixture, the git-host URL helpers, and the exclude
patterns each handler contributes. Carries forward
tests/test_content_extraction.py, which pins the same extraction
behavior on the frozen reference script, so the handlers read every
fixture the way the original did. Uses the synthetic fixtures in
tests/fixtures/ -- no real URLs or content.

This file is part of Extractium™
tests/test_site_handlers.py

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

import pytest
from bs4 import BeautifulSoup

from extractium.core import chunk
from extractium.core.models import CONTENT_TYPES, SOURCE_TYPES, SiteHandler
from extractium.sources import generic, github, tdx

TDX_URL = "https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1"
WIKI_URL = "https://github.com/example-org/example-repo/wiki/Setup-Guide"
REPO_ROOT_URL = "https://github.com/example-org/example-repo"
RELEASE_URL = "https://github.com/example-org/example-repo/releases/tag/v1.0.0"
MD_BLOB_URL = "https://github.com/example-org/example-repo/blob/main/docs/setup.md"
TXT_BLOB_URL = "https://github.com/example-org/example-repo/blob/main/docs/release-notes.txt"
GENERIC_URL = "https://example.org/about"

BUILT_IN_HANDLERS = (generic.GenericHandler, tdx.TdxHandler, github.GitHubHandler)


def _soup_from_fixture(fixtures_dir, name):
    text = (fixtures_dir / name).read_text(encoding="utf-8")
    return BeautifulSoup(text, "html.parser")


def _raw_soup_from_fixture(fixtures_dir, name, url):
    """A raw .md/.txt fixture as the crawl hands it to the handler: converted to a minimal document."""
    raw_text = (fixtures_dir / name).read_text(encoding="utf-8")
    return chunk.markdown_text_to_soup(raw_text, url)


# ---------------------------------------------------------------------------
# Protocol and URL matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("handler_class", BUILT_IN_HANDLERS)
def test_built_in_handlers_satisfy_the_protocol(handler_class):
    handler = handler_class()
    assert isinstance(handler, SiteHandler)
    assert handler.source_type in SOURCE_TYPES
    assert handler.content_type(GENERIC_URL) in CONTENT_TYPES


def test_tdx_handler_claims_portal_urls_only():
    handler = tdx.TdxHandler()
    assert handler.matches(TDX_URL) is True
    assert handler.matches("https://TEAMDYNAMIX.example.edu/TDClient/1/Org/Home/") is True
    assert handler.matches(GENERIC_URL) is False
    assert handler.matches(WIKI_URL) is False


def test_github_handler_claims_git_hosts_only():
    handler = github.GitHubHandler()
    assert handler.matches(REPO_ROOT_URL) is True
    assert handler.matches("https://example-org.github.io/docs/") is True
    assert handler.matches("https://gitlab.com/example-org/example-repo") is True
    assert handler.matches("https://git.example.edu/example-repo") is True
    assert handler.matches(GENERIC_URL) is False
    assert handler.matches(TDX_URL) is False


def test_generic_handler_claims_every_url():
    handler = generic.GenericHandler()
    assert all(handler.matches(url) for url in (GENERIC_URL, TDX_URL, WIKI_URL))


@pytest.mark.parametrize("handler_class", (generic.GenericHandler, tdx.TdxHandler))
def test_html_handlers_request_the_page_at_its_own_url(handler_class):
    handler = handler_class()
    assert handler.fetch_url(GENERIC_URL) == GENERIC_URL
    assert handler.expects_html(GENERIC_URL) is True


# ---------------------------------------------------------------------------
# TeamDynamix
# ---------------------------------------------------------------------------

def test_tdx_article_title_strips_prefix_and_suffix(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "tdx_article.html")
    extraction = tdx.TdxHandler().extract(soup, TDX_URL)
    assert extraction.title == "Sleep Hygiene Tips"


def test_tdx_article_content_selected_and_boilerplate_stripped(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "tdx_article.html")
    extraction = tdx.TdxHandler().extract(soup, TDX_URL)
    text = extraction.node.get_text(" ", strip=True)
    assert "Getting Started" in text
    assert "Synthetic breadcrumb" not in text  # <nav> stripped
    assert "Synthetic footer" not in text      # <footer> stripped


def test_tdx_pages_are_knowledge_base_articles():
    handler = tdx.TdxHandler()
    assert handler.source_type == "kb"
    assert handler.content_type(TDX_URL) == "article"


def test_tdx_breadcrumb_trail_becomes_categories_outermost_first():
    html = (
        "<html><head><title>Article - Remote Study Technology</title></head><body>"
        '<nav aria-label="Breadcrumb"><ol class="breadcrumb">'
        '<li><a href="/TDClient/210/Org/KB/">Knowledge Base</a></li>'
        '<li class="active"><a href="/TDClient/210/Org/KB/Category/1005/Tech">Technology for Health Research</a></li>'
        '<li class="active">Remote Study Technology</li>'
        "</ol></nav>"
        '<div id="divMainContent"><p>Synthetic article body text for the breadcrumb test.</p></div>'
        "</body></html>"
    )
    extraction = tdx.TdxHandler().extract(BeautifulSoup(html, "html.parser"), TDX_URL)
    # The unlinked last crumb is the page itself, not a category.
    assert extraction.categories == ("Knowledge Base", "Technology for Health Research")
    assert extraction.title == "Remote Study Technology"


def test_tdx_page_without_an_article_body_is_a_link_hop(fixtures_dir):
    # A category listing has links but no #divMainContent / #questionsContent.
    soup = BeautifulSoup("<html><body><main><a href='/x'>x</a></main></body></html>", "html.parser")
    assert tdx.TdxHandler().extract(soup, TDX_URL) is None


@pytest.mark.parametrize("title, expected", [
    ("Article - Sleep Hygiene Tips", "Sleep Hygiene Tips"),
    ("Question Detail - Why is my VPN slow", "Why is my VPN slow"),
    ("Plain Title", "Plain Title"),
])
def test_strip_title_prefix(title, expected):
    assert tdx.strip_title_prefix(title) == expected


# ---------------------------------------------------------------------------
# GitHub: wiki, release notes, repository root
# ---------------------------------------------------------------------------

def test_github_wiki_content_selected_via_markdown_body(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "github_wiki.html")
    handler = github.GitHubHandler()
    extraction = handler.extract(soup, WIKI_URL)
    assert "Installation" in extraction.node.get_text(" ", strip=True)
    assert "Synthetic GitHub wiki navigation" not in extraction.node.get_text(" ", strip=True)
    assert extraction.categories == ("example-org", "example-repo")
    assert handler.content_type(WIKI_URL) == "wiki"
    assert handler.source_type == "github"


def test_github_repo_root_is_a_link_discovery_hop(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "github_repo_root.html")
    assert github.GitHubHandler().extract(soup, REPO_ROOT_URL) is None


def test_github_release_tag_content_selected_via_markdown_body(fixtures_dir):
    soup = _soup_from_fixture(fixtures_dir, "github_release_tag.html")
    handler = github.GitHubHandler()
    extraction = handler.extract(soup, RELEASE_URL)
    assert "Highlights" in extraction.node.get_text(" ", strip=True)
    assert handler.content_type(RELEASE_URL) == "release_notes"


# ---------------------------------------------------------------------------
# GitHub: raw Markdown and text files
# ---------------------------------------------------------------------------

def test_github_text_blobs_are_requested_raw_as_plain_text():
    handler = github.GitHubHandler()
    assert handler.fetch_url(MD_BLOB_URL) == (
        "https://raw.githubusercontent.com/example-org/example-repo/main/docs/setup.md"
    )
    assert handler.expects_html(MD_BLOB_URL) is False
    assert handler.fetch_url(WIKI_URL) == WIKI_URL
    assert handler.expects_html(WIKI_URL) is True


def test_raw_markdown_file_renders_headings_code_and_table(fixtures_dir):
    soup = _raw_soup_from_fixture(fixtures_dir, "raw_markdown_file.md", MD_BLOB_URL)
    handler = github.GitHubHandler()
    extraction = handler.extract(soup, MD_BLOB_URL)

    assert extraction.title == "Setup Notes"                # <h1> fallback
    assert extraction.node.find("table") is not None        # "tables" extension
    assert extraction.node.find("code") is not None         # "fenced_code" extension
    assert "Prerequisites" in extraction.node.get_text(" ", strip=True)
    assert extraction.categories == ("example-org", "example-repo", "docs")
    assert handler.content_type(MD_BLOB_URL) == "text"


def test_raw_plain_text_file_wrapped_in_pre_and_title_from_path(fixtures_dir):
    soup = _raw_soup_from_fixture(fixtures_dir, "raw_plain_text_file.txt", TXT_BLOB_URL)
    assert soup.find("pre") is not None
    extraction = github.GitHubHandler().extract(soup, TXT_BLOB_URL)
    # No <title>/<h1> in a <pre>-wrapped plain-text file -> the title is
    # derived from the blob path.
    assert extraction.title == "Release Notes"
    assert "synthetic plain-text fixture" in extraction.node.get_text(" ", strip=True)


def test_empty_raw_file_is_not_indexed():
    soup = chunk.markdown_text_to_soup("", TXT_BLOB_URL)
    assert github.GitHubHandler().extract(soup, TXT_BLOB_URL) is None


@pytest.mark.parametrize("url, expected", [
    ("https://github.com/example-org/example-repo/blob/main/README.md", "readme"),
    ("https://github.com/example-org/example-repo/blob/main/docs/readme.txt", "readme"),
    (MD_BLOB_URL, "text"),
    (WIKI_URL, "wiki"),
    (RELEASE_URL, "release_notes"),
    (REPO_ROOT_URL, "page"),
])
def test_github_content_type_by_url(url, expected):
    assert github.GitHubHandler().content_type(url) == expected


def test_derive_title_from_blob_path():
    assert github.derive_title_from_blob_path(TXT_BLOB_URL) == "Release Notes"


@pytest.mark.parametrize("url, expected", [
    (REPO_ROOT_URL, ("example-org", "example-repo")),
    (WIKI_URL, ("example-org", "example-repo")),
    (MD_BLOB_URL, ("example-org", "example-repo", "docs")),
    ("https://github.com/example-org/example-repo/blob/main/README.md", ("example-org", "example-repo")),
    ("https://github.com", ()),
])
def test_repository_categories(url, expected):
    assert github.repository_categories(url) == expected


# ---------------------------------------------------------------------------
# GitHub: URL helpers (carried over from the reference's scope helpers)
# ---------------------------------------------------------------------------

def test_is_git_host_url():
    assert github.is_git_host_url(REPO_ROOT_URL) is True
    assert github.is_git_host_url("https://example.org/docs") is False


def test_is_git_blob_text_url():
    assert github.is_git_blob_text_url(MD_BLOB_URL) is True
    assert github.is_git_blob_text_url("https://github.com/example-org/example-repo/blob/main/src/app.py") is False
    assert github.is_git_blob_text_url("https://github.com/example-org/example-repo/tree/main/docs") is False


def test_to_git_raw_url_rewrites_blob_to_raw_githubusercontent():
    assert (
        github.to_git_raw_url(MD_BLOB_URL)
        == "https://raw.githubusercontent.com/example-org/example-repo/main/docs/setup.md"
    )


# ---------------------------------------------------------------------------
# Generic fallback
# ---------------------------------------------------------------------------

def test_generic_page_uses_generic_content_selectors_fallback(fixtures_dir):
    """
    The portal-flavoured selectors stay in the generic list on purpose: a
    knowledge-base portal on its own domain never reaches the tdx handler,
    and the bare "main" fallback comes after them.
    """
    soup = _soup_from_fixture(fixtures_dir, "generic_page_with_main.html")
    handler = generic.GenericHandler()
    extraction = handler.extract(soup, GENERIC_URL)
    assert extraction.node.name == "main"
    assert "About" in extraction.node.get_text(" ", strip=True)
    assert extraction.title == "Welcome"
    assert extraction.categories == ()
    assert handler.source_type == "web"
    assert handler.content_type(GENERIC_URL) == "page"


def test_generic_page_without_a_content_selector_is_a_link_hop():
    soup = BeautifulSoup("<html><body><div><a href='/x'>x</a></div></body></html>", "html.parser")
    assert generic.GenericHandler().extract(soup, GENERIC_URL) is None


def test_page_title_prefers_title_tag_then_h1_then_none():
    assert generic.page_title(BeautifulSoup("<title>Guide | Site</title><h1>H</h1>", "html.parser")) == "Guide"
    assert generic.page_title(BeautifulSoup("<h1>Heading Only</h1>", "html.parser")) == "Heading Only"
    assert generic.page_title(BeautifulSoup("<p>nothing</p>", "html.parser")) is None
    assert generic.GenericHandler().extract(
        BeautifulSoup("<main><p>Untitled page body.</p></main>", "html.parser"), GENERIC_URL
    ).title == generic.UNTITLED


# ---------------------------------------------------------------------------
# Exclude patterns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("handler_class", BUILT_IN_HANDLERS)
def test_handler_index_excludes_are_a_superset_of_its_crawl_excludes(handler_class):
    """A page never worth fetching is never worth indexing either."""
    handler = handler_class()
    assert set(handler.default_crawl_exclude_patterns) <= set(handler.default_index_exclude_patterns)
