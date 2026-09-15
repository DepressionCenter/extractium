"""
Summary: Synthetic Word, OpenDocument, RTF, and PDF files for the tests,
built in memory so no binary fixture is committed and every byte of each
file is visible in this module. Each builder produces a file with a known
structure: a title heading, body paragraphs, a second-level heading, a
list, and a table, or for a PDF a few pages of text with an outline and
properties, so a test can assert the exact text a reader produces. Also
holds two functions the isolation tests run in the reader's child
process: one that never finishes and one that dies. Nothing here is real
content.

This file is part of Extractium™
tests/document_fixtures.py

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
import os
import time
import zipfile
from xml.sax.saxutils import escape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
ODF_OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
ODF_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
ODF_TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
ODF_META_NS = "urn:oasis:names:tc:opendocument:xmlns:meta:1.0"

# The properties every sample file declares, and the paragraph the
# reader places before the body for them.
SAMPLE_PROPERTIES = {
    "title": "Properties Title",
    "subject": "Classroom mental health resources",
    "keywords": "depression, anxiety, classroom",
    "description": "A list of pre-approved videos for classroom presentations.",
}
SAMPLE_PROPERTIES_PARAGRAPH = (
    "Subject: Classroom mental health resources\n"
    "Keywords: depression, anxiety, classroom\n"
    "Description: A list of pre-approved videos for classroom presentations.\n"
)

# The first bytes of an OLE compound file, which is what a binary .doc is.
OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64

# Long enough that the chunker keeps each paragraph as a section of its own.
BODY = (
    "Pre-approved by the Example Center for use in classroom presentations, "
    "with running times noted beside each entry so a lesson can be planned."
)


### Word ###

def word_paragraph(text, style=None, numbered=False):
    """One w:p holding one run, with an optional style and list marker."""
    properties = ""
    if style or numbered:
        properties = "<w:pPr>"
        if style:
            properties += f'<w:pStyle w:val="{style}"/>'
        if numbered:
            properties += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
        properties += "</w:pPr>"
    return f"<w:p>{properties}<w:r><w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r></w:p>"


def word_table(rows):
    """One w:tbl from rows of cell text."""
    body = ""
    for row in rows:
        cells = "".join(f"<w:tc>{word_paragraph(cell)}</w:tc>" for cell in row)
        body += f"<w:tr>{cells}</w:tr>"
    return f"<w:tbl>{body}</w:tbl>"


def make_docx(body_xml, document_part="word/document.xml", properties=None):
    """
    A .docx holding the given body XML, and a core-properties part when
    properties are given (keys title, subject, keywords, description).
    The content-types part is included so the archive looks like one
    Word wrote; the reader does not read it.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        archive.writestr(
            document_part,
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W_NS}" xmlns:mc="{MC_NS}"><w:body>{body_xml}'
            '<w:sectPr/></w:body></w:document>',
        )
        if properties is not None:
            tags = {"title": "dc:title", "subject": "dc:subject", "keywords": "cp:keywords",
                    "description": "dc:description"}
            elements = "".join(
                f"<{tags[key]}>{escape(value)}</{tags[key]}>" for key, value in properties.items()
            )
            archive.writestr(
                "docProps/core.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<cp:coreProperties xmlns:cp="{CP_NS}" xmlns:dc="{DC_NS}">'
                f"{elements}<dc:creator>Example Author</dc:creator></cp:coreProperties>",
            )
    return buffer.getvalue()


SAMPLE_DOCX_BODY = (
    word_paragraph("Youth Mental Health Resources", style="Title")
    + word_paragraph(BODY)
    + word_paragraph("Middle School", style="Heading2")
    + word_paragraph("Breathing exercise video (3 minutes)", numbered=True)
    + word_paragraph("How it feels to have depression (2 minutes)", numbered=True)
    + word_table([["Resource", "Minutes"], ["Breathing", "3"], ["Feelings", "2"]])
    + word_paragraph("High School", style="Heading2")
    + word_paragraph("Personal stories from student athletes, each under seven minutes long.")
)

SAMPLE_DOCX = make_docx(SAMPLE_DOCX_BODY, properties=SAMPLE_PROPERTIES)

# The text every reader test expects from SAMPLE_DOCX.
SAMPLE_DOCX_MARKDOWN = (
    "# Youth Mental Health Resources\n\n"
    f"{BODY}\n\n"
    "## Middle School\n\n"
    "- Breathing exercise video (3 minutes)\n\n"
    "- How it feels to have depression (2 minutes)\n\n"
    "| Resource | Minutes |\n|---|---|\n| Breathing | 3 |\n| Feelings | 2 |\n\n"
    "## High School\n\n"
    "Personal stories from student athletes, each under seven minutes long.\n"
)


### OpenDocument ###

def make_odt(text_xml, mimetype="application/vnd.oasis.opendocument.text", properties=None):
    """An .odt holding the given office:text XML, and a meta part when properties are given."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", mimetype)
        if properties is not None:
            elements = "".join(
                f"<dc:{key}>{escape(properties[key])}</dc:{key}>"
                for key in ("title", "subject", "description") if key in properties
            )
            elements += "".join(
                f"<meta:keyword>{escape(word.strip())}</meta:keyword>"
                for word in properties.get("keywords", "").split(",") if word.strip()
            )
            archive.writestr(
                "meta.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<office:document-meta xmlns:office="{ODF_OFFICE_NS}" xmlns:dc="{DC_NS}" '
                f'xmlns:meta="{ODF_META_NS}"><office:meta>{elements}'
                "<meta:generator>Example Writer</meta:generator></office:meta></office:document-meta>",
            )
        archive.writestr(
            "content.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<office:document-content xmlns:office="{ODF_OFFICE_NS}" '
            f'xmlns:text="{ODF_TEXT_NS}" xmlns:table="{ODF_TABLE_NS}">'
            f"<office:body><office:text>{text_xml}</office:text></office:body>"
            "</office:document-content>",
        )
    return buffer.getvalue()


SAMPLE_ODT = make_odt(
    '<text:h text:outline-level="1">Intake Protocol</text:h>'
    f"<text:p>{escape(BODY)}</text:p>"
    '<text:h text:outline-level="2">Steps</text:h>'
    '<text:p>First<text:s text:c="2"/>step<text:tab/>tabbed <text:span>span text</text:span> tail.</text:p>'
    "<text:list><text:list-item><text:p>Greet</text:p></text:list-item>"
    "<text:list-item><text:p>Listen</text:p></text:list-item></text:list>"
    "<table:table><table:table-row><table:table-cell><text:p>Step</text:p></table:table-cell>"
    "<table:table-cell><text:p>Minutes</text:p></table:table-cell></table:table-row>"
    "<table:table-row><table:table-cell><text:p>Greet</text:p></table:table-cell>"
    "<table:table-cell><text:p>5</text:p></table:table-cell></table:table-row></table:table>",
    properties=SAMPLE_PROPERTIES,
)

SAMPLE_ODT_MARKDOWN = (
    "# Intake Protocol\n\n"
    f"{BODY}\n\n"
    "## Steps\n\n"
    "First  step\ttabbed span text tail.\n\n"
    "- Greet\n\n"
    "- Listen\n\n"
    "| Step | Minutes |\n|---|---|\n| Greet | 5 |\n"
)


### RTF ###

# The unicode escape is assembled from pieces so no tool that rewrites
# backslash-u sequences in source files can turn it into the character.
_UNICODE_QUOTE = "\\" + "u8217?"

SAMPLE_RTF = (
    r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0 Calibri;}}{\colortbl;\red0\green0\blue0;}"
    r"{\*\generator Example 1.0}"
    r"{\info{\title Properties Title}{\subject Classroom mental health resources}"
    r"{\keywords depression, anxiety, classroom}{\author Example Author}"
    r"{\doccomm A list of pre-approved videos for classroom presentations.}"
    r"{\creatim\yr2026\mo9\dy15}\version2}" + "\r\n"
    r"\pard\s1\outlinelevel0\b Classroom Plan\b0\par" + "\r\n"
    r"\pard This paragraph has an accented caf\'e9, a curly quote " + _UNICODE_QUOTE
    + r"s, and a \{brace\}.\par" + "\r\n"
    r"\pard\outlinelevel1 Materials\par" + "\r\n"
    r"\trowd\pard\intbl Item\cell Count\cell\row" + "\r\n"
    r"\trowd\pard\intbl Poster\cell 3\cell\row" + "\r\n"
    r"\pard Last line.{\*\bkmkstart x}\par" + "\r\n"
    r'{\field{\*\fldinst HYPERLINK "https://example.org"}{\fldrslt Example site}}\par'
    r"}"
).encode("latin-1")

SAMPLE_RTF_MARKDOWN = (
    "# Classroom Plan\n\n"
    "This paragraph has an accented caf\u00e9, a curly quote \u2019s, and a {brace}.\n\n"
    "## Materials\n\n"
    "| Item | Count |\n|---|---|\n| Poster | 3 |\n\n"
    "Last line.\n\n"
    "Example site\n"
)


### PDF ###

def pdf_string(text):
    """A PDF literal string: parentheses and backslashes escaped."""
    return "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def content_stream(paragraphs):
    """
    A page's content: each paragraph is a string or a list of lines, set
    in Helvetica, with a gap larger than a line between paragraphs.
    """
    ops = ["BT", "/F1 12 Tf", "14 TL", "72 720 Td"]
    for index, paragraph in enumerate(paragraphs):
        if index:
            ops.append("0 -40 Td")
        lines = paragraph if isinstance(paragraph, (list, tuple)) else [paragraph]
        for line_index, line in enumerate(lines):
            if line_index:
                ops.append("T*")
            ops.append(pdf_string(line) + " Tj")
    ops.append("ET")
    return "\n".join(ops).encode("latin-1")


def make_pdf(pages, properties=None, outline=(), encrypted=False, prefix=b""):
    """
    A small PDF, one content stream per page, with a classic cross-reference
    table so a reader finds every object where the table says it is.

    Args:
        pages (list): one entry per page, each a list of paragraphs for
            content_stream. An empty list is a page with no text.
        properties (dict | None): document information entries by their
            PDF key without the slash, such as "Title" and "Keywords".
        outline (Sequence[tuple[int, str, int]]): bookmarks as (nesting
            level from 1, title, page index) in reading order.
        encrypted (bool): whether to add a standard security handler
            entry with placeholder keys, which is enough for a reader to
            see the file as encrypted.
        prefix (bytes): bytes to put before the header, which the format
            allows and a reader must skip.
    """
    objects = []

    def add(body):
        objects.append(body)
        return len(objects)

    catalog = add(None)
    pages_obj = add(None)
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_numbers = []
    for paragraphs in pages:
        stream = content_stream(paragraphs)
        contents = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_numbers.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (pages_obj, font, contents)
        ))
    objects[pages_obj - 1] = (
        b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % n for n in page_numbers)
        + b"] /Count %d >>" % len(page_numbers)
    )
    info = None
    if properties:
        entries = b" ".join(
            b"/%s %s" % (key.encode("ascii"), pdf_string(value).encode("latin-1"))
            for key, value in properties.items()
        )
        info = add(b"<< " + entries + b" >>")
    outlines = None
    if outline:
        # Each bookmark is an object: siblings linked by /Prev and /Next,
        # children by /First and /Last, every one naming its /Parent.
        outlines = add(None)
        entry_numbers = [add(None) for _ in outline]
        parents = {}
        children = {}
        stack = []
        for position, (level, _, _) in enumerate(outline):
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else outlines
            parents[entry_numbers[position]] = parent
            children.setdefault(parent, []).append(entry_numbers[position])
            stack.append((level, entry_numbers[position]))
        for position, (level, title, page_index) in enumerate(outline):
            number = entry_numbers[position]
            siblings = children[parents[number]]
            at = siblings.index(number)
            parts = [
                b"/Title " + pdf_string(title).encode("latin-1"),
                b"/Parent %d 0 R" % parents[number],
                b"/Dest [%d 0 R /Fit]" % page_numbers[page_index],
            ]
            if at:
                parts.append(b"/Prev %d 0 R" % siblings[at - 1])
            if at + 1 < len(siblings):
                parts.append(b"/Next %d 0 R" % siblings[at + 1])
            own = children.get(number)
            if own:
                parts.append(b"/First %d 0 R /Last %d 0 R /Count %d" % (own[0], own[-1], len(own)))
            objects[number - 1] = b"<< " + b" ".join(parts) + b" >>"
        top = children[outlines]
        objects[outlines - 1] = b"<< /Type /Outlines /First %d 0 R /Last %d 0 R /Count %d >>" % (
            top[0], top[-1], len(top),
        )
    catalog_body = b"<< /Type /Catalog /Pages %d 0 R" % pages_obj
    if outlines:
        catalog_body += b" /Outlines %d 0 R /PageMode /UseOutlines" % outlines
    objects[catalog - 1] = catalog_body + b" >>"
    encrypt = None
    if encrypted:
        encrypt = add(
            b"<< /Filter /Standard /V 1 /R 2 /Length 40 /P -1 /O <"
            + b"00" * 32 + b"> /U <" + b"00" * 32 + b"> >>"
        )

    out = bytearray(prefix + b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    trailer = b"<< /Size %d /Root %d 0 R" % (len(objects) + 1, catalog)
    if info:
        trailer += b" /Info %d 0 R" % info
    if encrypt:
        trailer += b" /Encrypt %d 0 R /ID [<" % encrypt + b"01" * 16 + b"> <" + b"01" * 16 + b">]"
    trailer += b" >>"
    out += b"trailer\n" + trailer + b"\nstartxref\n%d\n%%%%EOF\n" % xref_at
    return bytes(out)


PDF_PROPERTIES = {
    "Title": SAMPLE_PROPERTIES["title"],
    "Subject": SAMPLE_PROPERTIES["subject"],
    "Keywords": SAMPLE_PROPERTIES["keywords"],
}

# Two pages, no outline: each page gets a heading, the first line of the
# first page stands alone so it can serve as the title, and the other
# wrapped lines of a paragraph are joined by a space.
SAMPLE_PDF = make_pdf(
    [[["Youth Mental Health Resources", "for Middle School"], BODY], ["Page two text."]],
    properties=PDF_PROPERTIES,
)
SAMPLE_PDF_MARKDOWN = (
    "## Page 1\n\n"
    "Youth Mental Health Resources\n\n"
    f"for Middle School {BODY}\n\n"
    "## Page 2\n\n"
    "Page two text.\n"
)
SAMPLE_PDF_PROPERTIES_PARAGRAPH = (
    "Subject: Classroom mental health resources\n"
    "Keywords: depression, anxiety, classroom\n"
)

# Three pages with bookmarks: the headings come from the bookmarks, with
# the page each points to, and a nested bookmark is one level deeper.
OUTLINED_PDF = make_pdf(
    [["Cover text."], ["Chapter one text."], ["Section text."]],
    outline=[(1, "Chapter 1", 1), (2, "Section 1.1", 2), (1, "Chapter 2", 2)],
)
OUTLINED_PDF_MARKDOWN = (
    "Cover text.\n\n"
    "## Chapter 1 (page 2)\n\n"
    "Chapter one text.\n\n"
    "### Section 1.1 (page 3)\n\n"
    "## Chapter 2 (page 3)\n\n"
    "Section text.\n"
)

SINGLE_PAGE_PDF = make_pdf([["Only page."]])
EMPTY_PAGE_PDF = make_pdf([[]])
ENCRYPTED_PDF = make_pdf([["Secret text."]], encrypted=True)
TRUNCATED_PDF = SAMPLE_PDF[: len(SAMPLE_PDF) // 2]
JUNK_PREFIX_PDF = make_pdf([["Hello"]], prefix=b"junk\n")


### Functions Run In The Reader's Child Process ###

def sleep_reader(data):
    """A reader that never finishes in time, for the timeout test."""
    time.sleep(30)
    return data


def crash_reader(data):
    """A reader that dies without answering, for the crash test."""
    os._exit(3)
