"""
Summary: The one entry point for reading a document file: decides the
format from the file's own first bytes, hands the bytes to the Word,
OpenDocument, or RTF reader, and renders what came back as Markdown-like
text with the headings kept, beside the title, subject, keywords, and
description the file's own properties declare. Also holds the rules
every source shares: which addresses and file names count as documents,
the size ceiling, and how a title is chosen. See
docs/configuration.md under "Reading Word, OpenDocument, and RTF files".

This file is part of Extractium™
extractium/readers/documents.py

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

import html
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from extractium.core import chunk

### Constants ###

# The file extensions a reader turns into text. `.doc`, the binary Word
# format, is deliberately absent: it has no safe standard-library reader,
# so a file in that format is reported as unreadable rather than guessed
# at.
DOCUMENT_EXTENSIONS = ("docx", "odt", "rtf")

# Extensions of document formats that are recognised but never read, so
# a local folder holding one gets a line saying why instead of a page of
# noise.
UNREADABLE_EXTENSIONS = ("doc",)

# An address that names a document file. The extension may end the
# path, be followed by a query, or be followed by one more segment: a
# content-delivery network serves a file as `/<hash>.docx/<title>`, with
# the file's own name after the stored name.
DOCUMENT_URL_RE = re.compile(
    r"\.(" + "|".join(DOCUMENT_EXTENSIONS) + r")(?:/[^/?#]+)?(?:[?#]|$)", re.I
)

# The most bytes of one document file that are read. Word files from a
# word processor run to a few hundred kilobytes; this leaves room for
# one full of images and stops a build downloading a mistaken link to
# an archive.
MAX_DOCUMENT_BYTES = 20_000_000

# The most characters of a first line that can serve as a title when a
# document declares no heading.
MAX_TITLE_CHARS = 120

# What the first bytes of each format look like. Every decision about a
# file's format is made from these, never from its name or its declared
# content type, so a file served under the wrong extension is still read
# as what it is.
ZIP_MAGIC = b"PK\x03\x04"
RTF_MAGIC = b"{\\rtf"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class DocumentError(ValueError):
    """
    Raised when a file cannot be read as a document: it is in a format no
    reader covers, it is malformed, or it is larger than a ceiling. The
    message is written to be shown in a progress line.
    """


### Blocks ###

@dataclass(frozen=True)
class Block:
    """
    One unit of a document's text as a reader saw it.

    Attributes:
        kind (str): "heading", "paragraph", or "table".
        text (str): the heading or paragraph text; empty for a table.
        level (int): the heading level, 1 to 6; 0 for other kinds.
        rows (tuple[tuple[str, ...], ...]): the table's rows of cell
            text; empty for other kinds.
    """

    kind: str
    text: str = ""
    level: int = 0
    rows: tuple = ()


def heading(level, text):
    """A heading block at the given level, clamped to the six Markdown levels."""
    return Block("heading", text=text, level=max(1, min(int(level), 6)))


def paragraph(text):
    """A paragraph block."""
    return Block("paragraph", text=text)


def table(rows):
    """A table block from rows of cell text; rows and cells become tuples."""
    return Block("table", rows=tuple(tuple(str(cell) for cell in row) for row in rows))


def _one_line(text):
    """Text with every run of whitespace collapsed to one space."""
    return " ".join(text.split())


def _escaped(text):
    """
    Text made safe to place in Markdown: markup characters are encoded,
    so a document that happens to contain a tag is indexed as the words
    it wrote rather than parsed as HTML, and a line that begins with a
    hash mark stays a line rather than becoming a heading.
    """
    escaped = html.escape(text, quote=False)
    return re.sub(r"(?m)^([ \t]*)#", r"\1\\#", escaped)


def to_markdown(blocks):
    """
    Renders blocks as Markdown-like text: `#` headings, paragraphs
    separated by blank lines, and pipe tables.

    Args:
        blocks (Iterable[Block]): what a reader produced.

    Returns:
        str: the text, with a trailing newline; empty when no block holds
        any text.
    """
    rendered = []
    for block in blocks:
        if block.kind == "heading":
            text = _one_line(block.text)
            if text:
                rendered.append("#" * block.level + " " + _escaped(text))
        elif block.kind == "paragraph":
            text = "\n".join(line.strip() for line in block.text.splitlines()).strip()
            if text:
                rendered.append(_escaped(text))
        elif block.kind == "table":
            rows = [
                [_escaped(_one_line(cell)).replace("|", "\\|") for cell in row]
                for row in block.rows
            ]
            rows = [row for row in rows if any(row)]
            if rows:
                width = max(len(row) for row in rows)
                lines = ["| " + " | ".join(row + [""] * (width - len(row))) + " |" for row in rows]
                lines.insert(1, "|" + "---|" * width)
                rendered.append("\n".join(lines))
    return "\n\n".join(rendered) + ("\n" if rendered else "")


### Properties ###

# The file properties a reader keeps, in the order they are shown, with
# the label each is shown under. A person who fills these in on a Word
# or OpenDocument file has written a summary of it, and that summary is
# worth indexing beside the text, and stands in for the text when a
# file is too long to index whole.
PROPERTY_LABELS = (
    ("subject", "Subject"),
    ("keywords", "Keywords"),
    ("description", "Description"),
)


@dataclass(frozen=True)
class ReadDocument:
    """
    What a reader produced for one file.

    Attributes:
        text (str): the body as Markdown-like text, with headings.
        properties (dict[str, str]): the file's own properties, among
            `title`, `subject`, `keywords`, and `description`, each
            present only when the file set it to something non-blank.
    """

    text: str
    properties: dict

    @property
    def indexed_text(self):
        """
        The text to index: the subject, keywords, and description the
        file declares, as one opening paragraph, followed by the body.
        The title is left out because the document is indexed under it.
        """
        lines = [
            f"{label}: {_one_line(self.properties[key])}"
            for key, label in PROPERTY_LABELS if self.properties.get(key)
        ]
        if not lines:
            return self.text
        opening = _escaped("\n".join(lines)) + "\n"
        return opening + ("\n" + self.text if self.text else "")


def clean_properties(raw):
    """
    The properties a reader found, with blanks dropped and whitespace
    collapsed, so a property set to an empty string is the same as one
    never set.

    Args:
        raw (Mapping[str, str | None]): what the reader read.

    Returns:
        dict[str, str]: the non-blank properties.
    """
    cleaned = {}
    for key, value in raw.items():
        text = _one_line(value or "")
        if text:
            cleaned[key] = text
    return cleaned


### Which Files Are Documents ###

def is_document_url(url):
    """True when an address names a file a reader can turn into text."""
    return bool(DOCUMENT_URL_RE.search(url))


def is_document_path(path):
    """
    True when a file name carries a document extension, readable or
    recognised as unreadable, so a caller can keep such a file away from
    the plain-text route either way.

    Args:
        path (pathlib.Path | str): the file.
    """
    suffix = str(path).rsplit(".", 1)[-1].lower() if "." in str(path) else ""
    return suffix in DOCUMENT_EXTENSIONS or suffix in UNREADABLE_EXTENSIONS


def name_from_url(url):
    """
    A display name for a document taken from its address: the file's
    own name when the address carries one after the stored name, else
    the last path segment, without the extension and with word
    separators turned into spaces.

    Args:
        url (str): the document's address.

    Returns:
        str: for example "Youth Mental Health Resources", or "Document"
        when the address holds no usable name.
    """
    segments = [unquote(segment) for segment in urlparse(url).path.split("/") if segment]
    name = ""
    for position, segment in enumerate(segments):
        if re.search(r"\.(" + "|".join(DOCUMENT_EXTENSIONS) + r")$", segment, re.I):
            # The segment after the stored name is the file's own name
            # when a content-delivery network serves it that way.
            name = segments[position + 1] if position + 1 < len(segments) else segment
            break
    if not name and segments:
        name = segments[-1]
    stem = re.sub(r"\.(" + "|".join(DOCUMENT_EXTENSIONS) + r")$", "", name, flags=re.I)
    words = re.sub(r"[-_]+", " ", stem).strip()
    return words.title() if words else "Document"


### Reading ###

def read_document(data, name=""):
    """
    The text and properties of one document file.

    The format is decided from the first bytes, never from the name: a
    zip archive is opened as a Word or OpenDocument file, an RTF header
    is parsed as RTF, and the binary Word signature is refused by name.

    Args:
        data (bytes): the whole file.
        name (str): the file's name or address, used only in messages.

    Returns:
        ReadDocument: the body as Markdown-like text with headings, an
        empty string when the file holds none, and the file's properties.

    Raises:
        DocumentError: if the file is over MAX_DOCUMENT_BYTES, is in a
            format no reader covers, or is malformed in a way the reader
            refuses (a document type declaration, an archive entry larger
            than its ceiling, an unreadable archive).
    """
    # The imports sit here so that reading this module, which every
    # source does, does not pull in both readers before either is used.
    from extractium.readers import office, rtf

    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentError(
            f"{len(data)} bytes is over the {MAX_DOCUMENT_BYTES} byte ceiling for a document"
        )
    if data.startswith(ZIP_MAGIC):
        blocks, properties = office.read_zip_document(data)
    elif data.startswith(RTF_MAGIC):
        blocks, properties = rtf.read_rtf(data)
    elif data.startswith(OLE_MAGIC):
        raise DocumentError(
            "the binary .doc format is not read; save the file as .docx to have it indexed"
        )
    else:
        raise DocumentError("not a Word, OpenDocument, or RTF file")
    return ReadDocument(text=to_markdown(blocks), properties=clean_properties(properties))


def document_title(read, fallback):
    """
    The title a document is indexed under: the first heading in its
    text, else the title its properties declare, else its first line
    when that is short enough to be one, else the fallback.

    A heading in the text comes first because it is what a reader of
    the file sees, and a properties title can be left over from the
    template a file was made from.

    Args:
        read (ReadDocument): what read_document returned.
        fallback (str): the name to use when the file offers none, such
            as the file name.

    Returns:
        str: a non-blank title.
    """
    first_line = ""
    for line in read.text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            found = stripped.lstrip("#").strip()
            if found:
                return html.unescape(found)
            continue
        if len(stripped) <= MAX_TITLE_CHARS and not stripped.startswith("|"):
            first_line = html.unescape(stripped.lstrip("\\"))
        break
    return read.properties.get("title") or first_line or fallback


def content_node(markdown):
    """
    The content node the chunker cuts at headings, rendered from the
    text a reader produced.

    Args:
        markdown (str): a ReadDocument's indexed_text, or any text a
            reader produced.

    Returns:
        bs4.Tag: the body of the rendered document.
    """
    return chunk.markdown_to_soup(markdown).body
