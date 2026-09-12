"""
Summary: The `okf` source: reads an Open Knowledge Format bundle, a folder
of Markdown files with YAML front matter such as the okf adapter writes,
and yields one Document per concept file, addressed at the resource the
front matter names. Two knowledge bases built by any tool that follows
the format can be merged through one build this way.

This file is part of Extractium™
extractium/sources/okf.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-12
Last Modified: 2026-09-12
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
__date__ = "2026-09-12"

import pathlib
import re
import urllib.parse

import yaml

from extractium.adapters.okf import CONCEPT_TYPES, INDEX_FILE, LOG_FILE
from extractium.core.models import LOCAL_URL_PREFIX, Document
from extractium.sources.local import files_inside
from extractium.core.chunk import markdown_text_to_soup

### Constants ###

# Every concept file is Markdown; the two reserved files at the bundle
# root are an index and a log, not concepts.
CONCEPT_GLOBS = ("**/*.md",)
RESERVED_FILES = frozenset({INDEX_FILE, LOG_FILE})

# The front-matter block: a fence, the YAML, a fence, at the top of the file.
FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)

# The lines the okf adapter writes between the front matter and the text:
# the title as a heading, and the address the page was read from. Both
# repeat what the front matter holds, so they are not indexed twice.
TITLE_LINE_RE = re.compile(r"^\s{0,3}#\s+.*$")
SOURCE_LINE_RE = re.compile(r"^Source:\s+\[.*\]\(.*\)\s*$")

# A concept's `type` names its kind in words; this is the okf adapter's
# table read the other way, so a page keeps its content type across a
# write and a read. A type this table does not know is an ordinary page.
CONTENT_TYPES_BY_CONCEPT = {concept: content for content, concept in CONCEPT_TYPES.items()}
DEFAULT_CONTENT_TYPE = "page"

# Only these schemes are recorded as a document's address. Anything else
# in a `resource` field is refused, so a bundle cannot make a build record
# a file path or a script address as a page.
ALLOWED_SCHEMES = ("http", "https")


### Reading One Concept ###

def split_front_matter(text):
    """
    Splits a concept file into its front-matter fields and its body.

    Args:
        text (str): the file's content.

    Returns:
        tuple[dict | None, str]: the fields, or None when the file has no
        front matter or it does not parse to a mapping, and the body.
    """
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return None, text
    try:
        fields = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None, text[match.end():]
    if not isinstance(fields, dict):
        return None, text[match.end():]
    return fields, text[match.end():]


def body_text(body):
    """
    The concept's text without the title heading and the source line the
    okf adapter writes above it, which repeat the front matter.

    Args:
        body (str): everything after the front matter.

    Returns:
        str: the Markdown to index.
    """
    lines = body.lstrip("\r\n").split("\n")
    if lines and TITLE_LINE_RE.match(lines[0]):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    if lines and SOURCE_LINE_RE.match(lines[0]):
        lines = lines[1:]
    return "\n".join(lines).strip()


def checked_resource(value):
    """
    The address a concept was read from, or None when it is not one.

    Args:
        value: the front matter's `resource` field.

    Returns:
        str | None: an http(s) address, or a "local:" address, or None.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    resource = value.strip()
    if resource.startswith(LOCAL_URL_PREFIX):
        return resource if len(resource) > len(LOCAL_URL_PREFIX) else None
    parsed = urllib.parse.urlsplit(resource)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        return None
    return resource


def document_from_concept(text):
    """
    One concept file as a Document, or None with the reason it was not.

    A concept read from a local folder by the build that wrote the bundle
    carries a "local:" address, and stays marked local here, so every
    output drops it unless the output opted in. A concept read from a
    public address is not local: the bundle is a copy of published pages.

    Args:
        text (str): the file's content.

    Returns:
        tuple[Document | None, str]: the document, or None and why.
    """
    fields, body = split_front_matter(text)
    if fields is None:
        return None, "no front matter"
    resource = checked_resource(fields.get("resource"))
    if resource is None:
        return None, "no readable resource address in the front matter"
    title = fields.get("title")
    if not isinstance(title, str) or not title.strip():
        return None, "no title in the front matter"
    markdown = body_text(body)
    if not markdown:
        return None, "no text"
    local = resource.startswith(LOCAL_URL_PREFIX)
    return Document(
        url=resource,
        title=title.strip(),
        content=markdown_text_to_soup(markdown, resource),
        source_type="local" if local else "web",
        content_type=CONTENT_TYPES_BY_CONCEPT.get(fields.get("type"), DEFAULT_CONTENT_TYPE),
        local=local,
    ), ""


### Source ###

class OkfSource:
    """
    Reads an Open Knowledge Format bundle from a folder.

    Args:
        options (Mapping): the validated options of an `okf` entry: `path`,
            the bundle folder.
    """

    name = "okf"

    def __init__(self, options):
        self.path = pathlib.Path(options["path"])
        self.read = 0
        self.skipped = 0

    def fetch(self, session, cache, progress):
        """
        Yields one Document per readable concept file in the bundle.

        Args:
            session: unused; a bundle is read from disk.
            cache: unused; there is nothing to revalidate.
            progress (Callable[[str], None]): receives one line per file
                read and one per file skipped, with the reason.

        Yields:
            extractium.core.models.Document: one per concept.
        """
        root = self.path.resolve()
        if not root.is_dir():
            progress(f"  skipped (not a folder): {self.path}")
            return
        for file in files_inside(root, CONCEPT_GLOBS, progress):
            relative = file.relative_to(root).as_posix()
            if relative in RESERVED_FILES:
                continue
            try:
                text = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                self.skipped += 1
                progress(f"  skipped (could not be read: {e}): {relative}")
                continue
            document, reason = document_from_concept(text)
            if document is None:
                self.skipped += 1
                progress(f"  skipped ({reason}): {relative}")
                continue
            self.read += 1
            progress(f"  read: {relative}")
            yield document

    def summary_lines(self):
        """One line saying how many concepts were read and skipped."""
        if not (self.read or self.skipped):
            return []
        return [f"{self.read} concept(s) read from the bundle, {self.skipped} skipped"]
