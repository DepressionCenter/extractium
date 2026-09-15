"""
Summary: Tests for the google_docs site handler: which addresses it
claims, how it folds the several link shapes of one file into one
address, the export address it requests for each kind, the title it
reads from an export, the landing it accepts, and a crawl that reaches
a shared document through an include pattern and indexes it once under
its one address. A file that is not shared answers with a sign-in
page, which the crawl reports and skips. Uses the synthetic exports in
tests/fixtures/; no test contacts Google.

This file is part of Extractium™
tests/test_site_google_docs.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-15
Last Modified: 2026-09-15
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
__date__ = "2026-09-15"

import pytest

from extractium.core import chunk
from extractium.core.models import SiteHandler
from extractium.sources import google_docs, web
from extractium.sources.google_docs import GoogleDocsHandler
from tests.conftest import FakeResponse
from tests.test_web_source import (
    BUILT_IN_HANDLERS, ROBOTS_ABSENT, crawl, html_response, make_source, text_response,
)

DOC_ID = "1ExampleDocumentIdentifier_abc-123"
SHEET_ID = "1ExampleSheetIdentifier_def-456"
SLIDES_ID = "1ExampleSlidesIdentifier_ghi-789"

DOC_EDIT_URL = f"https://docs.google.com/document/d/{DOC_ID}/edit?usp=sharing&ouid=1234&rtpof=true&sd=true"
DOC_VIEW_URL = f"https://docs.google.com/document/d/{DOC_ID}/view"
DOC_CANONICAL = f"https://docs.google.com/document/d/{DOC_ID}"
DOC_EXPORT = f"{DOC_CANONICAL}/export?format=txt"
SHEET_CANONICAL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
SHEET_EXPORT = f"{SHEET_CANONICAL}/export?format=csv"
SLIDES_CANONICAL = f"https://docs.google.com/presentation/d/{SLIDES_ID}"
SLIDES_EXPORT = f"{SLIDES_CANONICAL}/export?format=txt"

SEED = "https://example.org/resources"
INCLUDE_GOOGLE = (r"^https://example\.org/", r"^https://docs\.google\.com/")
HANDLERS = (GoogleDocsHandler(),) + BUILT_IN_HANDLERS
GOOGLE_ROBOTS_URL = "https://docs.google.com/robots.txt"
SEED_ROBOTS_URL = "https://example.org/robots.txt"

# Where a document that is not shared sends its export request.
SIGN_IN_URL = "https://accounts.google.com/ServiceLogin?continue=https://docs.google.com/document/d/x/export"

# Where every shared export is served from.
DELIVERY_URL = "https://doc-0s-8s-docstext.googleusercontent.com/export/abc123/def456"


@pytest.fixture
def doc_export(fixtures_dir):
    return (fixtures_dir / "google_doc_export.txt").read_text(encoding="utf-8")


@pytest.fixture
def sheet_export(fixtures_dir):
    return (fixtures_dir / "google_sheet_export.csv").read_text(encoding="utf-8")


def resources_page(*links):
    """A page on the example site linking to whatever addresses a test names."""
    anchors = "".join(f'<a href="{link}">A shared file</a>' for link in links)
    return html_response(f"<html><head><title>Resources</title></head><body><main><p>Files:</p>{anchors}</main></body></html>")


def google_crawl(session, progress=None):
    """A crawl of the example site that may follow links into docs.google.com."""
    source = make_source(SEED, handlers=HANDLERS, include_patterns=INCLUDE_GOOGLE)
    lines = []
    documents = crawl(source, session, progress=(progress or lines.append))
    return documents, lines


# ---------------------------------------------------------------------------
# Recognition and addresses
# ---------------------------------------------------------------------------

def test_the_handler_satisfies_the_protocol():
    assert isinstance(GoogleDocsHandler(), SiteHandler)
    assert GoogleDocsHandler.source_type == "web"
    assert GoogleDocsHandler().content_type(DOC_CANONICAL) == "text"


@pytest.mark.parametrize("url, expected", [
    (DOC_EDIT_URL, ("document", DOC_ID)),
    (DOC_VIEW_URL, ("document", DOC_ID)),
    (f"https://docs.google.com/document/u/0/d/{DOC_ID}/edit", ("document", DOC_ID)),
    (f"{SHEET_CANONICAL}/edit#gid=0", ("spreadsheets", SHEET_ID)),
    (f"{SLIDES_CANONICAL}/edit?usp=sharing", ("presentation", SLIDES_ID)),
    ("https://docs.google.com/forms/d/e/1FAIpQLSexample/viewform", None),
    ("https://docs.google.com/document/create", None),
    ("https://drive.google.com/drive/folders/1ExampleFolder", None),
    ("https://example.org/document/d/abc/edit", None),
])
def test_the_handler_claims_files_on_docs_google_com_only(url, expected):
    assert google_docs.file_kind_and_id(url) == expected
    assert GoogleDocsHandler().matches(url) is (expected is not None)


def test_every_link_shape_of_one_file_folds_to_one_address():
    handler = GoogleDocsHandler()
    for url in (DOC_EDIT_URL, DOC_VIEW_URL, f"{DOC_CANONICAL}/preview", f"{DOC_CANONICAL}/"):
        assert handler.canonical_url(url) == DOC_CANONICAL
    assert handler.canonical_url("https://example.org/page") == "https://example.org/page"


def test_each_kind_is_requested_at_its_export_address_as_text():
    handler = GoogleDocsHandler()
    assert handler.fetch_url(DOC_EDIT_URL) == DOC_EXPORT
    assert handler.fetch_url(f"{SHEET_CANONICAL}/edit#gid=0") == SHEET_EXPORT
    assert handler.fetch_url(f"{SLIDES_CANONICAL}/edit?usp=sharing") == SLIDES_EXPORT
    assert handler.expects_html(DOC_CANONICAL) is False


def test_an_export_may_land_on_the_delivery_host_and_nowhere_else():
    handler = GoogleDocsHandler()
    assert handler.landing_allowed(DOC_CANONICAL, DELIVERY_URL) is True
    assert handler.landing_allowed(DOC_CANONICAL, SIGN_IN_URL) is False
    assert handler.landing_allowed("https://example.org/page", DELIVERY_URL) is False


def test_the_handler_keeps_forms_drive_and_the_sign_in_host_out_of_every_crawl():
    patterns = web.default_exclude_patterns(HANDLERS, "crawl")
    compiled = web.fetching.compile_patterns(patterns)
    for url in (
        "https://docs.google.com/forms/d/e/1FAIpQLSexample/viewform",
        "https://drive.google.com/drive/folders/1ExampleFolder",
        SIGN_IN_URL,
    ):
        assert any(r.search(url) for r in compiled), url
    assert not any(r.search(DOC_CANONICAL) for r in compiled)
    assert not any(r.search("https://example.org/forms/") for r in compiled)


# ---------------------------------------------------------------------------
# What is read from an export
# ---------------------------------------------------------------------------

def test_the_title_is_the_first_line_of_the_export(doc_export):
    soup = chunk.markdown_text_to_soup(doc_export, DOC_CANONICAL)

    extraction = GoogleDocsHandler().extract(soup, DOC_CANONICAL)

    assert extraction.title == "Post-Test Survey Instructions"
    assert extraction.categories == ("Google Docs", "Documents")
    assert "class code printed on the handout" in extraction.node.get_text()


def test_a_long_first_line_is_cut_and_a_blank_export_is_untitled():
    assert google_docs.title_from_export("word " * 60, "document").endswith("...")
    assert len(google_docs.title_from_export("word " * 60, "document")) == google_docs.MAX_TITLE_CHARS
    assert google_docs.title_from_export("\n  \n", "spreadsheets") == "Untitled Google Sheet"
    assert google_docs.title_from_export(chr(0xFEFF) + "Marked", "presentation") == "Marked"


def test_an_empty_export_yields_nothing():
    soup = chunk.markdown_text_to_soup("", DOC_CANONICAL)
    assert GoogleDocsHandler().extract(soup, DOC_CANONICAL) is None


# ---------------------------------------------------------------------------
# Through a crawl
# ---------------------------------------------------------------------------

def test_a_shared_document_linked_three_ways_is_fetched_once_under_its_one_address(
    isolated_core_cache, fake_session_factory, doc_export,
):
    session = fake_session_factory({
        SEED_ROBOTS_URL: ROBOTS_ABSENT,
        GOOGLE_ROBOTS_URL: ROBOTS_ABSENT,
        SEED: resources_page(DOC_EDIT_URL, DOC_VIEW_URL, f"{DOC_CANONICAL}/preview"),
        DOC_EXPORT: text_response(doc_export),
    })

    documents, lines = google_crawl(session)

    google = [d for d in documents if "docs.google.com" in d.url]
    assert [d.url for d in google] == [DOC_CANONICAL]
    assert google[0].title == "Post-Test Survey Instructions"
    assert google[0].source_type == "web"
    assert google[0].content_type == "text"
    assert google[0].categories == ("Google Docs", "Documents")
    assert [c["url"] for c in session.calls].count(DOC_EXPORT) == 1
    assert any(line.startswith(f"[   2] {DOC_CANONICAL}") for line in lines)


def test_a_spreadsheet_export_is_read_as_csv(isolated_core_cache, fake_session_factory, sheet_export):
    session = fake_session_factory({
        SEED_ROBOTS_URL: ROBOTS_ABSENT,
        GOOGLE_ROBOTS_URL: ROBOTS_ABSENT,
        SEED: resources_page(f"{SHEET_CANONICAL}/edit#gid=0"),
        SHEET_EXPORT: FakeResponse(200, {"Content-Type": "text/csv; charset=utf-8"}, sheet_export),
    })

    documents, _ = google_crawl(session)

    sheet = [d for d in documents if d.url == SHEET_CANONICAL]
    assert len(sheet) == 1
    assert sheet[0].title == "School,Grade,Sessions,Facilitator role"
    assert sheet[0].categories == ("Google Docs", "Spreadsheets")
    assert "Example Charter Academy" in sheet[0].content.get_text()


def test_an_export_served_from_the_delivery_host_is_not_a_redirect_off_the_site(
    isolated_core_cache, fake_session_factory, doc_export,
):
    session = fake_session_factory({
        SEED_ROBOTS_URL: ROBOTS_ABSENT,
        GOOGLE_ROBOTS_URL: ROBOTS_ABSENT,
        SEED: resources_page(DOC_EDIT_URL),
        DOC_EXPORT: FakeResponse(200, {"Content-Type": "text/plain"}, doc_export, url=DELIVERY_URL),
    })

    documents, lines = google_crawl(session)

    assert [d.url for d in documents if "docs.google.com" in d.url] == [DOC_CANONICAL]
    assert not any("SKIP" in line and "docs.google.com" in line for line in lines)


def test_a_document_that_is_not_shared_is_reported_and_skipped(isolated_core_cache, fake_session_factory):
    """
    The export of a private file is a sign-in page. The crawl says so,
    with the landing address, and never asks again with a credential.
    """
    session = fake_session_factory({
        SEED_ROBOTS_URL: ROBOTS_ABSENT,
        GOOGLE_ROBOTS_URL: ROBOTS_ABSENT,
        SEED: resources_page(DOC_EDIT_URL),
        DOC_EXPORT: FakeResponse(
            200, {"Content-Type": "text/html; charset=utf-8"}, "<html><title>Sign in</title></html>",
            url=SIGN_IN_URL,
        ),
    })

    documents, lines = google_crawl(session)

    assert not any("docs.google.com" in d.url for d in documents)
    skip = [line for line in lines if line.startswith(f"  SKIP {DOC_EXPORT}")]
    assert len(skip) == 1
    assert "text/html" in skip[0] and "accounts.google.com" in skip[0]
    assert [c["url"] for c in session.calls].count(DOC_EXPORT) == 1
    assert not any("accounts.google.com" in c["url"] for c in session.calls)


def test_google_files_are_off_site_without_an_include_pattern(isolated_core_cache, fake_session_factory, doc_export):
    session = fake_session_factory({
        SEED_ROBOTS_URL: ROBOTS_ABSENT,
        SEED: resources_page(DOC_EDIT_URL),
        DOC_EXPORT: text_response(doc_export),
    })
    source = make_source(SEED, handlers=HANDLERS)

    documents = crawl(source, session)

    assert not any("docs.google.com" in d.url for d in documents)
    assert not any("docs.google.com" in c["url"] for c in session.calls)


def test_a_shared_document_is_reached_through_a_leaf_pattern_and_indexed_under_its_one_address(
    isolated_core_cache, fake_session_factory, doc_export,
):
    """
    The usual way to reach a shared file: the site stays in its own
    scope, and a leaf pattern lets the crawl read what it links to on
    docs.google.com without crawling anything there.
    """
    session = fake_session_factory({
        SEED_ROBOTS_URL: ROBOTS_ABSENT,
        GOOGLE_ROBOTS_URL: ROBOTS_ABSENT,
        SEED: resources_page(DOC_EDIT_URL, DOC_VIEW_URL),
        DOC_EXPORT: text_response(doc_export),
    })
    source = make_source(SEED, handlers=HANDLERS, leaf_patterns=(r"^https://docs\.google\.com/",))
    lines = []

    documents = crawl(source, session, progress=lines.append)

    assert [d.url for d in documents] == [SEED, DOC_CANONICAL]
    assert documents[1].title == "Post-Test Survey Instructions"
    assert [c["url"] for c in session.calls].count(DOC_EXPORT) == 1
    assert "       (leaf; its links are not followed)" in lines
