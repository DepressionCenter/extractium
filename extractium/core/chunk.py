"""
Summary: Turns one fetched page into parent (full-section) and child
(small overlapping window) chunks for small-to-big retrieval, including
the title/content extraction and Markdown/plain-text-to-HTML conversion
that feed the chunker.

This file is part of Extractium™
extractium/core/chunk.py

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

import html
import re
from urllib.parse import urljoin, urlparse

import markdown
from bs4 import BeautifulSoup

# Value-imported: these are pure functions with no module-level state any
# test monkeypatches, so (unlike extractium.core.cache from
# extractium.core.fetch) a direct value import is safe here.
from extractium.core.fetch import is_git_blob_text_url, is_git_host_url, normalise

### Constants ###

# "Parent" chunk sizing -- a parent is one full section (see
# split_into_parents), the text actually sent to the model. Parents are
# never embedded/searched directly; see CHILD_* below for the small-to-big
# retrieval unit that is.
CHUNK_MAX_CHARS = 1200
CHUNK_MIN_CHARS = 60

# "Child" chunk sizing -- the small, precise window that gets embedded and
# matched against a query (small-to-big retrieval: search small, return
# big). ~15% overlap so a fact sitting right at a window boundary is still
# fully contained in at least one child.
CHILD_CHUNK_MAX_CHARS = 350
CHILD_CHUNK_MIN_CHARS = 60
CHILD_OVERLAP_CHARS = 53

# Selectors tried, in order, for a page that is neither TeamDynamix nor a
# Git host -- the generic/fallback content extractor for any ordinary
# website.
GENERIC_CONTENT_SELECTORS = [
    "#tdBodyContent",
    ".kb-article-body",
    ".td-page-body",
    "[data-region='article-body']",
    "#articleBody",
    ".article-content",
    "main",
]
STRIP_TAGS = [
    "script", "style", "noscript", "nav", "footer", "header",
    "aside", ".breadcrumb", ".td-utility-bar", ".td-nav", ".pager",
    ".pagination", "#tdBreadcrumb", "#tdNavigation", "#tdSideMenu",
    ".td-side-menu",
]


### Title And Content Extraction ###

# TODO: the host-specific branches in this section (TeamDynamix selectors
# and title prefixes, Git-host wiki/release/blob handling, the "kind"
# facet) belong to site-handler plugins that the web source consults per
# URL, leaving only the generic fallback here. See extractium.sources.tdx
# and extractium.sources.github for where each branch goes.

def normalise_page_title(title, url=None):
    """Strips a TeamDynamix "Article - "/"Question Detail - " prefix, if present, for TDX URLs."""
    if url and "teamdynamix." in url.lower():
        for prefix in ("Article - ", "Question Detail - "):
            title = title.removeprefix(prefix)
    return title


def get_title(soup, url=None):
    """
    Derives a page's title, trying (in order) the <title> tag, an <h1>, a
    blob-path-derived fallback for raw Git text files, then "Untitled".

    Args:
        soup (BeautifulSoup): the parsed page.
        url (str, optional): the page URL, used for TDX prefix stripping
            and the Git blob-path fallback.

    Returns:
        str: the derived title.
    """
    t = soup.find("title")
    if t:
        title = re.sub(r"\s*[|]\s*.+$", "", t.get_text(" ", strip=True))
        return normalise_page_title(title, url)
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
        return normalise_page_title(title, url)
    if url and is_git_blob_text_url(url):
        return derive_title_from_blob_path(url)
    return "Untitled"


def extract_content(soup, url=None):
    """
    Selects the main content node from a parsed page, branching on host:
    TeamDynamix (#divMainContent/#questionsContent), a Git host wiki or
    release-tag page (.markdown-body/etc.), a raw Git blob's already-clean
    body, or the generic fallback selectors. Boilerplate elements
    (STRIP_TAGS) are removed from the returned node in place.

    Args:
        soup (BeautifulSoup): the parsed page.
        url (str, optional): the page URL, used to pick the extraction branch.

    Returns:
        bs4.Tag | None: the content node, or None if no branch matched or
        the matched node had no extractable text (e.g. a repo root page,
        which is a client-hydrated shell with nothing server-rendered).
    """
    if url and "teamdynamix." in url.lower():
        for sel in ("#divMainContent", "#questionsContent"):
            node = soup.select_one(sel)
            if node:
                for noise in STRIP_TAGS:
                    for el in node.select(noise):
                        el.decompose()
                if node.get_text(" ", strip=True):
                    return node
        return None

    if url and is_git_blob_text_url(url):
        # Content already came from a raw .md/.txt fetch and was converted
        # to a clean, chrome-free document by markdown_text_to_soup -- no
        # nav/footer noise to strip.
        body = soup.find("body")
        return body if body and body.get_text(strip=True) else None

    if is_git_host_url(url or ""):
        path = urlparse(url).path.rstrip("/").lower()
        if "/wiki" in path:
            # Wiki pages are still classic server-rendered (Gollum) HTML.
            selectors = (".markdown-body", "#wiki-content", "article", "main")
        elif re.search(r"/releases/tag/[^/]+$", path):
            # Individual release-notes pages are server-rendered inline.
            selectors = (".markdown-body",)
        else:
            # Repo root / tree / commit list / etc: client-hydrated shell
            # with no server-rendered content -- link-discovery hop only.
            return None
        for sel in selectors:
            node = soup.select_one(sel)
            if node:
                for noise in STRIP_TAGS:
                    for el in node.select(noise):
                        el.decompose()
                if node.get_text(" ", strip=True):
                    return node
        return None

    for sel in GENERIC_CONTENT_SELECTORS:
        node = soup.select_one(sel)
        if node:
            for noise in STRIP_TAGS:
                for el in node.select(noise):
                    el.decompose()
            return node
    return None


def extract_links(soup, base_url):
    """Resolves every <a href> against base_url and normalises each, for link discovery."""
    links = []
    for a in soup.find_all("a", href=True):
        href = normalise(urljoin(base_url, a["href"]))
        if href:
            links.append(href)
    return links


def chunk_kind(url):
    """
    Coarse per-chunk provenance facet, consumed by a browser-side
    router-driven facet filter (e.g. a code question shouldn't be scored
    against outreach pages) -- reserved for a future YouTube producer,
    which will add a fourth kind alongside these three.

    Returns:
        str: "code" for a Git host URL, "kb" for a TeamDynamix URL,
        otherwise "page".
    """
    if is_git_host_url(url):
        return "code"
    if "teamdynamix." in url.lower():
        return "kb"
    return "page"


def markdown_text_to_soup(raw_text, url):
    """
    Converts a fetched .md/.txt file's raw text into a minimal HTML
    document so it flows through the heading-based chunker
    (split_into_parents) unchanged: Markdown files get real <h1>-<h6>/<a>
    tags via python-markdown; plain-text files are wrapped in a single
    <pre> so they still yield one parent chunk.

    Args:
        raw_text (str): the file's raw text content.
        url (str): the file's URL, used only to detect the .md/.markdown
            extension.

    Returns:
        BeautifulSoup: a minimal <body>-wrapped document.
    """
    if url.lower().endswith((".md", ".markdown")):
        body_html = markdown.markdown(raw_text, extensions=["fenced_code", "tables"])
    else:
        body_html = "<pre>" + html.escape(raw_text) + "</pre>"
    return BeautifulSoup(f"<body>{body_html}</body>", "html.parser")


def derive_title_from_blob_path(url):
    """Fallback title for a repo text file with no Markdown H1: docs/setup.md -> 'Setup'."""
    name = urlparse(url).path.rsplit("/", 1)[-1]
    stem = re.sub(r"\.(md|markdown|txt)$", "", name, flags=re.I)
    return re.sub(r"[-_]+", " ", stem).strip().title() or "Untitled"


### Chunking ###

def split_into_parents(title, node, url):
    """
    Splits one page's content into "parent" chunks: one per <h2>/<h3>
    section (or the whole page, if it has no headings), further cut at
    CHUNK_MAX_CHARS if a section runs long. Parents are the full text
    handed to the model at answer time -- see split_parent_into_children
    for the smaller windows actually embedded and searched.

    Args:
        title (str): the page title, used as (part of) each parent's heading.
        node (bs4.Tag): the extracted content node.
        url (str): the page URL, used to derive host/kind metadata.

    Returns:
        list[dict]: parent chunk dicts with keys t (heading), x (text),
        u (url), host, kind, weight.
    """
    chunks = []
    host = urlparse(url).netloc.lower()
    kind = chunk_kind(url)

    def _make(heading, text):
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) < CHUNK_MIN_CHARS:
            return
        while len(text) > CHUNK_MAX_CHARS:
            cut = text.rfind("\n", 0, CHUNK_MAX_CHARS)
            if cut < CHUNK_MIN_CHARS:
                cut = CHUNK_MAX_CHARS
            chunks.append({"t": heading, "x": text[:cut], "u": url, "host": host, "kind": kind, "weight": 1.0})
            text = text[cut:].strip()
        if text:
            chunks.append({"t": heading, "x": text, "u": url, "host": host, "kind": kind, "weight": 1.0})

    headings = node.find_all(["h2", "h3"])
    if headings:
        before = []
        for el in node.children:
            if hasattr(el, "name") and el.name in ("h2", "h3"):
                break
            if hasattr(el, "get_text"):
                before.append(el.get_text(" ", strip=True))
        _make(title, " ".join(before))
        for h in headings:
            section_title = f"{title} -- {h.get_text(' ', strip=True)}"
            parts = []
            for sib in h.next_siblings:
                if hasattr(sib, "name") and sib.name in ("h2", "h3"):
                    break
                if hasattr(sib, "get_text"):
                    parts.append(sib.get_text(" ", strip=True))
            _make(section_title, " ".join(parts))
    else:
        text = node.get_text("\n", strip=True)
        _make(title, text)

    return chunks


def split_parent_into_children(parent):
    """
    Small-to-big child splitter. A parent shorter than CHILD_CHUNK_MAX_CHARS
    is returned as its own single child -- splitting an already-short
    section would only hand near-duplicate collapse a near-identical extra
    vector to discard later. Longer parents get a fixed-step sliding
    window (CHILD_OVERLAP_CHARS of overlap between windows, so a fact
    sitting at a window boundary still lands fully inside at least one
    child), each window trimmed back to the nearest preceding newline so
    children don't split mid-sentence any more than the parent splitter
    itself does.

    Args:
        parent (dict): one parent chunk dict, as produced by split_into_parents.

    Returns:
        list[dict]: one or more child chunk dicts, each a shallow copy of
        parent with "x" replaced by the child's text window.
    """
    text = parent["x"]
    if len(text) <= CHILD_CHUNK_MAX_CHARS:
        return [dict(parent)]

    children = []
    step = max(CHILD_CHUNK_MAX_CHARS - CHILD_OVERLAP_CHARS, CHILD_CHUNK_MIN_CHARS)
    n = len(text)
    start = 0
    while start < n:
        end = min(start + CHILD_CHUNK_MAX_CHARS, n)
        cut = text.rfind("\n", start, end) if end < n else end
        if cut <= start:
            cut = end
        child_text = text[start:cut].strip()
        if len(child_text) >= CHILD_CHUNK_MIN_CHARS:
            children.append({**parent, "x": child_text})
        if end >= n:
            break
        start += step  # fixed step, independent of `cut` -- guarantees progress every iteration
    return children if children else [dict(parent)]


def build_parent_and_child_chunks(title, node, url):
    """
    Produces one page's parent chunks (full section text, sent to the
    model) and child chunks (small windows, embedded/searched). Each
    child's `pid` is a 0-based index into THIS page's own parent list; a
    caller crawling multiple pages must offset it into a globally valid
    index as pages accumulate.

    Args:
        title (str): the page title.
        node (bs4.Tag): the extracted content node.
        url (str): the page URL.

    Returns:
        tuple[list[dict], list[dict]]: (parents, children).

    TODO: parents need stable ids that survive a rebuild: the first 16 hex
    characters of sha1(normalized URL + NUL + heading + NUL + ordinal),
    where the ordinal counts parents on the same page that share a
    heading. The ordinal is required because a long section is cut into
    several parents with one heading, and those must not collide. A
    child's id is derived, never stored: parent id, a hyphen, and the
    child's ordinal within its parent. The positional `pid` stays as the
    in-memory link between the two lists (docs/extractium-spec.md
    section 3, docs/container-format.md).
    """
    parents = split_into_parents(title, node, url)
    children = []
    for pid, parent in enumerate(parents):
        for child in split_parent_into_children(parent):
            child = dict(child)
            child["pid"] = pid
            children.append(child)
    return parents, children
