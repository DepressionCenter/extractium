"""
Summary: A small reader for Rich Text Format files that keeps the text
runs, the paragraph breaks, the outline levels that mark headings, the
cells of simple tables, and the title, subject, keywords, and comments
from the document-information group, and drops everything else: font
and color tables, style sheets, pictures, embedded objects, headers and
footers, and any destination it does not know.
The format has no maintained pure-Python reader, and reading the text
alone needs only a few rules of the grammar, so those rules are
written here rather than taken on as a dependency.

This file is part of Extractium™
extractium/readers/rtf.py

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

from extractium.readers.documents import DocumentError, heading, paragraph, table

### Constants ###

# Destinations whose content is never text a reader wants: tables of
# fonts, colors, styles, and lists; document metadata; pictures and
# embedded objects; headers, footers, footnotes, and comments; and the
# field instruction that sits beside a field's visible result. A group
# that begins with one of these is skipped whole.
SKIPPED_DESTINATIONS = frozenset({
    "fonttbl", "colortbl", "stylesheet", "listtable", "listoverridetable",
    "revtbl", "rsidtbl", "pict", "object", "header", "footer",
    "headerl", "headerr", "headerf", "footerl", "footerr", "footerf",
    "footnote", "annotation", "atnid", "atnauthor", "xe", "tc", "fldinst",
    "pntext", "pn", "generator", "themedata", "colorschememapping",
    "latentstyles", "datastore", "xmlnstbl", "template", "userprops",
    "docvar", "bkmkstart", "bkmkend", "nesttableprops", "shpinst", "sp",
    "mmathPr", "ud",
})

# The document-information group holds the file's properties, one
# destination each; these four are kept, under the names every reader
# uses, and every other destination in the group is skipped.
INFO_PROPERTY_WORDS = {
    "title": "title", "subject": "subject", "keywords": "keywords", "doccomm": "description",
}

# Control words that stand for one character.
CHARACTER_WORDS = {
    "tab": "\t", "line": "\n", "column": "\n", "emspace": " ", "enspace": " ",
    "qmspace": " ", "bullet": "\u2022", "endash": "\u2013", "emdash": "\u2014",
    "lquote": "\u2018", "rquote": "\u2019", "ldblquote": "\u201c", "rdblquote": "\u201d",
    "zwnj": "", "zwj": "", "lbr": "\n",
}

# Control symbols (a backslash followed by one character) that stand for
# one character.
SYMBOL_CHARACTERS = {"~": "\u00a0", "-": "", "_": "\u2011", "\\": "\\", "{": "{", "}": "}"}

# Control words that end a paragraph.
PARAGRAPH_END_WORDS = frozenset({"par", "page", "sect"})

# A control word: letters, an optional signed number, and an optional
# space that belongs to the control word rather than to the text.
CONTROL_WORD_RE = re.compile(r"([A-Za-z]+)(-?\d+)? ?")

# The code page each \ansicpg value names, for the bytes written as
# \'hh escapes. Windows-1252 is what Word writes by default.
DEFAULT_CODEPAGE = "cp1252"


### Reader ###

def read_rtf(data):
    """
    The blocks of an RTF file.

    Args:
        data (bytes): the whole file, already known to start with the
            RTF header.

    Returns:
        tuple[list[Block], dict[str, str]]: headings, paragraphs, and
        tables in document order, and the title, subject, keywords, and
        description from the document-information group.

    Raises:
        DocumentError: if the groups do not balance at all, which means
            the file is not RTF however it begins.
    """
    # RTF is seven-bit text. Bytes above 127 are rare and arrive through
    # \'hh escapes, so a one-to-one decoding keeps every byte in reach.
    return _Parser(data.decode("latin-1")).run()


class _Parser:
    """
    Walks the file once, keeping a stack of group states so that a
    skipped destination ends where its group ends and a change to the
    unicode skip count applies only inside the group that made it.
    """

    def __init__(self, text):
        self.text = text
        self.position = 0
        # One entry per open group: whether it is being skipped, how many
        # characters follow each \u escape as its fallback, whether the
        # group is inside the document-information group, which property
        # its text belongs to, and whether nothing has been read from it
        # yet (a destination is named by a group's first control word).
        self.stack = [{"skip": False, "uc": 1, "info": False, "property": None, "fresh": True}]
        self.codepage = DEFAULT_CODEPAGE
        self.blocks = []
        # The file's properties, each as the characters read so far.
        self.properties = {}
        # The paragraph being built, and the table rows collected so far.
        self.parts = []
        self.outline_level = None
        self.in_table = False
        self.cells = []
        self.rows = []
        # Bytes from \'hh escapes waiting to be decoded together, and how
        # many fallback characters after a \u escape are still to be
        # dropped.
        self.pending_bytes = bytearray()
        self.skip_characters = 0
        # Whether the next control word opens a destination the reader
        # must know to keep (the \* prefix).
        self.starred = False

    ### Groups ###

    @property
    def state(self):
        return self.stack[-1]

    def run(self):
        """Reads the whole file and returns its blocks."""
        text = self.text
        length = len(text)
        while self.position < length:
            character = text[self.position]
            if character == "{":
                self.position += 1
                self.stack.append({**self.state, "fresh": True})
                self.starred = False
            elif character == "}":
                self.position += 1
                self._flush_bytes()
                if len(self.stack) == 1:
                    raise DocumentError("the RTF groups do not balance")
                self.stack.pop()
            elif character == "\\":
                self._control()
            elif character in "\r\n":
                self.position += 1
            else:
                self.position += 1
                self._character(character)
        self._end_paragraph()
        self._end_table()
        return self.blocks, {name: "".join(parts) for name, parts in self.properties.items()}

    ### Control Words And Symbols ###

    def _control(self):
        """Reads one control word or symbol at the current position."""
        text = self.text
        self.position += 1
        if self.position >= len(text):
            return
        character = text[self.position]
        if character == "'":
            digits = text[self.position + 1:self.position + 3]
            self.position += 3
            if len(digits) == 2 and all(d in "0123456789abcdefABCDEF" for d in digits):
                if self.skip_characters > 0:
                    self.skip_characters -= 1
                elif not self.state["skip"]:
                    self.pending_bytes.append(int(digits, 16))
            return
        if character == "*":
            self.position += 1
            self.starred = True
            return
        matched = CONTROL_WORD_RE.match(text, self.position)
        if matched is None:
            self.position += 1
            if not self.state["skip"] and character in SYMBOL_CHARACTERS:
                self._character(SYMBOL_CHARACTERS[character])
            return
        self.position = matched.end()
        word = matched.group(1)
        parameter = matched.group(2)
        starred = self.starred
        self.starred = False
        self._word(word, int(parameter) if parameter is not None else None, starred)

    def _word(self, word, parameter, starred):
        """Applies one control word."""
        fresh = self.state["fresh"]
        self.state["fresh"] = False
        if word in SKIPPED_DESTINATIONS or (starred and word not in ("fldrslt",)):
            self.state["skip"] = True
            return
        if word == "info":
            self.state["info"] = True
            return
        if self.state["info"] and self.state["property"] is None:
            # Inside the document-information group, each property is a
            # group of its own, named by its first control word.
            if word in INFO_PROPERTY_WORDS:
                self.state["property"] = INFO_PROPERTY_WORDS[word]
                self.properties.setdefault(self.state["property"], [])
            elif fresh:
                self.state["skip"] = True
            return
        if word == "bin":
            # Binary data follows the control word; it is never text.
            self.position += max(0, parameter or 0)
            return
        if self.state["skip"]:
            return
        self._flush_bytes()
        if word == "u":
            code = parameter or 0
            if code < 0:
                code += 65536
            self._character(chr(code) if 0 <= code < 0x110000 else "\ufffd")
            self.skip_characters = self.state["uc"]
        elif word == "uc":
            self.state["uc"] = max(0, parameter or 0)
        elif word == "ansicpg":
            self.codepage = f"cp{parameter}" if parameter else DEFAULT_CODEPAGE
        elif word in CHARACTER_WORDS:
            self._character(CHARACTER_WORDS[word])
        elif word in PARAGRAPH_END_WORDS:
            self._end_paragraph()
        elif word == "pard":
            self.outline_level = None
        elif word == "outlinelevel":
            self.outline_level = parameter if parameter is not None else 0
        elif word == "intbl":
            self.in_table = True
        elif word == "cell":
            self.cells.append(" ".join("".join(self.parts).split()))
            self.parts = []
        elif word == "row":
            self.rows.append(self.cells)
            self.cells = []
            self.parts = []
            self.in_table = False
        elif word == "trowd":
            self.in_table = True

    ### Text ###

    def _character(self, character):
        """Appends one character of text, unless it is a \\u fallback to drop."""
        self.state["fresh"] = False
        if self.state["skip"]:
            return
        if self.skip_characters > 0:
            self.skip_characters -= 1
            return
        self._flush_bytes()
        self._emit(character)

    def _flush_bytes(self):
        """Decodes the \\'hh bytes collected so far with the file's code page."""
        if not self.pending_bytes:
            return
        try:
            decoded = self.pending_bytes.decode(self.codepage, errors="replace")
        except LookupError:
            decoded = self.pending_bytes.decode(DEFAULT_CODEPAGE, errors="replace")
        self.pending_bytes = bytearray()
        self._emit(decoded)

    def _emit(self, text):
        """Adds text to the paragraph being built, or to the property being read."""
        if self.state["property"] is not None:
            self.properties[self.state["property"]].append(text)
        elif not self.state["info"]:
            self.parts.append(text)

    def _end_paragraph(self):
        """Closes the paragraph being built as a heading or a paragraph block."""
        self._flush_bytes()
        if self.state["info"]:
            return
        text = "".join(self.parts)
        self.parts = []
        if self.in_table:
            # Text inside a table reaches the blocks through \cell and
            # \row; a paragraph mark inside a cell is a line break.
            if text.strip():
                self.parts = [text, "\n"]
            return
        self._end_table()
        if not text.strip():
            return
        if self.outline_level is not None:
            self.blocks.append(heading(self.outline_level + 1, text))
        else:
            self.blocks.append(paragraph(text))

    def _end_table(self):
        """Closes the rows collected so far as one table block."""
        if self.cells:
            self.rows.append(self.cells)
            self.cells = []
        if self.rows:
            if any(any(row) for row in self.rows):
                self.blocks.append(table(self.rows))
            self.rows = []
