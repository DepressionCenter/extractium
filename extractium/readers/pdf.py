"""
Summary: Reads a PDF file into blocks with pypdf: the text of each page
in order, headings taken from the file's outline (its bookmarks) when
it has one and from the page numbers when it does not, and the title,
subject, and keywords from the document information dictionary. Meant
to run inside the child process extractium.readers.isolated provides,
because a malformed PDF can keep a parser busy or hungry, and a process
can be ended where a thread cannot. An encrypted file is refused
unopened, and a file whose pages hold no text at all is reported as
one that is likely scanned images.

This file is part of Extractium™
extractium/readers/pdf.py

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

import io
import logging
import re

from extractium.readers.documents import DocumentError, heading, paragraph

### Limits ###

# The most pages read from one file. A report or a manual is well under
# this; a file past it is read up to the ceiling and the text says so,
# so a reader of the index knows the record is partial.
MAX_PDF_PAGES = 500

# The level page and outline headings are written at. The document's
# title is level one, so the sections the chunker cuts at sit below it.
PAGE_HEADING_LEVEL = 2

# A page's text arrives with a line break wherever the layout had one.
# Two or more in a row mark a paragraph; a single one is a wrapped line.
PARAGRAPH_BREAK_RE = re.compile(r"\n[^\S\n]*\n+")

# The character a font with no usable encoding turns every glyph into.
# It carries nothing a person can search for, so it is dropped.
REPLACEMENT_CHARACTER = "\ufffd"


### Reading ###

def read_pdf(data):
    """
    The blocks and properties of one PDF file.

    Headings come from the file's outline when it has one: each entry
    becomes a heading before the page it points to, with the page
    number appended, nested entries one level deeper. A file with no
    outline gets a "Page N" heading before every page, unless it has
    only one page. Either way each section of the index names the page
    it came from, which is the nearest thing to a page citation the
    index can carry.

    Args:
        data (bytes): the whole file.

    Returns:
        tuple[list[Block], dict[str, str]]: headings and paragraphs in
        page order, and the title, subject, and keywords the document
        information declares, blanks included for the caller to drop.

    Raises:
        DocumentError: if the file is encrypted, cannot be parsed, or
            holds pages but no text.
    """
    try:
        # pypdf is the optional pdf extra; the caller checks it is
        # installed before sending a file here.
        import pypdf
        from pypdf import errors
    except ImportError as e:  # pragma: no cover - the caller checks first
        raise DocumentError(f"the PDF reader is not installed ({e})") from e

    # pypdf logs what it tolerates in a damaged file. Those lines belong
    # to the file, not to the build, and would otherwise reach the console.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise DocumentError("the PDF is encrypted; encrypted files are not read")
        page_count = len(reader.pages)
        properties = _properties(reader)
        outline = _outline_by_page(reader)
        blocks = []
        text_seen = False
        for index, page in enumerate(reader.pages):
            if index >= MAX_PDF_PAGES:
                blocks.append(paragraph(
                    f"Only the first {MAX_PDF_PAGES} of {page_count} pages were read."
                ))
                break
            blocks.extend(_page_headings(index, outline, page_count))
            for text in _paragraphs(page.extract_text() or "", first_line_alone=index == 0):
                text_seen = True
                blocks.append(paragraph(text))
    except DocumentError:
        raise
    except (errors.PyPdfError, ValueError, TypeError, KeyError, IndexError,
            AttributeError, RecursionError, AssertionError) as e:
        raise DocumentError(f"the PDF could not be read ({type(e).__name__}: {_short(e)})") from e

    if page_count and not text_seen:
        raise DocumentError("the PDF holds no text; it is likely scanned images")
    return blocks, properties


def _properties(reader):
    """
    The title, subject, and keywords from the document information
    dictionary, each an empty string when absent. The XMP metadata
    stream is not read: the information dictionary is what every
    writer fills in and what a viewer shows.
    """
    try:
        info = reader.metadata
    except Exception:  # noqa: BLE001 -- a broken dictionary costs the properties, not the file
        info = None
    if not info:
        return {"title": "", "subject": "", "keywords": ""}
    return {
        "title": _as_text(info.get("/Title")),
        "subject": _as_text(info.get("/Subject")),
        "keywords": _as_text(info.get("/Keywords")),
    }


def _as_text(value):
    """A dictionary value as a string, or an empty string for anything odd."""
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:  # noqa: BLE001 -- an unreadable value is the same as none
        return ""


def _outline_by_page(reader):
    """
    The outline (bookmarks) grouped by the page each entry points to.

    Returns:
        dict[int, list[tuple[int, str]]]: page index to the entries on
        it, each as a nesting level starting at one and a title. Empty
        when the file has no outline or it cannot be read.
    """
    by_page = {}
    try:
        _collect_outline(reader, reader.outline, 1, by_page)
    except Exception:  # noqa: BLE001 -- a broken outline costs the headings, not the file
        return {}
    return by_page


def _collect_outline(reader, items, level, by_page):
    """Walks one level of the outline; a nested list is the children of the entry before it."""
    for item in items:
        if isinstance(item, list):
            _collect_outline(reader, item, level + 1, by_page)
            continue
        title = " ".join(_as_text(getattr(item, "title", "")).split())
        try:
            page_index = reader.get_destination_page_number(item)
        except Exception:  # noqa: BLE001 -- an entry pointing nowhere is skipped
            page_index = None
        if title and page_index is not None and page_index >= 0:
            by_page.setdefault(page_index, []).append((level, title))


def _page_headings(index, outline, page_count):
    """
    The heading blocks that open one page: its outline entries with the
    page number appended, or a page heading when the file has no
    outline and more than one page.
    """
    page_number = index + 1
    if outline:
        return [
            heading(PAGE_HEADING_LEVEL + level - 1, f"{title} (page {page_number})")
            for level, title in outline.get(index, ())
        ]
    if page_count > 1:
        return [heading(PAGE_HEADING_LEVEL, f"Page {page_number}")]
    return []


def _paragraphs(text, first_line_alone=False):
    """
    A page's extracted text as paragraphs: split at blank lines, with
    the wrapped lines inside each joined by a space, every run of
    whitespace collapsed, and replacement characters dropped.

    Args:
        text (str): what the page yielded.
        first_line_alone (bool): whether the first line stands as a
            paragraph of its own. True for the first page, because
            its first line is usually the document's title and the
            title rule reads the first line of the text.
    """
    text = text.replace(REPLACEMENT_CHARACTER, "")
    if first_line_alone:
        lines = text.splitlines()
        first = next((position for position, line in enumerate(lines) if line.strip()), None)
        if first is not None:
            yield " ".join(lines[first].split())
            text = "\n".join(lines[first + 1:])
    for chunk in PARAGRAPH_BREAK_RE.split(text):
        joined = " ".join(chunk.split())
        if joined:
            yield joined


def _short(error):
    """An exception's message cut to a length fit for a progress line."""
    message = " ".join(str(error).split())
    return message[:120] + ("..." if len(message) > 120 else "")
