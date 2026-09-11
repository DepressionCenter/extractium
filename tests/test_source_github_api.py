"""
Summary: Tests for the GitHub API source
(extractium.sources.github_api): the three ways of reading GitHub and the
order they are tried in, what a rejected token does, repository
selection, the file filter, the ledger that stops a demotion repeating
work, the coverage report, and the records produced. Every API response
is scripted from the committed fixture in tests/fixtures/github -- no
test contacts GitHub.

This file is part of Extractium™
tests/test_source_github_api.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-09
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
__date__ = "2026-09-09"

import io
import json
import pathlib
import re
import tarfile

import pytest

from extractium.core.models import Document, Source
from extractium.core.registry import build_registry
from extractium.sources import github_files
from extractium.sources.github_api import (
    TIER_AUTHENTICATED,
    TIER_CRAWL,
    TIER_PUBLIC,
    GitHubApiSource,
    GitHubSourceError,
    owner_and_repository,
)
from extractium.sources.github_client import API_ROOT
from extractium.sources.web import CrawlSettings
from tests.conftest import FakeApiResponse, FakeGitHubSession

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "github" / "example_org.json"

# A token that has never existed anywhere.
EXAMPLE_TOKEN = "example-token-not-a-real-credential"


@pytest.fixture
def fixture():
    """The synthetic organization every test in this module reads."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def quiet(line):
    """A progress sink for tests that do not inspect progress."""


def make_archive(entries, prefix="example-org-example-tools-abc1234"):
    """A gzip tar shaped the way GitHub ships one: everything under one top folder."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, body in entries.items():
            data = body.encode("utf-8")
            info = tarfile.TarInfo(f"{prefix}/{path}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def repository_archive(fixture, name):
    """The archive GitHub would ship for one repository of the fixture."""
    paths = {
        entry["path"]: fixture["blobs"][entry["sha"]]
        for entry in fixture["trees"][name]["tree"]
        if entry.get("type") == "blob" and entry["sha"] in fixture["blobs"]
    }
    return make_archive(paths, prefix=f"example-org-{name}-abc1234")


def api_routes(fixture, repositories=None, trees=None, archives=True):
    """
    The scripted API answers for the synthetic organization.

    Both routes to a file body are scripted: the repository archive, which
    is how a small repository is read, and the individual blobs, which is
    how a large one is.

    Args:
        fixture (dict): the loaded fixture file.
        repositories (list | None): the listing to serve; the fixture's
            own list by default.
        trees (dict | None): repository name to tree answer; the
            fixture's own trees by default.
        archives (bool): False leaves the tarball addresses unscripted, so
            a test can exercise the fall back to individual requests.
    """
    repositories = fixture["repositories"] if repositories is None else repositories
    trees = fixture["trees"] if trees is None else trees
    routes = {
        f"{API_ROOT}/users/example-org": FakeApiResponse(payload=fixture["account"]),
        f"{API_ROOT}/orgs/example-org/repos": FakeApiResponse(payload=repositories),
    }
    for entry in repositories:
        name = entry["name"]
        routes[f"{API_ROOT}/repos/example-org/{name}"] = FakeApiResponse(payload=entry)
        if name in trees:
            routes[f"{API_ROOT}/repos/example-org/{name}/git/trees/main"] = FakeApiResponse(
                payload=trees[name]
            )
            if archives:
                routes[f"{API_ROOT}/repos/example-org/{name}/tarball/main"] = FakeApiResponse(
                    content=repository_archive(fixture, name)
                )
    for sha, body in fixture["blobs"].items():
        routes[f"{API_ROOT}/repos/example-org/example-tools/git/blobs/{sha}"] = FakeApiResponse(text=body)
        routes[f"{API_ROOT}/repos/example-org/example-notes/git/blobs/{sha}"] = FakeApiResponse(text=body)
    return routes


def make_source(progress=quiet, **options):
    """A source over the option shape the configuration loader produces."""
    validated = {
        "org": "example-org", "user": None, "url": None,
        "include_repos": (), "exclude_repos": (),
        "include_forks": False, "include_archived": True,
        "include_code": True, "max_file_bytes": 2_000_000,
        **options,
    }
    source = GitHubApiSource(validated)
    source.configure(build_registry(), CrawlSettings(delay_seconds=0, max_pages=5))
    return source


def read(source, session, progress=quiet, cache=None):
    return list(source.fetch(session, {} if cache is None else cache, progress))


@pytest.fixture(autouse=True)
def no_token(monkeypatch):
    """
    Every test states its own token situation. Without this, whether the
    suite passes would depend on the machine it runs on.
    """
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def isolated_cache(isolated_core_cache):
    """
    Every test gets its own cache directory. Sharing one would let a file
    body read by an earlier test satisfy a later test's download, and the
    later test would pass for the wrong reason.
    """
    return isolated_core_cache


# ---------------------------------------------------------------------------
# The source contract
# ---------------------------------------------------------------------------

def test_the_source_satisfies_the_plugin_protocol():
    assert isinstance(make_source(), Source)
    assert GitHubApiSource.name == "github_api"


def test_an_owner_address_and_a_repository_address_mean_different_things():
    """
    Reading these the same way would turn a request for one repository
    into a request for every repository its owner has.
    """
    assert owner_and_repository("https://github.com/example-org") == ("example-org", None)
    assert owner_and_repository("https://github.com/example-org/example-tools") == (
        "example-org", "example-tools",
    )
    assert owner_and_repository("https://github.com/example-org/example-tools/tree/main/docs") == (
        "example-org", "example-tools",
    )
    assert owner_and_repository("https://example.org/somebody") == (None, None)


def test_a_url_that_is_not_a_github_address_is_refused_at_construction():
    with pytest.raises(GitHubSourceError, match="not a GitHub owner or repository address"):
        GitHubApiSource({"org": None, "user": None, "url": "https://example.org/nothing"})


# ---------------------------------------------------------------------------
# Reading an organization
# ---------------------------------------------------------------------------

def test_an_organization_is_read_through_the_api(fixture, fake_github_session_factory):
    session = fake_github_session_factory(api_routes(fixture))

    documents = read(make_source(), session)

    urls = [d.url for d in documents]
    assert "https://github.com/example-org/example-tools/blob/main/README.md" in urls
    assert "https://github.com/example-org/example-tools/blob/main/docs/setup.md" in urls
    assert "https://github.com/example-org/example-tools/blob/main/pyproject.toml" in urls
    assert all(d.source_type == "github" for d in documents)


def test_a_readme_a_manifest_and_other_prose_are_labelled_apart(fixture, fake_github_session_factory):
    session = fake_github_session_factory(api_routes(fixture))

    by_url = {d.url: d for d in read(make_source(), session)}

    root = "https://github.com/example-org/example-tools/blob/main"
    assert by_url[f"{root}/README.md"].content_type == "readme"
    assert by_url[f"{root}/docs/setup.md"].content_type == "text"
    assert by_url[f"{root}/pyproject.toml"].content_type == "manifest"


def test_a_manifest_says_what_it_is_for_in_its_title(fixture, fake_github_session_factory):
    session = fake_github_session_factory(api_routes(fixture))

    by_url = {d.url: d for d in read(make_source(), session)}
    manifest = by_url["https://github.com/example-org/example-tools/blob/main/pyproject.toml"]

    assert "Python project definition" in manifest.title


def test_categories_follow_the_folders_a_file_sits_in(fixture, fake_github_session_factory):
    session = fake_github_session_factory(api_routes(fixture))

    by_url = {d.url: d for d in read(make_source(), session)}

    assert by_url["https://github.com/example-org/example-tools/blob/main/docs/setup.md"].categories == (
        "example-org", "example-tools", "docs",
    )


def test_every_repository_gets_a_summary_naming_how_it_was_read(fixture, fake_github_session_factory):
    session = fake_github_session_factory(api_routes(fixture))

    maps = [d for d in read(make_source(), session) if d.content_type == "repo_map"]

    assert [d.url for d in maps] == [
        "https://github.com/example-org/example-tools",
        "https://github.com/example-org/example-notes",
        "https://github.com/example-org",
    ]
    assert "tier 2 (public API)" in maps[0].content
    assert "code analysis" in maps[0].content


def test_an_account_gets_one_map_naming_everything_it_publishes(
    fixture, fake_github_session_factory,
):
    """
    A reader asks which project holds the answer before they can search
    inside it. The account's own map is what answers that.
    """
    session = fake_github_session_factory(api_routes(fixture))

    documents = read(make_source(), session)

    owner_map = next(d for d in documents if d.url == "https://github.com/example-org")
    assert "example-tools: Shared analysis helpers" in owner_map.content
    assert "example-notes" in owner_map.content
    assert "Main language: Python" in owner_map.content


def test_a_request_for_one_repository_gets_no_account_map(fixture, fake_github_session_factory):
    session = fake_github_session_factory(api_routes(fixture))

    documents = read(make_source(org=None, url="https://github.com/example-org/example-tools"), session)

    assert not [d for d in documents if d.url == "https://github.com/example-org"]


# ---------------------------------------------------------------------------
# Which repositories are read
# ---------------------------------------------------------------------------

def test_a_fork_an_empty_repository_and_a_disabled_one_are_left_out(fixture, fake_github_session_factory):
    lines = []
    session = fake_github_session_factory(api_routes(fixture))

    read(make_source(), session, progress=lines.append)

    assert any("example-fork" in line and "fork" in line for line in lines)
    assert any("example-empty" in line and "empty" in line for line in lines)


def test_an_archived_repository_is_read_because_its_documentation_still_counts(
    fixture, fake_github_session_factory,
):
    session = fake_github_session_factory(api_routes(fixture))

    documents = read(make_source(), session)

    assert any("example-notes" in d.url for d in documents)


def test_archived_repositories_can_be_left_out(fixture, fake_github_session_factory):
    session = fake_github_session_factory(api_routes(fixture))

    documents = read(make_source(include_archived=False), session)

    assert not any("example-notes" in d.url for d in documents)


def test_include_repos_narrows_the_listing(fixture, fake_github_session_factory):
    session = fake_github_session_factory(api_routes(fixture))

    documents = read(make_source(include_repos=("example-notes",)), session)

    repositories = {d.url.split("/")[4] for d in documents if len(d.url.split("/")) > 4}
    assert repositories == {"example-notes"}


def test_exclude_repos_wins_over_include_repos(fixture, fake_github_session_factory):
    session = fake_github_session_factory(api_routes(fixture))

    documents = read(
        make_source(include_repos=("example-tools",), exclude_repos=("example-tools",)), session,
    )

    assert documents == []


def test_a_repository_address_reads_that_repository_and_never_the_whole_account(
    fixture, fake_github_session_factory,
):
    session = fake_github_session_factory(api_routes(fixture))

    documents = read(
        make_source(org=None, url="https://github.com/example-org/example-tools"), session,
    )

    assert {d.url.split("/")[4] for d in documents} == {"example-tools"}
    assert f"{API_ROOT}/orgs/example-org/repos" not in session.urls


def test_a_user_account_is_listed_from_the_user_endpoint(fixture, fake_github_session_factory):
    routes = {
        f"{API_ROOT}/users/someone": FakeApiResponse(payload={"login": "someone", "type": "User"}),
        f"{API_ROOT}/users/someone/repos": FakeApiResponse(payload=[]),
    }
    session = fake_github_session_factory(routes)

    read(make_source(org=None, user="someone"), session)

    assert f"{API_ROOT}/users/someone/repos" in session.urls


# ---------------------------------------------------------------------------
# Which files are read
# ---------------------------------------------------------------------------

def test_source_files_third_party_folders_and_secrets_are_never_downloaded(
    fixture, fake_github_session_factory,
):
    session = fake_github_session_factory(api_routes(fixture))

    urls = [d.url for d in read(make_source(), session)]

    assert not any("node_modules" in url for url in urls)
    assert not any(url.endswith("/.env") for url in urls)


def test_an_env_example_is_kept_because_it_documents_what_a_project_needs(
    fixture, fake_github_session_factory,
):
    assert github_files.classify(".env.example") == "manifest"
    assert github_files.classify(".env") is None


def test_a_file_over_the_size_ceiling_is_skipped_and_always_named(
    fixture, fake_github_session_factory,
):
    """A missing file nobody was told about is worse than one that was reported."""
    lines = []
    session = fake_github_session_factory(api_routes(fixture))

    read(make_source(), session, progress=lines.append)

    assert any("very-large-report.md" in line and "ceiling" in line for line in lines)


def test_the_size_ceiling_is_configurable(fixture, fake_github_session_factory):
    lines = []
    session = fake_github_session_factory(api_routes(fixture))

    read(make_source(max_file_bytes=100), session, progress=lines.append)

    assert any("README.md" in line and "ceiling" in line for line in lines)


def test_a_file_that_vanished_between_the_inventory_and_the_download_is_reported(
    fixture, fake_github_session_factory,
):
    routes = api_routes(fixture, archives=False)
    del routes[f"{API_ROOT}/repos/example-org/example-tools/git/blobs/"
               f"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
    lines = []
    session = fake_github_session_factory(routes)

    documents = read(make_source(), session, progress=lines.append)

    assert any("README.md" in line and "no longer" in line for line in lines)
    # One missing file does not destroy the repository.
    assert any(d.url.endswith("docs/setup.md") for d in documents)


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------

def test_a_build_with_a_token_reads_the_same_documents_as_one_without(
    fixture, fake_github_session_factory, monkeypatch,
):
    """A token buys request capacity, not capability."""
    without = read(make_source(), fake_github_session_factory(api_routes(fixture)))

    monkeypatch.setenv("GITHUB_TOKEN", EXAMPLE_TOKEN)
    authenticated_session = fake_github_session_factory(api_routes(fixture))
    with_token = read(make_source(), authenticated_session)

    assert [d.url for d in without] == [d.url for d in with_token]
    assert authenticated_session.sent_any_token()


def test_a_refused_token_drops_a_tier_indexes_the_same_content_and_says_so(
    fixture, fake_github_session_factory, monkeypatch,
):
    monkeypatch.setenv("GITHUB_TOKEN", EXAMPLE_TOKEN)
    routes = api_routes(fixture)
    # The first request is refused; every request after it succeeds, which
    # is what an anonymous retry of the same address looks like.
    routes[f"{API_ROOT}/users/example-org"] = [
        FakeApiResponse(status_code=401, payload={}),
        FakeApiResponse(payload=fixture["account"]),
    ]
    lines = []
    session = fake_github_session_factory(routes)
    source = make_source()

    documents = read(source, session, progress=lines.append)

    assert any("refused the access token" in line for line in lines)
    assert any(d.url.endswith("README.md") for d in documents)
    assert set(source.coverage.values()) == {TIER_PUBLIC}


def test_a_build_with_no_token_starts_at_the_public_tier(fixture, fake_github_session_factory):
    session = fake_github_session_factory(api_routes(fixture))
    source = make_source()

    read(source, session)

    assert set(source.coverage.values()) == {TIER_PUBLIC}
    assert not session.sent_any_token()


def test_a_token_that_works_records_the_authenticated_tier(
    fixture, fake_github_session_factory, monkeypatch,
):
    monkeypatch.setenv("GITHUB_TOKEN", EXAMPLE_TOKEN)
    session = fake_github_session_factory(api_routes(fixture))
    source = make_source()

    read(source, session)

    assert set(source.coverage.values()) == {TIER_AUTHENTICATED}


def test_a_misspelled_account_stops_the_source_instead_of_falling_back(fake_github_session_factory):
    """Falling back here would turn a typo into a strange, empty result."""
    session = fake_github_session_factory({})

    with pytest.raises(GitHubSourceError, match="Check the spelling"):
        read(make_source(org="no-such-account"), session)


def test_an_api_that_cannot_be_reached_falls_back_to_a_documentation_crawl(
    fixture, fake_github_session_factory, isolated_core_cache,
):
    routes = api_routes(fixture)
    routes[f"{API_ROOT}/users/example-org"] = FakeApiResponse(status_code=503, payload={})
    # The crawl that follows finds a page with nothing to index, which is
    # enough to show which route was taken.
    routes["https://github.com/example-org"] = FakeApiResponse(status_code=404)
    routes["https://github.com/robots.txt"] = FakeApiResponse(status_code=404)
    lines = []
    session = fake_github_session_factory(routes)

    read(make_source(), session, progress=lines.append)

    assert any("documentation crawl" in line for line in lines)
    assert any("no code analysis" in line for line in lines)


def test_the_fallback_crawl_keeps_the_scope_that_was_asked_for(fixture):
    """A request for one repository must not widen to the owner's other work."""
    source = make_source(org=None, url="https://github.com/example-org/example-tools")
    patterns = [re.compile(pattern, re.I) for pattern in source._crawl_include_patterns()]

    def in_scope(url):
        return any(pattern.search(url) for pattern in patterns)

    assert in_scope("https://github.com/example-org/example-tools/blob/main/README.md")
    assert in_scope("https://raw.githubusercontent.com/example-org/example-tools/main/README.md")
    assert not in_scope("https://github.com/example-org/example-notes/blob/main/README.md")
    assert not in_scope("https://github.com/somebody-else/their-tools")


def test_an_owner_request_falls_back_to_that_owner_and_no_further(fixture):
    patterns = [re.compile(p, re.I) for p in make_source()._crawl_include_patterns()]

    def in_scope(url):
        return any(pattern.search(url) for pattern in patterns)

    assert in_scope("https://github.com/example-org/example-notes/blob/main/README.md")
    assert not in_scope("https://github.com/somebody-else/their-tools")


def test_the_fallback_crawl_starts_from_the_address_that_was_asked_for():
    assert make_source().seed_url == "https://github.com/example-org"
    assert make_source(
        org=None, url="https://github.com/example-org/example-tools",
    ).seed_url == "https://github.com/example-org/example-tools"


def test_a_failure_partway_through_neither_loses_a_repository_nor_repeats_one(
    fixture, fake_github_session_factory, monkeypatch,
):
    """
    The authenticated read finished one repository and then failed. The
    tier below must finish the second one without reading the first again:
    two copies of every file would otherwise land in the index.
    """
    monkeypatch.setenv("GITHUB_TOKEN", EXAMPLE_TOKEN)
    routes = api_routes(fixture)
    routes[f"{API_ROOT}/repos/example-org/example-notes/git/trees/main"] = [
        FakeApiResponse(status_code=503, payload={}),
        FakeApiResponse(payload=fixture["trees"]["example-notes"]),
    ]
    session = fake_github_session_factory(routes)
    source = make_source()

    documents = read(source, session)

    urls = [d.url for d in documents]
    assert len(urls) == len(set(urls))
    assert any(url.endswith("example-tools/blob/main/README.md") for url in urls)
    assert any(url.endswith("example-notes/blob/main/README.md") for url in urls)
    # Each repository is reported under the tier that actually read it.
    assert source.coverage == {
        "example-org/example-tools": TIER_AUTHENTICATED,
        "example-org/example-notes": TIER_PUBLIC,
    }


# ---------------------------------------------------------------------------
# How file bodies are downloaded
# ---------------------------------------------------------------------------

def test_a_repository_is_read_as_one_archive_rather_than_a_request_per_file(
    fixture, fake_github_session_factory,
):
    """
    Requests are the scarce resource: an anonymous build gets roughly
    sixty an hour in total, and one archive spends one of them however
    many files come out of it.
    """
    session = fake_github_session_factory(api_routes(fixture))

    documents = read(make_source(), session)

    assert f"{API_ROOT}/repos/example-org/example-tools/tarball/main" in session.urls
    assert not [url for url in session.urls if "/git/blobs/" in url]
    assert any(d.url.endswith("example-tools/blob/main/README.md") for d in documents)


def test_a_repository_too_large_for_an_archive_is_read_a_file_at_a_time(
    fixture, fake_github_session_factory,
):
    """The ceiling is what keeps a very large repository out of memory."""
    large = dict(fixture["repositories"][0], size=999_999)
    lines = []
    session = fake_github_session_factory(
        api_routes(fixture, repositories=[large, fixture["repositories"][1]])
    )

    documents = read(make_source(), session, progress=lines.append)

    assert any("too large to read as one archive" in line for line in lines)
    assert [url for url in session.urls if "/git/blobs/" in url]
    assert any(d.url.endswith("example-tools/blob/main/README.md") for d in documents)


def test_an_archive_that_cannot_be_read_falls_back_to_one_request_per_file(
    fixture, fake_github_session_factory,
):
    """An unreadable archive must not cost the repository its documentation."""
    lines = []
    session = fake_github_session_factory(api_routes(fixture, archives=False))

    documents = read(make_source(), session, progress=lines.append)

    assert any("one at a time" in line for line in lines)
    assert any(d.url.endswith("example-tools/blob/main/README.md") for d in documents)


def test_a_file_read_once_is_never_downloaded_again(
    fixture, fake_github_session_factory, isolated_core_cache,
):
    """
    Both routes fill and read one cache, keyed by the blob name Git gives
    those exact bytes, so a repository nobody changed needs no download.
    """
    session = fake_github_session_factory(api_routes(fixture))
    read(make_source(), session)
    lines = []

    second_session = fake_github_session_factory(api_routes(fixture))
    documents = read(make_source(), second_session, progress=lines.append)

    assert f"{API_ROOT}/repos/example-org/example-tools/tarball/main" in session.urls
    assert not [url for url in second_session.urls if "/tarball/" in url]
    assert not [url for url in second_session.urls if "/git/blobs/" in url]
    assert any("unchanged since the last build" in line for line in lines)
    # The content is still there; it came off the disk.
    assert any(d.url.endswith("example-tools/blob/main/README.md") for d in documents)


def test_a_file_read_through_an_archive_is_stored_under_its_blob_name(
    fixture, fake_github_session_factory, isolated_core_cache,
):
    session = fake_github_session_factory(api_routes(fixture))

    read(make_source(), session)

    readme_sha = "a" * 40
    stored = isolated_core_cache / "github" / "blobs" / readme_sha
    assert stored.is_file()
    assert stored.read_text(encoding="utf-8") == fixture["blobs"][readme_sha]


# ---------------------------------------------------------------------------
# The coverage report
# ---------------------------------------------------------------------------

def test_the_coverage_report_names_every_repository_and_what_it_got(
    fixture, fake_github_session_factory,
):
    session = fake_github_session_factory(api_routes(fixture))
    source = make_source()
    read(source, session)

    report = source.summary_lines()

    assert len(report) == 2
    assert all("tier 2 (public API)" in line for line in report)
    assert all("documentation, code analysis" in line for line in report)


def test_the_coverage_report_is_empty_before_anything_is_read():
    assert make_source().summary_lines() == []


def test_a_crawled_repository_is_reported_as_documentation_only():
    source = make_source()
    source._record_crawled("https://github.com/example-org/example-tools/blob/main/README.md")

    assert source.coverage == {"example-org/example-tools": TIER_CRAWL}
    assert "no code analysis" in source.summary_lines()[0]


# ---------------------------------------------------------------------------
# What is never published
# ---------------------------------------------------------------------------

def test_a_private_repository_is_never_indexed_even_when_a_token_could_read_it(
    fixture, fake_github_session_factory, monkeypatch,
):
    monkeypatch.setenv("GITHUB_TOKEN", EXAMPLE_TOKEN)
    private = dict(fixture["repositories"][0], name="example-private",
                   full_name="example-org/example-private", private=True)
    session = fake_github_session_factory(api_routes(fixture, repositories=[private]))
    lines = []

    documents = read(make_source(), session, progress=lines.append)

    assert documents == []
    assert any("private" in line for line in lines)


def test_a_repository_reporting_another_owner_is_not_read(fixture, fake_github_session_factory):
    """
    The owner arrives in an API response, which is untrusted. A source
    reads the account it was pointed at, not one it is merely handed.
    """
    stranger = dict(
        fixture["repositories"][0],
        owner={"login": "somebody-else"},
        full_name="somebody-else/example-tools",
    )
    lines = []
    session = fake_github_session_factory(api_routes(fixture, repositories=[stranger]))

    documents = read(make_source(), session, progress=lines.append)

    assert documents == []
    assert any("add somebody-else to github_owners" in line for line in lines)


def test_no_document_a_source_produces_is_marked_local(fixture, fake_github_session_factory):
    """Local content has its own guardrail; nothing read from the web may borrow it."""
    session = fake_github_session_factory(api_routes(fixture))

    documents = read(make_source(), session)

    assert documents and all(isinstance(d, Document) and d.local is False for d in documents)
