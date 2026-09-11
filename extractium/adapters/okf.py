"""
Summary: The Open Knowledge Format (OKF v0.2) adapter. Writes a folder of
plain Markdown: one concept file per indexed page, with YAML front matter
(type, title, description, resource, tags, generated, sources), a root
index.md that lists every concept grouped by the source it came from, and
a log.md naming the build that wrote the folder. OKF defines no archive
packaging, so a directory is all this adapter writes. Nothing here knows
which kind of source produced a page. See
https://github.com/GoogleCloudPlatform/open-knowledge-format and
docs/extractium-spec.md section 4.

This file is part of Extractium™
extractium/adapters/okf.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-11
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

import hashlib
import re

import yaml

from extractium import __version__
from extractium.adapters.base import (
    count_of,
    excerpt,
    link,
    output_compendium,
    page_address,
    page_title,
    prepare_out_dir,
    section_title,
)

### Constants ###

# Folder written under the build's output folder. The bundle is a folder
# rather than a single file because that is what the format is: every
# concept is its own Markdown document, and the reserved index and log
# files sit beside them at the root.
BUNDLE_DIR = "okf"

# The two file names the format reserves (specification sections 8 and 9).
INDEX_FILE = "index.md"
LOG_FILE = "log.md"

# The version of the format this folder is written to. It is declared in
# the root index file, the only place the format allows front matter on an
# index.
OKF_VERSION = "0.2"

# Value of the `by` field under `generated`. The format asks for
# "<producer>/<version>" so a reader can tell which tool, at which
# version, last changed a concept.
PRODUCER = f"extractium/{__version__}"

# The `type` of a concept: the only field the format requires. Keyed on
# the record's content type, which is a core vocabulary rather than
# anything a particular source invents, so the same page yields the same
# type whichever source read it. Type names are not registered anywhere
# centrally, so these are chosen to read plainly to a person.
CONCEPT_TYPES = {
    "article": "Knowledge Base Article",
    "readme": "Project README",
    "wiki": "Wiki Page",
    "release_notes": "Release Notes",
    "page": "Web Page",
    "text": "Text Document",
    "video_transcript": "Video Transcript",
    "manifest": "Project Manifest",
    "repo_map": "Repository Map",
    "code_file": "Code File",
    "code_symbol": "Code Symbol",
}

# Used when a record carries a content type this adapter has no name for,
# which is what a plugin adding its own vocabulary would produce.
DEFAULT_CONCEPT_TYPE = "Document"

# Everything outside this set is replaced when a title becomes a file or
# folder name. An allowlist, so a name built from a crawled title can hold
# no path separator, no parent-folder step, and no character a file system
# elsewhere would refuse.
UNSAFE_IN_NAME = re.compile(r"[^a-z0-9]+")

# Strips the scheme from an address, so the part a person recognizes can
# be read off the end of what remains. Covers both an address with a host
# ("https://example.org/a") and the "local:" form a file read from a
# folder carries.
ADDRESS_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:(?://)?")

# Longest a single name may be before the address digest is appended.
# Keeps the whole path well inside the limits of a file system that stops
# at 260 characters.
MAX_NAME_CHARS = 60

# Hexadecimal characters of the address digest appended to every concept
# file name, so two pages with the same title stay two files. Lengthened,
# deterministically, on the vanishingly rare occasion that two addresses
# agree over this many characters.
NAME_DIGEST_CHARS = 8

# Names a file cannot take on Windows, whatever its extension, plus the
# two the format reserves for itself. A page titled "Aux" or "Index" is
# unremarkable; a file of that name is not.
RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", "index", "log"}
    | {f"com{digit}" for digit in range(1, 10)}
    | {f"lpt{digit}" for digit in range(1, 10)}
)

# Used when a title, or a source's name, holds nothing that survives the
# allowlist above -- a title written entirely in a non-Latin script, for
# instance. The address digest still tells the files apart.
FALLBACK_NAME = "concept"

# Heading of the log file, and the word that opens the entry every build
# writes. The format groups log entries under a date heading and treats
# the leading bold word as a convention rather than a rule.
LOG_HEADING = "Update Log"
LOG_ENTRY_WORD = "Build"

# Named in the index file so a reader knows what produced the folder and
# under what terms. The indexed text keeps whatever license its own source
# carries.
LICENSE_LINE = (
    "Compiled by Extractium (https://github.com/DepressionCenter/extractium), "
    "copyright (c) 2026 The Regents of the University of Michigan, licensed under "
    "the GNU General Public License v3.0 or later. The indexed content remains "
    "under the license of the source it was read from."
)

# What the folder is, for a reader who opened it with no context.
INDEX_ORIENTATION = (
    "This folder is an Open Knowledge Format bundle. Every Markdown file beside "
    "this one is a single concept: one page of the knowledge base, with its "
    "address and its description in the block at the top of the file.",
    "Each section below names one of the sources this knowledge base was built "
    "from. The entries under it link to the concepts that came from that source.",
)


### Page Grouping ###

def pages_with_sections(parents):
    """
    The indexed content as pages, each holding the sections it was split
    into.

    Grain: one entry per page. A page that ran long became several
    parents at build time, and the format asks for one document per
    concept, so those sections are gathered back into one file. A video
    is one concept too: every stretch of its transcript becomes a section
    of the one file, in time order, rather than a file each.

    Args:
        parents (Iterable[extractium.core.models.Parent]): the parents this
            output may write, in build order.

    Returns:
        list[dict]: url, title, source_label, content_type, categories,
        and sections (a list of (heading, text) pairs), in the order each
        address first appears.
    """
    pages = {}
    for parent in parents:
        address = page_address(parent)
        page = pages.get(address)
        if page is None:
            page = pages[address] = {
                "url": address,
                "title": page_title(parent.t),
                "source_label": parent.source_label,
                "content_type": parent.content_type,
                "categories": tuple(parent.categories),
                "sections": [],
            }
        page["sections"].append((section_title(parent.t), parent.x))
    return list(pages.values())


def page_text(page):
    """Every section of a page as one block of text, in build order."""
    return "\n\n".join(text for _, text in page["sections"])


### File Names ###

def safe_name(text, fallback=FALLBACK_NAME):
    """
    A file or folder name built from text nobody here controls.

    Only lowercase letters, digits, and single hyphens survive, so a name
    can hold no path separator, no parent-folder step, and no character
    another file system would refuse. A name that would collide with one
    the operating system or the format reserves gains a trailing hyphen.

    Args:
        text (str): a page title, or the name of a source.
        fallback (str): the name to use when nothing survives, such as for
            a title written entirely outside the Latin alphabet.

    Returns:
        str: a name safe to join to a path, never empty.
    """
    name = UNSAFE_IN_NAME.sub("-", text.lower()).strip("-")
    if len(name) > MAX_NAME_CHARS:
        cut = name.rfind("-", 0, MAX_NAME_CHARS)
        name = name[:cut if cut > 0 else MAX_NAME_CHARS].strip("-")
    if not name:
        return fallback
    return f"{name}-" if name in RESERVED_NAMES else name


def address_digest(url, length=NAME_DIGEST_CHARS):
    """
    A short, stable digest of an address, used to keep two pages with the
    same title in two files.

    Not a security control: it identifies a file, and nothing is decided
    from it.

    Args:
        url (str): the page's address.
        length (int): hexadecimal characters to keep.

    Returns:
        str: the first `length` characters of the SHA-1 digest.
    """
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:length]


def address_tail(url):
    """
    The last meaningful part of an address: the file name, or the last
    folder, or the site itself.

    Args:
        url (str): the page's address, of any scheme, including the
            "local:" form a file read from a folder carries.

    Returns:
        str: that part, or an empty string when the address has none.
    """
    without_target = url.split("#", 1)[0].split("?", 1)[0]
    without_scheme = ADDRESS_SCHEME.sub("", without_target)
    segments = [segment for segment in without_scheme.split("/") if segment]
    return segments[-1] if segments else ""


def display_titles(pages):
    """
    A name for each page that tells it apart from the others.

    Whole documentation sites give every page the same first heading, so
    the title alone would name eighteen files "Extractium" and leave a
    reader eighteen identical links to choose between. Where a title is
    shared, the end of the address is added to it, which is the part a
    person recognizes: a file name, or the last folder.

    Args:
        pages (Sequence[dict]): the records pages_with_sections returned.

    Returns:
        list[str]: one name per page, in the same order.
    """
    shared = {}
    for page in pages:
        shared[page["title"]] = shared.get(page["title"], 0) + 1
    names = []
    for page in pages:
        tail = address_tail(page["url"])
        if shared[page["title"]] > 1 and tail:
            names.append(f"{page['title']} ({tail})")
        else:
            names.append(page["title"])
    return names


def bundle_paths(pages):
    """
    Where each page is written inside the bundle.

    Pages are filed under the name of the source they came from, so the
    folder can be read by hand as well as by a program, and the grouping
    matches the sections of the index file.

    Args:
        pages (Sequence[dict]): the records pages_with_sections returned.

    Returns:
        list[str]: one bundle-relative path per page, in the same order,
        each ending in ".md" and each distinct.
    """
    taken = set()
    paths = []
    for page, name in zip(pages, display_titles(pages)):
        folder = safe_name(page["source_label"], fallback=FALLBACK_NAME)
        stem = safe_name(name, fallback=FALLBACK_NAME)
        length = NAME_DIGEST_CHARS
        path = f"{folder}/{stem}-{address_digest(page['url'], length)}.md"
        # Two different addresses whose digests agree over the short form
        # would otherwise overwrite one another, so the digest grows until
        # the names differ. Deterministic: the same corpus gives the same
        # names on every run.
        while path in taken and length < 40:
            length += NAME_DIGEST_CHARS
            path = f"{folder}/{stem}-{address_digest(page['url'], length)}.md"
        taken.add(path)
        paths.append(path)
    return paths


### Concept Files ###

def concept_type(content_type):
    """The `type` front-matter value for a record's content type."""
    return CONCEPT_TYPES.get(content_type, DEFAULT_CONCEPT_TYPE)


def tags_for(page):
    """
    The `tags` list: the name of the source, the kind of document, and
    whatever category path the source recorded, outermost first.

    Blanks are dropped and repeats removed, so a page whose category
    repeats its source name is tagged once.

    Args:
        page (dict): one record from pages_with_sections.

    Returns:
        list[str]: distinct, non-blank tags, in that order.
    """
    candidates = [page["source_label"], concept_type(page["content_type"]), *page["categories"]]
    tags = {}
    for tag in candidates:
        if isinstance(tag, str) and tag.strip():
            tags.setdefault(tag.strip(), None)
    return list(tags)


def front_matter(page, built_at, name=None):
    """
    The YAML block at the top of a concept file.

    `type` is the one field the format requires; the rest are the
    recommended ones. `resource` is the address the page was read from, so
    a reader can go back to the original. For a file read from a local
    folder that address is the "local:" form the build stores, which names
    a path relative to the source folder and never a path on anyone's
    disk.

    Args:
        page (dict): one record from pages_with_sections.
        built_at (str): the build time, UTC, ISO 8601 with a Z suffix.
        name (str | None): the display name for this page, which differs
            from its own title when a whole site shares one title. The
            title itself is used when none is given.

    Returns:
        dict: the front-matter fields, in the order they are written.
    """
    name = name or page["title"]
    return {
        "type": concept_type(page["content_type"]),
        "title": name,
        "description": excerpt(page_text(page)),
        "resource": page["url"],
        "tags": tags_for(page),
        "generated": {"by": PRODUCER, "at": built_at},
        "sources": [{"resource": page["url"], "title": name}],
    }


def render_front_matter(fields):
    """
    The front-matter block as text, fenced the way the format expects.

    Written by the YAML library rather than by hand: every value here
    began as a crawled title or address, and a title holding a colon, a
    quotation mark, or a leading dash has to be quoted correctly or the
    block stops parsing.

    Args:
        fields (Mapping): the front-matter fields, in order.

    Returns:
        str: the fenced block, ending in a newline.
    """
    body = yaml.safe_dump(
        dict(fields),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10_000,
    )
    return f"---\n{body}---\n"


def render_concept(page, built_at, name=None):
    """
    One concept file: the front matter, the page's title, the address it
    came from, and its sections in build order.

    A page short enough to have stayed one section has no section heading
    of its own, so its text follows the title directly rather than under a
    heading repeating it.

    Args:
        page (dict): one record from pages_with_sections.
        built_at (str): the build time, UTC, ISO 8601 with a Z suffix.
        name (str | None): the display name for this page, which differs
            from its own title when a whole site shares one title. The
            title itself is used when none is given.

    Returns:
        str: the file's complete text, ending in a newline.
    """
    name = name or page["title"]
    lines = [
        render_front_matter(front_matter(page, built_at, name)).rstrip("\n"),
        "",
        f"# {name}",
        "",
        f"Source: {link(page['url'], page['url'])}",
        "",
    ]
    for heading, text in page["sections"]:
        if not (len(page["sections"]) == 1 and heading == page["title"]):
            lines.extend([f"## {heading}", ""])
        lines.extend([text, ""])
    return "\n".join(lines).rstrip("\n") + "\n"


### Reserved Files ###

def labels_in_order(pages):
    """
    The source names to head the index file's sections with, in the order
    they first appear, which is the order the configuration lists its
    sources.

    Two sources sharing a name are one section on purpose: two sibling
    collections of one repository read as one place to a person looking
    for an answer.

    Args:
        pages (Iterable[dict]): the records pages_with_sections returned.

    Returns:
        list[str]: distinct names, in first-appearance order.
    """
    labels = {}
    for page in pages:
        labels.setdefault(page["source_label"], None)
    return list(labels)


def render_index(compendium, pages, paths):
    """
    The root index.md: what the folder is, and one link per concept
    grouped under the name of the source it came from.

    The format allows front matter on this file alone, and only to declare
    the version of the format the folder follows.

    Args:
        compendium (extractium.core.models.Compendium): the build result,
            already filtered to what this output may write.
        pages (Sequence[dict]): the records pages_with_sections returned.
        paths (Sequence[str]): each page's bundle-relative path, in the
            same order.

    Returns:
        str: the file's complete text, ending in a newline.
    """
    named = dict(zip((page["url"] for page in pages), display_titles(pages)))
    where = dict(zip((page["url"] for page in pages), paths))
    lines = [
        render_front_matter({"okf_version": OKF_VERSION}).rstrip("\n"),
        "",
        f"# {compendium.name}",
        "",
        f"A knowledge base of {count_of(len(pages), 'concept')}, "
        f"compiled on {compendium.built_at}.",
        "",
    ]
    for paragraph in INDEX_ORIENTATION:
        lines.extend([paragraph, ""])
    lines.extend([LICENSE_LINE, ""])
    for label in labels_in_order(pages):
        lines.extend([f"## {label}", ""])
        for page in (p for p in pages if p["source_label"] == label):
            lines.append(
                f"* {link(named[page['url']], where[page['url']])} - {excerpt(page_text(page))}"
            )
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_log(compendium, pages):
    """
    The root log.md: one dated entry for the build that wrote this folder.

    Every build rewrites the folder in full, so the file records that
    build rather than a history of earlier ones. The date heading is the
    day of the build, in UTC, which is the time zone every build time is
    stored in.

    Args:
        compendium (extractium.core.models.Compendium): the build result,
            already filtered to what this output may write.
        pages (Sequence[dict]): the records pages_with_sections returned.

    Returns:
        str: the file's complete text, ending in a newline.
    """
    day = compendium.built_at[:10]
    return (
        f"# {LOG_HEADING}\n"
        f"\n"
        f"## {day}\n"
        f"\n"
        f"* **{LOG_ENTRY_WORD}**: Wrote {count_of(len(pages), 'concept')} from "
        f"{count_of(len(compendium.parents), 'section')}, compiled at "
        f"{compendium.built_at}.\n"
    )


### Adapter ###

class OkfAdapter:
    """
    Writes an Open Knowledge Format bundle: a folder of Markdown files
    that opens in any Markdown viewer and parses as OKF v0.2.

    Every file is plain Markdown with real headings and real lists, so it
    reads correctly in a browser and in a screen reader. This adapter
    never fetches an address and never runs the embedding model: a bundle
    carries the text of the build, not its vectors, so it is a readable
    copy of the corpus rather than a search index.

    Files written by an earlier build are left alone. A page that has
    since disappeared from the source therefore stays in the folder until
    somebody removes it, which is the safe way round: this adapter never
    deletes anything it did not just write.
    """

    name = "okf"

    def write(self, compendium, out_dir, options):
        """
        Writes the bundle under `out_dir`.

        Args:
            compendium (extractium.core.models.Compendium): the build result.
            out_dir (str | pathlib.Path): folder to write under; the
                bundle is the "okf" folder inside it, created when it does
                not exist.
            options (Mapping): the output's validated options. Only
                `include_local` is read; this output has no others.

        Returns:
            tuple[pathlib.Path, ...]: the index file, the log file, then
            one path per concept file, in build order.

        Raises:
            OSError: if a file cannot be written.
        """
        compendium = output_compendium(compendium, options)
        folder = prepare_out_dir(out_dir) / BUNDLE_DIR
        folder.mkdir(parents=True, exist_ok=True)

        pages = pages_with_sections(compendium.parents)
        paths = bundle_paths(pages)
        names = display_titles(pages)

        written = [
            _write_file(folder / INDEX_FILE, render_index(compendium, pages, paths)),
            _write_file(folder / LOG_FILE, render_log(compendium, pages)),
        ]
        for page, path, name in zip(pages, paths, names):
            target = folder.joinpath(*path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            written.append(
                _write_file(target, render_concept(page, compendium.built_at, name))
            )
        return tuple(written)


def _write_file(path, body):
    """Writes one file as UTF-8 with newline endings, and returns its path."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return path
