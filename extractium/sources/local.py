"""
Summary: The local-filesystem source. Reads Markdown, plain-text, and HTML
files under a configured folder and yields one Document per file, every one
marked local so the adapter guardrail keeps it out of published outputs.
This is the one source whose content may never have been published, which
is why the whole confidentiality rule exists. See docs/extractium-spec.md
section 7.

This file is part of Extractium™
extractium/sources/local.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
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
__date__ = "2026-08-17"

import pathlib
import re

from bs4 import BeautifulSoup

from extractium.core.models import LOCAL_URL_PREFIX, Document
from extractium.sources.generic import GENERIC_CONTENT_SELECTORS, page_title, select_content

### Constants ###

# Suffixes read as HTML. Everything else is handed over as text, and the
# chunker renders a Markdown file and wraps a plain-text one.
HTML_SUFFIXES = (".html", ".htm")

# Suffixes rendered as Markdown by the chunker, which decides from the URL.
MARKDOWN_SUFFIXES = (".md", ".markdown")

# Content node selectors for a local HTML file: the same ones any web page
# gets, with the whole body as the last resort. A file exported from a word
# processor or a wiki often has no article container at all, and its body is
# then the content rather than page chrome.
LOCAL_CONTENT_SELECTORS = GENERIC_CONTENT_SELECTORS + ("body",)

# The first Markdown heading of a file, used as its title.
MARKDOWN_TITLE_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


### Reading Files ###

def relative_url(root, path):
    """
    The URL recorded for one file: the marker prefix and the file's path
    relative to the source folder, with forward slashes on every platform.

    The folder someone points the build at is often under their own home
    directory, and its name can identify a person or a study on its own, so
    the absolute path is dropped here and never travels any further.

    Args:
        root (pathlib.Path): the resolved source folder.
        path (pathlib.Path): the resolved file.

    Returns:
        str: for example, "local:notes/intake.md".
    """
    return LOCAL_URL_PREFIX + path.relative_to(root).as_posix()


def title_for(path, text):
    """
    A display title for one file: the page title of an HTML file, the first
    heading of a Markdown file, and otherwise the file name without its
    suffix.

    Args:
        path (pathlib.Path): the file.
        text (str): its content.

    Returns:
        str: a non-blank title.
    """
    suffix = path.suffix.lower()
    if suffix in HTML_SUFFIXES:
        return page_title(BeautifulSoup(text, "html.parser")) or path.stem
    if suffix in MARKDOWN_SUFFIXES:
        heading = MARKDOWN_TITLE_RE.search(text)
        if heading:
            return heading.group(1)
    return path.stem


def content_for(path, text):
    """
    The content one file contributes, in the form the chunker expects.

    An HTML file is parsed and reduced to its content node, so navigation
    and page chrome are dropped exactly as they are for a crawled page.
    Every other file is handed over as text; the chunker renders Markdown
    and wraps plain text, deciding from the URL suffix.

    Args:
        path (pathlib.Path): the file.
        text (str): its content.

    Returns:
        bs4.Tag | str | None: the content node or the text, or None when an
        HTML file holds no content node at all.
    """
    if path.suffix.lower() not in HTML_SUFFIXES:
        return text
    soup = BeautifulSoup(text, "html.parser")
    return select_content(soup, LOCAL_CONTENT_SELECTORS, require_text=True)


def content_type_for(path):
    """
    The CONTENT_TYPES value recorded on parents from one file: `page` for
    HTML, `text` for everything else.
    """
    return "page" if path.suffix.lower() in HTML_SUFFIXES else "text"


def files_inside(root, globs, progress):
    """
    Every file the glob patterns select under a folder, in a stable order,
    with anything reached from outside the folder refused.

    A pattern, or a symbolic link inside the folder, can name a file
    somewhere else entirely. Reading one would pull content from a part
    of the disk nobody asked to index, so a file whose real location is
    outside the folder is reported and skipped rather than read.

    Args:
        root (pathlib.Path): the resolved folder.
        globs (Iterable[str]): glob patterns relative to it.
        progress (Callable[[str], None]): receives one line per refusal.

    Returns:
        list[pathlib.Path]: resolved file paths, sorted so two runs of
        the same folder produce the same order.
    """
    found = {}
    for pattern in globs:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                progress(f"  skipped (outside the source folder): {path.name}")
                continue
            found[resolved] = None
    return sorted(found, key=lambda path: path.relative_to(root).as_posix())


### Source ###

class LocalSource:
    """
    Reads files from a folder on the machine running the build.

    Every document it yields is marked `local`, which the adapter base turns
    into the rule that no output may contain it unless that output set
    `include_local: true`. The `local:` URL prefix and the flag are checked
    against each other by the Document record itself, so neither can be set
    without the other.

    This source requests nothing over the network. It takes the session and
    the cache because every source does, and it uses neither.
    """

    name = "local"

    def __init__(self, options):
        """
        Args:
            options (Mapping): the validated options of the source's entry:
                `path`, the folder to read, and `include_globs`, the
                patterns deciding which files under it are read.
        """
        self.path = options["path"]
        self.include_globs = tuple(options["include_globs"])

    def matching_files(self, root, progress):
        """
        Every file the include patterns select, in a stable order, with
        anything reached from outside the folder refused.

        A pattern, or a symbolic link inside the folder, can name a file
        somewhere else entirely. Reading one would pull content from a part
        of the disk nobody asked to index, so a file whose real location is
        outside the folder is reported and skipped rather than read.

        Args:
            root (pathlib.Path): the resolved source folder.
            progress (Callable[[str], None]): receives one line per refusal.

        Returns:
            list[pathlib.Path]: resolved file paths, sorted so two runs of
            the same folder produce the same order.
        """
        return files_inside(root, self.include_globs, progress)

    def fetch(self, session, cache, progress):
        """
        Yields one Document per readable file under the configured folder.

        Args:
            session: unused; a local file is not requested over the network.
            cache: unused; the fetch cache exists for HTTP validators.
            progress (Callable[[str], None]): receives one line per file
                read and one per file skipped, with the reason.

        Yields:
            extractium.core.models.Document: one per file, `local` set.

        Raises:
            FileNotFoundError: if the configured folder does not exist. A
                mistyped path would otherwise look like an empty folder and
                produce a build that quietly indexed nothing.
        """
        root = pathlib.Path(self.path).expanduser()
        if not root.is_dir():
            raise FileNotFoundError(
                f"the local source folder {self.path!r} does not exist or is not a folder."
            )
        root = root.resolve()
        progress(f"Reading local files under {len(self.include_globs)} pattern(s).")

        for path in self.matching_files(root, progress):
            url = relative_url(root, path)
            try:
                # Replacement rather than failure: one file saved in another
                # encoding should not lose a whole build, and the text that
                # survives is still worth indexing and worth scanning.
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                progress(f"  skipped (could not be read: {e.strerror or e}): {url}")
                continue
            if not text.strip():
                progress(f"  skipped (empty): {url}")
                continue
            content = content_for(path, text)
            if content is None:
                progress(f"  skipped (no content found): {url}")
                continue
            progress(f"  read: {url}")
            yield Document(
                url=url,
                title=title_for(path, text),
                content=content,
                source_type="local",
                content_type=content_type_for(path),
                local=True,
            )
