"""
Summary: The llms.txt adapter. Writes the two plain-Markdown files a
web-browsing language model looks for: llms.txt, a one-line-per-page index
of everything indexed, and llms-full.txt, the whole corpus as readable
text. Neither carries vectors; they are for a model that reads pages
rather than searching an index. See https://llmstxt.org/ and
docs/extractium-spec.md section 4.

This file is part of Extractium™
extractium/adapters/llmstxt.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-08
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

import re

from extractium.adapters.base import output_compendium, prepare_out_dir

### Constants ###

INDEX_FILE = "llms.txt"
FULL_FILE = "llms-full.txt"

# Headings for the index file's sections, and the order they appear in.
# A source type with no pages gets no heading rather than an empty one.
SECTION_TITLES = (
    ("kb", "Knowledge base articles"),
    ("github", "Code repositories"),
    ("web", "Web pages"),
    ("youtube", "Video transcripts"),
    ("local", "Local documents"),
)

# Longest excerpt shown after a page's link in the index file. Long enough
# to tell two similarly named pages apart, short enough that the index
# stays an index.
EXCERPT_CHARS = 180

# A parent heading is "Page title -- Section heading". The page title is
# what the index file lists, because the index is one line per page.
HEADING_SEPARATOR = " -- "

# Collapses every run of whitespace, including newlines, into one space.
WHITESPACE_RUN = re.compile(r"\s+")

# Named in both files so a reader knows what produced them and under what
# terms. The indexed text keeps whatever license its own site carries.
LICENSE_LINE = (
    "Compiled by Extractium (https://github.com/DepressionCenter/extractium), "
    "copyright (c) 2026 The Regents of the University of Michigan, licensed under "
    "the GNU General Public License v3.0 or later. The indexed content remains "
    "under the license of the site it was read from."
)

# Sites named in the summary before the rest are counted rather than
# listed, so the opening line stays one readable sentence.
HOSTS_SHOWN = 3

# What each file is and how to use it, for a reader arriving with no
# context. The llms.txt convention puts the free-form explanation between
# the summary and the link sections, and allows no headings there, so
# these are plain paragraphs (https://llmstxt.org/).
INDEX_ORIENTATION = (
    "This file is an index, not the content itself. Each entry below names one "
    "page, links to it, and quotes the opening of its text, so you can judge "
    "whether a page answers your question before fetching it. Entries are "
    "grouped by the kind of source they came from, in the order the pages were "
    "found.",
    f"{FULL_FILE}, written alongside this file, holds the complete text of every "
    f"page listed here, in the same order. Read that instead if you want "
    f"everything at once rather than following links.",
)

FULL_ORIENTATION = (
    "This file holds the complete text of every page indexed, one heading per "
    "section, with the address it came from under each heading. A page that ran "
    "long appears as several sections sharing one heading.",
    f"{INDEX_FILE}, written alongside this file, lists the same pages as links "
    f"with a one-line excerpt each. Read that instead if you only need to find "
    f"the right page.",
)


### Text Helpers ###

def page_title(heading):
    """The page part of a parent heading, dropping the section part after the separator."""
    return heading.split(HEADING_SEPARATOR, 1)[0].strip()


def link(title, url):
    """
    One Markdown link, safe to build from a crawled page title and URL.

    Both come from a page nobody here controls. A `]` in a title or a `)`
    in a URL would end the link early and turn the rest of the line into
    stray text, so the first is escaped and the second is percent-encoded.
    """
    safe_title = title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    safe_url = url.replace("(", "%28").replace(")", "%29").replace(" ", "%20")
    return f"[{safe_title}]({safe_url})"


def excerpt(text, limit=EXCERPT_CHARS):
    """
    One line of text for a link's description: whitespace collapsed, cut
    at a word boundary, with an ellipsis when anything was cut.
    """
    flat = WHITESPACE_RUN.sub(" ", text).strip()
    if len(flat) <= limit:
        return flat
    cut = flat.rfind(" ", 0, limit)
    return flat[:cut if cut > 0 else limit].rstrip() + "..."


def pages_in_order(parents):
    """
    One entry per source URL, in the order that URL first appears.

    Grain: one entry per page, not per section. A page contributes several
    parents and the index file names it once.

    Args:
        parents (Iterable[extractium.core.models.Parent]): the parents this
            output may write, in build order.

    Returns:
        list[dict]: url, title, source_type, and the first section's text,
        in first-appearance order.
    """
    pages = {}
    for parent in parents:
        if parent.u in pages:
            continue
        pages[parent.u] = {
            "url": parent.u,
            "title": page_title(parent.t),
            "source_type": parent.source_type,
            "text": parent.x,
        }
    return list(pages.values())


### File Bodies ###

def source_hosts(parents):
    """
    The sites the content came from, in the order they first appear.

    Args:
        parents (Iterable[extractium.core.models.Parent]): the parents this
            output may write.

    Returns:
        tuple[str, ...]: distinct host names. Local files have no host and
        contribute none.
    """
    hosts = {}
    for parent in parents:
        if parent.host:
            hosts.setdefault(parent.host, None)
    return tuple(hosts)


def name_sites(hosts, limit=HOSTS_SHOWN):
    """
    The hosts as a readable phrase, counting the ones past the limit rather
    than listing them: "a.edu, b.org and 4 other sites".

    Returns:
        str: the phrase, or an empty string when there are no hosts, which
        is the case for an output of purely local content.
    """
    if not hosts:
        return ""
    shown, extra = list(hosts[:limit]), len(hosts) - limit
    if extra > 0:
        shown.append(f"{extra} other site{'s' if extra > 1 else ''}")
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def count_of(number, noun):
    """A counted noun that reads correctly in either number: "1 page", "2 pages"."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def summary(compendium, page_count):
    """
    The blockquote line: what this knowledge base is, where it came from,
    and when it was built. The llms.txt convention puts the information a
    reader needs in order to understand the rest of the file here, and the
    heading above it already carries the name.
    """
    sites = name_sites(source_hosts(compendium.parents))
    pages = count_of(page_count, "page") if sites else count_of(page_count, "file")
    drawn_from = f" drawn from {pages} on {sites}" if sites else f" drawn from {pages}"
    return (
        f"> A knowledge base of {count_of(len(compendium.parents), 'section')}"
        f"{drawn_from}, compiled on {compendium.built_at}."
    )


def _preamble(compendium, page_count, orientation):
    """
    The heading, summary, orientation, and license both files open with.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        page_count (int): pages named in this file.
        orientation (Sequence[str]): paragraphs saying what this file is
            and how to read it.
    """
    lines = [f"# {compendium.name}", "", summary(compendium, page_count), ""]
    for paragraph in orientation:
        lines.extend([paragraph, ""])
    lines.extend([LICENSE_LINE, ""])
    return lines


def render_index(compendium):
    """
    The llms.txt body: a heading, a summary, and one link per page grouped
    by the kind of source it came from.

    Args:
        compendium (extractium.core.models.Compendium): the build result,
            already filtered to what this output may write.

    Returns:
        str: the file's complete text, ending in a newline.
    """
    pages = pages_in_order(compendium.parents)
    lines = _preamble(compendium, len(pages), INDEX_ORIENTATION)
    for source_type, title in SECTION_TITLES:
        group = [page for page in pages if page["source_type"] == source_type]
        if not group:
            continue
        lines.append(f"## {title}")
        lines.append("")
        for page in group:
            lines.append(f"- {link(page['title'], page['url'])}: {excerpt(page['text'])}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_full(compendium):
    """
    The llms-full.txt body: every section in build order, each under its
    own heading with the URL it came from.

    Args:
        compendium (extractium.core.models.Compendium): the build result,
            already filtered to what this output may write.

    Returns:
        str: the file's complete text, ending in a newline.
    """
    pages = pages_in_order(compendium.parents)
    lines = _preamble(compendium, len(pages), FULL_ORIENTATION)
    for parent in compendium.parents:
        lines.append(f"## {parent.t}")
        lines.append("")
        lines.append(f"Source: {parent.u}")
        lines.append("")
        lines.append(parent.x)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


### Adapter ###

class LlmsTxtAdapter:
    """
    Writes llms.txt and llms-full.txt.

    Both are plain Markdown with real headings and real lists, so they read
    correctly in a browser, in a screen reader, and to a language model.
    This adapter never fetches a URL and never runs the embedding model.
    """

    name = "llmstxt"

    def write(self, compendium, out_dir, options):
        """
        Writes both files.

        Args:
            compendium (extractium.core.models.Compendium): the build result.
            out_dir (str | pathlib.Path): folder to write under; created
                when it does not exist.
            options (Mapping): the output's validated options. Only
                `include_local` is read; this output has no others.

        Returns:
            tuple[pathlib.Path, ...]: the index file, then the full file.
        """
        compendium = output_compendium(compendium, options)
        folder = prepare_out_dir(out_dir)
        written = []
        for filename, body in ((INDEX_FILE, render_index(compendium)),
                               (FULL_FILE, render_full(compendium))):
            path = folder / filename
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
            written.append(path)
        return tuple(written)
