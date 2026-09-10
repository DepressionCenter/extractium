"""
Summary: Tests for the DSpace repository source (extractium.sources.dspace
and extractium.sources.dspace_client): how a configured collection is
read, whether it is a handle or an identifier; the listing and its paging;
what a deposit becomes; the three kinds of address a deposit carries; the
extracted text and the ceiling on it; the change stamp that keeps a
rebuild from downloading anything; and the checks that keep an untrusted
response from sending a request somewhere it was not meant to go. Every
response is scripted from the committed fixture in tests/fixtures/dspace
-- no test contacts a repository.

This file is part of Extractium™
tests/test_source_dspace.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-10
Last Modified: 2026-09-10
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
__date__ = "2026-09-10"

import copy
import json
import pathlib

import pytest

from extractium.core.models import Source
from extractium.core.registry import build_registry
from extractium.sources.dspace import (
    DSpaceSource,
    DSpaceSourceError,
    collapse_whitespace,
    sorted_identifiers,
)
from extractium.sources.dspace_client import (
    DSpaceClient,
    DSpaceNotAnInterface,
    DSpaceUnavailable,
    collection_selectors,
    parse_collection_selector,
)
from tests.conftest import FakeApiResponse, FakeDSpaceSession

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "dspace" / "example_repository.json"

# The collection every test reads, and the deposit whose files carry text.
COLLECTION_ID = "11111111-1111-4111-8111-111111111111"
COLLECTION_HANDLE = "9999.1/1001"
TEXT_DEPOSIT_ID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
TEXT_CONTENT_URL = (
    "https://repository.example.edu/server/api/core/bitstreams/"
    "a2222222-2222-4222-8222-a22222222222/content"
)
LICENSE_CONTENT_URL = (
    "https://repository.example.edu/server/api/core/bitstreams/"
    "a4444444-4444-4444-8444-a44444444444/content"
)


@pytest.fixture(autouse=True)
def _deposit_cache_in_a_temporary_folder(isolated_core_cache):
    """
    Keeps every test's stored deposit text in its own temporary folder.

    Without this, one test's download would satisfy the next test's read,
    and a test asserting that nothing was downloaded would pass for the
    wrong reason.
    """


@pytest.fixture
def fixture():
    """The synthetic repository every test in this module reads."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def quiet(line):
    """A progress sink for tests that do not inspect progress."""


def options(fixture, collections=(COLLECTION_ID,), **overrides):
    """The validated options of a dspace source entry, as the configuration produces them."""
    settings = {
        "api_url": fixture["api_url"],
        "site_url": fixture["site_url"],
        "collections": tuple(collections),
        "include_full_text": True,
        "max_file_bytes": 2_000_000,
    }
    settings.update(overrides)
    return settings


def search_page(records, page=0, total_pages=1):
    """One page of a discover search, shaped the way the interface answers one."""
    return {
        "_embedded": {
            "searchResult": {
                "page": {
                    "number": page,
                    "size": 100,
                    "totalPages": total_pages,
                    "totalElements": len(records),
                },
                "_embedded": {
                    "objects": [{"_embedded": {"indexableObject": record}} for record in records],
                },
            }
        }
    }


def routes(fixture, pages=None, collection=None, texts=None):
    """
    The scripted interface answers for the synthetic repository.

    Args:
        fixture (dict): the loaded fixture file.
        pages (list | None): the listing pages to serve, each a list of
            deposit records; one page of the fixture's own deposits by
            default.
        collection (dict | None): the collection record to serve; the
            fixture's own by default.
        texts (dict | None): file address to body; the fixture's own by
            default.
    """
    api = fixture["api_url"]
    pages = [fixture["deposits_page_one"]] if pages is None else pages
    collection = fixture["collection"] if collection is None else collection
    texts = fixture["texts"] if texts is None else texts

    scripted = {
        f"{api}/core/collections/{collection['uuid']}": FakeApiResponse(payload=collection),
        f"{api}/pid/find": FakeApiResponse(
            status_code=302,
            headers={"Location": f"{api}/core/collections/{collection['uuid']}"},
        ),
        f"{api}/discover/search/objects": [
            FakeApiResponse(payload=search_page(records, page=number, total_pages=len(pages)))
            for number, records in enumerate(pages)
        ],
    }
    for href, body in texts.items():
        scripted[href] = FakeApiResponse(
            headers={"content-type": "text/plain;charset=UTF-8"}, text=body
        )
    return scripted


def read(fixture, session=None, progress=quiet, **option_overrides):
    """Runs the source against a scripted session and returns the documents and the source."""
    session = session if session is not None else FakeDSpaceSession(routes(fixture))
    source = DSpaceSource(options(fixture, **option_overrides))
    return list(source.fetch(session, {}, progress)), source


def body_of(documents, title):
    """The indexed body of one document, found by title."""
    return next(document.content for document in documents if document.title == title)


### Registration ###

def test_the_repository_source_is_registered_under_its_own_name():
    registry = build_registry()
    assert registry.get_source("dspace") is DSpaceSource


def test_the_repository_source_satisfies_the_source_protocol():
    assert isinstance(DSpaceSource(options({"api_url": "https://r.example.edu/server/api",
                                            "site_url": "https://r.example.edu"})), Source)


### Configured Collections ###

@pytest.mark.parametrize("written, selector", [
    ("11111111-1111-4111-8111-111111111111", "11111111-1111-4111-8111-111111111111"),
    ("11111111-1111-4111-8111-111111111111".upper(), "11111111-1111-4111-8111-111111111111"),
    ("https://hdl.handle.net/9999.1/1001", "hdl:9999.1/1001"),
    ("http://hdl.handle.net/9999.1/1001", "hdl:9999.1/1001"),
    ("9999.1/1001", "hdl:9999.1/1001"),
    ("hdl:9999.1/1001", "hdl:9999.1/1001"),
    ("https://repository.example.edu/collections/11111111-1111-4111-8111-111111111111",
     "11111111-1111-4111-8111-111111111111"),
    ("https://repository.example.edu/handle/9999.1/1001", "hdl:9999.1/1001"),
])
def test_a_collection_may_be_written_as_a_handle_or_as_an_identifier(written, selector):
    assert parse_collection_selector(written) == selector


def test_one_deposit_is_not_a_collection():
    with pytest.raises(ValueError, match="one deposit, not a collection"):
        parse_collection_selector(
            "https://repository.example.edu/items/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
        )


@pytest.mark.parametrize("written", ["", "   ", "not-a-collection", "hdl:nonsense",
                                     "https://repository.example.edu/", "2027.42"])
def test_anything_that_names_no_collection_is_refused(written):
    with pytest.raises(ValueError):
        parse_collection_selector(written)


def test_the_same_collection_written_two_ways_is_read_once():
    assert collection_selectors([
        "https://hdl.handle.net/9999.1/1001",
        "hdl:9999.1/1001",
    ]) == ("hdl:9999.1/1001",)


def test_a_handle_is_resolved_by_reading_the_redirect_rather_than_following_it(fixture):
    session = FakeDSpaceSession(routes(fixture))
    documents, _ = read(fixture, session=session, collections=(f"hdl:{COLLECTION_HANDLE}",))

    lookup = next(call for call in session.calls if call["url"].endswith("/pid/find"))
    assert lookup["params"]["id"] == f"hdl:{COLLECTION_HANDLE}"
    assert lookup["allow_redirects"] is False
    assert documents


def test_a_handle_naming_a_deposit_is_refused_rather_than_searched(fixture):
    api = fixture["api_url"]
    scripted = routes(fixture)
    scripted[f"{api}/pid/find"] = FakeApiResponse(
        status_code=302,
        headers={"Location": f"{api}/core/items/{TEXT_DEPOSIT_ID}"},
    )
    with pytest.raises(DSpaceSourceError, match="names a deposit"):
        read(fixture, session=FakeDSpaceSession(scripted),
             collections=(f"hdl:{COLLECTION_HANDLE}",))


def test_a_handle_pointed_at_another_host_is_refused(fixture):
    api = fixture["api_url"]
    scripted = routes(fixture)
    scripted[f"{api}/pid/find"] = FakeApiResponse(
        status_code=302,
        headers={"Location": "https://elsewhere.example.net/core/collections/"
                             "11111111-1111-4111-8111-111111111111"},
    )
    with pytest.raises(DSpaceSourceError, match="not a collection on"):
        read(fixture, session=FakeDSpaceSession(scripted),
             collections=(f"hdl:{COLLECTION_HANDLE}",))


def test_a_collection_the_repository_does_not_have_stops_the_source(fixture):
    missing = "22222222-2222-4222-8222-222222222222"
    with pytest.raises(DSpaceSourceError, match=missing):
        read(fixture, session=FakeDSpaceSession(routes(fixture)), collections=(missing,))


def test_a_collection_is_confirmed_before_any_search_is_made(fixture):
    session = FakeDSpaceSession(routes(fixture))
    read(fixture, session=session)

    assert session.urls[0].endswith(f"/core/collections/{COLLECTION_ID}")
    assert "/discover/search/objects" in session.urls[1]


def test_an_identifier_that_is_not_a_uuid_never_reaches_a_request(fixture):
    session = FakeDSpaceSession(routes(fixture))
    source = DSpaceSource(options(fixture, collections=("../core/collections",)))
    with pytest.raises(DSpaceSourceError, match="UUID"):
        list(source.fetch(session, {}, quiet))
    assert session.calls == []


### Reading A Collection ###

def test_every_published_deposit_becomes_one_document(fixture):
    documents, _ = read(fixture)

    titles = [document.title for document in documents]
    assert titles == [
        "Wearable Sleep Tracking in Practice",
        "Poster: Example Study Findings",
        "Example Dataset Documentation",
        "Example Deposit Without Identifiers",
    ]


def test_a_withdrawn_deposit_produces_nothing(fixture):
    documents, _ = read(fixture)
    assert all("Withdrawn" not in document.title for document in documents)


def test_a_deposit_still_in_a_submission_workflow_produces_nothing(fixture):
    pages = copy.deepcopy(fixture["deposits_page_one"])
    pages[1]["inArchive"] = False
    documents, _ = read(fixture, session=FakeDSpaceSession(routes(fixture, pages=[pages])))

    assert all("Poster" not in document.title for document in documents)


def test_a_record_with_no_title_is_reported_rather_than_indexed(fixture):
    pages = copy.deepcopy(fixture["deposits_page_one"])
    pages[0]["metadata"].pop("dc.title")
    pages[0].pop("name")
    lines = []
    documents, _ = read(
        fixture,
        session=FakeDSpaceSession(routes(fixture, pages=[pages])),
        progress=lines.append,
    )

    assert all("Wearable" not in document.title for document in documents)
    assert any("no identifier or title" in line for line in lines)


def test_an_empty_collection_produces_nothing_and_does_not_fail(fixture):
    documents, source = read(fixture, session=FakeDSpaceSession(routes(fixture, pages=[[]])))

    assert documents == []
    assert source.coverage == (("Example Research Collection", 0, 0),)


def test_a_listing_is_read_across_every_page(fixture):
    session = FakeDSpaceSession(routes(
        fixture, pages=[fixture["deposits_page_one"], fixture["deposits_page_two"]]
    ))
    documents, _ = read(fixture, session=session)

    assert "Example Deposit On The Second Page" in [document.title for document in documents]
    pages = [call["params"]["page"] for call in session.calls
             if "/discover/search/objects" in call["url"]]
    assert pages == [0, 1]


def test_a_listing_asks_for_the_files_alongside_the_metadata(fixture):
    session = FakeDSpaceSession(routes(fixture))
    read(fixture, session=session)

    search = next(call for call in session.calls if "/discover/search/objects" in call["url"])
    assert search["params"]["embed"] == "bundles/bitstreams"
    assert search["params"]["scope"] == COLLECTION_ID
    assert search["params"]["dsoType"] == "item"


def test_an_interface_that_answers_a_web_page_is_reported_clearly(fixture):
    api = fixture["api_url"]
    scripted = {
        f"{api}/core/collections/{COLLECTION_ID}": FakeApiResponse(
            headers={"content-type": "text/html; charset=UTF-8"},
            text="<!DOCTYPE html><html><head><title>Example Repository</title></head></html>",
        ),
    }
    with pytest.raises(DSpaceSourceError, match="reader site"):
        read(fixture, session=FakeDSpaceSession(scripted))


def test_a_search_answered_with_something_other_than_a_listing_is_reported(fixture):
    api = fixture["api_url"]
    scripted = routes(fixture)
    scripted[f"{api}/discover/search/objects"] = FakeApiResponse(payload={"type": "discover"})
    with pytest.raises(DSpaceSourceError, match="other than a list of deposits"):
        read(fixture, session=FakeDSpaceSession(scripted))


### What A Deposit Becomes ###

def test_a_document_points_at_the_deposit_page_a_person_can_open(fixture):
    documents, _ = read(fixture)

    assert documents[0].url == f"{fixture['site_url']}/items/{TEXT_DEPOSIT_ID}"


def test_a_deposit_is_recorded_as_a_repository_article_in_its_collection(fixture):
    documents, _ = read(fixture)

    assert documents[0].source_type == "repository"
    assert documents[0].content_type == "article"
    assert documents[0].categories == ("Example Research Collection",)


def test_the_abstract_comes_before_the_facts_and_the_facts_before_the_file_text(fixture):
    documents, _ = read(fixture)
    body = documents[0].content

    assert body.startswith("A synthetic abstract")
    assert body.index("Authors: Example, Ada; Sample, Bo") < body.index("Summary")
    assert "Published: 2026-01-26" in body
    assert "Publisher: Example Research Center" in body
    assert "Rights: Attribution-ShareAlike 4.0 International" in body
    assert "Collection: Example Research Collection" in body


def test_a_subject_listed_twice_is_recorded_once(fixture):
    documents, _ = read(fixture)

    subjects = next(line for line in documents[0].content.splitlines()
                    if line.startswith("Subjects: "))
    assert subjects == "Subjects: sleep-research, wearables, example-topic"


def test_the_deposited_files_are_named_with_their_sizes(fixture):
    documents, _ = read(fixture)

    assert "Files: Wearable Sleep Tracking in Practice.pdf (134.9 KB)" in documents[0].content


def test_who_submitted_a_deposit_is_never_indexed(fixture):
    documents, _ = read(fixture)

    assert all("depositor@example.edu" not in document.content for document in documents)
    assert all("Example Depositor" not in document.content for document in documents)


### Identifiers ###

def test_the_three_kinds_of_address_are_told_apart_and_all_kept(fixture):
    body = body_of(read(fixture)[0], "Wearable Sleep Tracking in Practice")

    assert "Permanent address: https://hdl.handle.net/9999.1/2001" in body
    assert "DOI: https://doi.org/10.9999/example-1 https://dx.doi.org/10.9999/example-1" in body
    assert "Also published at: https://docs.example.edu/guides/sleep-measures" in body


def test_a_deposit_with_only_a_handle_carries_only_that(fixture):
    body = body_of(read(fixture)[0], "Poster: Example Study Findings")

    assert "Permanent address: https://hdl.handle.net/9999.1/2002" in body
    assert "DOI:" not in body
    assert "Also published at:" not in body


def test_a_deposit_with_no_addresses_at_all_is_still_indexed(fixture):
    body = body_of(read(fixture)[0], "Example Deposit Without Identifiers")

    assert body.startswith("A synthetic abstract")
    assert "Permanent address:" not in body


def test_the_same_address_written_twice_is_recorded_once():
    deposit = {"metadata": {
        "dc.identifier.uri": [{"value": "https://doi.org/10.9999/example-1"}],
        "dc.identifier.doi": [{"value": "https://doi.org/10.9999/example-1"}],
    }}
    assert sorted_identifiers(deposit) == ([], ["https://doi.org/10.9999/example-1"], [])


### Extracted Text ###

def test_the_text_a_repository_extracted_is_indexed(fixture):
    body = body_of(read(fixture)[0], "Wearable Sleep Tracking in Practice")

    assert "Synthetic body text standing in for the plain text" in body


def test_extracted_text_is_tidied_before_it_is_indexed(fixture):
    body = body_of(read(fixture)[0], "Wearable Sleep Tracking in Practice")

    assert "  " not in body
    assert "\n\n\n" not in body
    assert " \n" not in body


def test_collapsing_whitespace_keeps_paragraph_breaks():
    assert collapse_whitespace("One   line  \n \n \n Another   line \n") == "One line\n\nAnother line"


def test_only_the_extracted_text_is_downloaded(fixture):
    session = FakeDSpaceSession(routes(fixture))
    read(fixture, session=session)

    assert TEXT_CONTENT_URL in session.urls
    assert LICENSE_CONTENT_URL not in session.urls
    assert not any("thumbnail" in url.lower() for url in session.urls)


def test_a_deposit_whose_files_hold_no_readable_text_says_so(fixture):
    body = body_of(read(fixture)[0], "Poster: Example Study Findings")

    assert "No text could be read out of the file(s) deposited here" in body
    assert "Files: Example_Poster_2025.png (2.7 MB)" in body


def test_an_extracted_text_file_over_the_ceiling_is_named_and_skipped(fixture):
    lines = []
    documents, source = read(fixture, progress=lines.append)
    body = body_of(documents, "Example Dataset Documentation")

    assert any("over the 2000000 byte ceiling" in line for line in lines)
    assert "Synthetic text for an oversized file" not in body
    assert body.startswith("A synthetic abstract")


def test_a_body_larger_than_the_ceiling_is_refused_even_if_the_listing_understated_it(fixture):
    api = fixture["api_url"]
    scripted = routes(fixture)
    scripted[TEXT_CONTENT_URL] = FakeApiResponse(
        headers={"content-type": "text/plain"}, text="x" * 2_000_001
    )
    lines = []
    documents, _ = read(fixture, session=FakeDSpaceSession(scripted), progress=lines.append)

    assert any("byte ceiling" in line for line in lines)
    assert "xxxx" not in body_of(documents, "Wearable Sleep Tracking in Practice")
    assert api  # the interface address is unchanged by the refusal


def test_a_file_answered_as_something_other_than_text_is_left_out(fixture):
    scripted = routes(fixture)
    scripted[TEXT_CONTENT_URL] = FakeApiResponse(
        headers={"content-type": "application/octet-stream"}, text="not text"
    )
    documents, _ = read(fixture, session=FakeDSpaceSession(scripted))

    assert "not text" not in body_of(documents, "Wearable Sleep Tracking in Practice")


def test_a_file_address_on_another_host_is_never_requested(fixture):
    pages = copy.deepcopy(fixture["deposits_page_one"])
    bundles = pages[0]["_embedded"]["bundles"]["_embedded"]["bundles"]
    text_bundle = next(bundle for bundle in bundles if bundle["name"] == "TEXT")
    files = text_bundle["_embedded"]["bitstreams"]["_embedded"]["bitstreams"]
    files[0]["_links"]["content"]["href"] = "https://elsewhere.example.net/steal/content"

    session = FakeDSpaceSession(routes(fixture, pages=[pages]))
    lines = []
    documents, _ = read(fixture, session=session, progress=lines.append)

    assert all("elsewhere.example.net" not in url for url in session.urls)
    assert any("is not a file on" in line for line in lines)
    assert body_of(documents, "Wearable Sleep Tracking in Practice").startswith("A synthetic")


def test_a_deposit_is_indexed_without_its_text_when_full_text_is_switched_off(fixture):
    session = FakeDSpaceSession(routes(fixture))
    documents, _ = read(fixture, session=session, include_full_text=False)

    assert TEXT_CONTENT_URL not in session.urls
    assert "Synthetic body text" not in body_of(documents, "Wearable Sleep Tracking in Practice")


### Rebuilds ###

def test_a_collection_nobody_has_changed_downloads_nothing(fixture):
    first = FakeDSpaceSession(routes(fixture))
    read(fixture, session=first)
    assert TEXT_CONTENT_URL in first.urls

    second = FakeDSpaceSession(routes(fixture))
    documents, source = read(fixture, session=second)

    assert TEXT_CONTENT_URL not in second.urls
    assert source.downloads == 0
    assert "Synthetic body text standing in for the plain text" in body_of(
        documents, "Wearable Sleep Tracking in Practice"
    )


def test_only_a_deposit_the_repository_says_changed_is_read_again(fixture):
    read(fixture, session=FakeDSpaceSession(routes(fixture)))

    changed = copy.deepcopy(fixture["deposits_page_one"])
    changed[0]["lastModified"] = "2026-09-01T00:00:00.000+00:00"
    session = FakeDSpaceSession(routes(fixture, pages=[changed]))
    _, source = read(fixture, session=session)

    assert TEXT_CONTENT_URL in session.urls
    assert source.downloads == 1


### Reporting ###

def test_the_report_says_how_much_of_a_collection_is_description_only(fixture):
    _, source = read(fixture)

    assert source.summary_lines() == [
        "Example Research Collection  4 deposit(s)  1 with file text  3 description only"
    ]


def test_nothing_read_reports_nothing(fixture):
    assert DSpaceSource(options(fixture)).summary_lines() == []


### Client Checks ###

def test_the_client_sends_the_builds_own_identity_and_no_credential(fixture):
    session = FakeDSpaceSession(routes(fixture))
    client = DSpaceClient(session, fixture["api_url"], user_agent="Extractium/test")
    client.collection(COLLECTION_ID)

    assert session.calls[0]["headers"]["User-Agent"] == "Extractium/test"
    assert "Authorization" not in session.calls[0]["headers"]
    assert "Cookie" not in session.calls[0]["headers"]


def test_the_client_refuses_a_file_address_that_is_not_a_deposited_file(fixture):
    client = DSpaceClient(FakeDSpaceSession({}), fixture["api_url"])
    inside = fixture["api_url"] + "/core/collections/" + COLLECTION_ID

    with pytest.raises(ValueError, match="does not name a deposited file"):
        client.deposit_text(inside, 1000)


def test_the_client_reports_an_answer_that_is_not_json(fixture):
    api = fixture["api_url"]
    session = FakeDSpaceSession({f"{api}/core/collections/{COLLECTION_ID}": FakeApiResponse()})
    client = DSpaceClient(session, api)

    with pytest.raises(DSpaceUnavailable, match="not JSON"):
        client.collection(COLLECTION_ID)


def test_the_client_names_the_reader_site_when_it_answers_instead(fixture):
    api = fixture["api_url"]
    session = FakeDSpaceSession({
        f"{api}/core/collections/{COLLECTION_ID}": FakeApiResponse(
            headers={"content-type": "text/html"}, text="<html></html>"
        )
    })
    client = DSpaceClient(session, api)

    with pytest.raises(DSpaceNotAnInterface, match="dspaceServer"):
        client.collection(COLLECTION_ID)
