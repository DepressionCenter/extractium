"""
Summary: The GitHub site handler: an on-by-default plugin the web source
consults for github.com, github.io, and generic git-host URLs. It
rewrites Markdown and text blob URLs to their raw-content equivalent,
extracts server-rendered wiki and release-notes pages, treats repository
root and tree pages as link-discovery hops with no indexable content, and
owns the code-host exclude patterns (issues, commits, settings, and the
like). It also keeps a crawl to the GitHub accounts the operator named,
and offers the API source when a crawl is seeded at a GitHub address.
Reading an account through the API is a separate source plugin,
extractium.sources.github_api, not this handler. See
docs/extractium-spec.md section 5 and
docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/sources/github.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
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
import re
from urllib.parse import urlparse

from extractium.core.models import Extraction
from extractium.sources.generic import UNTITLED, page_title, select_content

### Constants ###

# Hosts this handler claims: GitHub, GitLab, a self-hosted git.<org>
# host, and GitHub Pages.
GIT_HOST_RE = re.compile(
    r"^(?:github\.com|gitlab\.com|git\.[^.]+\.(?:com|edu|org|io)|(?:[^.]+\.)?github\.io)$",
    re.I,
)

# A blob (file viewer) URL for a Markdown or plain-text file, at any depth.
GIT_TEXT_FILE_RE = re.compile(r"/blob/[^/]+/.+\.(md|markdown|txt)$", re.I)

# The path of a blob URL: owner, repository, branch, then the file path.
_BLOB_PATH_RE = re.compile(r"^/([^/]+)/([^/]+)/blob/([^/]+)/(.*)$")

# A single release's notes page, which GitHub renders server-side.
_RELEASE_TAG_RE = re.compile(r"/releases/tag/[^/]+$")

# A repository README, in any of the text formats this handler reads.
_README_RE = re.compile(r"(^|/)readme(\.md|\.markdown|\.txt)?$", re.I)

# Wiki pages are classic server-rendered HTML; release-notes pages render
# their Markdown body inline.
WIKI_CONTENT_SELECTORS = (".markdown-body", "#wiki-content", "article", "main")
RELEASE_CONTENT_SELECTORS = (".markdown-body",)

# Repository housekeeping views that hold no documentation.
# A code host serves each of its navigation pages both bare, as
# ".../issues", and with something after it, as "/issues/12" or
# "/issues?q=is%3Aopen". A pattern ending in a character class such as
# `[/?]` matches only the second shape, so every list page slips through:
# measured against the Depression Center organization, that let 150 of a
# 500-page crawl go to issue, pull-request, branch, and fork listings that
# contributed no indexed content at all. Ending each segment with this
# instead covers both shapes.
SEGMENT_END = r"(?:[/?#]|$)"

# Every enabled handler's exclude patterns apply to every URL in a crawl,
# not only to the hosts that handler claims. So each segment below is
# anchored under an owner and a repository: without that, "/projects?"
# would also exclude an ordinary site's own /project page, and
# "/community" its community page.
REPOSITORY_PATH = r"^https?://[^/]+/[^/]+/[^/]+"

# Repository paths that are the code host's own furniture rather than
# documentation. Each entry is one path segment, and a trailing "?" in an
# entry makes its own last letter optional ("pulls?" covers /pull and
# /pulls). A repository actually named after one of these would be skipped
# too; no such name exists on the hosts this ships enabled for, and
# `crawl_exclude_patterns` in the configuration file overrides the list.
GITHUB_NON_CONTENT_SEGMENTS = (
    "pulse",
    "issues?",
    "projects?",
    "pulls?",
    "pushes?",
    "forks?",
    "network",
    "commits?",
    "discussions?",
    "categories",
    "announcements?",
    "contribs?",
    "contributions?",
    "checks?",
    "watchers",
    "stargazers",
    "stars",
    "graphs",            # contributors, commit-activity, code-frequency, punch-card, traffic
    "actions",           # CI workflow runs
    "security",          # security advisories -- not KB content; /releases stays indexable
    "compare",
    "deployments",
    "environments",
    "packages",
    "sponsors",
    "people",
    "followers",
    "following",
    # Further listings GitHub links from every repository landing page.
    "branches",
    "activity",
    "custom-properties",
    "community",
    "milestones",
    "labels",
)

GITHUB_CRAWL_EXCLUDE_PATTERNS = tuple(
    rf"{REPOSITORY_PATH}/{segment}{SEGMENT_END}" for segment in GITHUB_NON_CONTENT_SEGMENTS
) + (
    r"/blame/",
    r"/raw/",               # Markdown and text file bodies are fetched from the raw content
                            # host instead (see fetch_url), so this only avoids re-crawling
                            # the redirect URL when a page happens to link to it.
    r"/find/",
    # Wiki housekeeping actions (edit form, revision history, new-page
    # draft, access settings) -- not real content.
    r"/_edit$",
    r"/_history$",
    r"/_new$",
    r"/_access$",
)

# Directory listings link to files worth reading but are pure navigation
# themselves, so they are followed and not indexed.
GITHUB_INDEX_ONLY_EXCLUDE_PATTERNS = (
    r"/tree/",
)

GITHUB_INDEX_EXCLUDE_PATTERNS = GITHUB_CRAWL_EXCLUDE_PATTERNS + GITHUB_INDEX_ONLY_EXCLUDE_PATTERNS


### Which Accounts May Be Read ###

# GitHub account names turn up everywhere: in a README's credits, in a
# dependency list, in a fork notice, in a contributor's profile link.
# Following them is how a build meant to read one organization ends up
# indexing thousands of strangers' repositories. So an account is read
# only when the operator named it, and these patterns are how the account
# is read out of an address.
#
# All three GitHub-shaped hosts are covered, because the same account owns
# content on each of them.
_ACCOUNT_PATH_HOSTS = ("github.com", "www.github.com", "raw.githubusercontent.com",
                       "gist.github.com", "objects.githubusercontent.com")
_ACCOUNT_PAGES_HOST_RE = re.compile(r"^([^.]+)\.github\.io$", re.I)

# Paths under github.com that belong to GitHub itself rather than to an
# account, so they are never mistaken for an account name.
GITHUB_RESERVED_ACCOUNT_NAMES = frozenset({
    "about", "apps", "assets", "blog", "collections", "contact", "customer-stories",
    "enterprise", "events", "explore", "features", "git", "github", "issues",
    "join", "login", "logout", "marketplace", "new", "notifications", "orgs",
    "pricing", "pulls", "search", "security", "settings", "signup", "site",
    "sponsors", "stars", "topics", "trending", "users",
})


### URL Helpers ###

def is_git_host_url(url):
    """True if url's host is GitHub, GitLab, a generic self-hosted git host, or GitHub Pages."""
    host = urlparse(url).netloc.lower()
    return bool(GIT_HOST_RE.match(host))


def is_git_blob_text_url(url):
    """
    True for a git-host blob URL pointing at a Markdown or plain-text
    file, at any path depth, e.g. .../blob/main/docs/setup.md. GitHub's
    blob viewer is a client-hydrated app -- the file body exists only as
    JSON inside the page's embedded data payload, not as scrapeable HTML
    -- so these are fetched from raw.githubusercontent.com instead of
    parsed out of the blob page. Wiki pages and /releases/tag pages are
    still classic server-rendered HTML and don't need this path.
    """
    return is_git_host_url(url) and bool(GIT_TEXT_FILE_RE.search(urlparse(url).path))


def to_git_raw_url(blob_url):
    """
    Rewrites a github.com blob URL to its raw.githubusercontent.com
    equivalent: /<owner>/<repo>/blob/<branch>/<path> ->
    /<owner>/<repo>/<branch>/<path>. Only meaningful for URLs already
    matched by is_git_blob_text_url.
    """
    path = re.sub(r"^/([^/]+)/([^/]+)/blob/", r"/\1/\2/", urlparse(blob_url).path)
    return f"https://raw.githubusercontent.com{path}"


def derive_title_from_blob_path(url):
    """Fallback title for a repo text file with no Markdown H1: docs/setup.md -> 'Setup'."""
    name = urlparse(url).path.rsplit("/", 1)[-1]
    stem = re.sub(r"\.(md|markdown|txt)$", "", name, flags=re.I)
    return re.sub(r"[-_]+", " ", stem).strip().title() or UNTITLED


def owner_for_url(url):
    """
    The GitHub account an address belongs to, or None when it belongs to
    no account.

    Args:
        url (str): any URL.

    Returns:
        str | None: the account name, lowercased, for a github.com,
        raw.githubusercontent.com, or <account>.github.io address; None
        for every other host, and for GitHub's own pages, which belong to
        no account.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    pages = _ACCOUNT_PAGES_HOST_RE.match(host)
    if pages:
        return pages.group(1).lower()
    if host not in _ACCOUNT_PATH_HOSTS:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return None
    owner = segments[0].lower()
    return None if owner in GITHUB_RESERVED_ACCOUNT_NAMES else owner


def repository_categories(url):
    """
    The hierarchy a git-host URL sits in, outermost first: the owner and
    repository (the first two path segments), then, for a file, the
    folders between the branch and the file.

    Args:
        url (str): a git-host URL.

    Returns:
        tuple[str, ...]: path segments; empty for a host root.
    """
    path = urlparse(url).path
    blob = _BLOB_PATH_RE.match(path)
    if blob:
        owner, repo, _branch, file_path = blob.groups()
        folders = file_path.split("/")[:-1]
        return (owner, repo, *[f for f in folders if f])
    segments = [s for s in path.split("/") if s]
    return tuple(segments[:2])


### Accounts A Build May Read ###

def accounts_named_by(sources):
    """
    The GitHub accounts a build's own sources named.

    An account joins this set only by being asked for: as the owner of a
    `github_api` source, or as the owner in the address a `web` source is
    seeded at. Nothing joins it by being linked, forked, depended on, or
    mentioned often.

    Args:
        sources (Iterable): the configuration's source entries, each with
            a `type` and an `options` mapping.

    Returns:
        set[str]: account names, lowercased.
    """
    named = set()
    for entry in sources:
        options = entry.options
        if entry.type == "github_api":
            for key in ("org", "user"):
                if options.get(key):
                    named.add(options[key].lower())
            owner = owner_for_url(options.get("url") or "")
            if owner:
                named.add(owner)
        elif entry.type == "web":
            # Every seed counts, not only the first: one crawl may start at
            # more than one address, and each names whatever account it
            # belongs to.
            seeds = options.get("seed_urls") or ([options["seed_url"]] if options.get("seed_url") else [])
            for seed in seeds:
                owner = owner_for_url(seed or "")
                if owner:
                    named.add(owner)
    return named


### Handler ###

class GitHubHandler:
    """
    Reads the server-rendered parts of a git host: wiki pages, release
    notes, and Markdown or text files through their raw URLs. Repository
    root, tree, and every other view is a link-discovery hop only.

    TODO: a GitHub Pages site (<owner>.github.io) is plain static HTML
    that the generic selectors could read; this handler still treats it
    as a link hop, the behaviour of the original script.
    """

    name = "github"
    source_type = "github"
    default_crawl_exclude_patterns = GITHUB_CRAWL_EXCLUDE_PATTERNS
    default_index_exclude_patterns = GITHUB_INDEX_EXCLUDE_PATTERNS

    def __init__(self):
        # None means "no account rule in force". A handler constructed
        # directly, by a library caller or a test, restricts nothing; the
        # rule only applies once a build hands over what its operator
        # actually asked for. Defaulting the other way would make a plain
        # GitHubHandler() drop every GitHub URL, and that failure would
        # look like a broken crawl rather than a guardrail.
        self.allowed_accounts = None
        self.skipped_accounts = collections.Counter()

    def configure(self, settings):
        """
        Adopts the build's global crawl settings, which carry the GitHub
        accounts the operator named.

        This is the optional settings hook of the site-handler protocol.
        A handler whose rules depend only on the URL does not define it.

        Args:
            settings: the build's crawl settings, or None to leave the
                account rule out of force.
        """
        accounts = getattr(settings, "github_owners", None)
        self.allowed_accounts = None if accounts is None else frozenset(
            account.lower() for account in accounts
        )

    def allows(self, url):
        """
        Whether a crawl may follow a URL, under the account rule.

        A GitHub account is read only when the operator named it: as a
        source, or in the `github_owners` setting. Nothing else joins that
        set, however it was linked and however often it is mentioned.

        This matters most for the default crawl scope. A crawl seeded at
        github.com/SomeOrg has github.com as its origin, and a crawl stays
        inside its origin by default, so without this rule every account
        on the host would be in scope.

        Args:
            url (str): a URL the crawl is considering.

        Returns:
            bool: True unless the URL belongs to a GitHub account the
            operator did not name. A URL on any other host is not this
            handler's business and is always allowed.

        Side effects:
            Counts each refused account, so the build can report once what
            it held back rather than once per link.
        """
        if self.allowed_accounts is None:
            return True
        owner = owner_for_url(url)
        if owner is None or owner in self.allowed_accounts:
            return True
        self.skipped_accounts[owner] += 1
        return False

    def offer_source(self, seed_url):
        """
        Offers the GitHub API source for a crawl seeded at a GitHub
        address, so an account is read through the API rather than scraped
        page by page.

        The offer is for the seed only. A link to somebody's repository
        found halfway through crawling an unrelated website stays an
        ordinary link; otherwise one stray mention could pull an entire
        GitHub account into a small site crawl.

        An owner address means that owner's repositories and a repository
        address means that one repository. The two are kept strictly
        apart: reading them the same way would turn a small request into
        hours of work.

        Args:
            seed_url (str): the URL the crawl would start from.

        Returns:
            tuple[str, dict] | None: the source name and its options, or
            None when the seed is not a GitHub owner or repository
            address.
        """
        parsed = urlparse(seed_url)
        if parsed.netloc.lower() not in ("github.com", "www.github.com"):
            return None
        segments = [segment for segment in parsed.path.split("/") if segment]
        if not segments or segments[0].lower() in GITHUB_RESERVED_ACCOUNT_NAMES:
            return None
        options = {"org": None, "user": None, "url": seed_url}
        return ("github_api", options)

    def skipped_account_report(self):
        """
        One line naming the accounts the rule held back, with how many
        links pointed at each.

        Returns:
            str: the report, or an empty string when nothing was skipped.
            An operator who did want one of these can see it and say so,
            and one who did not can see that the guardrail worked.
        """
        if not self.skipped_accounts:
            return ""
        named = ", ".join(
            f"{account} ({count} link{'s' if count != 1 else ''})"
            for account, count in self.skipped_accounts.most_common()
        )
        return f"Not read; add to github_owners to include: {named}"

    def matches(self, url):
        """True for any URL on a git host (see GIT_HOST_RE)."""
        return is_git_host_url(url)

    def fetch_url(self, url):
        """A Markdown or text blob is requested from the raw content host; anything else at its own URL."""
        return to_git_raw_url(url) if is_git_blob_text_url(url) else url

    def expects_html(self, url):
        """Raw files are plain text; every other page is HTML."""
        return not is_git_blob_text_url(url)

    def extract(self, soup, url):
        """
        The page's content node, or None for a link-discovery hop.

        A raw file arrives already converted to a clean document (see
        extractium.core.chunk.markdown_text_to_soup), so its body is
        returned whole. Wiki and release-notes pages are read through
        their selectors with boilerplate stripped. Everything else on a
        git host is a client-hydrated shell with nothing to read.
        """
        categories = repository_categories(url)
        if is_git_blob_text_url(url):
            body = soup.find("body")
            if body is None or not body.get_text(strip=True):
                return None
            title = page_title(soup) or derive_title_from_blob_path(url)
            return Extraction(title=title, node=body, categories=categories)

        path = urlparse(url).path.rstrip("/").lower()
        if "/wiki" in path:
            selectors = WIKI_CONTENT_SELECTORS
        elif _RELEASE_TAG_RE.search(path):
            selectors = RELEASE_CONTENT_SELECTORS
        else:
            return None
        node = select_content(soup, selectors, require_text=True)
        if node is None:
            return None
        return Extraction(title=page_title(soup) or UNTITLED, node=node, categories=categories)

    def content_type(self, url):
        """readme, text, wiki, or release_notes by URL; page for anything else."""
        path = urlparse(url).path.rstrip("/")
        if is_git_blob_text_url(url):
            return "readme" if _README_RE.search(path) else "text"
        if "/wiki" in path.lower():
            return "wiki"
        if _RELEASE_TAG_RE.search(path.lower()):
            return "release_notes"
        return "page"
