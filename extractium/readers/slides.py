"""
Summary: Reads PowerPoint (.pptx) and OpenDocument presentation (.odp)
files with the standard library alone. Both are zip archives of XML,
opened through the same guarded part reader as Word and OpenDocument
text files. Each slide becomes one numbered heading with the slide's
title, followed by its text and tables, and its speaker notes marked as
notes, so the chunker cuts a deck one section per slide and a citation
names the slide. Pictures are not read. The deck's own properties are
read from the same parts a text document keeps them in.

This file is part of Extractium™
extractium/readers/slides.py

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

import posixpath
import re

from extractium.readers.documents import DocumentError, heading, paragraph, table

### Constants ###

# The parts a PowerPoint archive keeps its slide order, its slide
# files, and each slide's notes in. Slides are listed in the
# presentation part by relationship id, and the relationships part maps
# each id to a slide file; a slide's own relationships part names its
# notes page the same way.
PPTX_PRESENTATION_PART = "ppt/presentation.xml"
PPTX_PRESENTATION_RELS_PART = "ppt/_rels/presentation.xml.rels"
PPTX_SLIDE_RELATIONSHIP = "/slide"
PPTX_NOTES_RELATIONSHIP = "/notesSlide"

ODF_PRESENTATION_MIMETYPE = "application/vnd.oasis.opendocument.presentation"

# The heading every slide gets, so a section names its slide whether or
# not the slide has a title.
SLIDE_HEADING_LEVEL = 2
SLIDE_LABEL = "Slide {number}"
NOTES_LABEL = "Notes: "

# XML namespaces, written the way ElementTree spells a qualified name.
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
PRESENTATION = "{urn:oasis:names:tc:opendocument:xmlns:presentation:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
TEXT_P = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p"

# Placeholders that hold a slide's furniture rather than its content: the
# slide number, the date, the header and footer, and on a notes page the
# picture of the slide itself.
PPTX_FURNITURE_PLACEHOLDERS = frozenset({"sldNum", "dt", "hdr", "ftr", "sldImg"})
PPTX_TITLE_PLACEHOLDERS = frozenset({"title", "ctrTitle"})
ODF_FURNITURE_CLASSES = frozenset({"page-number", "date-time", "header", "footer"})
ODF_TITLE_CLASSES = frozenset({"title"})

# A slide file's name, so the order the presentation lists them in can be
# checked against a relationship that points somewhere else.
PPTX_SLIDE_NAME_RE = re.compile(r"^ppt/slides/[^/]+\.xml$")


### PowerPoint ###

def read_pptx(archive, xml_part, core_properties):
    """
    The blocks of a PowerPoint deck, one numbered heading per slide.

    Args:
        archive (zipfile.ZipFile): the open archive.
        xml_part (Callable[[zipfile.ZipFile, str], Element]): the guarded
            part reader the office module uses.
        core_properties (Callable[[Element], dict]): reads the title,
            subject, keywords, and description from the core part.

    Returns:
        tuple[list[Block], dict[str, str]]: the blocks in slide order,
        and the deck's properties, with the first slide's title standing
        in for a missing title.

    Raises:
        DocumentError: if the presentation part is missing a slide list,
            or a part is refused by the guarded reader.
    """
    names = set(archive.namelist())
    properties = {}
    if "docProps/core.xml" in names:
        properties = core_properties(xml_part(archive, "docProps/core.xml"))
    blocks = []
    first_title = ""
    for number, slide_name in enumerate(_pptx_slide_names(archive, xml_part, names), start=1):
        title, body = _pptx_slide(xml_part(archive, slide_name))
        first_title = first_title or title
        blocks.append(heading(SLIDE_HEADING_LEVEL, _slide_heading(number, title)))
        blocks.extend(body)
        notes_name = _pptx_notes_name(archive, xml_part, names, slide_name)
        if notes_name is not None:
            _, notes = _pptx_slide(xml_part(archive, notes_name))
            blocks.extend(_notes_blocks(notes))
    if not (properties.get("title") or "").strip():
        properties["title"] = first_title
    return blocks, properties


def _pptx_slide_names(archive, xml_part, names):
    """The slide parts in the order the deck shows them."""
    if PPTX_PRESENTATION_PART not in names:
        raise DocumentError(f"{PPTX_PRESENTATION_PART} is missing from the archive")
    presentation = xml_part(archive, PPTX_PRESENTATION_PART)
    targets = _relationships(xml_part(archive, PPTX_PRESENTATION_RELS_PART), "ppt") \
        if PPTX_PRESENTATION_RELS_PART in names else {}
    slide_names = []
    for slide_id in presentation.iter(f"{P}sldId"):
        target = targets.get(slide_id.get(f"{R}id"), ("", ""))
        if target[0].endswith(PPTX_SLIDE_RELATIONSHIP) and PPTX_SLIDE_NAME_RE.match(target[1]) \
                and target[1] in names:
            slide_names.append(target[1])
    return slide_names


def _pptx_notes_name(archive, xml_part, names, slide_name):
    """The notes part for one slide, or None when the slide has none."""
    folder, base = posixpath.split(slide_name)
    rels_name = f"{folder}/_rels/{base}.rels"
    if rels_name not in names:
        return None
    for kind, target in _relationships(xml_part(archive, rels_name), folder).values():
        if kind.endswith(PPTX_NOTES_RELATIONSHIP) and target in names:
            return target
    return None


def _relationships(root, folder):
    """
    The relationships of one part: id to (type, target part name), with
    each target resolved against the folder the part sits in and kept
    inside the archive's own tree.
    """
    found = {}
    for relationship in root.iter(f"{REL}Relationship"):
        target = relationship.get("Target") or ""
        if relationship.get("TargetMode") == "External" or not target:
            continue
        resolved = posixpath.normpath(posixpath.join(folder, target)).lstrip("/")
        if resolved.startswith(".."):
            continue
        found[relationship.get("Id")] = (relationship.get("Type") or "", resolved)
    return found


def _pptx_slide(root):
    """
    The title and the body blocks of one slide or notes page.

    Shapes are walked in the order they sit in the part, groups
    included, so the text reads top to bottom as the author laid it out.
    Placeholders holding the slide number, the date, the header, the
    footer, or a notes page's slide picture are passed over.

    Returns:
        tuple[str, list[Block]]: the title text, empty when the slide has
        no title shape, and the other blocks.
    """
    title = ""
    blocks = []
    tree = root.find(f"{P}cSld/{P}spTree")
    if tree is None:
        return title, blocks
    for shape in _pptx_shapes(tree):
        if shape.tag == f"{P}graphicFrame":
            for grid in shape.iter(f"{A}tbl"):
                block = _pptx_table(grid)
                if block is not None:
                    blocks.append(block)
            continue
        placeholder = shape.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
        kind = placeholder.get("type", "body") if placeholder is not None else ""
        if kind in PPTX_FURNITURE_PLACEHOLDERS:
            continue
        paragraphs = _pptx_paragraphs(shape.find(f"{P}txBody"))
        if kind in PPTX_TITLE_PLACEHOLDERS and not title:
            title = " ".join(" ".join(paragraphs).split())
            continue
        blocks.extend(paragraph(text) for text in paragraphs)
    return title, blocks


def _pptx_shapes(tree):
    """Yields the text shapes and graphic frames under a shape tree, groups walked through."""
    for child in tree:
        if child.tag in (f"{P}sp", f"{P}graphicFrame"):
            yield child
        elif child.tag == f"{P}grpSp":
            yield from _pptx_shapes(child)


def _pptx_paragraphs(body):
    """
    The paragraphs of one text body, each with its runs joined, line
    breaks kept, and a bullet mark in front of a list item.
    """
    paragraphs = []
    if body is None:
        return paragraphs
    for element in body.findall(f"{A}p"):
        text = _pptx_paragraph_text(element)
        if not text.strip():
            continue
        properties = element.find(f"{A}pPr")
        bulleted = properties is not None and (
            properties.find(f"{A}buChar") is not None or properties.find(f"{A}buAutoNum") is not None
        )
        paragraphs.append(("- " + " ".join(text.split())) if bulleted else text)
    return paragraphs


def _pptx_paragraph_text(element):
    """The text of one paragraph: runs and fields in order, breaks as newlines."""
    parts = []
    for child in element:
        if child.tag in (f"{A}r", f"{A}fld"):
            text = child.find(f"{A}t")
            parts.append("".join(text.itertext()) if text is not None else "")
        elif child.tag == f"{A}br":
            parts.append("\n")
    return "".join(parts)


def _pptx_table(grid):
    """A table block from a slide's table, or None when every cell is empty."""
    rows = []
    for row in grid.findall(f"{A}tr"):
        cells = []
        for cell in row.findall(f"{A}tc"):
            cells.append(" ".join(" ".join(text.split()) for text in _pptx_paragraphs(cell.find(f"{A}txBody"))))
        rows.append(cells)
    return table(rows) if any(any(row) for row in rows) else None


### OpenDocument ###

def read_odp(root, odf_walk, odf_text):
    """
    The blocks of an OpenDocument presentation, one numbered heading per
    page.

    Args:
        root (Element): the parsed content part.
        odf_walk (Callable[[Element], Iterator[Block]]): the office
            module's walker for paragraphs, lists, and tables.
        odf_text (Callable[[Element], str]): the office module's reader
            for one paragraph's text.

    Returns:
        tuple[list[Block], str]: the blocks in page order, and the first
        page's title, for the caller to use when the file declares none.

    Raises:
        DocumentError: if the content part holds no presentation body.
    """
    body = root.find(f"{OFFICE}body/{OFFICE}presentation")
    if body is None:
        raise DocumentError("content.xml holds no presentation body")
    blocks = []
    first_title = ""
    for number, page in enumerate(body.findall(f"{DRAW}page"), start=1):
        notes_element = page.find(f"{PRESENTATION}notes")
        notes_frames = set(map(id, notes_element.iter(f"{DRAW}frame"))) if notes_element is not None else set()
        title = ""
        body_blocks = []
        for frame in page.iter(f"{DRAW}frame"):
            if id(frame) in notes_frames:
                continue
            kind = frame.get(f"{PRESENTATION}class") or ""
            if kind in ODF_FURNITURE_CLASSES:
                continue
            if kind in ODF_TITLE_CLASSES and not title:
                title = " ".join(" ".join(odf_text(p) for p in frame.iter(TEXT_P)).split())
                continue
            body_blocks.extend(odf_walk(frame))
        notes = []
        if notes_element is not None:
            for frame in notes_element.iter(f"{DRAW}frame"):
                if (frame.get(f"{PRESENTATION}class") or "") not in ODF_FURNITURE_CLASSES:
                    notes.extend(odf_walk(frame))
        first_title = first_title or title
        blocks.append(heading(SLIDE_HEADING_LEVEL, _slide_heading(number, title)))
        blocks.extend(body_blocks)
        blocks.extend(_notes_blocks(notes))
    return blocks, first_title


### Shared ###

def _slide_heading(number, title):
    """The heading text for one slide: its number, and its title when it has one."""
    label = SLIDE_LABEL.format(number=number)
    return f"{label}: {title}" if title else label


def _notes_blocks(blocks):
    """
    The speaker notes of one slide as a single marked paragraph, so a
    reader can tell what was said from what was shown. Tables in notes
    are kept as tables after it.
    """
    lines = []
    tables = []
    for block in blocks:
        if block.kind == "table":
            tables.append(block)
        elif block.text.strip():
            lines.append(" ".join(block.text.split()))
    result = []
    if lines:
        result.append(paragraph(NOTES_LABEL + "\n".join(lines)))
    result.extend(tables)
    return result
