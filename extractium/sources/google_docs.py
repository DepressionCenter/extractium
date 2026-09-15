"""
Summary: Site handler for Google Docs, Sheets, and Slides files shared
as "anyone with the link". Such a file can be read without a key or a
sign-in through its export address, so the handler claims the file's
address on docs.google.com, folds its several link shapes into one, and
requests the plain-text export (CSV for a spreadsheet) the way the
GitHub handler requests a raw file for a blob page. A file that is not
shared answers its export with a sign-in page, which the crawl reports
and skips; nothing is ever retried with a credential. Forms, Drive
folders, and the sign-in host are kept out of every crawl.

This file is part of Extractium™
extractium/sources/google_docs.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-15
Last Modified: 2026-09-15
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
__date__ = "2026-09-15"

import re
from urllib.parse import urlparse

from extractium.core.models import Extraction

### Constants ###

# The one host this handler claims.
GOOGLE_DOCS_HOST = "docs.google.com"

# A file's address: the kind, an optional signed-in account index
# (`/u/0/`), then `/d/` and the file identifier. Everything after the
# identifier (`/edit`, `/view`, `/preview`, a sharing query) names the
# same file, so it is dropped when the address is folded.
_FILE_PATH_RE = re.compile(
    r"^/(document|spreadsheets|presentation)/(?:u/\d+/)?d/([A-Za-z0-9_-]+)(?:/|$)"
)

# What each kind exports as, and what to call it. A spreadsheet exports
# its first sheet as CSV; a document and a presentation export as plain
# text.
KINDS = {
    "document": {"format": "txt", "label": "Documents", "untitled": "Untitled Google Document"},
    "spreadsheets": {"format": "csv", "label": "Spreadsheets", "untitled": "Untitled Google Sheet"},
    "presentation": {"format": "txt", "label": "Presentations", "untitled": "Untitled Google Slides"},
}

# The category every file from this handler is filed under, then its kind.
CATEGORY = "Google Docs"

# An export is served from a delivery host rather than from
# docs.google.com itself, so a request for one lands there. The crawl
# would otherwise read that landing as a redirect off the site.
EXPORT_LANDING_RE = re.compile(r"^https://[a-z0-9-]+\.googleusercontent\.com/", re.I)

# The most characters of a file's first line that serve as its title.
MAX_TITLE_CHARS = 120

# Addresses on Google's hosts that are never worth fetching in any crawl:
# a form is an application, a Drive folder listing is one too, and the
# sign-in host is where a file that is not shared sends a request. Each
# is anchored to its host, because every enabled handler's patterns apply
# to every URL in a crawl.
GOOGLE_CRAWL_EXCLUDE_PATTERNS = (
    r"^https?://docs\.google\.com/forms/",
    r"^https?://drive\.google\.com/",
    r"^https?://accounts\.google\.com/",
)


### URL Helpers ###

def file_kind_and_id(url):
    """
    The kind and identifier of a Google Docs file address, or None for
    any other address.

    Args:
        url (str): any URL.

    Returns:
        tuple[str, str] | None: ("document", "<id>"), ("spreadsheets",
        "<id>"), or ("presentation", "<id>"); None when the URL is not a
        file on docs.google.com. Forms, Drive folders, and the host's
        other pages are None.
    """
    parsed = urlparse(url)
    if parsed.netloc.lower() != GOOGLE_DOCS_HOST:
        return None
    matched = _FILE_PATH_RE.match(parsed.path)
    if matched is None:
        return None
    return matched.group(1), matched.group(2)


def canonical_file_url(kind, file_id):
    """The one address a file is visited under and cited by, whatever link shape reached it."""
    return f"https://{GOOGLE_DOCS_HOST}/{kind}/d/{file_id}"


def export_url(kind, file_id):
    """The address that answers with the file's text, or its first sheet as CSV."""
    return f"{canonical_file_url(kind, file_id)}/export?format={KINDS[kind]['format']}"


def title_from_export(text, kind):
    """
    The title of an exported file: its first non-blank line, which is
    the document's own first line, cut to MAX_TITLE_CHARS; the kind's
    "Untitled" name when the export is blank.

    Args:
        text (str): the export as fetched.
        kind (str): one of the KINDS keys.
    """
    for line in text.lstrip("\ufeff").splitlines():
        title = " ".join(line.split())
        if title:
            if len(title) > MAX_TITLE_CHARS:
                title = title[:MAX_TITLE_CHARS - 3].rstrip() + "..."
            return title
    return KINDS[kind]["untitled"]


### Handler ###

class GoogleDocsHandler:
    """
    Reads Google Docs, Sheets, and Slides files shared with the link,
    through their export addresses. Claims only a file's own address on
    docs.google.com; forms, Drive folders, and every other page on the
    host are left to no handler at all, because the exclude patterns
    keep them out of the crawl.

    A file reaches a crawl only through `include_patterns`, because
    docs.google.com is off-site for every seed. A file that is not
    shared answers its export with a sign-in page, which the fetch
    layer reports with the landing address and skips.
    """

    name = "google_docs"
    source_type = "web"
    default_crawl_exclude_patterns = GOOGLE_CRAWL_EXCLUDE_PATTERNS
    default_index_exclude_patterns = GOOGLE_CRAWL_EXCLUDE_PATTERNS

    def matches(self, url):
        """True for a document, spreadsheet, or presentation address on docs.google.com."""
        return file_kind_and_id(url) is not None

    def canonical_url(self, url):
        """
        The one address for a file linked as `/edit`, `/edit?usp=sharing`,
        `/view`, or `/preview`, so the crawl fetches it once and cites it
        by one address. Any other URL is returned as written.
        """
        found = file_kind_and_id(url)
        if found is None:
            return url
        return canonical_file_url(*found)

    def fetch_url(self, url):
        """The file's export address: plain text, or CSV for a spreadsheet."""
        found = file_kind_and_id(url)
        return export_url(*found) if found else url

    def expects_html(self, url):
        """An export is text, never HTML; an HTML answer is a sign-in page and is refused."""
        return False

    def landing_allowed(self, url, final_url):
        """
        True when an export request landed on Google's delivery host,
        which is where every export is served from and not a redirect
        off the site. A landing anywhere else, the sign-in host above
        all, is left to the crawl's scope rule.
        """
        return self.matches(url) and bool(EXPORT_LANDING_RE.match(final_url or ""))

    def extract(self, soup, url):
        """
        The export's text as the crawl wrapped it, titled by its first
        line. None when the export holds no text at all.
        """
        found = file_kind_and_id(url)
        if found is None:
            return None
        kind, _ = found
        body = soup.find("body") or soup
        if not body.get_text(strip=True).lstrip("\ufeff"):
            return None
        return Extraction(
            title=title_from_export(body.get_text(), kind),
            node=body,
            categories=(CATEGORY, KINDS[kind]["label"]),
        )

    def content_type(self, url):
        """Every file this handler reads is recorded as text."""
        return "text"
