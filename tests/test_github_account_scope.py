"""
Summary: Tests for the rule that a GitHub account is read only when the
operator named it: which accounts a configuration allows, the account
read out of each GitHub-shaped address, the crawl scope that keeps an
unnamed account out however it was linked, the one report naming what was
held back, and the handler's offer of the API source for a GitHub seed.
No test contacts the network.

This file is part of Extractium™
tests/test_github_account_scope.py

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
from extractium.core.registry import build_registry
from extractium.sources import github, web
from extractium.sources.generic import GenericHandler
from tests.conftest import FakeResponse

# The organization a build in these tests asked for, and one it did not.
NAMED = "example-org"
UNNAMED = "some-other-org"


def quiet(line):
    """A progress sink for tests that do not inspect progress."""


def configured_handler(*accounts):
    """A GitHub handler with the account rule in force for the given accounts."""
    handler = github.GitHubHandler()
    handler.configure(web.CrawlSettings(github_owners=accounts))
    return handler


# ---------------------------------------------------------------------------
# Reading the account out of an address
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("https://github.com/example-org", "example-org"),
    ("https://github.com/Example-Org/repo/blob/main/README.md", "example-org"),
    ("https://raw.githubusercontent.com/example-org/repo/main/README.md", "example-org"),
    ("https://example-org.github.io/handbook/", "example-org"),
    ("https://gist.github.com/example-org/abc123", "example-org"),
    # GitHub's own pages belong to no account.
    ("https://github.com/topics/python", None),
    ("https://github.com/settings/profile", None),
    ("https://github.com/", None),
    # Any other host is not this rule's business.
    ("https://example.org/example-org", None),
])
def test_the_account_is_read_from_every_github_shaped_address(url, expected):
    assert github.owner_for_url(url) == expected


# ---------------------------------------------------------------------------
# Which accounts a build allows
# ---------------------------------------------------------------------------

def test_an_account_named_by_a_github_source_is_allowed():
    cfg = config.config_from_mapping({"sources": [{"type": "github_api", "org": NAMED}]})

    assert github.accounts_named_by(cfg.sources) == {NAMED}


def test_an_account_named_in_a_web_seed_is_allowed():
    cfg = config.config_from_mapping({
        "sources": [{"type": "web", "seed_url": f"https://github.com/{NAMED}/example-tools"}],
    })

    assert github.accounts_named_by(cfg.sources) == {NAMED}


def test_an_account_named_by_a_repository_address_is_allowed():
    cfg = config.config_from_mapping({
        "sources": [{"type": "github_api", "url": f"https://github.com/{NAMED}/example-tools"}],
    })

    assert github.accounts_named_by(cfg.sources) == {NAMED}


def test_a_crawl_of_an_ordinary_website_allows_no_github_account():
    cfg = config.config_from_mapping({
        "sources": [{"type": "web", "seed_url": "https://example.org/docs"}],
    })

    assert github.accounts_named_by(cfg.sources) == set()


def test_allowing_an_account_is_not_the_same_as_listing_everything_it_has():
    """
    github_owners says "you may follow links into this account". Only
    naming an account as a source reads the whole account.
    """
    cfg = config.config_from_mapping({
        "github_owners": [UNNAMED],
        "sources": [{"type": "github_api", "org": NAMED}],
    })

    assert github.accounts_named_by(cfg.sources) == {NAMED}
    assert [entry.type for entry in cfg.sources] == ["github_api"]
    assert [entry.options["org"] for entry in cfg.sources] == [NAMED]


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------

def test_an_unconfigured_handler_restricts_nothing():
    """
    A handler built directly, by a library caller or a test, has not been
    told what the operator asked for. Refusing everything then would look
    like a broken crawl rather than a guardrail.
    """
    handler = github.GitHubHandler()

    assert handler.allows(f"https://github.com/{UNNAMED}/anything")


def test_an_account_the_operator_named_is_read():
    handler = configured_handler(NAMED)

    assert handler.allows(f"https://github.com/{NAMED}/example-tools/blob/main/README.md")


def test_an_account_the_operator_did_not_name_is_not_read():
    handler = configured_handler(NAMED)

    assert not handler.allows(f"https://github.com/{UNNAMED}/their-tools")


@pytest.mark.parametrize("url", [
    f"https://github.com/{UNNAMED}/their-tools/blob/main/README.md",
    f"https://raw.githubusercontent.com/{UNNAMED}/their-tools/main/README.md",
    f"https://{UNNAMED}.github.io/their-site/",
])
def test_the_rule_covers_every_github_shaped_host(url):
    """The same account owns content on all three, so one host is not enough."""
    handler = configured_handler(NAMED)

    assert not handler.allows(url)


def test_a_url_on_another_host_is_never_this_handlers_business():
    handler = configured_handler(NAMED)

    assert handler.allows("https://example.org/anything")
    assert handler.allows("https://gitlab.com/somebody/project")


def test_an_empty_allowlist_reads_no_account_at_all():
    handler = configured_handler()

    assert not handler.allows(f"https://github.com/{NAMED}/example-tools")


def test_the_account_name_is_matched_regardless_of_letter_case():
    handler = configured_handler("Example-Org")

    assert handler.allows("https://github.com/example-org/example-tools")


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def test_a_skipped_account_is_counted_and_reported_once_not_once_per_link():
    handler = configured_handler(NAMED)
    for number in range(14):
        handler.allows(f"https://github.com/{UNNAMED}/project-{number}")
    handler.allows("https://github.com/a-contributor/profile-project")

    report = handler.skipped_account_report()

    assert report == (
        "Not read; add to github_owners to include: "
        f"{UNNAMED} (14 links), a-contributor (1 link)"
    )


def test_nothing_is_reported_when_nothing_was_held_back():
    assert configured_handler(NAMED).skipped_account_report() == ""


# ---------------------------------------------------------------------------
# Crawl scope
# ---------------------------------------------------------------------------

def html_response(text):
    return FakeResponse(status_code=200, headers={"Content-Type": "text/html"}, text=text)


ROBOTS_ABSENT = FakeResponse(status_code=404)


def test_an_unnamed_account_linked_from_a_readme_is_never_crawled(
    isolated_core_cache, fake_session_factory,
):
    """
    This is the case the rule exists for. A crawl seeded at github.com has
    github.com as its origin, so without the rule every account on the
    host is same-origin and therefore in scope.
    """
    seed = f"https://github.com/{NAMED}/example-tools/wiki"
    page = (
        '<html><head><title>Wiki</title></head><body><article>'
        f'<p>Built on <a href="https://github.com/{UNNAMED}/their-tools">their tools</a>, '
        f'with thanks to <a href="https://github.com/a-contributor">a contributor</a>. '
        "This paragraph is long enough to clear the minimum chunk size the chunker uses.</p>"
        f'<a href="https://github.com/{NAMED}/example-notes/wiki">our other notes</a>'
        "</article></body></html>"
    )
    session = fake_session_factory({
        seed: html_response(page),
        f"https://github.com/{NAMED}/example-notes/wiki": html_response(page),
        "https://github.com/robots.txt": ROBOTS_ABSENT,
    })
    handler = configured_handler(NAMED)
    source = web.WebSource(
        {"seed_url": seed, "include_patterns": (), "crawl_exclude_patterns": None,
         "index_exclude_patterns": None, "site_handlers": None},
        (handler, GenericHandler()),
        web.CrawlSettings(max_pages=10, delay_seconds=0, github_owners=(NAMED,)),
    )

    list(source.fetch(session, {}, quiet))

    requested = [call["url"] for call in session.calls]
    assert not any(UNNAMED in url for url in requested)
    assert not any("a-contributor" in url for url in requested)
    # The account the operator did name is still crawled.
    assert f"https://github.com/{NAMED}/example-notes/wiki" in requested
    # Both crawled pages point at the same outside account, and each
    # pointer is counted: the report says how many links led there.
    assert handler.skipped_accounts[UNNAMED] == 2


def test_the_settings_reach_the_handlers_the_registry_builds():
    handlers = web.resolve_site_handlers(
        build_registry(), None, web.CrawlSettings(github_owners=(NAMED,)),
    )
    handler = next(h for h in handlers if h.name == "github")

    assert handler.allowed_accounts == frozenset({NAMED})


def test_a_handler_with_no_opinion_never_blocks_a_url():
    """Only handlers that define the hook are asked; the rest are unaffected."""
    assert web.handlers_allow((GenericHandler(),), f"https://github.com/{UNNAMED}/anything")


# ---------------------------------------------------------------------------
# Offering the API source for a seed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed, expected_url", [
    (f"https://github.com/{NAMED}", f"https://github.com/{NAMED}"),
    (f"https://github.com/{NAMED}/example-tools", f"https://github.com/{NAMED}/example-tools"),
])
def test_a_github_seed_is_offered_the_api_source(seed, expected_url):
    offer = github.GitHubHandler().offer_source(seed)

    assert offer is not None
    name, options = offer
    assert name == "github_api"
    assert options["url"] == expected_url


@pytest.mark.parametrize("seed", [
    "https://example.org/docs",
    "https://gitlab.com/somebody/project",
    "https://github.com/topics/python",
    "https://github.com/",
    "https://example-org.github.io/handbook/",
])
def test_anything_else_is_crawled_as_it_was_before(seed):
    assert github.GitHubHandler().offer_source(seed) is None


def test_the_offer_is_never_taken_for_a_source_that_turned_it_off():
    """
    The GitHub source falls back to a crawl of the same address. Without
    this, the crawl would hand the seed straight back to the source it
    just came from.
    """
    source = web.WebSource(
        {"seed_url": f"https://github.com/{NAMED}", "promote": False},
        (github.GitHubHandler(), GenericHandler()),
        web.CrawlSettings(delay_seconds=0),
    )
    source.registry = build_registry()

    assert source._offered_source(quiet) is None


def test_a_link_found_mid_crawl_never_redirects_the_build(
    isolated_core_cache, fake_session_factory,
):
    """
    The offer is for the seed only. Otherwise one mention of a repository
    on an unrelated website could pull a whole GitHub account into a small
    site crawl.
    """
    seed = "https://example.org/docs"
    page = (
        '<html><head><title>Docs</title></head><body><main>'
        f'<p>Our code lives at <a href="https://github.com/{NAMED}">our account</a>. '
        "This paragraph is long enough to clear the minimum chunk size threshold.</p>"
        "</main></body></html>"
    )
    session = fake_session_factory({
        seed: html_response(page),
        "https://example.org/robots.txt": ROBOTS_ABSENT,
    })
    source = web.WebSource(
        {"seed_url": seed, "include_patterns": (), "crawl_exclude_patterns": None,
         "index_exclude_patterns": None, "site_handlers": None},
        (github.GitHubHandler(), GenericHandler()),
        web.CrawlSettings(max_pages=10, delay_seconds=0),
    )
    source.registry = build_registry()

    documents = list(source.fetch(session, {}, quiet))

    assert [d.url for d in documents] == [seed]
    assert not any("api.github.com" in call["url"] for call in session.calls)
