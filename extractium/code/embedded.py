"""
Summary: Pulls code out of the files that hold another language inside
them -- Jupyter notebooks, R Markdown and Quarto, Lua Server Pages, and
HTML -- and hands back the prose separately from the blocks. A notebook's
stored outputs are never read: they can hold printed rows of real
participant data, and nothing in this project needs them. See
docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/code/embedded.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-10
Last Modified: 2026-09-10
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
__date__ = "2026-09-10"

import json
import re
from dataclasses import dataclass

from extractium.code import languages

### What Comes Out Of A Container ###


@dataclass(frozen=True)
class Block:
    """
    One run of code found inside a container file.

    Attributes:
        language (str): the language registry name the block is written
            in, or an empty string when the container did not say and it
            cannot be read from the file.
        text (str): the block's source.
        start_line (int): the line of the container the block starts on,
            counting from 1, so a symbol found in the block can be
            reported at its line in the file a reader will open.
    """

    language: str
    text: str
    start_line: int = 1


@dataclass(frozen=True)
class Contents:
    """
    What one container file holds.

    Attributes:
        kind (str): "notebook", "rmarkdown", "lua_server_pages", or
            "html".
        prose (str): the text a reader would read, with the code taken
            out. Indexed as documentation.
        blocks (tuple[Block, ...]): the code, in the order it appears.
        title (str): a heading read out of the file, when it has one.
    """

    kind: str
    prose: str = ""
    blocks: tuple = ()
    title: str = ""

    def __post_init__(self):
        object.__setattr__(self, "blocks", tuple(self.blocks))


### Limits ###

# A notebook larger than this is not read. The ceiling is generous for a
# file of prose and code, and it keeps one enormous stored output -- an
# embedded image, a printed table of a million rows -- from being decoded
# only to be thrown away.
MAX_NOTEBOOK_BYTES = 20_000_000

# The most cells or chunks read from one file. A generated notebook can
# hold thousands, and what a reader wants from one is its shape.
MAX_BLOCKS = 500


### Names A Container Uses For A Language ###

# What a notebook kernel or a chunk label calls a language, mapped to the
# registry name. A name not listed here is looked up directly, so a
# notebook declaring "python" or a chunk labelled "sql" needs no entry.
LANGUAGE_ALIASES = {
    "python3": "python", "ipython": "python", "ipython3": "python",
    "sh": "bash", "shell": "bash", "zsh": "bash",
    "node": "javascript", "js": "javascript", "ts": "typescript",
    "c#": "csharp", "cs": "csharp", "c_sharp": "csharp",
    "rscript": "r", "irkernel": "r",
    "octave": "matlab",
    "pwsh": "powershell", "posh": "powershell",
}


def language_named(label):
    """
    The registry language a container's label names, or None.

    Args:
        label (str): whatever the file called it -- a kernel name, a
            chunk label, a script type.
    """
    cleaned = (label or "").strip().lower()
    if not cleaned:
        return None
    return languages.language_named(LANGUAGE_ALIASES.get(cleaned, cleaned))


### Jupyter Notebooks ###

def read_notebook(text):
    """
    A notebook's Markdown cells as prose and its code cells as blocks.

    Stored outputs are not read. A notebook in this field can hold
    printed rows of real participant data in its outputs, and no part of
    this project needs them, so they are never decoded, never indexed,
    and never cached.

    Args:
        text (str): the file's content.

    Returns:
        Contents | None: None when the file is not a notebook this can
        read. A notebook is a file somebody else wrote, so a file that
        claims the extension and holds something else is refused rather
        than trusted.
    """
    if len(text) > MAX_NOTEBOOK_BYTES:
        return None
    try:
        notebook = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(notebook, dict):
        return None

    default = _notebook_language(notebook.get("metadata"))
    prose = []
    blocks = []
    line = 1
    cells = notebook.get("cells")
    for cell in cells if isinstance(cells, list) else ():
        if not isinstance(cell, dict) or len(blocks) >= MAX_BLOCKS:
            continue
        source = _cell_source(cell.get("source"))
        if not source.strip():
            continue
        kind = cell.get("cell_type")
        if kind == "markdown":
            prose.append(source)
        elif kind == "code":
            blocks.append(Block(language=default, text=source, start_line=line))
        line += source.count("\n") + 1
    return Contents(kind="notebook", prose="\n\n".join(prose), blocks=blocks)


def _notebook_language(metadata):
    """The language a notebook's kernel writes, or an empty string."""
    if not isinstance(metadata, dict):
        return ""
    for section, key in (("kernelspec", "language"), ("language_info", "name"),
                         ("kernelspec", "name")):
        block = metadata.get(section)
        if isinstance(block, dict) and isinstance(block.get(key), str):
            spec = language_named(block[key])
            if spec is not None:
                return spec.name
    return ""


def _cell_source(source):
    """
    One cell's source, whichever of the two shapes the file uses.

    The notebook format allows a string or a list of strings, and a file
    written by hand may hold either. Anything else is not source and is
    left alone.
    """
    if isinstance(source, str):
        return source
    if isinstance(source, list):
        return "".join(part for part in source if isinstance(part, str))
    return ""


### R Markdown And Quarto ###

# A chunk opens with a fence and a label in braces: ```{r setup} or
# ```{python}. Everything up to the closing fence is code.
CHUNK_OPEN = re.compile(r"^[ \t]*(?:```|~~~)\s*\{([^}]*)\}\s*$")
CHUNK_CLOSE = re.compile(r"^[ \t]*(?:```|~~~)\s*$")

# The first word of a chunk label is its language: "r setup, echo=FALSE"
# is an R chunk.
CHUNK_LANGUAGE = re.compile(r"^\s*([A-Za-z0-9_#+.-]+)")

# A title written in the file's own front matter.
FRONT_MATTER_TITLE = re.compile(r"^title:\s*[\"']?(.+?)[\"']?\s*$", re.M)

# The front matter itself: settings for whatever renders the document,
# read for the title and then kept out of the prose.
FRONT_MATTER = re.compile(r"\A---\r?\n.*?\r?\n---[ \t]*\r?\n", re.S)


def read_rmarkdown(text):
    """
    An R Markdown or Quarto file's prose and its code chunks.

    Args:
        text (str): the file's content.

    Returns:
        Contents: the prose with the chunks removed, and one block per
        chunk, each labelled with the language its fence declared.
    """
    prose = []
    blocks = []
    collecting = None
    body = []
    start = 1
    for number, line in enumerate(text.splitlines(), start=1):
        if collecting is None:
            opened = CHUNK_OPEN.match(line)
            if opened and len(blocks) < MAX_BLOCKS:
                label = CHUNK_LANGUAGE.match(opened.group(1))
                spec = language_named(label.group(1)) if label else None
                collecting = spec.name if spec is not None else ""
                body = []
                start = number + 1
                continue
            prose.append(line)
        elif CHUNK_CLOSE.match(line):
            blocks.append(Block(language=collecting, text="\n".join(body), start_line=start))
            collecting = None
        else:
            body.append(line)
    if collecting is not None and body:
        blocks.append(Block(language=collecting, text="\n".join(body), start_line=start))

    title = FRONT_MATTER_TITLE.search(text)
    return Contents(
        kind="rmarkdown",
        prose=FRONT_MATTER.sub("", "\n".join(prose)).strip(),
        blocks=blocks,
        title=title.group(1).strip() if title else "",
    )


### Lua Server Pages ###

# A Lua Server Page is an HTML page with Lua between delimiters, the way
# PHP works. Both delimiter families that CGILua documents are read:
# <?lua ... ?> with its short forms, and the <% ... %> pair. An equals
# sign after the opening delimiter means "print this expression", which
# is still Lua and is read as Lua.
LUA_BLOCK = re.compile(r"<\?(?:lua)?=?(.*?)\?>|<%=?(.*?)%>", re.S)


def read_lua_server_pages(text):
    """
    A Lua Server Page's markup as prose and its Lua as blocks.

    Nothing is run to read one. The delimiters are found, each block is
    handed to the Lua grammar, and what is left is the page a reader
    sees.

    Args:
        text (str): the file's content.

    Returns:
        Contents: the page text and one block per Lua run.
    """
    blocks = []
    markup = []
    position = 0
    for match in LUA_BLOCK.finditer(text):
        if len(blocks) >= MAX_BLOCKS:
            break
        markup.append(text[position:match.start()])
        code = match.group(1) if match.group(1) is not None else match.group(2)
        if code and code.strip():
            blocks.append(Block(
                language="lua",
                text=code,
                start_line=text.count("\n", 0, match.start()) + 1,
            ))
        position = match.end()
    markup.append(text[position:])
    page = read_html("".join(markup))
    return Contents(
        kind="lua_server_pages", prose=page.prose, blocks=blocks, title=page.title,
    )


### HTML ###

# A script element without a type, or with a JavaScript type, holds code.
# One holding JSON, a template, or an import map does not, and parsing it
# as JavaScript would produce nonsense.
SCRIPT_ELEMENT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
SCRIPT_TYPE = re.compile(r"""type\s*=\s*["']?([^"'\s>]+)""", re.I)
SCRIPT_SOURCE = re.compile(r"""\bsrc\s*=""", re.I)
JAVASCRIPT_TYPES = frozenset({
    "text/javascript", "application/javascript", "module", "text/babel",
    "text/jsx", "application/ecmascript",
})
TAG = re.compile(r"<[^>]+>")
STYLE_ELEMENT = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.I | re.S)
HTML_TITLE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.I | re.S)
BLANK_RUN = re.compile(r"\n{3,}")


def read_html(text):
    """
    An HTML page's text as prose and its inline scripts as blocks.

    Args:
        text (str): the file's content.

    Returns:
        Contents: the page text and one block per inline script.
    """
    blocks = []
    for match in SCRIPT_ELEMENT.finditer(text):
        if len(blocks) >= MAX_BLOCKS:
            break
        attributes, code = match.group(1), match.group(2)
        if SCRIPT_SOURCE.search(attributes):
            continue                      # the code is in another file
        declared = SCRIPT_TYPE.search(attributes)
        if declared and declared.group(1).lower() not in JAVASCRIPT_TYPES:
            continue
        if code.strip():
            blocks.append(Block(
                language="javascript",
                text=code,
                start_line=text.count("\n", 0, match.start(2)) + 1,
            ))

    stripped = SCRIPT_ELEMENT.sub(" ", text)
    stripped = STYLE_ELEMENT.sub(" ", stripped)
    prose = BLANK_RUN.sub("\n\n", TAG.sub(" ", stripped))
    prose = "\n".join(line.strip() for line in prose.splitlines())
    title = HTML_TITLE.search(text)
    return Contents(
        kind="html",
        prose=BLANK_RUN.sub("\n\n", prose).strip(),
        blocks=blocks,
        title=TAG.sub("", title.group(1)).strip() if title else "",
    )


### The One Way In ###

READERS = {
    "notebook": read_notebook,
    "rmarkdown": read_rmarkdown,
    "lua_server_pages": read_lua_server_pages,
    "html": read_html,
}


def read(path, text):
    """
    What a container file holds, or None when the file is not one.

    Args:
        path (str): the repository-relative path, which says what kind of
            container the file is.
        text (str): its content.

    Returns:
        Contents | None: the prose and the code blocks, or None when the
        path names no container or the file could not be read as one.
    """
    kind = languages.container_for_path(path)
    reader = READERS.get(kind)
    return reader(text) if reader else None
