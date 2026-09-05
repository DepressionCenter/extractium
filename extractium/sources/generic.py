"""
Summary: The generic site handler, the core fallback the web source uses
for any page no other handler claims: common content selectors,
boilerplate stripping, and the page-title rule. The other built-in
handlers (extractium.sources.tdx, extractium.sources.github) reuse its
helpers. It is registered like any other handler so an operator's plugin
can shadow it, and the web source always consults it last. See
docs/extractium-spec.md section 5.

This file is part of Extractium™
extractium/sources/generic.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-04
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

from extractium.core.models import Extraction

### Constants ###

# Title recorded when a page has neither a <title> nor an <h1>.
UNTITLED = "Untitled"

# Selectors tried, in order, for a page no host-specific handler claims.
# The portal-flavoured ids are kept ahead of the bare "main" fallback so a
# knowledge-base portal served from its own domain, where the tdx handler
# does not match, still yields the article body rather than the page
# chrome.
GENERIC_CONTENT_SELECTORS = (
    "#tdBodyContent",
    ".kb-article-body",
    ".td-page-body",
    "[data-region='article-body']",
    "#articleBody",
    ".article-content",
    "main",
)

# Elements removed from a content node before chunking: scripts, page
# chrome, and the navigation blocks common to portals and wikis.
STRIP_TAGS = (
    "script", "style", "noscript", "nav", "footer", "header",
    "aside", ".breadcrumb", ".td-utility-bar", ".td-nav", ".pager",
    ".pagination", "#tdBreadcrumb", "#tdNavigation", "#tdSideMenu",
    ".td-side-menu",
)

# Non-content pages found on most websites: search forms, sign-in pages,
# print views, tag listings, and per-person pages. Applied to every crawl
# because this handler is always enabled.
GENERIC_CRAWL_EXCLUDE_PATTERNS = (
    r"/Search[/?$]",
    r"/Login[/?$]",
    r"/Tags[/?$]",
    r"/Print[/?$]",
    r"\?print=",
    r"/Archive[/?$]",
    r"/tags$",
    r"/tagged$",
    r"&tab=",
    r"/settings[/?]",
    r"/comments?[/?]",
    r"/author[/?]",
    r"/profile[/?]",
)

# A page never worth fetching is never worth indexing either, so the index
# list starts from the crawl list.
GENERIC_INDEX_EXCLUDE_PATTERNS = GENERIC_CRAWL_EXCLUDE_PATTERNS

# Everything after a vertical bar in a <title> is the site name.
_TITLE_SUFFIX_RE = re.compile(r"\s*[|]\s*.+$")


### Shared Helpers ###

def page_title(soup):
    """
    The page's own title: the <title> text with any "| Site name" suffix
    removed, else the first <h1>, else None.

    Args:
        soup (BeautifulSoup): the parsed page.

    Returns:
        str | None: the title, or None when the page declares none.
    """
    t = soup.find("title")
    if t:
        return _TITLE_SUFFIX_RE.sub("", t.get_text(" ", strip=True))
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    return None


def strip_boilerplate(node):
    """Removes every STRIP_TAGS match from node, in place, and returns node."""
    for noise in STRIP_TAGS:
        for el in node.select(noise):
            el.decompose()
    return node


def select_content(soup, selectors, require_text):
    """
    Returns the first content node one of the selectors finds, with
    boilerplate stripped.

    Args:
        soup (BeautifulSoup): the parsed page.
        selectors (Sequence[str]): CSS selectors tried in order.
        require_text (bool): True keeps trying later selectors when a
            matched node holds no text after stripping; False returns the
            first match whatever it holds.

    Returns:
        bs4.Tag | None: the content node, or None when no selector matched
        (or, with require_text, none matched with text).
    """
    for selector in selectors:
        node = soup.select_one(selector)
        if node is None:
            continue
        strip_boilerplate(node)
        if not require_text or node.get_text(" ", strip=True):
            return node
    return None


### Handler ###

class GenericHandler:
    """
    Reads any page: the fallback of last resort. Matches every URL, so
    the web source must consult it after every other handler.
    """

    name = "generic"
    source_type = "web"
    default_crawl_exclude_patterns = GENERIC_CRAWL_EXCLUDE_PATTERNS
    default_index_exclude_patterns = GENERIC_INDEX_EXCLUDE_PATTERNS

    def matches(self, url):
        """True for every URL; this handler is the fallback."""
        return True

    def fetch_url(self, url):
        """The page is requested at its own URL."""
        return url

    def expects_html(self, url):
        """Every page this handler reads is HTML."""
        return True

    def extract(self, soup, url):
        """
        The first GENERIC_CONTENT_SELECTORS match, stripped of boilerplate,
        or None when no selector matches. A matched node is returned even
        when it holds no text, so the chunker (not this handler) decides
        that the page is too short to keep.
        """
        node = select_content(soup, GENERIC_CONTENT_SELECTORS, require_text=False)
        if node is None:
            return None
        return Extraction(title=page_title(soup) or UNTITLED, node=node)

    def content_type(self, url):
        """Every page this handler reads is recorded as a plain page."""
        return "page"
