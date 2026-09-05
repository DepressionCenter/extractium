"""
Summary: Turns one document into parent (full-section) and child (small
overlapping window) chunks for small-to-big retrieval, gives every parent
a stable identifier, and holds the host-independent helpers the crawl
needs around chunking: link discovery and Markdown or plain-text to HTML
conversion. Reading a page's title and content node is the site
handlers' job (extractium.sources); nothing here branches on a host.

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

import hashlib
import html
import re
from urllib.parse import urljoin, urlparse

import markdown
from bs4 import BeautifulSoup

# Value-imported: normalise is a pure function with no module-level state
# any test monkeypatches, so (unlike extractium.core.cache from
# extractium.core.fetch) a direct value import is safe here.
from extractium.core.fetch import normalise

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

# A parent id is this many leading hexadecimal characters of a SHA-1
# digest: 64 bits, enough that two sections in one index will not collide
# and short enough to cite.
PARENT_ID_HEX_CHARS = 16


### Stable Identifiers ###

def parent_id(url, heading, ordinal):
    """
    The stable identifier of one parent: the first PARENT_ID_HEX_CHARS
    of sha1(normalized URL, NUL, heading, NUL, ordinal). The ordinal
    counts parents on the same page that share a heading, because a long
    section is cut into several parents with one heading and those must
    not collide. The id survives a rebuild while the URL and heading are
    unchanged, so saved answers and cached enrichment can be matched to
    fresh content (docs/extractium-spec.md section 3.3).

    Args:
        url (str): the page URL; normalised before hashing so a trailing
            slash or fragment does not change the id.
        heading (str): the parent's heading (its `t` field).
        ordinal (int): 0-based position among same-heading parents on
            the page.

    Returns:
        str: 16 lowercase hexadecimal characters.
    """
    key = "\0".join((normalise(url), heading, str(int(ordinal))))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:PARENT_ID_HEX_CHARS]


def child_id(parent_identifier, ordinal):
    """A child's identifier, derived and never stored: parent id, a hyphen, the child's ordinal within its parent."""
    return f"{parent_identifier}-{int(ordinal)}"


def assign_parent_ids(parents):
    """
    Sets the `id` of every parent dict in place, numbering same-heading
    parents in list order.

    Args:
        parents (list[dict]): one page's parents, each with `t` and `u`.

    Returns:
        list[dict]: the same list, for chaining.
    """
    seen = {}
    for parent in parents:
        ordinal = seen.get(parent["t"], 0)
        seen[parent["t"]] = ordinal + 1
        parent["id"] = parent_id(parent["u"], parent["t"], ordinal)
    return parents


### Text To HTML ###

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


### Link Discovery ###

def extract_links(soup, base_url):
    """Resolves every <a href> against base_url and normalises each, for link discovery."""
    links = []
    for a in soup.find_all("a", href=True):
        href = normalise(urljoin(base_url, a["href"]))
        if href:
            links.append(href)
    return links


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
        url (str): the page URL, recorded on each parent and hashed into
            its id.

    Returns:
        list[dict]: parent chunk dicts with keys id (stable identifier),
        t (heading), x (text), u (url), host, weight.
    """
    chunks = []
    host = urlparse(url).netloc.lower()

    def _make(heading, text):
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) < CHUNK_MIN_CHARS:
            return
        while len(text) > CHUNK_MAX_CHARS:
            cut = text.rfind("\n", 0, CHUNK_MAX_CHARS)
            if cut < CHUNK_MIN_CHARS:
                cut = CHUNK_MAX_CHARS
            chunks.append({"t": heading, "x": text[:cut], "u": url, "host": host, "weight": 1.0})
            text = text[cut:].strip()
        if text:
            chunks.append({"t": heading, "x": text, "u": url, "host": host, "weight": 1.0})

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

    return assign_parent_ids(chunks)


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


def _children_for(parents):
    """Every parent's children in parent order, each carrying the page-local `pid` of its parent."""
    children = []
    for pid, parent in enumerate(parents):
        for child in split_parent_into_children(parent):
            child = dict(child)
            child["pid"] = pid
            children.append(child)
    return children


def build_parent_and_child_chunks(title, node, url):
    """
    Produces one page's parent chunks (full section text, sent to the
    model) and child chunks (small windows, embedded/searched). Each
    child's `pid` is a 0-based index into THIS page's own parent list; a
    caller crawling multiple pages must offset it into a globally valid
    index as pages accumulate. Children carry a copy of their parent's
    fields, including its `id`; a child's own id is derived with
    child_id and never stored.

    Args:
        title (str): the page title.
        node (bs4.Tag): the extracted content node.
        url (str): the page URL.

    Returns:
        tuple[list[dict], list[dict]]: (parents, children).
    """
    parents = split_into_parents(title, node, url)
    return parents, _children_for(parents)


def chunk_document(document):
    """
    Chunks one Document into parents and children that carry the
    document's metadata, ready for the build step.

    Plain-text content (a str) is wrapped into a minimal HTML document
    first: Markdown when the URL ends in .md or .markdown, a single <pre>
    block otherwise. A parsed node is chunked as it is.

    Args:
        document (extractium.core.models.Document): what a source yielded.

    Returns:
        tuple[list[dict], list[dict]]: (parents, children). Every parent
        dict holds id, t, x, u, host, source_type, content_type,
        categories, local, and weight; every child is a copy of its
        parent with its own `x` and a page-local `pid`.
    """
    node = document.content
    if isinstance(node, str):
        node = markdown_text_to_soup(node, document.url)
    parents = split_into_parents(document.title, node, document.url)
    for parent in parents:
        parent["source_type"] = document.source_type
        parent["content_type"] = document.content_type
        parent["categories"] = tuple(document.categories)
        parent["local"] = document.local
        parent["weight"] = document.weight
    return parents, _children_for(parents)
