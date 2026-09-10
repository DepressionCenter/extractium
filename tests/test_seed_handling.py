"""
Summary: Tests for how a build handles its starting addresses and the
ground they cover: a crawl that begins at more than one address, a seed
that redirects somewhere the crawl may not follow, and two sources that
reach the same page. No test contacts the network.

This file is part of Extractium™
tests/test_seed_handling.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-09
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
__date__ = "2026-09-09"

import pytest

from extractium import config
from extractium.core import fetch as fetching
from extractium.core.build import build_compendium, chunk_documents
from extractium.core.models import Document
from extractium.sources import web
from extractium.sources.generic import GenericHandler
from extractium.sources.github import accounts_named_by
from tests.conftest import FakeResponse

ROBOTS_ABSENT = FakeResponse(status_code=404)

# Long enough to clear the chunker's minimum section size.
BODY = ("Body text for this page that is comfortably longer than the minimum "
        "section size the chunker uses, so it becomes one section of its own.")


def quiet(line):
    """A progress sink for tests that do not inspect progress."""


def page(title, body=BODY, links=()):
    anchors = "".join(f'<a href="{href}">{href}</a>' for href in links)
    return FakeResponse(
        status_code=200,
        headers={"Content-Type": "text/html"},
        text=f"<html><head><title>{title}</title></head><body><main>"
             f"<p>{body}</p>{anchors}</main></body></html>",
    )


class RedirectingResponse(FakeResponse):
    """A response that reports landing somewhere other than where it was sent."""

    def __init__(self, final_url, **kwargs):
        super().__init__(**kwargs)
        self.url = final_url


def make_source(options, settings=None):
    validated = {
        "include_patterns": (), "crawl_exclude_patterns": None,
        "index_exclude_patterns": None, "site_handlers": None, **options,
    }
    return web.WebSource(validated, (GenericHandler(),),
                         settings or web.CrawlSettings(max_pages=10, delay_seconds=0))


# ---------------------------------------------------------------------------
# Several starting addresses, one crawl
# ---------------------------------------------------------------------------

def test_a_crawl_can_start_at_more_than_one_address(isolated_core_cache, fake_session_factory):
    """
    Two sections of one site that do not link to each other. One crawl, so
    one page list and one page budget.
    """
    first = "https://library.example/collections/aaa"
    second = "https://library.example/collections/bbb"
    session = fake_session_factory({
        first: page("Collection A"),
        second: page("Collection B", body=BODY.replace("Body", "Second")),
        "https://library.example/robots.txt": ROBOTS_ABSENT,
    })

    documents = list(make_source({"seed_urls": (first, second)}).fetch(session, {}, quiet))

    assert sorted(d.url for d in documents) == [first, second]


def test_one_seed_still_works_exactly_as_before(isolated_core_cache, fake_session_factory):
    seed = "https://example.org/start"
    session = fake_session_factory({
        seed: page("Start"), "https://example.org/robots.txt": ROBOTS_ABSENT,
    })

    documents = list(make_source({"seed_url": seed}).fetch(session, {}, quiet))

    assert [d.url for d in documents] == [seed]


def test_a_page_reachable_from_both_seeds_is_fetched_once(
    isolated_core_cache, fake_session_factory,
):
    """
    This is why several seeds beat several sources: one crawl keeps one
    list of what it has visited.
    """
    first = "https://example.org/a"
    second = "https://example.org/b"
    shared = "https://example.org/shared"
    session = fake_session_factory({
        first: page("A", links=[shared]),
        second: page("B", body=BODY.replace("Body", "Second"), links=[shared]),
        shared: page("Shared", body=BODY.replace("Body", "Shared")),
        "https://example.org/robots.txt": ROBOTS_ABSENT,
    })

    documents = list(make_source({"seed_urls": (first, second)}).fetch(session, {}, quiet))

    requested = [c["url"] for c in session.calls if not c["url"].endswith("robots.txt")]
    assert requested.count(shared) == 1
    assert len([d for d in documents if d.url == shared]) == 1


def test_scope_covers_every_seed(isolated_core_cache, fake_session_factory):
    """
    A link inside any seed's scope is followed, and nothing else is. With
    one seed, the second host would be out of scope entirely.
    """
    first = "https://a.example/docs"
    second = "https://b.example/guide"
    session = fake_session_factory({
        first: page("A", links=["https://b.example/guide/page", "https://c.example/nope"]),
        second: page("B", body=BODY.replace("Body", "Second")),
        "https://b.example/guide/page": page("B page", body=BODY.replace("Body", "Third")),
        "https://a.example/robots.txt": ROBOTS_ABSENT,
        "https://b.example/robots.txt": ROBOTS_ABSENT,
        "https://c.example/robots.txt": ROBOTS_ABSENT,
    })

    documents = list(make_source({"seed_urls": (first, second)}).fetch(session, {}, quiet))

    assert "https://b.example/guide/page" in [d.url for d in documents]
    assert not any("c.example" in c["url"] for c in session.calls)


def test_the_same_seed_written_twice_is_one_seed():
    source = make_source({"seed_urls": ("https://example.org/a", "https://example.org/a/")})

    assert source.seed_urls == ("https://example.org/a",)


def test_in_scope_takes_one_prefix_or_several():
    """The single-seed form is what every existing caller passes."""
    assert fetching.in_scope("https://a.example/x", "https://a.example", "https://a.example", [], [])
    assert fetching.in_scope(
        "https://b.example/x", ("https://a.example", "https://b.example"),
        ("https://a.example", "https://b.example"), [], [],
    )
    assert not fetching.in_scope(
        "https://c.example/x", ("https://a.example", "https://b.example"),
        ("https://a.example", "https://b.example"), [], [],
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def test_seed_urls_fills_in_both_keys():
    entry = config.config_from_mapping({
        "sources": [{"type": "web", "seed_urls": ["https://a.example/", "https://b.example/"]}],
    }).sources[0]

    assert entry.options["seed_urls"] == ("https://a.example/", "https://b.example/")
    assert entry.options["seed_url"] == "https://a.example/"


def test_one_seed_url_fills_in_both_keys_too():
    entry = config.config_from_mapping({
        "sources": [{"type": "web", "seed_url": "https://a.example/"}],
    }).sources[0]

    assert entry.options["seed_urls"] == ("https://a.example/",)
    assert entry.options["seed_url"] == "https://a.example/"


def test_giving_both_forms_is_a_contradiction():
    with pytest.raises(config.ConfigError, match="not both"):
        config.config_from_mapping({"sources": [{
            "type": "web", "seed_url": "https://a.example/", "seed_urls": ["https://b.example/"],
        }]})


def test_an_empty_seed_list_is_refused():
    with pytest.raises(config.ConfigError, match="at least one URL"):
        config.config_from_mapping({"sources": [{"type": "web", "seed_urls": []}]})


@pytest.mark.parametrize("bad", ["ftp://a.example/", "not a url", "/relative/path"])
def test_every_seed_in_the_list_is_checked(bad):
    with pytest.raises(config.ConfigError):
        config.config_from_mapping({"sources": [{
            "type": "web", "seed_urls": ["https://a.example/", bad],
        }]})


def test_every_seed_names_the_github_account_it_belongs_to():
    """A crawl starting in two GitHub accounts names both, not only the first."""
    cfg = config.config_from_mapping({"sources": [{
        "type": "web",
        "seed_urls": ["https://github.com/example-org/tools",
                      "https://github.com/other-org/tools"],
    }]})

    assert accounts_named_by(cfg.sources) == {"example-org", "other-org"}


# ---------------------------------------------------------------------------
# A seed that redirects out of scope
# ---------------------------------------------------------------------------

def test_a_seed_that_redirects_off_its_own_host_is_refused_with_the_address_to_use(
    isolated_core_cache, fake_session_factory,
):
    """
    A short link is the usual cause. The page arrives, but scope came from
    the address that was configured, so nothing on it can be followed. The
    build would index one page and stop, and nothing about the result would
    show why.
    """
    seed = "https://short.example/kb"
    landed = "https://portal.example/TDClient/210/Org/Home/"
    session = fake_session_factory({
        seed: RedirectingResponse(
            landed, status_code=200, headers={"Content-Type": "text/html"},
            text=page("Portal").text,
        ),
        "https://short.example/robots.txt": ROBOTS_ABSENT,
    })
    lines = []

    documents = list(make_source({"seed_url": seed}).fetch(session, {}, lines.append))

    assert documents == []
    message = " ".join(lines)
    assert landed in message
    assert "redirects to" in message
    assert "Use " + landed + " as the seed instead" in message


def test_a_redirect_that_stays_in_scope_passes_without_comment(
    isolated_core_cache, fake_session_factory,
):
    """http to https, a missing trailing slash, a canonical host: all normal."""
    seed = "https://example.org/start"
    session = fake_session_factory({
        seed: RedirectingResponse(
            "https://example.org/start/", status_code=200,
            headers={"Content-Type": "text/html"}, text=page("Start").text,
        ),
        "https://example.org/robots.txt": ROBOTS_ABSENT,
    })
    lines = []

    documents = list(make_source({"seed_url": seed}).fetch(session, {}, lines.append))

    assert [d.url for d in documents] == [seed]
    assert not any("redirects to" in line for line in lines)


def test_a_seed_redirecting_into_an_include_pattern_is_allowed(
    isolated_core_cache, fake_session_factory,
):
    """The operator said that address is in scope, so the redirect is fine."""
    seed = "https://short.example/kb"
    landed = "https://portal.example/kb/home"
    session = fake_session_factory({
        seed: RedirectingResponse(
            landed, status_code=200, headers={"Content-Type": "text/html"},
            text=page("Portal").text,
        ),
        "https://short.example/robots.txt": ROBOTS_ABSENT,
    })

    documents = list(make_source({
        "seed_url": seed, "include_patterns": (r"portal\.example/kb",),
    }).fetch(session, {}, quiet))

    assert [d.url for d in documents] == [seed]


def test_only_a_seed_is_checked_for_this(isolated_core_cache, fake_session_factory):
    """
    An ordinary page that redirects elsewhere is not a problem: the crawl
    already has somewhere to go.
    """
    seed = "https://example.org/start"
    inner = "https://example.org/inner"
    session = fake_session_factory({
        seed: page("Start", links=[inner]),
        inner: RedirectingResponse(
            "https://elsewhere.example/page", status_code=200,
            headers={"Content-Type": "text/html"},
            text=page("Inner", body=BODY.replace("Body", "Inner")).text,
        ),
        "https://example.org/robots.txt": ROBOTS_ABSENT,
    })
    lines = []

    documents = list(make_source({"seed_url": seed}).fetch(session, {}, lines.append))

    assert sorted(d.url for d in documents) == [inner, seed]
    assert not any("redirects to" in line for line in lines)


def test_a_session_that_does_not_report_where_it_landed_changes_nothing(
    isolated_core_cache, fake_session_factory,
):
    seed = "https://example.org/start"
    session = fake_session_factory({
        seed: page("Start"), "https://example.org/robots.txt": ROBOTS_ABSENT,
    })

    documents = list(make_source({"seed_url": seed}).fetch(session, {}, quiet))

    assert [d.url for d in documents] == [seed]


# ---------------------------------------------------------------------------
# Two sources reaching the same page
# ---------------------------------------------------------------------------

def document(url, title="Page", body=BODY):
    return Document(url=url, title=title, content=body,
                    source_type="web", content_type="page")


def test_a_page_two_sources_both_reached_is_indexed_once(fake_embed_chunks_core):
    """
    A site and a section of it, or a portal and a short link into it. This
    used to stop the build with a repeated identifier, which named neither
    the page nor the sources responsible.
    """
    documents = [
        document("https://example.org/toolkit"),
        document("https://example.org/toolkit"),
        document("https://example.org/other", body=BODY.replace("Body", "Other")),
    ]

    compendium = build_compendium(documents, name="test", embedder=fake_embed_chunks_core)

    assert sorted({p.u for p in compendium.parents}) == [
        "https://example.org/other", "https://example.org/toolkit",
    ]


def test_the_first_source_to_reach_a_page_keeps_it():
    first = document("https://example.org/page", title="From the first source")
    second = document("https://example.org/page", title="From the second source")

    parents, _, _ = chunk_documents([first, second], quiet)

    assert all("From the first source" in parent["t"] for parent in parents)


@pytest.mark.parametrize("repeat", [
    "https://example.org/page",
    "https://example.org/page/",       # a trailing slash is the same page
    "https://example.org/page#main",   # so is a fragment
])
def test_addresses_that_differ_only_in_form_count_as_one_page(repeat):
    """Identifiers are built from the normalised address, so these collide."""
    documents = [document("https://example.org/page"), document(repeat)]

    parents, _, _ = chunk_documents(documents, quiet)

    assert len({parent["id"] for parent in parents}) == len(parents)


def test_the_skipped_pages_are_reported_rather_than_dropped_quietly():
    documents = [document("https://example.org/page"), document("https://example.org/page")]
    lines = []

    chunk_documents(documents, lines.append)

    assert any("already indexed by an earlier source" in line for line in lines)
    assert any("Skipped 1 page(s)" in line for line in lines)


def test_nothing_is_reported_when_no_sources_overlap():
    documents = [
        document("https://example.org/a"),
        document("https://example.org/b", body=BODY.replace("Body", "Second")),
    ]
    lines = []

    chunk_documents(documents, lines.append)

    assert not any("already indexed" in line for line in lines)


def test_a_page_that_produced_nothing_does_not_block_a_later_source():
    """
    The first source found no indexable text there. The page is not spoken
    for, so a source that can read it still gets its chance.
    """
    documents = [
        document("https://example.org/page", body="tiny"),      # under the minimum size
        document("https://example.org/page"),
    ]

    parents, _, _ = chunk_documents(documents, quiet)

    assert len(parents) == 1
    assert parents[0]["u"] == "https://example.org/page"
