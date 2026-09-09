"""
Summary: The GitHub REST transport the API source reads through: the
access token (from the environment only), paginated listings, repository
metadata and Git trees, file bodies by blob SHA, and one repository
archive read in memory. Rate-limit headers are obeyed, and every failure
is raised as one of two kinds -- something the build can work around by
reading GitHub another way, or something only the operator can fix. See
docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/sources/github_client.py

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

import collections
import io
import os
import re
import tarfile
import time

import requests

from extractium.core import cache as caching
from extractium.core.fetch import DEFAULT_USER_AGENT, REQUEST_TIMEOUT_SECONDS

### Constants ###

# Where the REST API lives. Overridable per client so a test never has to
# monkeypatch a module constant, and so a GitHub Enterprise host could be
# pointed at later without touching this file.
API_ROOT = "https://api.github.com"

# The API version header GitHub asks callers to pin, so a future default
# change on their side cannot alter what this code receives.
API_VERSION = "2022-11-28"

# Listings come back one page at a time; 100 is the largest page GitHub
# serves, and asking for it turns four requests into one.
PAGE_SIZE = 100

# A hard stop on paging. An owner with more repositories than this is far
# outside what one knowledge base should hold, and a listing that never
# ends would otherwise loop until the rate limit stopped it.
MAX_PAGES = 100

# The environment variable the token is read from. It is never read from
# the configuration file: a configuration file is committed to a
# repository, and a token in one is a token that has been published.
TOKEN_ENVIRONMENT_VARIABLE = "GITHUB_TOKEN"

# A ceiling on folder-by-folder requests when a recursive tree came back
# truncated. Real repositories finish long before this; the ceiling exists
# so a response describing a folder as its own child cannot spin forever.
MAX_SUBTREE_REQUESTS = 2000

# Longest this client will sit and wait for a rate-limit window to reopen.
# Past this, moving down to another way of reading GitHub beats blocking a
# build for the better part of an hour.
MAX_RATE_LIMIT_WAIT_SECONDS = 60

# Requests kept in reserve. Repository work is planned against the
# remaining budget minus this, so a run does not spend its last request on
# a listing and then fail partway through a repository.
RATE_LIMIT_RESERVE = 5

# Largest repository archive this client will pull into memory, in bytes.
# Archives are read as a stream and never written to disk, so the ceiling
# is what keeps a very large repository from exhausting memory.
MAX_ARCHIVE_BYTES = 80_000_000

# Read the archive stream in blocks rather than all at once, so the
# ceiling above is enforced while the download is happening.
ARCHIVE_CHUNK_BYTES = 262_144

# Statuses that mean the credential in use was not accepted.
REFUSED_STATUS_CODES = (401,)

# Statuses that mean the request was throttled rather than wrong.
THROTTLED_STATUS_CODES = (403, 429)

# A GitHub owner or repository name, checked before it is placed in a
# request path. Names arrive from configuration and from API responses,
# both of which are untrusted input; an unchecked name could otherwise
# reach a different endpoint than the one intended.
NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,99})$")


### Errors ###

class GitHubError(Exception):
    """Base class for every failure this client reports."""


class GitHubUnavailable(GitHubError):
    """
    GitHub could not be read this way, but might be readable another way:
    the host is unreachable, the service is failing, or the request budget
    is spent. The build responds by trying the next way of reading GitHub,
    not by stopping.
    """


class GitHubRefused(GitHubUnavailable):
    """
    The credential in use was rejected. A bad token is an operator
    mistake, not a reason to lose a build, so this drops to reading GitHub
    without a token -- but it is always reported, because a token that was
    silently ignored looks exactly like a token that worked.
    """


class GitHubNotFound(GitHubError):
    """
    GitHub says the account or repository does not exist. This is the
    operator asking for the wrong thing, so it stops the source instead of
    being worked around: quietly falling back turns a typo into a strange,
    empty result.
    """


### Rate Limit ###

class RateLimit:
    """
    What the last response said about the remaining request budget.

    Attributes:
        limit (int | None): requests allowed in the current window.
        remaining (int | None): requests left in it.
        reset_at (float | None): when the window reopens, as a Unix time.
        retry_after (float | None): the wait GitHub asked for outright.
    """

    def __init__(self):
        self.limit = None
        self.remaining = None
        self.reset_at = None
        self.retry_after = None

    def update(self, headers):
        """Reads the rate-limit headers of one response. Unparsable values are ignored."""
        self.limit = _as_number(headers.get("X-RateLimit-Limit"))
        self.remaining = _as_number(headers.get("X-RateLimit-Remaining"))
        self.reset_at = _as_number(headers.get("X-RateLimit-Reset"))
        self.retry_after = _as_number(headers.get("Retry-After"))

    @property
    def budget(self):
        """
        Requests that may still be spent, keeping a small reserve back.
        None when GitHub has not said, which means "do not plan on a
        number" rather than "unlimited".
        """
        if self.remaining is None:
            return None
        return max(0, self.remaining - RATE_LIMIT_RESERVE)

    def wait_seconds(self, now=None):
        """
        How long to wait before the next request, in seconds.

        A Retry-After wins outright, because GitHub sent it deliberately.
        Otherwise a window with nothing left in it is waited out until it
        resets. Anything else waits not at all.
        """
        now = time.time() if now is None else now
        if self.retry_after is not None:
            return max(0.0, float(self.retry_after))
        if self.remaining == 0 and self.reset_at is not None:
            return max(0.0, float(self.reset_at) - now)
        return 0.0


def _as_number(value):
    """A header value as a float, or None when it is absent or not a number."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


### Client ###

class GitHubClient:
    """
    Reads GitHub through its REST API.

    The session, the progress callback, and the token all come from the
    caller, so a library user, a test, and a person at a terminal each
    control them. The client never prints and never constructs a session.

    Args:
        session: the HTTP session to request through (requests.Session or
            a test double with the same get() signature).
        token (str | None): the access token to send, or None to read
            GitHub anonymously. Read from the environment by the caller;
            see token_from_environment.
        user_agent (str): how the build introduces itself.
        progress (Callable[[str], None] | None): receives one line per
            event worth reporting. Never receives the token.
        api_root (str): the API base address.

    Attributes:
        rate_limit (RateLimit): what the last response said about the
            remaining budget.
    """

    def __init__(self, session, token=None, user_agent=DEFAULT_USER_AGENT,
                 progress=None, api_root=API_ROOT):
        self.session = session
        self._token = token or None
        self.user_agent = user_agent
        self.progress = progress
        self.api_root = api_root.rstrip("/")
        self.rate_limit = RateLimit()
        self.request_count = 0

    @property
    def authenticated(self):
        """True when a token is being sent. The token itself is never exposed."""
        return self._token is not None

    ### Requests ###

    def _headers(self, accept="application/vnd.github+json"):
        """
        The headers one API request sends.

        The token travels here and nowhere else: not in a URL, not in a
        log line, not in a cache file, and not in anything this build
        writes out.
        """
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": self.user_agent,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _report(self, line):
        """Sends one line to the progress callback, when there is one."""
        if self.progress is not None:
            self.progress(line)

    def _wait_for_budget(self):
        """
        Pauses when GitHub has asked for one, and gives up when the wait
        is longer than a build should sit still for.

        Raises:
            GitHubUnavailable: when the window will not reopen soon
                enough. Moving to another way of reading GitHub beats
                blocking a build for the better part of an hour.
        """
        wait = self.rate_limit.wait_seconds()
        if wait <= 0:
            return
        if wait > MAX_RATE_LIMIT_WAIT_SECONDS:
            raise GitHubUnavailable(
                f"the GitHub request budget is spent and does not reset for "
                f"{int(wait / 60)} minute(s)."
            )
        self._report(f"  waiting {int(wait)}s for the GitHub request budget to reset")
        time.sleep(wait)

    def _get(self, url, accept="application/vnd.github+json", params=None, stream=False):
        """
        Makes one API request and classifies the answer.

        Returns:
            requests.Response: a successful response.

        Raises:
            GitHubNotFound: the account or repository does not exist.
            GitHubRefused: the credential was rejected.
            GitHubUnavailable: the request was throttled, the service
                failed, or the host could not be reached.
        """
        self._wait_for_budget()
        try:
            response = self.session.get(
                url,
                headers=self._headers(accept),
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
                stream=stream,
            )
        except requests.RequestException as e:
            # The message names the address, never the headers: an
            # exception string can end up in a log, and the headers hold
            # the token.
            raise GitHubUnavailable(f"GitHub could not be reached at {url} ({e}).") from e

        self.request_count += 1
        self.rate_limit.update(response.headers)
        status = response.status_code

        if status == 404:
            raise GitHubNotFound(f"GitHub has nothing at {url}.")
        if status in REFUSED_STATUS_CODES:
            raise GitHubRefused("GitHub refused the access token supplied in GITHUB_TOKEN.")
        if status in THROTTLED_STATUS_CODES:
            raise GitHubUnavailable(self._throttle_message(status))
        if status >= 400:
            raise GitHubUnavailable(f"GitHub answered {status} for {url}.")
        return response

    def _throttle_message(self, status):
        """Why a 403 or 429 happened, in words an operator can act on."""
        if self.rate_limit.remaining == 0 and not self.authenticated:
            return (
                "the anonymous GitHub request budget is spent. Setting GITHUB_TOKEN "
                "raises it considerably."
            )
        if self.rate_limit.remaining == 0:
            return "the GitHub request budget is spent."
        return f"GitHub answered {status}; the request was refused or throttled."

    def get_json(self, path, params=None):
        """
        Reads one JSON document from the API.

        Args:
            path (str): a path under the API root, starting with a slash.
            params (Mapping | None): query parameters.

        Returns:
            dict | list: the decoded document.

        Raises:
            GitHubUnavailable: if the answer is not usable JSON.
        """
        response = self._get(self.api_root + path, params=params)
        try:
            return response.json()
        except ValueError as e:
            raise GitHubUnavailable(f"GitHub sent something that is not JSON for {path} ({e}).") from e

    def paginate(self, path, params=None):
        """
        Reads every page of a listing.

        Args:
            path (str): a listing path under the API root.
            params (Mapping | None): query parameters; the page size is
                filled in.

        Yields:
            dict: each item, in the order GitHub returned it.

        Raises:
            GitHubUnavailable: if a page is not a list, which means the
                endpoint answered something other than a listing.
        """
        query = dict(params or {})
        query["per_page"] = PAGE_SIZE
        for page in range(1, MAX_PAGES + 1):
            query["page"] = page
            items = self.get_json(path, params=query)
            if not isinstance(items, list):
                raise GitHubUnavailable(f"GitHub answered {path} with something other than a list.")
            yield from items
            if len(items) < PAGE_SIZE:
                return
        self._report(f"  stopped listing {path} after {MAX_PAGES} pages")

    ### Accounts And Repositories ###

    def account(self, name):
        """
        Reads one account, so its kind is known rather than guessed.

        Args:
            name (str): the account name.

        Returns:
            dict: the account, including its "type" ("Organization" or
            "User").

        Raises:
            ValueError: if name is not shaped like an account name.
            GitHubNotFound: if no such account exists.
        """
        return self.get_json(f"/users/{_checked(name, 'account name')}")

    def repositories_for(self, name, kind):
        """
        Lists an account's public repositories.

        Args:
            name (str): the account name.
            kind (str): "Organization" or "User", as the account reported.

        Yields:
            dict: one repository record each.
        """
        checked = _checked(name, "account name")
        path = f"/orgs/{checked}/repos" if kind == "Organization" else f"/users/{checked}/repos"
        yield from self.paginate(path, params={"type": "public", "sort": "full_name"})

    def repository(self, owner, name):
        """
        Reads one repository's metadata.

        Raises:
            GitHubNotFound: if no such repository exists.
        """
        owner = _checked(owner, "owner name")
        name = _checked(name, "repository name")
        return self.get_json(f"/repos/{owner}/{name}")

    ### Trees And Files ###

    def tree(self, owner, name, ref):
        """
        Takes a complete inventory of one repository, at one commit or
        branch, before a single file body is downloaded.

        GitHub caps a recursive tree and marks the answer truncated when
        it does. A truncated tree treated as complete produces a
        repository that looks fully indexed and is not, which is the worst
        failure available here because it is invisible. So the subtrees
        are walked until the inventory is whole.

        Args:
            owner (str): the account that owns the repository.
            name (str): the repository name.
            ref (str): the branch, tag, or commit to read.

        Returns:
            list[dict]: every blob in the repository, each with "path",
            "sha", and usually "size". Directories are not returned; they
            are only walked.
        """
        owner = _checked(owner, "owner name")
        name = _checked(name, "repository name")
        root = self.get_json(f"/repos/{owner}/{name}/git/trees/{_checked_ref(ref)}",
                             params={"recursive": "1"})
        entries = [e for e in root.get("tree", []) if e.get("type") == "blob"]
        if not root.get("truncated"):
            return entries

        self._report(f"  {owner}/{name}: the file list was cut short; walking it folder by folder")
        return self._walk_subtrees(owner, name, root, entries)

    def _walk_subtrees(self, owner, name, root, entries):
        """
        Completes a truncated inventory by requesting each folder in turn.

        Folders are read breadth first and keyed by their own path, not by
        their tree object: two folders can hold identical content and so
        share one object name, and skipping the second would lose every
        file in it. A path cannot repeat, so an ordinary repository
        finishes; a request ceiling covers the pathological case of a
        folder that reports itself as its own child.
        """
        found = {entry["path"]: entry for entry in entries}
        pending = collections.deque(
            (e["path"], e["sha"]) for e in root.get("tree", []) if e.get("type") == "tree"
        )
        seen_paths = {path for path, _ in pending}
        requests_made = 0

        while pending:
            if requests_made >= MAX_SUBTREE_REQUESTS:
                self._report(
                    f"  {owner}/{name}: stopped listing folders after "
                    f"{MAX_SUBTREE_REQUESTS} requests; the file list may be incomplete"
                )
                break
            prefix, sha = pending.popleft()
            requests_made += 1
            try:
                subtree = self.get_json(f"/repos/{owner}/{name}/git/trees/{sha}")
            except GitHubNotFound:
                self._report(f"  {owner}/{name}: the folder {prefix} could not be read; skipped")
                continue
            for entry in subtree.get("tree", []):
                path = f"{prefix}/{entry.get('path', '')}"
                if entry.get("type") == "blob":
                    found[path] = {**entry, "path": path}
                elif entry.get("type") == "tree" and path not in seen_paths:
                    seen_paths.add(path)
                    pending.append((path, entry["sha"]))
        return [found[path] for path in sorted(found)]

    def blob_text(self, owner, name, blob_sha):
        """
        Reads one file body, through the blob cache.

        The blob SHA is the cache key: the same SHA means the same bytes,
        whatever branch or path points at it, so a file that appears in
        several repositories is downloaded once.

        Args:
            owner (str): the account that owns the repository.
            name (str): the repository name.
            blob_sha (str): the file's Git object name.

        Returns:
            str: the file's text.

        Raises:
            ValueError: if blob_sha is not a Git object name.
            GitHubNotFound: if the blob has vanished since the inventory.
            GitHubUnavailable: for a throttled or failed request.
        """
        cached = caching.load_github_blob(blob_sha)
        if cached is not None:
            return cached
        owner = _checked(owner, "owner name")
        name = _checked(name, "repository name")
        response = self._get(
            f"{self.api_root}/repos/{owner}/{name}/git/blobs/{blob_sha}",
            accept="application/vnd.github.raw",
        )
        text = response.text
        caching.save_github_blob(blob_sha, text)
        return text

    def archive_files(self, owner, name, ref, wanted_paths):
        """
        Reads several files from one repository in a single download.

        The archive is streamed into memory and read there. Nothing is
        extracted to disk, so no path inside the archive can be used to
        write anywhere: archive paths are compared against the wanted set
        and never joined onto a real directory. Only regular files are
        read, so a symbolic link or a device entry inside the archive is
        ignored rather than followed.

        Args:
            owner (str): the account that owns the repository.
            name (str): the repository name.
            ref (str): the branch, tag, or commit to download.
            wanted_paths (Iterable[str]): repository-relative paths to
                read. Anything else in the archive is discarded.

        Returns:
            dict[str, str]: path to text, for every wanted file that was
            present and could be decoded as text.

        Raises:
            GitHubUnavailable: if the archive is too large to read in
                memory, cannot be downloaded, or is not a readable
                archive.
        """
        owner = _checked(owner, "owner name")
        name = _checked(name, "repository name")
        wanted = set(wanted_paths)
        response = self._get(
            f"{self.api_root}/repos/{owner}/{name}/tarball/{_checked_ref(ref)}",
            accept="application/vnd.github+json",
            stream=True,
        )
        payload = _read_capped(response, MAX_ARCHIVE_BYTES)
        return _files_from_archive(payload, wanted, self._report)


### Archive Reading ###

def _read_capped(response, ceiling):
    """
    Reads a streamed response into memory, stopping at a ceiling.

    Raises:
        GitHubUnavailable: if the download passes the ceiling, or the
            stream breaks partway through.
    """
    buffer = io.BytesIO()
    total = 0
    try:
        for block in response.iter_content(chunk_size=ARCHIVE_CHUNK_BYTES):
            if not block:
                continue
            total += len(block)
            if total > ceiling:
                raise GitHubUnavailable(
                    f"the repository archive is larger than {ceiling} bytes; "
                    "its files will be requested one at a time instead."
                )
            buffer.write(block)
    except requests.RequestException as e:
        raise GitHubUnavailable(f"the repository archive download failed ({e}).") from e
    return buffer.getvalue()


def _files_from_archive(payload, wanted, report):
    """
    Pulls the wanted files out of an in-memory archive.

    GitHub wraps every archive in one top-level folder named after the
    repository and commit, so the first path segment is dropped to get
    repository-relative paths back.
    """
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                _, _, path = member.name.partition("/")
                if path not in wanted:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                try:
                    files[path] = extracted.read().decode("utf-8")
                except UnicodeDecodeError:
                    report(f"  {path}: not text; skipped")
    except tarfile.TarError as e:
        raise GitHubUnavailable(f"the repository archive could not be read ({e}).") from e
    return files


### Names And Tokens ###

def _checked(name, label):
    """
    Returns name when it is a GitHub name, and refuses it otherwise.

    Names reach this module from a configuration file and from API
    responses, both untrusted. A name holding a slash or a dot-dot segment
    placed into a request path would address a different endpoint than the
    one intended.

    Raises:
        ValueError: if name is not shaped like a GitHub name.
    """
    if not isinstance(name, str) or not NAME_RE.match(name) or name in (".", ".."):
        raise ValueError(f"{label} must be a GitHub name; got {name!r}.")
    return name


def _checked_ref(ref):
    """
    Returns a branch, tag, or commit name safe to place in a request path.

    Raises:
        ValueError: if ref is empty, or holds a character that would
            change which endpoint the request reaches.
    """
    if not isinstance(ref, str) or not ref or ref.startswith("/"):
        raise ValueError(f"a branch or commit name must be text; got {ref!r}.")
    if any(character in ref for character in ("..", "?", "#", " ", "\\")):
        raise ValueError(f"a branch or commit name cannot contain {ref!r}.")
    return ref


def token_from_environment(environment=None):
    """
    Reads the access token, from the environment and nowhere else.

    A configuration file is committed to a repository, and a token written
    in one is a token that has been published. So the token is only ever
    read from the process environment.

    Args:
        environment (Mapping | None): the environment to read; None reads
            the process environment.

    Returns:
        str | None: the token, or None when the variable is unset or
        blank.
    """
    environment = os.environ if environment is None else environment
    token = (environment.get(TOKEN_ENVIRONMENT_VARIABLE) or "").strip()
    return token or None
