"""
Summary: The GitHub site handler: an on-by-default plugin the web source
consults for github.com, github.io, and generic git-host URLs. It
rewrites Markdown and text blob URLs to their raw-content equivalent,
extracts server-rendered wiki and release-notes pages, treats repository
root and tree pages as link-discovery hops with no indexable content, and
owns the code-host exclude patterns (issues, commits, settings, and the
like). Enumerating an organization through the GitHub API is a separate
source plugin, extractium.sources.github_api, not this handler. See
docs/extractium-spec.md section 5.

This file is part of Extractium™
extractium/sources/github.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
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
GITHUB_CRAWL_EXCLUDE_PATTERNS = (
    r"/pulse$",
    r"/issues?[/?]",
    r"/projects?[/?]",
    r"/pulls?[/?]",
    r"/pushes?[/?]",
    r"/forks?[/?]",
    r"/network[/?]",
    r"/commits?[/?]",
    r"/discussions?[/?]",
    r"/categories[/?]",
    r"/announcements?[/?]",
    r"/contribs?[/?]",
    r"/contributions?[/?]",
    r"/checks?[/?]",
    r"/watchers[/?]",
    r"/stargazers[/?]",
    r"/stars[/?]",
    r"/graphs[/?]",         # contributors, commit-activity, code-frequency, punch-card, traffic
    r"/actions[/?]",        # CI workflow runs
    r"/security[/?]",       # security advisories -- not KB content; /releases stays indexable
    r"/compare[/?]",
    r"/blame/",
    r"/raw/",               # Markdown and text file bodies are fetched from the raw content
                            # host instead (see fetch_url), so this only avoids re-crawling
                            # the redirect URL when a page happens to link to it.
    r"/find/",
    r"/deployments[/?]",
    r"/environments[/?]",
    r"/packages[/?]",
    r"/sponsors[/?]",
    r"/people[/?]",
    r"/followers[/?]",
    r"/following[/?]",
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
