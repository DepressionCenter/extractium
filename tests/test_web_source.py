"""
Summary: Tests for the web source (extractium.sources.web): the fixture
crawl produces the same parents and children as the frozen reference
script apart from the added id and metadata fields; site handlers are
selected by URL with generic last; the omitted exclude lists complete to
exactly what the reference excluded; robots.txt and max_pages are
honored; the User-Agent is sent; and progress goes to the callback, not
to standard output. Uses FakeSession and the synthetic fixtures in
tests/fixtures/ -- no real network.

This file is part of Extractium™
tests/test_web_source.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-04
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

import importlib
import pathlib
import tomllib

import pytest

from extractium.core import chunk, fetch, registry
from extractium.core.models import Document, Source
from extractium.sources import generic, github, tdx, web
from tests import document_fixtures as document_files
from tests.conftest import FakeResponse

PYPROJECT_PATH = pathlib.Path(__file__).parent.parent / "pyproject.toml"

# The built-in handlers in the order the registry lists them.
BUILT_IN_HANDLERS = (github.GitHubHandler(), tdx.TdxHandler(), generic.GenericHandler())

# A robots.txt that allows everything is the same as no robots.txt, and
# a portal answering 404 is the common case.
ROBOTS_ABSENT = FakeResponse(status_code=404)


def html_response(text):
    return FakeResponse(status_code=200, headers={"Content-Type": "text/html"}, text=text)


def text_response(text):
    return FakeResponse(status_code=200, headers={"Content-Type": "text/plain"}, text=text)


def robots_response(text):
    return FakeResponse(status_code=200, headers={"Content-Type": "text/plain"}, text=text)


def quiet(line):
    """A progress sink for tests that do not inspect progress."""


def make_source(seed, handlers=BUILT_IN_HANDLERS, settings=None, **options):
    """A WebSource over the validated-options shape the loader produces, with test-friendly settings."""
    validated = {
        "seed_url": seed,
        "include_patterns": (),
        "crawl_exclude_patterns": None,
        "index_exclude_patterns": None,
        "site_handlers": None,
        **options,
    }
    settings = settings or web.CrawlSettings(max_pages=10, delay_seconds=0)
    return web.WebSource(validated, handlers, settings)


def crawl(source, session, progress=quiet, cache=None):
    return list(source.fetch(session, {} if cache is None else cache, progress))


def chunk_all(documents):
    """Accumulates every document's chunks into one list pair, offsetting pids as the reference crawl does."""
    all_parents, all_children = [], []
    for document in documents:
        parents, children = chunk.chunk_document(document)
        offset = len(all_parents)
        for child in children:
            child["pid"] += offset
        all_parents.extend(parents)
        all_children.extend(children)
    return all_parents, all_children


def pick(record, keys):
    return {key: record[key] for key in keys}


REFERENCE_FIELDS = ("t", "x", "u", "host", "weight")


# ---------------------------------------------------------------------------
# Fixture crawl versus the reference script
# ---------------------------------------------------------------------------

def test_two_page_crawl_matches_reference_apart_from_the_added_fields(
    reference, isolated_cache, isolated_core_cache, fake_session_factory, patch_crawl_session, fixtures_dir
):
    page_a = (fixtures_dir / "page_boilerplate_a.html").read_text(encoding="utf-8")
    page_b = (fixtures_dir / "page_boilerplate_b.html").read_text(encoding="utf-8")
    seed = "https://example.org/team"
    page_b_url = "https://example.org/project"
    responses = {
        seed: html_response(page_a),
        page_b_url: html_response(page_b),
        "https://example.org/robots.txt": ROBOTS_ABSENT,
    }

    patch_crawl_session(fake_session_factory(responses))
    ref_parents, ref_children, site_name = reference.crawl(
        seed, max_pages=10, delay=0, include_res=[], crawl_exclude_res=[], index_exclude_res=[]
    )

    session = fake_session_factory(responses)
    documents = crawl(make_source(seed), session)
    parents, children = chunk_all(documents)

    assert documents[0].title == site_name == "Team Directory"
    assert [pick(p, REFERENCE_FIELDS) for p in parents] == [pick(p, REFERENCE_FIELDS) for p in ref_parents]
    assert [pick(c, REFERENCE_FIELDS + ("pid",)) for c in children] == [
        pick(c, REFERENCE_FIELDS + ("pid",)) for c in ref_children
    ]
    # The additions the reference never had.
    assert all(len(p["id"]) == 16 for p in parents)
    assert all(p["source_type"] == "web" and p["content_type"] == "page" for p in parents)


def test_mixed_host_crawl_matches_reference_through_every_handler(
    reference, isolated_cache, isolated_core_cache, fake_session_factory, patch_crawl_session, fixtures_dir
):
    """
    One crawl that crosses from a portal article to a wiki page, a raw
    Markdown file, a repository root (link hop only), and a category
    listing (followed, not indexed): the same graph the original script
    walked, now routed through three handlers.
    """
    portal = "https://teamdynamix.example.edu/TDClient/210/ExampleOrg"
    seed = f"{portal}/KB/ArticleDet?ID=1"
    category = f"{portal}/KB/Category/5"
    wiki = "https://github.com/example-org/example-repo/wiki/Setup-Guide"
    blob = "https://github.com/example-org/example-repo/blob/main/docs/setup.md"
    raw = "https://raw.githubusercontent.com/example-org/example-repo/main/docs/setup.md"
    root = "https://github.com/example-org/example-repo"
    article = (
        "<html><head><title>Article - Remote Study Technology</title></head><body>"
        '<nav><ol class="breadcrumb"><li><a href="/TDClient/210/ExampleOrg/KB/">Knowledge Base</a></li>'
        '<li>Remote Study Technology</li></ol></nav>'
        '<div id="divMainContent">'
        "<h2>Overview</h2><p>Synthetic overview paragraph long enough to clear the sixty character minimum.</p>"
        "<h2>Links</h2><p>Synthetic links paragraph, also long enough to clear the sixty character minimum. "
        f'<a href="{wiki}">wiki</a> <a href="{blob}">setup</a> <a href="{root}">repo</a> '
        f'<a href="{category}">category</a></p>'
        "</div></body></html>"
    )
    listing = (
        "<html><head><title>Category</title></head><body>"
        f'<div id="divMainContent"><p>Listing text long enough to clear the minimum chunk size threshold.</p>'
        f'<a href="{seed}">article</a></div></body></html>'
    )
    responses = {
        seed: html_response(article),
        category: html_response(listing),
        wiki: html_response((fixtures_dir / "github_wiki.html").read_text(encoding="utf-8")),
        raw: text_response((fixtures_dir / "raw_markdown_file.md").read_text(encoding="utf-8")),
        root: html_response((fixtures_dir / "github_repo_root.html").read_text(encoding="utf-8")),
        "https://teamdynamix.example.edu/robots.txt": ROBOTS_ABSENT,
        "https://github.com/robots.txt": ROBOTS_ABSENT,
        "https://raw.githubusercontent.com/robots.txt": ROBOTS_ABSENT,
    }
    include = [r"/TDClient/210/ExampleOrg/", r"github\.com/example-org/"]

    patch_crawl_session(fake_session_factory(responses))
    ref_parents, ref_children, _ = reference.crawl(
        seed, max_pages=10, delay=0,
        include_res=reference.compile_patterns(include),
        crawl_exclude_res=reference.compile_patterns(reference.CRAWL_EXCLUDE_PATTERNS),
        index_exclude_res=reference.compile_patterns(reference.INDEX_EXCLUDE_PATTERNS),
    )

    session = fake_session_factory(responses)
    documents = crawl(make_source(seed, include_patterns=tuple(include)), session)
    parents, children = chunk_all(documents)

    assert [pick(p, REFERENCE_FIELDS) for p in parents] == [pick(p, REFERENCE_FIELDS) for p in ref_parents]
    assert [pick(c, REFERENCE_FIELDS + ("pid",)) for c in children] == [
        pick(c, REFERENCE_FIELDS + ("pid",)) for c in ref_children
    ]
    assert [d.url for d in documents] == [seed, wiki, blob]   # root and category yield nothing
    by_url = {d.url: d for d in documents}
    assert (by_url[seed].source_type, by_url[seed].content_type) == ("kb", "article")
    assert by_url[seed].categories == ("Knowledge Base",)
    assert (by_url[wiki].source_type, by_url[wiki].content_type) == ("github", "wiki")
    assert (by_url[blob].source_type, by_url[blob].content_type) == ("github", "text")
    assert by_url[blob].categories == ("example-org", "example-repo", "docs")
    # The blob was fetched from the raw host, never from the blob page.
    requested = [c["url"] for c in session.calls]
    assert raw in requested and blob not in requested


# ---------------------------------------------------------------------------
# Crawl loop behavior carried over from the reference
# ---------------------------------------------------------------------------

def test_seed_is_visited_even_if_it_matches_a_crawl_exclude_pattern(isolated_core_cache, fake_session_factory):
    """
    The exclude lists govern which discovered links are followed; the seed
    is queued unconditionally, the behavior the reference script pinned.
    """
    seed = "https://example.org/Login.aspx"
    html = (
        "<html><head><title>Login</title></head><body><main>"
        "<p>No headings here, just enough placeholder text to clear the sixty character minimum.</p>"
        "</main></body></html>"
    )
    session = fake_session_factory({seed: html_response(html), "https://example.org/robots.txt": ROBOTS_ABSENT})

    documents = crawl(
        make_source(seed, crawl_exclude_patterns=(r"/Login\.aspx",), index_exclude_patterns=()), session
    )

    assert [d.url for d in documents] == [seed]


def test_a_page_whose_text_runs_past_the_ceiling_is_indexed_as_an_outline(
    isolated_core_cache, fake_session_factory,
):
    """
    A site that publishes everything on one page is one address with
    hundreds of thousands of characters, and chunking it whole would
    make thousands of sections for that one address. Its outline is
    indexed instead, and the log says so.
    """
    seed = "https://example.org/everything"
    html = (
        "<html><head><title>Everything</title></head><body><main>"
        "<h1>Everything</h1><p>All the resources, on one page.</p><h2>Guides</h2>"
        + "<p>guide to peer support groups</p>" * 12_000
        + "</main></body></html>"
    )
    lines = []
    session = fake_session_factory({seed: html_response(html), "https://example.org/robots.txt": ROBOTS_ABSENT})

    documents = crawl(make_source(seed), session, progress=lines.append)

    assert len(documents) == 1
    record = documents[0].content
    assert isinstance(record, str)
    assert record.startswith("Everything\n\nAll the resources, on one page.")
    assert "Headings: Everything; Guides" in record
    assert "guide, peer, support, groups" in record
    assert "only this outline was indexed" in record
    assert any("indexed as an outline" in line for line in lines)


def test_max_pages_ceiling_stops_the_crawl(isolated_core_cache, fake_session_factory):
    seed = "https://example.org/a"
    other = "https://example.org/b"
    html_a = (
        '<html><head><title>Page A</title></head><body><nav><a href="/b">next</a></nav>'
        "<main><p>Placeholder content long enough to clear the sixty character minimum threshold.</p></main>"
        "</body></html>"
    )
    session = fake_session_factory({
        seed: html_response(html_a), other: html_response(html_a), "https://example.org/robots.txt": ROBOTS_ABSENT,
    })

    documents = crawl(make_source(seed, settings=web.CrawlSettings(max_pages=1, delay_seconds=0)), session)

    assert [d.url for d in documents] == [seed]
    assert [c["url"] for c in session.calls if not c["url"].endswith("robots.txt")] == [seed]


def test_index_excluded_page_is_followed_but_not_yielded(isolated_core_cache, fake_session_factory):
    seed = "https://example.org/Category/1"
    article = "https://example.org/article"
    listing = (
        '<html><head><title>Listing</title></head><body><main><a href="/article">a</a>'
        "<p>Listing text long enough to clear the sixty character minimum chunk threshold.</p></main></body></html>"
    )
    page = (
        "<html><head><title>Article</title></head><body><main>"
        "<p>Article text long enough to clear the sixty character minimum chunk threshold.</p></main></body></html>"
    )
    session = fake_session_factory({
        seed: html_response(listing), article: html_response(page), "https://example.org/robots.txt": ROBOTS_ABSENT,
    })

    documents = crawl(make_source(seed), session)   # /Category/ is in the tdx index-only defaults

    assert [d.url for d in documents] == [article]


def test_pages_with_no_content_node_yield_nothing_but_are_still_followed(isolated_core_cache, fake_session_factory):
    seed = "https://example.org/hub"
    leaf = "https://example.org/leaf"
    hub = '<html><head><title>Hub</title></head><body><div><a href="/leaf">leaf</a></div></body></html>'
    page = (
        "<html><head><title>Leaf</title></head><body><main>"
        "<p>Leaf text long enough to clear the sixty character minimum chunk threshold.</p></main></body></html>"
    )
    session = fake_session_factory({
        seed: html_response(hub), leaf: html_response(page), "https://example.org/robots.txt": ROBOTS_ABSENT,
    })

    assert [d.url for d in crawl(make_source(seed), session)] == [leaf]


def test_documents_are_valid_document_records(isolated_core_cache, fake_session_factory, fixtures_dir):
    seed = "https://example.org/team"
    session = fake_session_factory({
        seed: html_response((fixtures_dir / "page_boilerplate_a.html").read_text(encoding="utf-8")),
        "https://example.org/project": FakeResponse(status_code=404),
        "https://example.org/robots.txt": ROBOTS_ABSENT,
    })
    documents = crawl(make_source(seed), session)
    assert len(documents) == 1
    assert isinstance(documents[0], Document)
    assert documents[0].local is False


# ---------------------------------------------------------------------------
# Etiquette: robots.txt, User-Agent, pacing
# ---------------------------------------------------------------------------

def _two_page_site(fake_session_factory, robots):
    seed = "https://example.org/"
    private = "https://example.org/private/page"
    home = (
        '<html><head><title>Home</title></head><body><main><a href="/private/page">p</a>'
        "<p>Home text long enough to clear the sixty character minimum chunk threshold.</p></main></body></html>"
    )
    page = (
        "<html><head><title>Private</title></head><body><main>"
        "<p>Private text long enough to clear the sixty character minimum chunk threshold.</p></main></body></html>"
    )
    session = fake_session_factory({
        "https://example.org": html_response(home),
        private: html_response(page),
        "https://example.org/robots.txt": robots,
    })
    return seed, private, session


def test_robots_disallow_is_honored(isolated_core_cache, fake_session_factory):
    seed, private, session = _two_page_site(
        fake_session_factory, robots_response("User-agent: *\nDisallow: /private/\n")
    )
    lines = []

    documents = crawl(make_source(seed), session, progress=lines.append)

    assert [d.url for d in documents] == ["https://example.org"]
    assert private not in [c["url"] for c in session.calls]
    assert any("robots.txt" in line and private in line for line in lines)


def test_robots_rules_for_this_crawler_by_name_are_honored(isolated_core_cache, fake_session_factory):
    seed, private, session = _two_page_site(
        fake_session_factory,
        robots_response("User-agent: extractium\nDisallow: /\n\nUser-agent: *\nAllow: /\n"),
    )
    documents = crawl(make_source(seed), session)
    assert documents == []
    assert [c["url"] for c in session.calls] == ["https://example.org/robots.txt"]


def test_robots_is_fetched_once_per_origin(isolated_core_cache, fake_session_factory):
    seed, private, session = _two_page_site(fake_session_factory, ROBOTS_ABSENT)
    crawl(make_source(seed), session)
    assert [c["url"] for c in session.calls].count("https://example.org/robots.txt") == 1


def test_robots_can_be_switched_off(isolated_core_cache, fake_session_factory):
    seed, private, session = _two_page_site(
        fake_session_factory, robots_response("User-agent: *\nDisallow: /\n")
    )
    settings = web.CrawlSettings(max_pages=10, delay_seconds=0, respect_robots_txt=False)

    documents = crawl(make_source(seed, settings=settings), session)

    assert [d.url for d in documents] == ["https://example.org", private]
    assert "https://example.org/robots.txt" not in [c["url"] for c in session.calls]


def test_unreadable_robots_fails_closed(isolated_core_cache, fake_session_factory):
    seed, private, session = _two_page_site(fake_session_factory, FakeResponse(status_code=503))
    lines = []

    documents = crawl(make_source(seed), session, progress=lines.append)

    assert documents == []
    assert any("robots.txt unavailable" in line for line in lines)


def test_user_agent_is_sent_on_every_request(isolated_core_cache, fake_session_factory):
    seed, private, session = _two_page_site(fake_session_factory, ROBOTS_ABSENT)
    settings = web.CrawlSettings(max_pages=10, delay_seconds=0, user_agent="ExampleBot/1.0 (+https://example.edu)")

    crawl(make_source(seed, settings=settings), session)

    assert session.calls  # robots.txt and both pages
    assert all(c["headers"]["User-Agent"] == "ExampleBot/1.0 (+https://example.edu)" for c in session.calls)


def test_default_settings_use_the_truthful_user_agent_and_honor_robots():
    settings = web.CrawlSettings()
    assert settings.user_agent == fetch.DEFAULT_USER_AGENT
    assert settings.respect_robots_txt is True
    assert settings.max_pages == 10000 and settings.delay_seconds == 0.5


def test_the_crawl_itself_never_sleeps_because_the_session_paces_per_host(
    isolated_core_cache, fake_session_factory, monkeypatch
):
    """
    The pause between requests is kept per host by the session a build
    makes (extractium.core.transport), so two sources reading one host
    together stay within the delay. A crawl handed a bare session is
    therefore not paced, and must not sleep on its own either.
    """
    import time
    seed, private, session = _two_page_site(fake_session_factory, ROBOTS_ABSENT)
    monkeypatch.setattr(time, "sleep", lambda seconds: pytest.fail(f"slept {seconds}"))

    documents = crawl(make_source(seed, settings=web.CrawlSettings(max_pages=10, delay_seconds=0.25)), session)

    assert len(documents) == 2


# ---------------------------------------------------------------------------
# Several fetches in flight
# ---------------------------------------------------------------------------

def _chain_site(fake_session_factory, count=6):
    """A seed whose page links to every other page, each linking onward, so order matters."""
    urls = [f"https://example.org/page-{n}" for n in range(count)]

    def html(n):
        links = "".join(f'<a href="/page-{m}">{m}</a>' for m in range(count) if m != n)
        return (
            f"<html><head><title>Page {n}</title></head><body><nav>{links}</nav>"
            f"<main><p>Page {n} body text long enough to clear the sixty character minimum threshold.</p>"
            f'<a href="/page-{(n + 1) % count}">next</a></main></body></html>'
        )

    responses = {url: html_response(html(n)) for n, url in enumerate(urls)}
    responses["https://example.org/robots.txt"] = ROBOTS_ABSENT
    return urls[0], fake_session_factory(responses)


def test_pages_in_flight_change_nothing_but_the_wall_clock(isolated_core_cache, fake_session_factory):
    """
    With several fetches in flight the crawl still visits, follows, and
    yields pages in the order a one-at-a-time crawl would, and its log
    reads the same, so the setting is safe to leave on.
    """
    seed, sequential = _chain_site(fake_session_factory)
    one_at_a_time = []
    expected = crawl(make_source(seed, settings=web.CrawlSettings(max_pages=10, delay_seconds=0)),
                     sequential, progress=one_at_a_time.append)

    seed, session = _chain_site(fake_session_factory)
    in_flight = []
    documents = crawl(
        make_source(seed, settings=web.CrawlSettings(max_pages=10, delay_seconds=0, parallel_pages=3)),
        session, progress=in_flight.append,
    )

    assert [d.url for d in documents] == [d.url for d in expected]
    assert [d.title for d in documents] == [d.title for d in expected]
    assert in_flight == one_at_a_time
    requested = [c["url"] for c in session.calls if not c["url"].endswith("robots.txt")]
    assert len(requested) == len(set(requested)) == 6


def test_the_page_ceiling_holds_with_pages_in_flight(isolated_core_cache, fake_session_factory):
    seed, session = _chain_site(fake_session_factory)

    documents = crawl(
        make_source(seed, settings=web.CrawlSettings(max_pages=2, delay_seconds=0, parallel_pages=4)),
        session,
    )

    assert len(documents) == 2
    assert len([c for c in session.calls if not c["url"].endswith("robots.txt")]) == 2


def test_a_page_s_own_progress_lines_stay_under_its_own_line(isolated_core_cache, fake_session_factory):
    """
    A fetch in flight reports through a list of its own, replayed when the
    page is processed, so a cached page's line never lands under another
    page's heading in the log.
    """
    seed, session = _chain_site(fake_session_factory)
    cache = {}
    crawl(make_source(seed, settings=web.CrawlSettings(max_pages=10, delay_seconds=0)), session, cache=cache)

    lines = []
    seed, session = _chain_site(fake_session_factory)
    for url in list(cache):
        session.responses[url] = FakeResponse(status_code=304)
    crawl(make_source(seed, settings=web.CrawlSettings(max_pages=10, delay_seconds=0, parallel_pages=3)),
          session, progress=lines.append, cache=cache)

    for position, line in enumerate(lines):
        if "(cached, not modified)" in line:
            assert lines[position - 1].startswith("[")


def test_a_robots_refusal_is_reported_in_order_with_pages_in_flight(isolated_core_cache, fake_session_factory):
    seed, private, session = _two_page_site(
        fake_session_factory, robots_response("User-agent: *\nDisallow: /private/\n")
    )
    lines = []

    documents = crawl(
        make_source(seed, settings=web.CrawlSettings(max_pages=10, delay_seconds=0, parallel_pages=3)),
        session, progress=lines.append,
    )

    assert [d.url for d in documents] == ["https://example.org"]
    skip = next(i for i, line in enumerate(lines) if "disallowed by robots.txt" in line)
    assert lines[skip - 1] == f"[   2] {private}"


def test_crawl_settings_default_to_one_fetch_at_a_time():
    assert web.CrawlSettings().parallel_pages == 1


# ---------------------------------------------------------------------------
# Progress and silence
# ---------------------------------------------------------------------------

def test_progress_goes_to_the_callback_and_nothing_is_printed(isolated_core_cache, fake_session_factory, capsys):
    seed, private, session = _two_page_site(fake_session_factory, ROBOTS_ABSENT)
    lines = []

    crawl(make_source(seed), session, progress=lines.append)

    assert any(line.startswith("[   1] ") for line in lines)
    assert any("Crawled 2 page(s)" in line for line in lines)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_failed_fetches_are_reported_through_progress(isolated_core_cache, fake_session_factory):
    seed = "https://example.org/missing"
    session = fake_session_factory({
        seed: FakeResponse(status_code=500), "https://example.org/robots.txt": ROBOTS_ABSENT,
    })
    lines = []

    assert crawl(make_source(seed), session, progress=lines.append) == []
    assert any(line.startswith("  SKIP ") and seed in line for line in lines)


# ---------------------------------------------------------------------------
# Site handler selection
# ---------------------------------------------------------------------------

def test_the_three_handlers_are_selected_by_url():
    source = make_source("https://example.org/")
    assert source.handler_for("https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1").name == "tdx"
    assert source.handler_for("https://github.com/example-org/example-repo/wiki/Home").name == "github"
    assert source.handler_for("https://example.org/about").name == "generic"


def test_generic_handler_is_always_present_and_last():
    assert [h.name for h in make_source("https://example.org/", handlers=()).handlers] == ["generic"]
    reordered = make_source("https://example.org/", handlers=(generic.GenericHandler(), tdx.TdxHandler()))
    assert [h.name for h in reordered.handlers] == ["tdx", "generic"]


def test_disabling_a_handler_routes_its_pages_to_generic():
    source = make_source("https://example.org/", handlers=(generic.GenericHandler(),))
    url = "https://teamdynamix.umich.edu/TDClient/210/Test/KB/ArticleDet?ID=1"
    assert source.handler_for(url).name == "generic"


def _built_in_registry():
    reg = registry.Registry()
    for handler_class in (generic.GenericHandler, tdx.TdxHandler, github.GitHubHandler):
        reg.register_site_handler(handler_class, registry.Tier.BUILTIN)
    return reg


def test_resolve_site_handlers_none_means_every_registered_handler():
    handlers = web.resolve_site_handlers(_built_in_registry(), None)
    assert [h.name for h in handlers] == ["github", "tdx", "generic"]


def test_resolve_site_handlers_empty_means_generic_only():
    assert [h.name for h in web.resolve_site_handlers(_built_in_registry(), ())] == ["generic"]


def test_resolve_site_handlers_keeps_the_requested_order_with_generic_last():
    handlers = web.resolve_site_handlers(_built_in_registry(), ("generic", "tdx"))
    assert [h.name for h in handlers] == ["tdx", "generic"]


def test_resolve_site_handlers_rejects_an_unknown_name():
    with pytest.raises(registry.RegistryError, match="no site handler named 'nope'"):
        web.resolve_site_handlers(_built_in_registry(), ("nope",))


# ---------------------------------------------------------------------------
# Identity when a site refuses the truthful User-Agent
# ---------------------------------------------------------------------------

def test_a_crawl_that_honors_robots_never_retries_as_a_browser():
    assert web.CrawlSettings().blocked_retry_user_agent is None
    assert web.CrawlSettings(respect_robots_txt=True).blocked_retry_user_agent is None


def test_turning_robots_off_allows_one_browser_retry_for_a_refused_page():
    settings = web.CrawlSettings(respect_robots_txt=False)

    assert settings.blocked_retry_user_agent == fetch.BROWSER_USER_AGENT
    assert settings.blocked_retry_user_agent.startswith("Mozilla/5.0")


def test_a_refused_page_is_retried_as_a_browser_only_when_robots_is_off(
    isolated_core_cache, fake_session_factory
):
    """
    One site in the Depression Center's own scope allows every crawler in
    its robots.txt and still answers 403 to anything that does not look
    like a browser. Working around that is an opt-in, not a default.
    """
    url = "https://example.org/blocked"
    page = html_response("<html><head><title>Blocked Page</title></head>"
                         "<body><main><p>Content behind the filter.</p></main></body></html>")

    refused_only = fake_session_factory({url: [FakeResponse(status_code=403)]})
    assert fetch.fetch(refused_only, url, {}, progress=quiet) is None
    assert len(refused_only.calls) == 1

    retried = fake_session_factory({url: [FakeResponse(status_code=403), page]})
    soup = fetch.fetch(retried, url, {}, progress=quiet,
                       fallback_user_agent=fetch.BROWSER_USER_AGENT)

    assert soup is not None
    assert len(retried.calls) == 2
    assert retried.calls[0]["headers"]["User-Agent"] == fetch.DEFAULT_USER_AGENT
    assert retried.calls[1]["headers"]["User-Agent"] == fetch.BROWSER_USER_AGENT


def test_a_page_that_is_merely_missing_is_not_retried_as_a_browser(
    isolated_core_cache, fake_session_factory
):
    url = "https://example.org/gone"
    session = fake_session_factory({url: [FakeResponse(status_code=404)]})

    assert fetch.fetch(session, url, {}, progress=quiet,
                       fallback_user_agent=fetch.BROWSER_USER_AGENT) is None
    assert len(session.calls) == 1


def test_the_browser_retry_is_reported_so_a_log_shows_which_identity_was_used(
    isolated_core_cache, fake_session_factory
):
    url = "https://example.org/blocked"
    page = html_response("<html><head><title>Blocked</title></head><body><main>"
                         "<p>Content.</p></main></body></html>")
    session = fake_session_factory({url: [FakeResponse(status_code=403), page]})
    lines = []

    fetch.fetch(session, url, {}, progress=lines.append,
                fallback_user_agent=fetch.BROWSER_USER_AGENT)

    assert any("403" in line and "retrying once as a browser" in line for line in lines)


def test_the_crawl_loop_passes_the_retry_identity_down_to_each_request(
    isolated_core_cache, fake_session_factory
):
    seed = "https://example.org/blocked"
    page = html_response("<html><head><title>Blocked</title></head><body><main>"
                         "<p>Content long enough to clear the minimum chunk size threshold "
                         "used by the chunker in this test.</p></main></body></html>")
    session = fake_session_factory({
        seed: [FakeResponse(status_code=403), page],
        "https://example.org/robots.txt": ROBOTS_ABSENT,
    })
    source = web.WebSource({"seed_url": seed},
                           settings=web.CrawlSettings(delay_seconds=0, respect_robots_txt=False))

    documents = list(source.fetch(session, {}, quiet))

    assert [d.title for d in documents] == ["Blocked"]
    assert session.calls[-1]["headers"]["User-Agent"] == fetch.BROWSER_USER_AGENT


# ---------------------------------------------------------------------------
# configure(): adopting the registry and the global crawl settings
# ---------------------------------------------------------------------------

def test_configure_resolves_the_handlers_the_entry_asked_for():
    source = web.WebSource({"seed_url": "https://example.org/", "site_handlers": ("tdx",)})

    source.configure(_built_in_registry(), web.CrawlSettings())

    assert [h.name for h in source.handlers] == ["tdx", "generic"]


def test_configure_with_no_site_handlers_option_enables_every_installed_handler():
    source = web.WebSource({"seed_url": "https://example.org/"})

    source.configure(_built_in_registry(), web.CrawlSettings())

    assert [h.name for h in source.handlers] == ["github", "tdx", "generic"]


def test_configure_adopts_the_global_crawl_settings():
    settings = web.CrawlSettings(max_pages=5, delay_seconds=0, user_agent="UA/1.0",
                                 respect_robots_txt=False)
    source = web.WebSource({"seed_url": "https://example.org/"})

    source.configure(_built_in_registry(), settings)

    assert source.settings == settings


def test_configure_recomputes_the_exclude_defaults_for_the_handlers_it_adopted():
    source = web.WebSource({"seed_url": "https://example.org/", "site_handlers": ()})

    source.configure(_built_in_registry(), web.CrawlSettings())

    assert r"/issues?[/?]" not in source.crawl_exclude_patterns      # github is off
    assert r"\.pdf$" in source.crawl_exclude_patterns                # asset patterns stay


def test_configure_leaves_an_explicit_exclude_list_as_written():
    source = web.WebSource({"seed_url": "https://example.org/", "crawl_exclude_patterns": (r"/x",)})

    source.configure(_built_in_registry(), web.CrawlSettings())

    assert source.crawl_exclude_patterns == (r"/x",)


def test_extra_exclude_patterns_are_added_to_the_defaults():
    """
    One site's own navigation can be kept out of a crawl without
    rewriting the built-in list, which an explicit list would replace.
    """
    source = web.WebSource({
        "seed_url": "https://example.org/",
        "extra_crawl_exclude_patterns": (r"/our-members\?",),
        "extra_index_exclude_patterns": (r"/directory/",),
    })

    source.configure(_built_in_registry(), web.CrawlSettings())

    assert r"\.pdf$" in source.crawl_exclude_patterns
    assert source.crawl_exclude_patterns[-1] == r"/our-members\?"
    assert r"\.pdf$" in source.index_exclude_patterns
    assert source.index_exclude_patterns[-1] == r"/directory/"


def test_extra_exclude_patterns_are_added_to_an_explicit_list_too():
    source = web.WebSource({
        "seed_url": "https://example.org/",
        "crawl_exclude_patterns": (r"/x",),
        "extra_crawl_exclude_patterns": (r"/y", r"/x"),
    })

    source.configure(_built_in_registry(), web.CrawlSettings())

    assert source.crawl_exclude_patterns == (r"/x", r"/y")


def test_configure_rejects_a_site_handler_the_entry_names_but_nothing_installs():
    source = web.WebSource({"seed_url": "https://example.org/", "site_handlers": ("nope",)})

    with pytest.raises(registry.RegistryError, match="no site handler named 'nope'"):
        source.configure(_built_in_registry(), web.CrawlSettings())


# ---------------------------------------------------------------------------
# Default exclude patterns
# ---------------------------------------------------------------------------

# URLs the frozen script's exclude lists were written to keep out, in the
# shapes the real sites serve them in. The script's own patterns miss most
# of these, so this list is the intent rather than a record of behaviour.
NON_CONTENT_URLS = (
    "https://github.com/DepressionCenter/Repo/issues",
    "https://github.com/DepressionCenter/Repo/issues/12",
    "https://github.com/DepressionCenter/Repo/pulls",
    "https://github.com/DepressionCenter/Repo/pull/12",
    "https://github.com/DepressionCenter/Repo/forks",
    "https://github.com/DepressionCenter/Repo/branches",
    "https://github.com/DepressionCenter/Repo/security",
    "https://github.com/DepressionCenter/Repo/activity",
    "https://github.com/DepressionCenter/Repo/milestones",
    "https://github.com/DepressionCenter/Repo/labels",
    "https://github.com/DepressionCenter/Repo/commits/main",
    "https://github.com/DepressionCenter/Repo/stargazers",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Login.aspx",
    "https://teamdynamix.umich.edu/TDClient/210/Org/KB/PrintArticle?ID=10904",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=0&TagID=8464&Filter=answered",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?Filter=unanswered&Page=2",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=200076&TagID=10475",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=200076&TagID=0",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=0&TagID=8464",
    "https://teamdynamix.umich.edu/TDClient/210/Org/People/Details?ID=0b0d00e0-d00a-ed00-ade0-c00000000eb0&popup=1",
    "https://example.org/Search",
    "https://example.org/Login",
    "https://example.org/cdn-cgi/l/email-protection",
    "https://example.org/cgi-bin/counter.pl?page=home",
    "https://example.org/scripts/",
    "https://example.org/api/v2/pages",
    "https://example.org/docs/API?format=json",
    "https://example.org/become-member/our-members?f[0]=research:329",
    "https://example.org/our-members?f[0]=population:201&f[1]=methods:252",
    "https://example.org/our-members?appointment=All&methods=All&search_api_fulltext=&sort_by=name",
)

# Pages that must survive every exclude list: documentation on a code
# host, and an ordinary site's own pages whose names happen to match a
# code host's furniture.
CONTENT_URLS = (
    "https://github.com/DepressionCenter/Repo",
    "https://github.com/DepressionCenter/Repo/blob/main/README.md",
    "https://github.com/DepressionCenter/Repo/wiki",
    "https://github.com/DepressionCenter/Repo/releases",
    "https://example.org/project",
    "https://example.org/community",
    "https://example.org/security",
    "https://teamdynamix.umich.edu/TDClient/210/Org/KB/Article/10904/How-to-do-a-thing",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions/Details/100010",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?Page=2",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=0&TagID=0",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions/Categories",
    "https://teamdynamix.umich.edu/TDClient/210/Org/KB?CategoryID=1015",
    "https://teamdynamix.umich.edu/TDClient/210/Org/KB/TagID/8245",
    "https://example.org/reports?Filter=recent",
    "https://example.org/People/",
    "https://example.org/api-reference/",
    "https://example.org/docs/scripting-guide",
    "https://example.org/apiary-notes",
    "https://example.org/become-member/our-members",
    "https://example.org/become-member/our-members?page=1",
)


def _excludes(kind):
    return fetch.compile_patterns(web.default_exclude_patterns(BUILT_IN_HANDLERS, kind))


@pytest.mark.parametrize("url", NON_CONTENT_URLS)
def test_default_crawl_excludes_keep_out_the_pages_they_were_written_for(url):
    """
    The frozen script writes these patterns as `/issues?[/?]` and
    `/TagID=`, which match only a sub-path or a path-style parameter. The
    real sites serve a bare `/issues` and a query-string `&TagID=`, so the
    original lets nearly every one of these through. Measured against the
    Depression Center organization, that sent 150 pages of a 500-page
    crawl to listings that produced no indexed content at all.
    """
    assert any(p.search(url) for p in _excludes("crawl")), url


@pytest.mark.parametrize("url", CONTENT_URLS)
def test_default_crawl_excludes_leave_real_pages_alone(url):
    """
    Every enabled handler's patterns apply to every URL in a crawl, so a
    code host's exclusions must not reach an ordinary site's own pages.
    """
    assert not any(p.search(url) for p in _excludes("crawl")), url


def test_default_exclude_patterns_have_no_duplicates():
    for kind in ("crawl", "index"):
        patterns = web.default_exclude_patterns(BUILT_IN_HANDLERS, kind)
        assert len(patterns) == len(set(patterns))


def test_default_excludes_still_cover_everything_the_reference_excluded(reference):
    """
    The pattern strings deliberately differ from the frozen script's, so
    the comparison is behavioural: no URL the original kept out may now
    get in.
    """
    ours = _excludes("crawl")
    theirs = fetch.compile_patterns(reference.CRAWL_EXCLUDE_PATTERNS)
    probes = NON_CONTENT_URLS + (
        "https://github.com/Org/Repo/pulse",
        "https://github.com/Org/Repo/network/members",
        "https://github.com/Org/Repo/blame/main/x.md",
        "https://teamdynamix.umich.edu/TDClient/210/Org/Login.aspx",
        "https://example.org/page?print=1",
    )
    for url in probes:
        if any(p.search(url) for p in theirs):
            assert any(p.search(url) for p in ours), url


@pytest.mark.parametrize("url", [
    "https://teamdynamix.umich.edu/TDClient/210/Org/KB/Category/1015/All-Things-Data",
    "https://teamdynamix.umich.edu/TDClient/210/Org/KB?CategoryID=1015",
    "https://teamdynamix.umich.edu/TDClient/210/Org/KB/CategoryID/1015",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=0&TagID=0",
    "https://teamdynamix.umich.edu/TDClient/210/Org/KB/TagID/8245",
    "https://github.com/DepressionCenter/Repo/tree/main/docs",
])
def test_listing_pages_are_followed_for_links_but_not_indexed(url):
    """
    A category, tag, or directory listing links to real content and holds
    none of its own, so it belongs on the index list and not the crawl
    list. A TeamDynamix portal publishes no sitemap and no full article
    index, so these listings are the only route to most of what it holds:
    dropping them from the crawl would shrink the knowledge base to
    whatever the home page happens to link to. The portal's flat question
    listing is the one exception the other way: it reaches every question
    itself, so its narrowed views are the ones dropped.
    """
    assert not any(p.search(url) for p in _excludes("crawl")), url
    assert any(p.search(url) for p in _excludes("index")), url


def test_an_unfiltered_portal_listing_is_still_crawled():
    """
    The portal writes "no tag filter" as TagID=0, so a rule that skipped
    the crawl on sight of a tag parameter would skip the unfiltered
    listing too, which is the widest discovery page the portal has.
    """
    url = "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=0&TagID=0"

    assert not any(p.search(url) for p in _excludes("crawl"))


@pytest.mark.parametrize("url", [
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=0&TagID=0&Filter=answered",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=0&TagID=8464&Filter=unanswered",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=200080&Filter=answered",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?Filter=answered&Page=2",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=200076&TagID=10475&Filter=answered",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=200076&TagID=0",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=0&TagID=8464",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=200076&TagID=10475",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=200076&Page=2",
])
def test_narrowed_portal_question_listings_are_not_crawled(url):
    """
    The portal's question listing is one flat, paged list of every
    question, and it offers itself narrowed by category, by tag, by both,
    and by an answered or unanswered filter. Measured against the
    Depression Center portal, the flat list reached every question and
    the 84 narrowed views reached nothing more, so the narrowed views
    stay off the crawl.
    """
    assert any(p.search(url) for p in _excludes("crawl")), url


@pytest.mark.parametrize("url", [
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?Page=3",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=0&TagID=0",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions?CategoryID=0&TagID=0&Page=2",
    "https://teamdynamix.umich.edu/TDClient/210/Org/Questions/Details/100010",
])
def test_the_flat_portal_question_listing_and_its_pages_are_crawled(url):
    """The flat list, its pages, and the questions themselves are the route to every question."""
    assert not any(p.search(url) for p in _excludes("crawl")), url


def test_index_defaults_are_a_superset_of_crawl_defaults():
    assert set(web.default_exclude_patterns(BUILT_IN_HANDLERS, "crawl")) <= set(
        web.default_exclude_patterns(BUILT_IN_HANDLERS, "index")
    )


def test_asset_extension_patterns_cover_binary_and_source_extensions():
    for ext in fetch.BINARY_EXTENSIONS + fetch.SOURCE_EXTENSIONS:
        assert rf"\.{ext}$" in fetch.ASSET_EXCLUDE_PATTERNS


def test_omitted_exclude_lists_complete_to_the_handler_defaults():
    source = make_source("https://example.org/")
    assert source.crawl_exclude_patterns == web.default_exclude_patterns(BUILT_IN_HANDLERS, "crawl")
    assert source.index_exclude_patterns == web.default_exclude_patterns(BUILT_IN_HANDLERS, "index")


def test_explicit_exclude_lists_are_used_as_written():
    source = make_source("https://example.org/", crawl_exclude_patterns=(), index_exclude_patterns=(r"/x",))
    assert source.crawl_exclude_patterns == ()
    assert source.index_exclude_patterns == (r"/x",)


def test_disabling_a_handler_drops_its_patterns():
    generic_only = make_source("https://example.org/", handlers=(generic.GenericHandler(),))
    patterns = fetch.compile_patterns(generic_only.crawl_exclude_patterns)

    def excluded(url):
        return any(p.search(url) for p in patterns)

    assert not excluded("https://teamdynamix.umich.edu/TDClient/210/Org/Login.aspx")  # tdx off
    assert not excluded("https://github.com/Org/Repo/issues")                         # github off
    assert excluded("https://example.org/Login")            # generic, always on
    assert excluded("https://example.org/handbook.pdf")     # asset, always on


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def test_web_source_satisfies_the_source_protocol():
    assert isinstance(make_source("https://example.org/"), Source)
    assert web.WebSource.name == "web"


def test_pyproject_declares_the_built_ins_and_each_target_loads():
    """
    Read from pyproject.toml rather than the installed metadata, so the
    check holds whether or not the package was reinstalled after the
    entry points were added.
    """
    with open(PYPROJECT_PATH, "rb") as f:
        entry_points = tomllib.load(f)["project"]["entry-points"]
    assert set(entry_points["extractium.sources"]) == {
        "web", "local", "github_api", "dspace", "youtube", "okf",
    }
    assert set(entry_points["extractium.site_handlers"]) == {
        "generic", "tdx", "github", "youtube", "google_docs",
    }

    reg = registry.Registry()
    for group, register in (
        ("extractium.sources", reg.register_source),
        ("extractium.site_handlers", reg.register_site_handler),
    ):
        for name, target in entry_points[group].items():
            module_name, _, attribute = target.partition(":")
            plugin = getattr(importlib.import_module(module_name), attribute)
            assert plugin.name == name
            register(plugin, registry.Tier.BUILTIN)
    assert reg.source_names() == ("dspace", "github_api", "local", "okf", "web", "youtube")
    assert reg.site_handler_names() == ("generic", "github", "google_docs", "tdx", "youtube")


def test_a_portal_seed_stays_inside_its_portal_folder_through_the_tdx_handler(fake_session_factory):
    """
    The portal-folder scope rule lives in the tdx handler: with it enabled
    a crawl seeded inside one portal never follows a link into another
    portal on the same host, and with it disabled the scope is the host.
    """
    portal = "https://teamdynamix.example.edu/TDClient/210/ExampleOrg"
    other = "https://teamdynamix.example.edu/TDClient/999/OtherOrg/KB/ArticleDet?ID=7"
    seed = f"{portal}/KB/ArticleDet?ID=1"
    inside = f"{portal}/KB/ArticleDet?ID=2"
    page = (
        "<html><head><title>Article - Inside</title></head><body>"
        '<main id="divMainContent"><p>Synthetic paragraph long enough to clear the sixty character minimum for a section.</p>'
        f'<a href="{inside}">inside</a> <a href="{other}">other portal</a></main></body></html>'
    )
    responses = {
        seed: html_response(page),
        inside: html_response(page),
        other: html_response(page),
        "https://teamdynamix.example.edu/robots.txt": ROBOTS_ABSENT,
    }

    with_tdx = crawl(make_source(seed), fake_session_factory(responses))
    assert sorted(d.url for d in with_tdx) == sorted([seed, inside])

    without = crawl(make_source(seed, handlers=()), fake_session_factory(responses))
    assert sorted(d.url for d in without) == sorted([seed, inside, other])


# ---------------------------------------------------------------------------
# Documents linked from pages, and folded addresses
# ---------------------------------------------------------------------------

DOCUMENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOC_ORIGIN = "https://example.org"
DOC_SEED = f"{DOC_ORIGIN}/resources"
CDN_DOCX = "https://cdn.example.org/files/p/prod/0a1b2c.docx/youth-resources"
CDN_DOCX_NAMED = "https://cdn.example.org/files/p/prod/0a1b2c.docx/youth-resources.docx?dl"
SITE_DOCX = f"{DOC_ORIGIN}/files/plan.docx"
SITE_DOC = f"{DOC_ORIGIN}/files/old.doc"
CDN_INCLUDE = (r"^https://example\.org/", r"^https://cdn\.example\.org/files/.*\.docx")


def document_response(data, **extra):
    return FakeResponse(200, {"Content-Type": DOCUMENT_TYPE}, content=data, **extra)


def page_with_links(*links):
    anchors = "".join(f'<a href="{link}">file</a>' for link in links)
    return html_response(
        f"<html><head><title>Files</title></head><body><main><p>Resources</p>{anchors}</main></body></html>"
    )


def document_crawl(session, read_documents=True, **options):
    lines = []
    source = make_source(DOC_SEED, read_documents=read_documents, **options)
    documents = crawl(source, session, progress=lines.append)
    return documents, lines


def test_a_linked_word_file_is_read_when_read_documents_is_on(isolated_core_cache, fake_session_factory):
    session = fake_session_factory({
        f"{DOC_ORIGIN}/robots.txt": ROBOTS_ABSENT,
        DOC_SEED: page_with_links(SITE_DOCX, SITE_DOC),
        SITE_DOCX: document_response(document_files.SAMPLE_DOCX),
    })

    documents, lines = document_crawl(session)

    by_url = {d.url: d for d in documents}
    document = by_url[SITE_DOCX]
    assert document.title == "Youth Mental Health Resources"
    assert document.content_type == "text"
    assert document.source_type == "web"
    assert document.content.find("h2").get_text() == "Middle School"
    assert "Keywords: depression, anxiety, classroom" in document.content.get_text()
    assert "       document: Youth Mental Health Resources" in lines
    # The binary .doc format has no reader, so the link is never fetched.
    assert SITE_DOC not in [c["url"] for c in session.calls]
    assert SITE_DOC not in by_url


def test_document_links_are_left_alone_by_default(isolated_core_cache, fake_session_factory):
    session = fake_session_factory({
        f"{DOC_ORIGIN}/robots.txt": ROBOTS_ABSENT,
        DOC_SEED: page_with_links(SITE_DOCX),
        SITE_DOCX: document_response(document_files.SAMPLE_DOCX),
    })

    documents, _ = document_crawl(session, read_documents=False)

    assert [d.url for d in documents] == [DOC_SEED]
    assert SITE_DOCX not in [c["url"] for c in session.calls]


def test_a_file_on_a_delivery_host_is_read_through_an_include_pattern_and_once_for_its_two_addresses(
    isolated_core_cache, fake_session_factory,
):
    """
    A delivery network serves one file as /<stored name>.docx/<title> and
    again with the title carrying the extension and a download flag. Both
    are fetched, because the address alone cannot tell them apart, and the
    bytes decide that they are one file.
    """
    session = fake_session_factory({
        f"{DOC_ORIGIN}/robots.txt": ROBOTS_ABSENT,
        "https://cdn.example.org/robots.txt": ROBOTS_ABSENT,
        DOC_SEED: page_with_links(CDN_DOCX, CDN_DOCX_NAMED),
        CDN_DOCX: document_response(document_files.SAMPLE_DOCX),
        CDN_DOCX_NAMED: document_response(document_files.SAMPLE_DOCX),
    })

    documents, lines = document_crawl(session, include_patterns=CDN_INCLUDE)

    assert [d.url for d in documents if "cdn." in d.url] == [CDN_DOCX]
    assert f"       (the same file as {CDN_DOCX}; not indexed again)" in lines
    requested = [c["url"] for c in session.calls]
    assert CDN_DOCX in requested and CDN_DOCX_NAMED in requested
    accept = next(c["headers"]["Accept"] for c in session.calls if c["url"] == CDN_DOCX)
    assert accept.startswith("application/vnd.openxmlformats-officedocument")


def test_a_document_address_that_answers_a_web_page_is_reported_and_skipped(
    isolated_core_cache, fake_session_factory,
):
    session = fake_session_factory({
        f"{DOC_ORIGIN}/robots.txt": ROBOTS_ABSENT,
        DOC_SEED: page_with_links(SITE_DOCX),
        SITE_DOCX: FakeResponse(
            200, {"Content-Type": "text/html"}, "<html>sign in</html>", url=f"{DOC_ORIGIN}/login",
        ),
    })

    documents, lines = document_crawl(session)

    assert SITE_DOCX not in [d.url for d in documents]
    skip = [line for line in lines if line.startswith(f"  SKIP {SITE_DOCX}")]
    assert skip and "text/html" in skip[0] and f"landed on {DOC_ORIGIN}/login" in skip[0]


def test_a_file_the_reader_refuses_is_reported_with_the_reason(isolated_core_cache, fake_session_factory):
    session = fake_session_factory({
        f"{DOC_ORIGIN}/robots.txt": ROBOTS_ABSENT,
        DOC_SEED: page_with_links(SITE_DOCX),
        SITE_DOCX: document_response(b"not a document at all"),
    })

    documents, lines = document_crawl(session)

    assert SITE_DOCX not in [d.url for d in documents]
    assert f"  SKIP {SITE_DOCX} -- not a Word, OpenDocument, or RTF file" in lines


def test_a_long_document_is_indexed_as_an_outline_that_keeps_its_properties(
    isolated_core_cache, fake_session_factory, monkeypatch,
):
    monkeypatch.setattr(web.prose, "MAX_PROSE_CHARS", 200)
    session = fake_session_factory({
        f"{DOC_ORIGIN}/robots.txt": ROBOTS_ABSENT,
        DOC_SEED: page_with_links(SITE_DOCX),
        SITE_DOCX: document_response(document_files.SAMPLE_DOCX),
    })

    documents, lines = document_crawl(session)

    document = next(d for d in documents if d.url == SITE_DOCX)
    assert isinstance(document.content, str)
    assert "Keywords: depression, anxiety, classroom" in document.content
    assert "Headings: Youth Mental Health Resources; Middle School; High School" in document.content
    assert any("indexed as an outline" in line for line in lines)


def test_a_document_on_the_index_exclude_list_is_fetched_but_not_indexed(
    isolated_core_cache, fake_session_factory,
):
    session = fake_session_factory({
        f"{DOC_ORIGIN}/robots.txt": ROBOTS_ABSENT,
        DOC_SEED: page_with_links(SITE_DOCX),
        SITE_DOCX: document_response(document_files.SAMPLE_DOCX),
    })

    documents, _ = document_crawl(session, index_exclude_patterns=(r"/files/plan",))

    assert SITE_DOCX in [c["url"] for c in session.calls]
    assert SITE_DOCX not in [d.url for d in documents]


def test_reading_documents_drops_their_extensions_from_both_default_exclude_lists():
    off = make_source(DOC_SEED)
    on = make_source(DOC_SEED, read_documents=True)

    assert r"\.docx$" in off.crawl_exclude_patterns and r"\.docx$" in off.index_exclude_patterns
    assert r"\.docx$" not in on.crawl_exclude_patterns and r"\.docx$" not in on.index_exclude_patterns
    assert r"\.rtf$" not in on.crawl_exclude_patterns
    assert r"\.pdf$" in on.crawl_exclude_patterns and r"\.doc$" in on.crawl_exclude_patterns


class _FoldingHandler:
    """A handler that folds a page's tracking parameter away, so one page has one address."""

    name = "folding"
    source_type = "web"
    default_crawl_exclude_patterns = ()
    default_index_exclude_patterns = ()

    def matches(self, url):
        return "/article/" in url

    def canonical_url(self, url):
        return url.split("?")[0]

    def fetch_url(self, url):
        return url

    def expects_html(self, url):
        return True

    def extract(self, soup, url):
        return generic.GenericHandler().extract(soup, url)

    def content_type(self, url):
        return "page"


def test_a_handler_folds_the_addresses_of_one_page_so_it_is_fetched_once(
    isolated_core_cache, fake_session_factory,
):
    article = f"{DOC_ORIGIN}/article/one"
    session = fake_session_factory({
        f"{DOC_ORIGIN}/robots.txt": ROBOTS_ABSENT,
        DOC_SEED: page_with_links(f"{article}?ref=menu", f"{article}?ref=footer", article),
        article: html_response(
            "<html><head><title>One</title></head><body><main><p>Article text long enough.</p></main></body></html>"
        ),
    })
    source = make_source(DOC_SEED, handlers=(_FoldingHandler(),) + BUILT_IN_HANDLERS)

    documents = crawl(source, session)

    assert [d.url for d in documents] == [DOC_SEED, article]
    assert [c["url"] for c in session.calls].count(article) == 1
    assert not any("?ref=" in c["url"] for c in session.calls)
