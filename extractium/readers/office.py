"""
Summary: Reads Word (.docx) and OpenDocument text (.odt) files with the
standard library alone. Both formats are zip archives of XML: the
reader opens the archive in memory, takes the one part that holds the
body, walks it for paragraphs, headings, lists, and tables, and reads
the title, subject, keywords, and description from the part that holds
the file's properties. Two
kinds of malformed input are refused rather than handled: an archive
entry larger than its ceiling, whatever size it declares, and any XML
part carrying a document type declaration, which is the only way an
entity expansion or an external entity can reach the parser.

This file is part of Extractium™
extractium/readers/office.py

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
import re
import zipfile
from xml.etree import ElementTree

from extractium.readers.documents import DocumentError, heading, paragraph, table

### Constants ###

# The most bytes one XML part of an archive may unpack to. A document's
# body part is a few megabytes at the very most; a part that unpacks past
# this is a compressed bomb, not a document.
MAX_PART_BYTES = 50_000_000

# A document type declaration is refused outright. Neither format uses
# one, and it is the only place an entity definition can appear.
DOCTYPE_RE = re.compile(rb"<!(?:DOCTYPE|ENTITY)", re.I)

# The archive entries each format keeps its body and its properties in.
WORD_BODY_PART = "word/document.xml"
WORD_PROPERTIES_PART = "docProps/core.xml"
ODF_BODY_PART = "content.xml"
ODF_PROPERTIES_PART = "meta.xml"
ODF_MIMETYPE_PART = "mimetype"
ODF_TEXT_MIMETYPE = "application/vnd.oasis.opendocument.text"

# XML namespaces, written the way ElementTree spells a qualified name.
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
CP = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
DC = "{http://purl.org/dc/elements/1.1/}"
TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
META = "{urn:oasis:names:tc:opendocument:xmlns:meta:1.0}"

# Where each property sits in each format's properties part. Both
# formats use Dublin Core for the title, subject, and description; the
# keywords are the one element each format names its own way.
WORD_PROPERTY_TAGS = {
    "title": f"{DC}title", "subject": f"{DC}subject",
    "keywords": f"{CP}keywords", "description": f"{DC}description",
}
ODF_PROPERTY_TAGS = {
    "title": f"{DC}title", "subject": f"{DC}subject", "description": f"{DC}description",
}
ODF_KEYWORD_TAG = f"{META}keyword"

# Word style identifiers that mean a heading: "Heading1" through
# "Heading9", and the document title. A paragraph may also carry an
# outline level directly, which is read when the style says nothing.
WORD_HEADING_STYLE_RE = re.compile(r"^heading(\d)$", re.I)
WORD_TITLE_STYLE = "title"


### Archive ###

def read_zip_document(data):
    """
    The blocks of a Word or OpenDocument text file.

    Args:
        data (bytes): the whole file, already known to start with the
            zip signature.

    Returns:
        tuple[list[Block], dict[str, str]]: headings, paragraphs, and
        tables in document order, and the title, subject, keywords, and
        description the file's properties declare, blanks included for
        the caller to drop.

    Raises:
        DocumentError: if the archive cannot be read, is neither format,
            is an OpenDocument file of another kind, or a part is refused.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise DocumentError(f"not a readable archive ({e})") from e
    with archive:
        names = set(archive.namelist())
        if WORD_BODY_PART in names:
            properties = {}
            if WORD_PROPERTIES_PART in names:
                properties = _word_properties(_xml_part(archive, WORD_PROPERTIES_PART))
            return _word_blocks(_xml_part(archive, WORD_BODY_PART)), properties
        if ODF_BODY_PART in names:
            if ODF_MIMETYPE_PART in names:
                mimetype = _raw_part(archive, ODF_MIMETYPE_PART).decode("ascii", "replace").strip()
                if mimetype != ODF_TEXT_MIMETYPE:
                    raise DocumentError(
                        f"an OpenDocument file of type {mimetype}; only text documents are read"
                    )
            properties = {}
            if ODF_PROPERTIES_PART in names:
                properties = _odf_properties(_xml_part(archive, ODF_PROPERTIES_PART))
            return _odf_blocks(_xml_part(archive, ODF_BODY_PART)), properties
    raise DocumentError("an archive that is neither a Word nor an OpenDocument text file")


def _raw_part(archive, name):
    """
    One archive entry's bytes, read no further than the ceiling however
    large the entry claims or turns out to be.

    Raises:
        DocumentError: if the entry declares or unpacks to more than
            MAX_PART_BYTES, or cannot be read.
    """
    info = archive.getinfo(name)
    if info.file_size > MAX_PART_BYTES:
        raise DocumentError(
            f"{name} declares {info.file_size} bytes, over the {MAX_PART_BYTES} byte ceiling"
        )
    try:
        with archive.open(info) as part:
            raw = part.read(MAX_PART_BYTES + 1)
    except (zipfile.BadZipFile, EOFError, OSError) as e:
        raise DocumentError(f"{name} could not be read from the archive ({e})") from e
    if len(raw) > MAX_PART_BYTES:
        raise DocumentError(f"{name} unpacks to more than the {MAX_PART_BYTES} byte ceiling")
    return raw


def _xml_part(archive, name):
    """
    One archive entry parsed as XML, with a document type declaration
    refused before the parser sees it.

    Raises:
        DocumentError: as _raw_part, or if the part carries a DOCTYPE or
            ENTITY declaration, or is not well-formed.
    """
    raw = _raw_part(archive, name)
    if DOCTYPE_RE.search(raw):
        raise DocumentError(
            f"{name} carries a document type declaration, which this reader refuses"
        )
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError as e:
        raise DocumentError(f"{name} is not well-formed XML ({e})") from e


### Word ###

def _word_properties(root):
    """The title, subject, keywords, and description of a Word file's core properties part."""
    return {
        key: "".join((root.find(tag).itertext()) if root.find(tag) is not None else "")
        for key, tag in WORD_PROPERTY_TAGS.items()
    }


def _word_blocks(root):
    """The blocks of a Word body, in document order."""
    body = root.find(f"{W}body")
    if body is None:
        raise DocumentError(f"{WORD_BODY_PART} holds no document body")
    return list(_word_walk(body))


def _word_walk(element):
    """
    Yields the blocks under an element. Paragraphs and tables are
    blocks; anything else that can hold them, such as a content
    control, is walked through.
    """
    for child in element:
        if child.tag == f"{W}p":
            block = _word_paragraph(child)
            if block is not None:
                yield block
        elif child.tag == f"{W}tbl":
            block = _word_table(child)
            if block is not None:
                yield block
        elif child.tag == f"{W}sectPr":
            continue
        else:
            yield from _word_walk(child)


def _word_paragraph(element):
    """A heading, a list item, or a paragraph; None when it holds no text."""
    text = _word_text(element)
    if not text.strip():
        return None
    level = _word_heading_level(element)
    if level:
        return heading(level, text)
    properties = element.find(f"{W}pPr")
    if properties is not None and properties.find(f"{W}numPr") is not None:
        return paragraph("- " + " ".join(text.split()))
    return paragraph(text)


def _word_heading_level(element):
    """
    The heading level a paragraph's style or outline level gives it, or
    0 for body text.
    """
    properties = element.find(f"{W}pPr")
    if properties is None:
        return 0
    style = properties.find(f"{W}pStyle")
    style_id = (style.get(f"{W}val") or "") if style is not None else ""
    matched = WORD_HEADING_STYLE_RE.match(style_id)
    if matched:
        return int(matched.group(1))
    if style_id.lower() == WORD_TITLE_STYLE:
        return 1
    outline = properties.find(f"{W}outlineLvl")
    if outline is not None and (outline.get(f"{W}val") or "").isdigit():
        return int(outline.get(f"{W}val")) + 1
    return 0


def _word_text(element):
    """
    The text of one paragraph or cell: its runs in order, with tabs and
    line breaks kept. Deleted text from tracked changes, field
    instructions, and the fallback half of an alternate-content block
    are left out, because each would repeat or corrupt what a reader
    sees.
    """
    parts = []

    def walk(node):
        for child in node:
            tag = child.tag
            if tag in (f"{W}del", f"{W}delText", f"{W}instrText", f"{MC}Fallback"):
                continue
            if tag == f"{W}t":
                parts.append(child.text or "")
            elif tag == f"{W}tab":
                parts.append("\t")
            elif tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
            else:
                walk(child)

    walk(element)
    return "".join(parts)


def _word_table(element):
    """A table block from a Word table, or None when every cell is empty."""
    rows = []
    for row in (child for child in element if child.tag == f"{W}tr"):
        cells = []
        for cell in (child for child in row if child.tag == f"{W}tc"):
            texts = [_word_text(p) for p in cell.iter(f"{W}p")]
            cells.append(" ".join(" ".join(text.split()) for text in texts if text.strip()))
        rows.append(cells)
    return table(rows) if any(any(row) for row in rows) else None


### OpenDocument ###

def _odf_properties(root):
    """
    The title, subject, keywords, and description of an OpenDocument
    file's meta part. Keywords are one element each, joined with commas.
    """
    meta = root.find(f"{OFFICE}meta")
    if meta is None:
        return {}
    properties = {
        key: "".join((meta.find(tag).itertext()) if meta.find(tag) is not None else "")
        for key, tag in ODF_PROPERTY_TAGS.items()
    }
    keywords = [" ".join(("".join(k.itertext())).split()) for k in meta.findall(ODF_KEYWORD_TAG)]
    properties["keywords"] = ", ".join(k for k in keywords if k)
    return properties


def _odf_blocks(root):
    """The blocks of an OpenDocument text body, in document order."""
    body = root.find(f"{OFFICE}body/{OFFICE}text")
    if body is None:
        raise DocumentError(f"{ODF_BODY_PART} holds no text body")
    return list(_odf_walk(body))


def _odf_walk(element):
    """Yields the blocks under an element, walking through sections and lists."""
    for child in element:
        tag = child.tag
        if tag == f"{TEXT}h":
            text = _odf_text(child)
            if text.strip():
                level = child.get(f"{TEXT}outline-level") or "1"
                yield heading(int(level) if level.isdigit() else 1, text)
        elif tag == f"{TEXT}p":
            text = _odf_text(child)
            if text.strip():
                yield paragraph(text)
        elif tag == f"{TEXT}list":
            for item in child.iter(f"{TEXT}list-item"):
                for entry in item:
                    if entry.tag in (f"{TEXT}p", f"{TEXT}h"):
                        text = " ".join(_odf_text(entry).split())
                        if text:
                            yield paragraph("- " + text)
        elif tag == f"{TABLE}table":
            block = _odf_table(child)
            if block is not None:
                yield block
        else:
            yield from _odf_walk(child)


def _odf_text(element):
    """
    The text of one paragraph or heading, with the format's own spacing
    elements turned back into spaces, tabs, and line breaks. Footnotes
    and annotations are left out so a sentence reads as written.
    """
    parts = [element.text or ""]

    def walk(node):
        for child in node:
            tag = child.tag
            if tag == f"{TEXT}s":
                count = child.get(f"{TEXT}c") or "1"
                parts.append(" " * (int(count) if count.isdigit() else 1))
            elif tag == f"{TEXT}tab":
                parts.append("\t")
            elif tag == f"{TEXT}line-break":
                parts.append("\n")
            elif tag in (f"{TEXT}note", f"{OFFICE}annotation"):
                pass
            else:
                parts.append(child.text or "")
                walk(child)
            parts.append(child.tail or "")

    walk(element)
    return "".join(parts)


def _odf_table(element):
    """A table block from an OpenDocument table, or None when every cell is empty."""
    rows = []
    for row in element.iter(f"{TABLE}table-row"):
        cells = []
        for cell in (child for child in row if child.tag == f"{TABLE}table-cell"):
            texts = [_odf_text(p) for p in cell.iter(f"{TEXT}p")]
            cells.append(" ".join(" ".join(text.split()) for text in texts if text.strip()))
        rows.append(cells)
    return table(rows) if any(any(row) for row in rows) else None
