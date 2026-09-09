"""
Summary: Tests for the GitHub REST transport
(extractium.sources.github_client): paginated listings, a truncated tree
completed through its subtrees, rate-limit headers, the four refusal
statuses, blob bodies cached by SHA, an archive read in memory without
touching the disk, and the rule that a token never leaves the request
headers. Every response is scripted from the committed fixture in
tests/fixtures/github -- no test contacts GitHub.

This file is part of Extractium™
tests/test_github_client.py

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

import io
import tarfile
import time

import pytest
import requests

from extractium.core import cache as caching
from extractium.sources import github_client as client_module
from extractium.sources.github_client import (
    API_ROOT,
    GitHubClient,
    GitHubNotFound,
    GitHubRefused,
    GitHubUnavailable,
    token_from_environment,
)
from tests.conftest import FakeApiResponse, FakeGitHubSession

# A token that has never existed anywhere. Used to prove it stays in the
# request headers and reaches nothing else.
EXAMPLE_TOKEN = "example-token-not-a-real-credential"


def quiet(line):
    """A progress sink for tests that do not inspect progress."""


def make_client(responses, token=None, progress=quiet):
    session = FakeGitHubSession(responses)
    return session, GitHubClient(session, token=token, progress=progress)


def json_response(payload, headers=None):
    return FakeApiResponse(status_code=200, payload=payload, headers=headers)


# ---------------------------------------------------------------------------
# Requests and headers
# ---------------------------------------------------------------------------

def test_a_token_travels_in_the_header_and_nowhere_else():
    session, client = make_client(
        {f"{API_ROOT}/users/example-org": json_response({"login": "example-org"})},
        token=EXAMPLE_TOKEN,
    )

    client.account("example-org")

    call = session.calls[0]
    assert call["headers"]["Authorization"] == f"Bearer {EXAMPLE_TOKEN}"
    assert EXAMPLE_TOKEN not in call["url"]
    assert EXAMPLE_TOKEN not in str(call["params"])


def test_no_token_is_sent_when_there_is_none():
    session, client = make_client(
        {f"{API_ROOT}/users/example-org": json_response({"login": "example-org"})},
    )

    client.account("example-org")

    assert not session.sent_any_token()
    assert client.authenticated is False


def test_the_token_is_read_from_the_environment_only():
    assert token_from_environment({"GITHUB_TOKEN": EXAMPLE_TOKEN}) == EXAMPLE_TOKEN
    assert token_from_environment({}) is None
    assert token_from_environment({"GITHUB_TOKEN": "   "}) is None


def test_an_unreachable_host_is_something_to_work_around():
    class BrokenSession:
        def get(self, *args, **kwargs):
            raise requests.ConnectionError("name or service not known")

    client = GitHubClient(BrokenSession(), progress=quiet)

    with pytest.raises(GitHubUnavailable, match="could not be reached"):
        client.account("example-org")


# ---------------------------------------------------------------------------
# How a failure is classified
# ---------------------------------------------------------------------------

def test_a_missing_account_is_the_operator_asking_for_the_wrong_thing():
    """A 404 must not be worked around: it would turn a typo into an empty result."""
    _, client = make_client({})

    with pytest.raises(GitHubNotFound):
        client.account("no-such-account")


def test_a_rejected_token_is_reported_as_refused_not_as_missing():
    session, client = make_client(
        {f"{API_ROOT}/users/example-org": FakeApiResponse(status_code=401, payload={})},
        token=EXAMPLE_TOKEN,
    )

    with pytest.raises(GitHubRefused, match="refused the access token"):
        client.account("example-org")


@pytest.mark.parametrize("status", [403, 429])
def test_a_throttled_request_is_something_to_work_around(status):
    _, client = make_client({
        f"{API_ROOT}/users/example-org": FakeApiResponse(
            status_code=status, payload={}, headers={"X-RateLimit-Remaining": "0"},
        ),
    })

    with pytest.raises(GitHubUnavailable):
        client.account("example-org")


def test_a_spent_anonymous_budget_says_a_token_would_raise_it():
    _, client = make_client({
        f"{API_ROOT}/users/example-org": FakeApiResponse(
            status_code=403, payload={}, headers={"X-RateLimit-Remaining": "0"},
        ),
    })

    with pytest.raises(GitHubUnavailable, match="GITHUB_TOKEN"):
        client.account("example-org")


def test_a_server_failure_is_something_to_work_around():
    _, client = make_client({
        f"{API_ROOT}/users/example-org": FakeApiResponse(status_code=502, payload={}),
    })

    with pytest.raises(GitHubUnavailable, match="502"):
        client.account("example-org")


def test_an_answer_that_is_not_json_is_reported_rather_than_crashing():
    _, client = make_client({f"{API_ROOT}/users/example-org": FakeApiResponse(status_code=200)})

    with pytest.raises(GitHubUnavailable, match="not JSON"):
        client.account("example-org")


# ---------------------------------------------------------------------------
# Names placed into request paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["../other", "a/b", "", ".", "..", "has space", None])
def test_a_name_that_would_change_the_endpoint_is_refused(name):
    """Names arrive from configuration and from API responses; both are untrusted."""
    _, client = make_client({})

    with pytest.raises(ValueError):
        client.account(name)


@pytest.mark.parametrize("ref", ["../main", "main?x=1", "a b", "", "/main"])
def test_a_branch_name_that_would_change_the_endpoint_is_refused(ref):
    _, client = make_client({})

    with pytest.raises(ValueError):
        client.tree("example-org", "example-tools", ref)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def test_a_listing_asks_for_the_largest_page_and_stops_on_a_short_one():
    full_page = [{"name": f"repo-{n}"} for n in range(client_module.PAGE_SIZE)]
    session, client = make_client({
        f"{API_ROOT}/orgs/example-org/repos": [
            json_response(full_page), json_response([{"name": "last"}]),
        ],
    })

    listed = list(client.repositories_for("example-org", "Organization"))

    assert len(listed) == client_module.PAGE_SIZE + 1
    assert session.calls[0]["params"]["per_page"] == client_module.PAGE_SIZE
    assert [call["params"]["page"] for call in session.calls] == [1, 2]


def test_a_listing_that_answers_something_other_than_a_list_is_reported():
    _, client = make_client({f"{API_ROOT}/orgs/example-org/repos": json_response({"message": "no"})})

    with pytest.raises(GitHubUnavailable, match="other than a list"):
        list(client.repositories_for("example-org", "Organization"))


def test_a_user_account_is_listed_from_the_user_endpoint():
    session, client = make_client({f"{API_ROOT}/users/someone/repos": json_response([])})

    list(client.repositories_for("someone", "User"))

    assert session.urls == [f"{API_ROOT}/users/someone/repos"]


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------

def test_the_remaining_budget_is_read_from_the_response_headers():
    _, client = make_client({
        f"{API_ROOT}/users/example-org": json_response(
            {"login": "example-org"},
            headers={"X-RateLimit-Limit": "5000", "X-RateLimit-Remaining": "4996"},
        ),
    })

    client.account("example-org")

    assert client.rate_limit.remaining == 4996
    # A reserve is kept back, so a run does not spend its last request.
    assert client.rate_limit.budget == 4996 - client_module.RATE_LIMIT_RESERVE


def test_a_long_reset_is_not_waited_out():
    """Moving to another way of reading GitHub beats blocking a build for an hour."""
    _, client = make_client({
        f"{API_ROOT}/users/example-org": json_response(
            {"login": "example-org"},
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()) + 3000)},
        ),
        f"{API_ROOT}/users/other": json_response({"login": "other"}),
    })

    client.account("example-org")
    with pytest.raises(GitHubUnavailable, match="does not reset"):
        client.account("other")


def test_a_short_wait_is_honored(monkeypatch):
    slept = []
    monkeypatch.setattr(client_module.time, "sleep", slept.append)
    _, client = make_client({
        f"{API_ROOT}/users/example-org": json_response(
            {"login": "example-org"}, headers={"Retry-After": "2"},
        ),
        f"{API_ROOT}/users/other": json_response({"login": "other"}),
    })

    client.account("example-org")
    client.account("other")

    assert slept == [2.0]


def test_an_unreadable_rate_limit_header_is_ignored_rather_than_believed():
    _, client = make_client({
        f"{API_ROOT}/users/example-org": json_response(
            {"login": "example-org"}, headers={"X-RateLimit-Remaining": "not a number"},
        ),
    })

    client.account("example-org")

    assert client.rate_limit.remaining is None
    assert client.rate_limit.budget is None


# ---------------------------------------------------------------------------
# Trees
# ---------------------------------------------------------------------------

def test_a_complete_tree_returns_every_file_and_no_folder():
    _, client = make_client({
        f"{API_ROOT}/repos/example-org/example-tools/git/trees/main": json_response({
            "truncated": False,
            "tree": [
                {"path": "README.md", "type": "blob", "sha": "a" * 40},
                {"path": "docs", "type": "tree", "sha": "b" * 40},
            ],
        }),
    })

    entries = client.tree("example-org", "example-tools", "main")

    assert [e["path"] for e in entries] == ["README.md"]


def test_a_truncated_tree_is_completed_through_its_subtrees():
    """
    A truncated tree treated as complete produces a repository that looks
    fully indexed and is not, which is the worst failure available here
    because nothing about the result shows it.
    """
    session, client = make_client({
        f"{API_ROOT}/repos/example-org/example-tools/git/trees/main": json_response({
            "truncated": True,
            "tree": [
                {"path": "README.md", "type": "blob", "sha": "a" * 40},
                {"path": "docs", "type": "tree", "sha": "b" * 40},
            ],
        }),
        f"{API_ROOT}/repos/example-org/example-tools/git/trees/{'b' * 40}": json_response({
            "tree": [
                {"path": "setup.md", "type": "blob", "sha": "c" * 40},
                {"path": "how-to", "type": "tree", "sha": "d" * 40},
            ],
        }),
        f"{API_ROOT}/repos/example-org/example-tools/git/trees/{'d' * 40}": json_response({
            "tree": [{"path": "import.md", "type": "blob", "sha": "e" * 40}],
        }),
    })

    entries = client.tree("example-org", "example-tools", "main")

    assert [e["path"] for e in entries] == [
        "README.md", "docs/how-to/import.md", "docs/setup.md",
    ]


def test_two_folders_holding_the_same_content_both_appear():
    """
    Identical folders share one tree object. Keying the walk on that
    object would silently lose every file in the second one.
    """
    same_sha = "b" * 40
    _, client = make_client({
        f"{API_ROOT}/repos/example-org/example-tools/git/trees/main": json_response({
            "truncated": True,
            "tree": [
                {"path": "one", "type": "tree", "sha": same_sha},
                {"path": "two", "type": "tree", "sha": same_sha},
            ],
        }),
        f"{API_ROOT}/repos/example-org/example-tools/git/trees/{same_sha}": json_response({
            "tree": [{"path": "notes.md", "type": "blob", "sha": "c" * 40}],
        }),
    })

    entries = client.tree("example-org", "example-tools", "main")

    assert [e["path"] for e in entries] == ["one/notes.md", "two/notes.md"]


def test_a_folder_that_reports_itself_as_its_own_child_cannot_spin_forever(monkeypatch):
    monkeypatch.setattr(client_module, "MAX_SUBTREE_REQUESTS", 5)
    sha = "b" * 40
    lines = []
    session = FakeGitHubSession({
        f"{API_ROOT}/repos/example-org/example-tools/git/trees/main": json_response({
            "truncated": True,
            "tree": [{"path": "loop", "type": "tree", "sha": sha}],
        }),
        f"{API_ROOT}/repos/example-org/example-tools/git/trees/{sha}": json_response({
            "tree": [{"path": "loop", "type": "tree", "sha": sha}],
        }),
    })
    client = GitHubClient(session, progress=lines.append)

    client.tree("example-org", "example-tools", "main")

    assert any("may be incomplete" in line for line in lines)


def test_a_folder_that_vanished_is_reported_and_the_rest_still_read():
    lines = []
    session = FakeGitHubSession({
        f"{API_ROOT}/repos/example-org/example-tools/git/trees/main": json_response({
            "truncated": True,
            "tree": [
                {"path": "README.md", "type": "blob", "sha": "a" * 40},
                {"path": "gone", "type": "tree", "sha": "b" * 40},
            ],
        }),
    })
    client = GitHubClient(session, progress=lines.append)

    entries = client.tree("example-org", "example-tools", "main")

    assert [e["path"] for e in entries] == ["README.md"]
    assert any("gone" in line and "skipped" in line for line in lines)


# ---------------------------------------------------------------------------
# File bodies
# ---------------------------------------------------------------------------

def test_a_file_body_is_read_once_and_then_served_from_the_cache(isolated_core_cache):
    sha = "a" * 40
    session, client = make_client({
        f"{API_ROOT}/repos/example-org/example-tools/git/blobs/{sha}":
            FakeApiResponse(status_code=200, text="# Notes\n"),
    })

    first = client.blob_text("example-org", "example-tools", sha)
    second = client.blob_text("example-org", "example-tools", sha)

    assert first == second == "# Notes\n"
    assert len(session.calls) == 1


def test_a_cached_file_body_never_holds_a_token(isolated_core_cache):
    sha = "a" * 40
    _, client = make_client(
        {f"{API_ROOT}/repos/example-org/example-tools/git/blobs/{sha}":
            FakeApiResponse(status_code=200, text="# Notes\n")},
        token=EXAMPLE_TOKEN,
    )

    client.blob_text("example-org", "example-tools", sha)

    written = list(isolated_core_cache.rglob("*"))
    bodies = [path.read_text(encoding="utf-8") for path in written if path.is_file()]
    assert bodies == ["# Notes\n"]
    assert not any(EXAMPLE_TOKEN in body for body in bodies)


@pytest.mark.parametrize("sha", ["../escape", "not-a-sha", "A" * 40, "a" * 39, ""])
def test_a_blob_name_that_is_not_a_git_object_is_refused(sha, isolated_core_cache):
    """The SHA arrives in an API response; an unchecked one could name a path outside the cache."""
    _, client = make_client({})

    with pytest.raises(ValueError):
        caching.github_blob_path(sha)


# ---------------------------------------------------------------------------
# Archives
# ---------------------------------------------------------------------------

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


def test_an_archive_yields_only_the_wanted_files_with_repository_relative_paths():
    payload = make_archive({
        "README.md": "# Example\n",
        "docs/setup.md": "# Setup\n",
        "src/app.py": "print('hello')\n",
    })
    _, client = make_client({
        f"{API_ROOT}/repos/example-org/example-tools/tarball/main":
            FakeApiResponse(status_code=200, content=payload),
    })

    files = client.archive_files("example-org", "example-tools", "main", {"README.md", "docs/setup.md"})

    assert files == {"README.md": "# Example\n", "docs/setup.md": "# Setup\n"}


def test_an_archive_entry_that_is_not_a_regular_file_is_ignored(tmp_path):
    """A symbolic link inside an archive is never followed, because nothing is extracted."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        link = tarfile.TarInfo("example-org-example-tools-abc/README.md")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    _, client = make_client({
        f"{API_ROOT}/repos/example-org/example-tools/tarball/main":
            FakeApiResponse(status_code=200, content=buffer.getvalue()),
    })

    assert client.archive_files("example-org", "example-tools", "main", {"README.md"}) == {}


def test_an_archive_path_that_climbs_out_of_the_repository_matches_nothing(tmp_path):
    payload = make_archive({"../../../../etc/passwd": "root:x:0:0\n"})
    _, client = make_client({
        f"{API_ROOT}/repos/example-org/example-tools/tarball/main":
            FakeApiResponse(status_code=200, content=payload),
    })

    files = client.archive_files("example-org", "example-tools", "main", {"README.md"})

    assert files == {}
    # Nothing is ever written: the archive is read in memory only.
    assert not (tmp_path / "etc").exists()


def test_an_archive_larger_than_the_ceiling_is_refused_rather_than_read(monkeypatch):
    monkeypatch.setattr(client_module, "MAX_ARCHIVE_BYTES", 32)
    _, client = make_client({
        f"{API_ROOT}/repos/example-org/example-tools/tarball/main":
            FakeApiResponse(status_code=200, content=b"x" * 4096),
    })

    with pytest.raises(GitHubUnavailable, match="larger than"):
        client.archive_files("example-org", "example-tools", "main", {"README.md"})


def test_an_archive_that_is_not_a_readable_archive_is_reported():
    _, client = make_client({
        f"{API_ROOT}/repos/example-org/example-tools/tarball/main":
            FakeApiResponse(status_code=200, content=b"not an archive at all"),
    })

    with pytest.raises(GitHubUnavailable, match="could not be read"):
        client.archive_files("example-org", "example-tools", "main", {"README.md"})


def test_an_archive_entry_that_is_not_text_is_skipped_with_a_message():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("example-org-example-tools-abc/README.md")
        data = b"\xff\xfe\x00binary"
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    lines = []
    session = FakeGitHubSession({
        f"{API_ROOT}/repos/example-org/example-tools/tarball/main":
            FakeApiResponse(status_code=200, content=buffer.getvalue()),
    })
    client = GitHubClient(session, progress=lines.append)

    assert client.archive_files("example-org", "example-tools", "main", {"README.md"}) == {}
    assert any("not text" in line for line in lines)
