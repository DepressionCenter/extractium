"""
Summary: The TeamDynamix (TDX) client-portal site handler: an on-by-default
plugin the web source consults for teamdynamix.* URLs. It owns the
portal's content selectors (#divMainContent, #questionsContent), the
"Article - " and "Question Detail - " title prefix stripping, breadcrumb
categories, and the portal's exclude patterns (login, print, file, tag,
and category views). It is not a crawler: link discovery stays in
extractium.sources.web. See docs/extractium-spec.md section 5.

This file is part of Extractium™
extractium/sources/tdx.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-12
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

# One TeamDynamix host serves many organizations' portals, each under its
# own folder. A crawl seeded inside one stays inside it.
PORTAL_FOLDER_RE = re.compile(r"(/TDClient/\d+/[^/]+/)")

# A TeamDynamix portal is recognized by its host name. The portal serves
# full article HTML to the truthful default User-Agent (checked against
# the real portal on 2026-09-04), so no User-Agent override is needed.
TDX_HOST_MARKER = "teamdynamix."

# Article body and question body, in the order they are tried.
TDX_CONTENT_SELECTORS = ("#divMainContent", "#questionsContent")

# The portal prefixes every <title> with the page kind.
TDX_TITLE_PREFIXES = ("Article - ", "Question Detail - ")

# The portal cuts a long <title> short and marks the cut with an ellipsis,
# so an article's <title> can read "How to use OData query filt...". A
# heading is what a reader is shown and what an answer cites, so a cut-off
# one is worth replacing.
TDX_TITLE_TRUNCATION_MARKERS = ("...", "…")

# Where the whole title survives when the <title> does not. The metadata
# the portal publishes for link sharing is unambiguous; the article's own
# <h1> is the visible heading. Both are read before the body is stripped.
TDX_FULL_TITLE_META = "og:title"

# The breadcrumb trail above an article: "Knowledge Base > Category >
# Article". Linked crumbs are the hierarchy; the unlinked last crumb is
# the page itself.
TDX_BREADCRUMB_SELECTORS = ("#tdBreadcrumb", ".breadcrumb")

# Portal pages with no article content: sign-in, print views, file
# downloads, and tag listings.
# The portal identifies a tag or a category in a query string, as
# "Questions?CategoryID=0&TagID=8245", as well as in a path. A pattern
# beginning "/TagID=" matches only the path form, so every filtered
# listing was indexed: measured against the Depression Center portal, one
# question list appeared 123 times under different filter combinations,
# contributing an eighth of the whole index in navigation furniture. This
# leading class covers both places a parameter can start.
PARAMETER_START = r"[/?&]"

TDX_CRAWL_EXCLUDE_PATTERNS = (
    r"/Login\.aspx",
    r"/PrintArticle\?ID=",
    r"/FileOpen(?:[/?#]|$)",
    r"/FileDownload(?:[/?#]|$)",
)

# Category and tag listings link to real articles and questions and hold
# no content of their own, so they are followed and not indexed.
#
# They must stay on the crawl: a TeamDynamix portal publishes no sitemap
# and no full article index, so browsing these listings is the only way to
# reach most of what a portal holds. Excluding them from the crawl instead
# would quietly shrink the knowledge base to whatever the home page
# happens to link to. Note also that the portal writes an unfiltered
# listing as "TagID=0", so a rule that skips the crawl on sight of a tag
# parameter would skip the unfiltered page too.
TDX_INDEX_ONLY_EXCLUDE_PATTERNS = (
    rf"{PARAMETER_START}CategoryID=",
    r"/CategoryID/[0-9]+",
    r"/Category/",
    rf"{PARAMETER_START}TagID=",
    r"/TagID/[0-9]+",
)

TDX_INDEX_EXCLUDE_PATTERNS = TDX_CRAWL_EXCLUDE_PATTERNS + TDX_INDEX_ONLY_EXCLUDE_PATTERNS


### Helpers ###

def is_tdx_url(url):
    """True when url belongs to a TeamDynamix portal host."""
    return TDX_HOST_MARKER in url.lower()


def strip_title_prefix(title):
    """Removes the portal's "Article - " or "Question Detail - " prefix from a title."""
    for prefix in TDX_TITLE_PREFIXES:
        title = title.removeprefix(prefix)
    return title


def is_truncated_title(title):
    """True when the portal cut this title short and marked it with an ellipsis."""
    return title.endswith(TDX_TITLE_TRUNCATION_MARKERS)


def full_title(soup):
    """
    The article's whole title, taken from a part of the page the portal
    leaves intact.

    Args:
        soup (BeautifulSoup): the parsed page, before boilerplate is
            stripped, because the heading can sit inside an element the
            stripper removes.

    Returns:
        str | None: the title, or None when neither source has one that
        is itself uncut.
    """
    meta = soup.find("meta", attrs={"property": TDX_FULL_TITLE_META})
    heading = soup.find("h1")
    candidates = (
        (meta.get("content") or "") if meta else "",
        heading.get_text(" ", strip=True) if heading else "",
    )
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and not is_truncated_title(candidate):
            return candidate
    return None


def article_title(soup):
    """
    The title recorded on every section of one portal page: the <title>
    without the portal's page-kind prefix, replaced by the article's own
    heading when the portal cut the <title> short.
    """
    title = strip_title_prefix(page_title(soup) or UNTITLED)
    if is_truncated_title(title):
        return full_title(soup) or title
    return title


def breadcrumb_categories(soup):
    """
    The linked crumbs of the page's breadcrumb trail, outermost first.

    Args:
        soup (BeautifulSoup): the parsed page, before boilerplate is
            stripped (the trail sits outside the content node).

    Returns:
        tuple[str, ...]: crumb texts; empty when the page shows no trail.
    """
    for selector in TDX_BREADCRUMB_SELECTORS:
        trail = soup.select_one(selector)
        if trail is None:
            continue
        crumbs = []
        for item in trail.find_all("li"):
            link = item.find("a")
            if link is None:
                continue
            text = link.get_text(" ", strip=True)
            if text:
                crumbs.append(text)
        return tuple(crumbs)
    return ()


### Handler ###

class TdxHandler:
    """Reads knowledge-base articles and questions on a TeamDynamix portal."""

    name = "tdx"
    source_type = "kb"
    default_crawl_exclude_patterns = TDX_CRAWL_EXCLUDE_PATTERNS
    default_index_exclude_patterns = TDX_INDEX_EXCLUDE_PATTERNS

    def matches(self, url):
        """True for any URL on a teamdynamix.* host."""
        return is_tdx_url(url)

    def scope_prefix(self, seed_url):
        """
        The portal folder a crawl seeded inside a TeamDynamix portal stays
        within, or None for any other address.

        One TeamDynamix host serves many organizations' portals, each
        under its own /TDClient/<number>/<name>/ folder, so a crawl scoped
        to the host would wander into every other organization's
        knowledge base. The folder is the right default scope. The rule
        reads the path alone, because a portal may be served from an
        organization's own host as well as from a teamdynamix one.

        Args:
            seed_url (str): one of the crawl's starting addresses.

        Returns:
            str | None: the origin plus the portal folder, or None.
        """
        match = PORTAL_FOLDER_RE.search(seed_url)
        if not match:
            return None
        parsed = urlparse(seed_url)
        return f"{parsed.scheme}://{parsed.netloc}{match.group(1)}"

    def fetch_url(self, url):
        """The page is requested at its own URL."""
        return url

    def expects_html(self, url):
        """Every portal page is HTML."""
        return True

    def extract(self, soup, url):
        """
        The article or question body with boilerplate stripped, or None
        when neither selector finds a node with text (a listing page).
        The categories and the title are both read before the body is
        stripped, because the breadcrumb trail and the article heading
        can sit inside elements the stripper removes.
        """
        categories = breadcrumb_categories(soup)
        title = article_title(soup)
        node = select_content(soup, TDX_CONTENT_SELECTORS, require_text=True)
        if node is None:
            return None
        return Extraction(title=title, node=node, categories=categories)

    def content_type(self, url):
        """Every page this handler reads is a knowledge-base article."""
        return "article"
