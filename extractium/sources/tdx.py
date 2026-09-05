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

from extractium.core.models import Extraction
from extractium.sources.generic import UNTITLED, page_title, select_content

### Constants ###

# A TeamDynamix portal is recognized by its host name. The portal serves
# full article HTML to the truthful default User-Agent (checked against
# the real portal on 2026-09-04), so no User-Agent override is needed.
TDX_HOST_MARKER = "teamdynamix."

# Article body and question body, in the order they are tried.
TDX_CONTENT_SELECTORS = ("#divMainContent", "#questionsContent")

# The portal prefixes every <title> with the page kind.
TDX_TITLE_PREFIXES = ("Article - ", "Question Detail - ")

# The breadcrumb trail above an article: "Knowledge Base > Category >
# Article". Linked crumbs are the hierarchy; the unlinked last crumb is
# the page itself.
TDX_BREADCRUMB_SELECTORS = ("#tdBreadcrumb", ".breadcrumb")

# Portal pages with no article content: sign-in, print views, file
# downloads, and tag listings.
TDX_CRAWL_EXCLUDE_PATTERNS = (
    r"/Login\.aspx",
    r"/PrintArticle\?ID=",
    r"/FileOpen[/?$]",
    r"/FileDownload[/?$]",
    r"/TagID=",
    r"/TagID/[0-9]+",
)

# Category listings link to real articles but hold no content of their
# own, so they are followed and not indexed.
TDX_INDEX_ONLY_EXCLUDE_PATTERNS = (
    r"/CategoryID=",
    r"/CategoryID/[0-9]+",
    r"/Category/",
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
        Categories come from the breadcrumb trail, read before the body
        is stripped.
        """
        categories = breadcrumb_categories(soup)
        node = select_content(soup, TDX_CONTENT_SELECTORS, require_text=True)
        if node is None:
            return None
        title = strip_title_prefix(page_title(soup) or UNTITLED)
        return Extraction(title=title, node=node, categories=categories)

    def content_type(self, url):
        """Every page this handler reads is a knowledge-base article."""
        return "article"
