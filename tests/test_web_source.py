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

import importlib
import pathlib
import tomllib

import pytest

from extractium.core import chunk, fetch, registry
from extractium.core.models import Document, Source
from extractium.sources import generic, github, tdx, web
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


def test_delay_is_applied_between_pages(isolated_core_cache, fake_session_factory, monkeypatch):
    seed, private, session = _two_page_site(fake_session_factory, ROBOTS_ABSENT)
    sleeps = []
    monkeypatch.setattr(web.time, "sleep", sleeps.append)

    crawl(make_source(seed, settings=web.CrawlSettings(max_pages=10, delay_seconds=0.25)), session)

    assert sleeps == [0.25, 0.25]


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
# Default exclude patterns
# ---------------------------------------------------------------------------

def test_default_crawl_exclude_patterns_match_reference_script(reference):
    """
    The asset patterns plus every built-in handler's contribution must
    exclude exactly what the frozen original excluded. Order carries no
    meaning (any single match excludes a URL), so the comparison is
    set-based.
    """
    patterns = web.default_exclude_patterns(BUILT_IN_HANDLERS, "crawl")
    assert set(patterns) == set(reference.CRAWL_EXCLUDE_PATTERNS)
    assert len(patterns) == len(set(patterns))


def test_default_index_exclude_patterns_match_reference_script(reference):
    patterns = web.default_exclude_patterns(BUILT_IN_HANDLERS, "index")
    assert set(patterns) == set(reference.INDEX_EXCLUDE_PATTERNS)


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
    assert r"/Login\.aspx" not in generic_only.crawl_exclude_patterns      # tdx
    assert r"/issues?[/?]" not in generic_only.crawl_exclude_patterns      # github
    assert r"/Login[/?$]" in generic_only.crawl_exclude_patterns           # generic, always on
    assert r"\.pdf$" in generic_only.crawl_exclude_patterns                # asset, always on


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
    assert set(entry_points["extractium.sources"]) == {"web"}
    assert set(entry_points["extractium.site_handlers"]) == {"generic", "tdx", "github"}

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
    assert reg.source_names() == ("web",)
    assert reg.site_handler_names() == ("generic", "github", "tdx")
