"""
Summary: The GitHub API source: reads an organization, a user, or one
repository through GitHub's REST API instead of scraping rendered web
pages, and keeps working when there is no token and when there is no API
at all. Three ways of reading GitHub are tried in order -- with a token,
without one, and finally a documentation-only web crawl -- and what each
repository actually got is reported rather than left for the reader to
discover. See docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/sources/github_api.py

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

import re

from extractium.core import cache as caching
from extractium.core.fetch import DEFAULT_USER_AGENT, normalise
from extractium.core.models import Document
from extractium.sources import github_files as files
from extractium.sources.github_client import (
    GitHubClient,
    GitHubNotFound,
    GitHubRefused,
    GitHubUnavailable,
    token_from_environment,
)

### Constants ###

# The three ways of reading GitHub, in the order they are tried. A token
# buys request capacity, not capability: anything that can be indexed with
# one can be indexed without one, so tier 2 is not a reduced mode. Tier 3
# is different in kind, and says so.
TIER_AUTHENTICATED = 1
TIER_PUBLIC = 2
TIER_CRAWL = 3

TIER_NAMES = {
    TIER_AUTHENTICATED: "tier 1 (authenticated API)",
    TIER_PUBLIC: "tier 2 (public API)",
    TIER_CRAWL: "tier 3 (documentation crawl)",
}

TIER_COVERAGE = {
    TIER_AUTHENTICATED: "documentation, code analysis",
    TIER_PUBLIC: "documentation, code analysis",
    TIER_CRAWL: "documentation only; no code analysis",
}

# Where a repository's files live, and the address a reader can open.
GITHUB_WEB_ROOT = "https://github.com"

# An owner or repository address on GitHub, as an operator would paste it.
OWNER_URL_RE = re.compile(r"^https?://(?:www\.)?github\.com/([^/?#]+)(?:/([^/?#]+))?", re.I)

# One archive is the default way of reading a repository's files, because
# the scarce resource is requests rather than bytes. Reading anonymously
# allows roughly sixty requests an hour for the whole build, so a single
# documentation-heavy repository can spend the lot one file at a time,
# while the same content arrives in one request as an archive.
#
# Repository sizes GitHub reports are in kibibytes. Above this ceiling the
# archive is not worth holding in memory, and the files are requested
# individually instead.
MAX_ARCHIVE_REPOSITORY_KIB = 60_000


class GitHubSourceError(Exception):
    """
    Raised when the operator asked for something GitHub does not have, or
    for a combination the source cannot act on. These stop the source
    rather than moving it down a tier: quietly demoting a misspelled
    organization name turns a typo into a strange, empty result.
    """


### Source ###

class GitHubApiSource:
    """
    Reads documentation out of an account's repositories, or one
    repository, through the GitHub API.

    The source takes the HTTP session, the fetch cache, and the progress
    callback from the caller, and reads its access token from the
    environment. It never constructs a session and never prints.

    Args:
        options (Mapping): the validated options of a `github_api` entry:
            exactly one of org, user, or url; include_repos,
            exclude_repos, include_forks, include_archived, include_code,
            and max_file_bytes.

    Attributes:
        coverage (dict[str, int]): repository full name to the tier that
            read it, in the order they were read.
        acquired (set[str]): every URL already turned into a document, so
            a fall back to crawling neither loses a repository nor fetches
            one twice.
        mapped (set[str]): repositories that already have a summary
            record, so a repository finished at a lower tier gets one
            summary rather than two.
    """

    name = "github_api"

    def __init__(self, options):
        self.options = options
        self.owner, self.repository = _target_from(options)
        self.include_repos = tuple(options.get("include_repos") or ())
        self.exclude_repos = tuple(options.get("exclude_repos") or ())
        self.include_forks = bool(options.get("include_forks", False))
        self.include_archived = bool(options.get("include_archived", True))
        self.max_file_bytes = int(options.get("max_file_bytes") or 2_000_000)
        self.registry = None
        self.settings = None
        self.coverage = {}
        self.acquired = set()
        self.mapped = set()

    def configure(self, registry, settings):
        """
        Adopts the plugin registry and the build's global crawl settings.

        Both are needed for the last way of reading GitHub, which is an
        ordinary web crawl and therefore needs the same settings every
        other crawl in the build runs under.

        Args:
            registry (extractium.core.registry.Registry): where plugin
                classes are looked up.
            settings (extractium.sources.web.CrawlSettings): the page
                ceiling, the delay, the User-Agent, robots.txt handling,
                and the allowed GitHub accounts.
        """
        self.registry = registry
        self.settings = settings

    ### Reading ###

    def fetch(self, session, cache, progress):
        """
        Reads the configured account or repository, and yields a Document
        for every file worth indexing.

        Three ways of reading GitHub are tried in order, and the first
        that works is used. A way is abandoned only when it cannot
        proceed: an unreachable host, a refused credential, or a spent
        request budget. A misspelled account name is not one of those, and
        stops the source instead.

        Args:
            session: HTTP session to request through.
            cache (dict): the fetch cache metadata, used by the crawl this
                falls back to.
            progress (Callable[[str], None]): receives one line per event.

        Yields:
            extractium.core.models.Document: one per indexed file, plus
            one summary per repository.

        Raises:
            GitHubSourceError: if the account or repository does not
                exist, or none of the three ways of reading it produced
                anything.
        """
        progress(f"GitHub:       {self.target_description}")
        for tier, token in self._api_tiers():
            client = GitHubClient(
                session, token=token, user_agent=self._user_agent(), progress=progress,
            )
            progress(f"  reading through the {TIER_NAMES[tier]}")
            try:
                yield from self._read_through_api(client, tier, progress)
                return
            except GitHubRefused as e:
                progress(f"  {e} Reading GitHub without a token instead.")
            except GitHubUnavailable as e:
                progress(f"  {e}")

        yield from self._read_through_crawl(session, cache, progress)

    def _api_tiers(self):
        """
        The API tiers to try, in order, each with the token it uses.

        A build with no token starts at tier 2 rather than pretending to
        try tier 1, so the report says what actually happened.
        """
        token = token_from_environment()
        tiers = []
        if token:
            tiers.append((TIER_AUTHENTICATED, token))
        tiers.append((TIER_PUBLIC, None))
        return tiers

    def _read_through_api(self, client, tier, progress):
        """
        Reads every selected repository through one API tier.

        Repositories already read at an earlier tier are skipped, so a run
        that failed partway through does not fetch the same repository
        twice when it tries again lower down.
        """
        for repository in self._selected_repositories(client, progress):
            full_name = repository.get("full_name") or f"{self.owner}/{repository.get('name')}"
            if full_name in self.coverage:
                continue
            try:
                yield from self._read_repository(client, repository, tier, progress)
            except GitHubNotFound as e:
                # One repository disappearing between the listing and the
                # read must not destroy an organization-wide build.
                progress(f"  {full_name}: skipped ({e})")
            self.coverage[full_name] = tier

    def _selected_repositories(self, client, progress):
        """
        The repositories to read, after the operator's filters.

        Raises:
            GitHubSourceError: if the account or repository does not
                exist. That is the operator asking for the wrong thing.
        """
        try:
            if self.repository:
                return [client.repository(self.owner, self.repository)]
            account = client.account(self.owner)
            listed = client.repositories_for(self.owner, account.get("type"))
            return [r for r in listed if self._wanted(r, progress)]
        except GitHubNotFound as e:
            raise GitHubSourceError(
                f"GitHub has no {self.target_description}. Check the spelling. ({e})"
            ) from e
        except ValueError as e:
            raise GitHubSourceError(str(e)) from e

    def _wanted(self, repository, progress):
        """
        Whether one listed repository is read, and why not when it is not.

        Every exclusion is reported. A repository silently missing from an
        index is indistinguishable from one that was never there.
        """
        name = repository.get("name") or ""
        if self.include_repos and name not in self.include_repos:
            return False
        if name in self.exclude_repos:
            progress(f"  {name}: skipped (excluded by exclude_repos)")
            return False
        if repository.get("private"):
            # A token can read private repositories; this source never
            # publishes them. See docs/github-repository-indexing.md.
            progress(f"  {name}: skipped (private)")
            return False
        if repository.get("fork") and not self.include_forks:
            progress(f"  {name}: skipped (a fork; set include_forks to read it)")
            return False
        if repository.get("archived") and not self.include_archived:
            progress(f"  {name}: skipped (archived)")
            return False
        if repository.get("disabled"):
            progress(f"  {name}: skipped (disabled by GitHub)")
            return False
        if repository.get("size") == 0:
            progress(f"  {name}: skipped (empty)")
            return False
        return True

    def _read_repository(self, client, repository, tier, progress):
        """
        Reads one repository: its inventory, then the files worth indexing,
        then a summary record naming how completely it was read.
        """
        owner = (repository.get("owner") or {}).get("login") or self.owner
        name = repository.get("name") or ""
        full_name = repository.get("full_name") or f"{owner}/{name}"
        branch = repository.get("default_branch") or "main"
        # The owner comes back in an API response, which is untrusted like
        # any other. A repository reporting a different owner is not read:
        # this source reads the account the operator named, and nothing it
        # is merely pointed at.
        if not self._may_read(owner):
            progress(f"  {full_name}: skipped; add {owner} to github_owners to read it")
            return
        progress(f"  {full_name}: taking inventory")

        entries = client.tree(owner, name, branch)
        wanted = self._files_to_read(full_name, entries, progress)
        # A repository the previous tier had already started is finished
        # rather than read again. Two documents for one file would be two
        # copies of the same text in the index.
        wanted = {
            path: entry for path, entry in wanted.items()
            if normalise(self._url_for(owner, name, branch, path)) not in self.acquired
        }
        bodies = self._download(client, owner, name, branch, repository, wanted, progress)

        indexed = 0
        for path in wanted:
            text = bodies.get(path)
            if text is None:
                continue
            document = self._document_for(owner, name, branch, path, text)
            if document is None:
                progress(f"  {full_name}/{path}: skipped (no readable text)")
                continue
            self.acquired.add(normalise(document.url))
            indexed += 1
            yield document

        progress(f"  {full_name}: indexed {indexed} file(s) of {len(entries)}")
        if full_name not in self.mapped:
            self.mapped.add(full_name)
            yield self._repository_map(repository, full_name, owner, name, branch, indexed, tier)

    def _files_to_read(self, full_name, entries, progress):
        """
        The files worth downloading, chosen from the inventory alone.

        A file left out for its size is always named. An index quietly
        missing a project's largest documentation file is worse than one
        that says it skipped it.
        """
        wanted = {}
        for entry in entries:
            path = entry.get("path") or ""
            if files.classify(path) is None:
                continue
            size = entry.get("size")
            if size is not None and size > self.max_file_bytes:
                progress(
                    f"  {full_name}/{path}: skipped ({size} bytes is over the "
                    f"{self.max_file_bytes} byte ceiling)"
                )
                continue
            if entry.get("sha"):
                wanted[path] = entry
        return wanted

    def _download(self, client, owner, name, branch, repository, wanted, progress):
        """
        Reads the wanted file bodies, from one archive where it can.

        Requests are the scarce resource, not bytes: an anonymous build
        gets roughly sixty requests an hour in total, and one archive
        spends one of them however many files come out of it. So an
        archive is the default, and files are requested one at a time only
        when the repository is too large to hold in memory or the archive
        could not be read. When neither route is possible the repository
        is reported and skipped, rather than guessing and doing the
        expensive thing anyway.
        """
        if not wanted:
            return {}
        full_name = f"{owner}/{name}"
        size_kib = repository.get("size") or 0

        # Whatever a previous build already read costs nothing to read
        # again, and is taken out of the plan before a route is chosen. A
        # repository nobody has changed therefore needs no download at all.
        bodies, outstanding = self._from_cache(wanted)
        if not outstanding:
            progress(f"  {full_name}: every file unchanged since the last build")
            return bodies

        if size_kib <= MAX_ARCHIVE_REPOSITORY_KIB:
            progress(f"  {full_name}: reading {len(outstanding)} file(s) from one archive")
            try:
                fetched = client.archive_files(owner, name, branch, outstanding)
                self._cache(outstanding, fetched)
                return {**bodies, **fetched}
            except (GitHubUnavailable, GitHubNotFound) as e:
                # An archive that cannot be read is not the end of the
                # repository; its files can still be asked for one by one.
                progress(f"  {full_name}: {e} Requesting its files one at a time.")
        else:
            progress(
                f"  {full_name}: too large to read as one archive ({size_kib} KiB); "
                f"requesting its {len(outstanding)} file(s) one at a time"
            )

        budget = client.rate_limit.budget
        if budget is not None and budget < len(outstanding):
            progress(
                f"  {full_name}: skipped; reading its {len(outstanding)} files needs more "
                f"requests than are left. Setting GITHUB_TOKEN raises the budget."
            )
            return bodies

        for path, entry in outstanding.items():
            try:
                bodies[path] = client.blob_text(owner, name, entry["sha"])
            except GitHubNotFound:
                progress(f"  {full_name}/{path}: skipped (no longer in the repository)")
            except ValueError as e:
                progress(f"  {full_name}/{path}: skipped ({e})")
        return bodies

    def _from_cache(self, wanted):
        """
        Splits the wanted files into what is already on disk and what
        still has to be downloaded.

        Returns:
            tuple[dict, dict]: path to text for the files the blob cache
            already holds, and path to inventory entry for the rest.
        """
        bodies = {}
        outstanding = {}
        for path, entry in wanted.items():
            cached = _cached_body(entry.get("sha"))
            if cached is None:
                outstanding[path] = entry
            else:
                bodies[path] = cached
        return bodies, outstanding

    def _cache(self, wanted, fetched):
        """
        Stores file bodies read from an archive under their blob names, so
        the next build reads them from disk.

        Keyed the same way single-file downloads are keyed, so the two
        routes fill and read one cache rather than two.
        """
        for path, text in fetched.items():
            sha = (wanted.get(path) or {}).get("sha")
            if sha:
                try:
                    caching.save_github_blob(sha, text)
                except (OSError, ValueError):
                    # A cache that cannot be written costs a slower next
                    # build. It must never cost this one its content.
                    pass

    def _url_for(self, owner, name, branch, path):
        """
        The address a reader can open for one repository file.

        This is the same address the crawler would visit for that file, so
        one ledger covers both ways of reading GitHub: a file already read
        through the API is recognised when a crawl reaches it.
        """
        return f"{GITHUB_WEB_ROOT}/{owner}/{name}/blob/{branch}/{path}"

    def _document_for(self, owner, name, branch, path, text):
        """One indexed repository file, or None when it holds no text."""
        if not text or not text.strip():
            return None
        full_name = f"{owner}/{name}"
        return Document(
            url=self._url_for(owner, name, branch, path),
            title=files.title_for(full_name, path),
            content=text,
            source_type="github",
            content_type=files.content_type_for(path),
            categories=files.categories_for(owner, name, path),
        )

    def _repository_map(self, repository, full_name, owner, name, branch, indexed, tier):
        """
        The per-repository summary document.

        It records how completely the repository could be read, so someone
        searching the finished index sees the gap without going back to
        the build log. A gap the reader cannot see is a gap that will be
        mistaken for an answer.
        """
        licence = (repository.get("license") or {}).get("name") or "not stated"
        topics = ", ".join(repository.get("topics") or ()) or "none listed"
        lines = [
            f"Repository {full_name} on GitHub.",
            "",
            f"Description: {repository.get('description') or 'none given'}",
            f"Main language: {repository.get('language') or 'not stated'}",
            f"Licence: {licence}",
            f"Topics: {topics}",
            f"Default branch: {branch}",
            f"Last updated: {repository.get('updated_at') or 'not stated'}",
            f"Archived: {'yes' if repository.get('archived') else 'no'}",
            "",
            f"Read through the {TIER_NAMES[tier]}.",
            f"Coverage: {TIER_COVERAGE[tier]}.",
            f"Documentation files indexed: {indexed}.",
        ]
        return Document(
            url=f"{GITHUB_WEB_ROOT}/{owner}/{name}",
            title=f"{full_name}: repository summary",
            content="\n".join(lines),
            source_type="github",
            content_type="repo_map",
            categories=(owner, name),
        )

    ### Falling Back To A Crawl ###

    def _read_through_crawl(self, session, cache, progress):
        """
        Reads whatever documentation an ordinary web crawl can reach.

        This is documentation only. GitHub's file viewer builds its
        content in the browser, so scraping a source file yields markup
        rather than source, and a parse of that would be worse than no
        parse at all. Nothing here analyses code.

        The requested scope survives: a request for one repository crawls
        that repository and does not widen to the owner's other work. What
        the API already read is not fetched again.
        """
        if self.registry is None:
            raise GitHubSourceError(
                f"GitHub could not be read for {self.target_description}, and no "
                "plugin registry was supplied to fall back to a documentation crawl."
            )
        from extractium.sources.web import WebSource, resolve_site_handlers

        progress(f"  falling back to the {TIER_NAMES[TIER_CRAWL]}; no code analysis")
        options = {
            "seed_url": self.seed_url,
            "include_patterns": self._crawl_include_patterns(),
            "crawl_exclude_patterns": None,
            "index_exclude_patterns": None,
            "site_handlers": None,
            "already_indexed": set(self.acquired),
            "promote": False,
        }
        handlers = resolve_site_handlers(self.registry, None, self.settings)
        source = WebSource(options, handlers, self.settings)
        for document in source.fetch(session, cache, progress):
            self.acquired.add(normalise(document.url))
            self._record_crawled(document.url)
            yield document

    def _crawl_include_patterns(self):
        """
        The scope the fallback crawl keeps to.

        Written from what the operator asked for, not from the seed's
        origin: every account on github.com shares that origin, so an
        origin-wide crawl of an owner request would wander into other
        people's repositories.
        """
        owner = re.escape(self.owner)
        if self.repository:
            repository = re.escape(self.repository)
            return (
                rf"^https://github\.com/{owner}/{repository}(?:/|$)",
                rf"^https://raw\.githubusercontent\.com/{owner}/{repository}/",
            )
        return (
            rf"^https://github\.com/{owner}(?:/|$)",
            rf"^https://raw\.githubusercontent\.com/{owner}/",
        )

    def _record_crawled(self, url):
        """Notes which repository a crawled page belonged to, for the coverage report."""
        match = OWNER_URL_RE.match(url)
        if match and match.group(2):
            self.coverage.setdefault(f"{match.group(1)}/{match.group(2)}", TIER_CRAWL)

    ### Reporting ###

    def _may_read(self, owner):
        """
        Whether this source may read an account.

        The account it was pointed at is always readable. Any other is
        readable only when the operator listed it, which is the same rule
        the crawler follows.
        """
        if owner.lower() == self.owner.lower():
            return True
        allowed = getattr(self.settings, "github_owners", ()) or ()
        return owner.lower() in {account.lower() for account in allowed}

    def _user_agent(self):
        """How this source introduces itself: the build's identity, or the default."""
        return self.settings.user_agent if self.settings else DEFAULT_USER_AGENT

    @property
    def target_description(self):
        """What this source was asked to read, in words."""
        if self.repository:
            return f"repository {self.owner}/{self.repository}"
        return f"account {self.owner}"

    @property
    def seed_url(self):
        """The address a crawl of this source's target starts from."""
        if self.repository:
            return f"{GITHUB_WEB_ROOT}/{self.owner}/{self.repository}"
        return f"{GITHUB_WEB_ROOT}/{self.owner}"

    def summary_lines(self):
        """
        One line per repository, naming the tier that read it and what is
        therefore missing from the index.

        Returns:
            list[str]: the coverage report, empty when nothing was read.
        """
        if not self.coverage:
            return []
        width = max(len(name) for name in self.coverage)
        return [
            f"{name:<{width}}  {TIER_NAMES[tier]:<30}  {TIER_COVERAGE[tier]}"
            for name, tier in self.coverage.items()
        ]


def _cached_body(blob_sha):
    """The file body the cache holds for a blob name, or None for anything unreadable."""
    if not blob_sha:
        return None
    try:
        return caching.load_github_blob(blob_sha)
    except ValueError:
        # The SHA came from an API response. One that is not a Git object
        # name is not looked up; the file is downloaded instead, and the
        # transport refuses the name if it is still wrong.
        return None


### Target ###

def _target_from(options):
    """
    Reads the owner, and the repository when one was named, from a
    source entry's options.

    Returns:
        tuple[str, str | None]: the account, and the repository name or
        None for a whole account.

    Raises:
        GitHubSourceError: if no selector is present, or a url selector
            is not a GitHub owner or repository address.
    """
    for key in ("org", "user"):
        if options.get(key):
            return options[key], None
    url = options.get("url")
    if not url:
        raise GitHubSourceError("a github_api source needs exactly one of org, user, or url.")
    owner, repository = owner_and_repository(url)
    if not owner:
        raise GitHubSourceError(
            f"{url!r} is not a GitHub owner or repository address, such as "
            "https://github.com/DepressionCenter/extractium."
        )
    return owner, repository


def owner_and_repository(url):
    """
    Reads the account, and the repository when there is one, out of a
    GitHub address.

    A repository address means that repository, and an owner address means
    that owner's repositories. Reading this backwards turns a small
    request into hours of work and an index full of content nobody asked
    for, so the two are kept strictly apart.

    Args:
        url (str): a github.com address.

    Returns:
        tuple[str | None, str | None]: the owner and repository, either of
        which is None when the address does not name it.
    """
    match = OWNER_URL_RE.match(url or "")
    if not match:
        return None, None
    return match.group(1), match.group(2)


