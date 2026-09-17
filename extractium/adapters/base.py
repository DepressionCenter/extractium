"""
Summary: What every Extractium adapter shares: the text helpers the
Markdown outputs build links and excerpts with, preparing the output
folder, and the confidentiality guardrail that keeps content read from a
local folder out of an output unless that output asked for it. Publishing
is the normal use of every output, so the safe default is the one that
cannot leak by omission (docs/extractium-spec.md section 7).

This file is part of Extractium™
extractium/adapters/base.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
Last Modified: 2026-09-17
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
__date__ = "2026-09-17"

import dataclasses
import pathlib
import re
from collections import Counter

import numpy as np

from extractium.core.bm25 import build_bm25_index
from extractium.core.build import utf16_slice
from extractium.core.calibration import compute_calibration_stats
from extractium.core.models import CODE_CONTENT_TYPES, Children, page_address_of

### Constants ###

# A parent heading is "Page title -- Section heading". Outputs that list
# pages rather than sections keep the part before the separator.
HEADING_SEPARATOR = " -- "

# Collapses every run of whitespace, including newlines, into one space.
WHITESPACE_RUN = re.compile(r"\s+")

# Longest one-line excerpt of a page's text. Long enough to tell two
# similarly named pages apart, short enough to stay a single line.
EXCERPT_CHARS = 180

# How much of a summary an index entry quotes. Long enough for two
# sentences, short enough that five hundred entries stay one readable file.
DESCRIPTION_CHARS = 300

# A summary carried by more pages of one source than this is the site's
# default description, repeated on every page that has none of its own.
# It says nothing about any one page, so it is treated as absent.
SHARED_SUMMARY_PAGES = 3

### Page Addresses ###

def page_address(parent):
    """
    The address of the page one section belongs to.

    For almost every source this is the section's own address, because a
    page and its sections share one. A video is the exception: each
    stretch of a transcript is addressed at the moment it begins, so one
    video has as many addresses as it has sections. An output that lists
    pages groups those back into the video.

    Args:
        parent (extractium.core.models.Parent): the section.

    Returns:
        str: the page's address. Unchanged for every source but a video.
    """
    return page_address_of(parent.u, getattr(parent, "source_type", ""))


### Text Helpers ###

def page_title(heading):
    """The page part of a parent heading, dropping the section part after the separator."""
    return heading.split(HEADING_SEPARATOR, 1)[0].strip()


def section_title(heading):
    """
    The section part of a parent heading, or the whole heading when the
    page contributed a single untitled section.

    Args:
        heading (str): a parent's `t`, as the build wrote it.

    Returns:
        str: the text after the separator, or the heading itself.
    """
    page, separator, section = heading.partition(HEADING_SEPARATOR)
    return section.strip() if separator and section.strip() else page.strip()


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


def count_of(number, noun):
    """A counted noun that reads correctly in either number: "1 page", "2 pages"."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


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


### Pages ###

def prose_parents(parents):
    """
    The sections that are not code records, in the order given.

    Args:
        parents (Iterable[extractium.core.models.Parent]): sections in
            build order.

    Returns:
        tuple[extractium.core.models.Parent, ...]: the sections whose
        content type is not one of CODE_CONTENT_TYPES.
    """
    return tuple(parent for parent in parents if parent.content_type not in CODE_CONTENT_TYPES)


def keywords_named(parent):
    """
    The keywords that describe the page a section belongs to.

    The page's own tags come first, less the categories the source
    recorded, because those are the keywords most of its sections
    share. A page whose sections share none is described by its first
    section's keywords instead, so a page is not left without any
    merely for being about several things.

    Args:
        parent (extractium.core.models.Parent): the page's first section.

    Returns:
        tuple[str, ...]: the keywords, most telling first; empty when
        no keyword step ran.
    """
    categories = set(parent.categories)
    shared = tuple(tag for tag in (parent.tags or ()) if tag not in categories)
    return shared or tuple(parent.keywords or ())


def page_records(parents):
    """
    One record per page, in the order that page first appears.

    Grain: one record per page, not per section. A page contributes
    several sections and is named once. A video counts as one page
    however many stretches of its transcript were indexed, so a long talk
    is one record and not one every couple of minutes.

    A summary that more than SHARED_SUMMARY_PAGES pages of one source
    carry is that site's default description, so it is blanked here and
    describe() falls back to what the page itself offers. A keyword list
    shared the same way is replaced by the first section's own keywords.

    Args:
        parents (Iterable[extractium.core.models.Parent]): the sections an
            output may write, in build order.

    Returns:
        list[dict]: url, title, source_label, source_type, content_type,
        categories, the first section's text, `summary` (the page's own,
        or "" when its source's pages share it), `given_summary` (what the
        source gave, shared or not, because a site's default description
        is the right description of the site), `keywords` (the page's
        tags, or the keywords of its first section when its source's pages
        share the tags), and `own_keywords` (the first section's).
    """
    pages = {}
    for parent in parents:
        address = page_address(parent)
        if address in pages:
            continue
        pages[address] = {
            "url": address,
            "title": page_title(parent.t),
            "source_label": parent.source_label,
            "source_type": parent.source_type,
            "content_type": parent.content_type,
            "categories": tuple(parent.categories),
            "text": parent.x,
            "summary": (parent.summary or "").strip(),
            "given_summary": (parent.summary or "").strip(),
            "keywords": keywords_named(parent),
            "own_keywords": tuple(parent.keywords or ()),
        }
    records = list(pages.values())
    summaries = Counter((page["source_label"], page["summary"]) for page in records if page["summary"])
    keywords = Counter((page["source_label"], page["keywords"]) for page in records if page["keywords"])
    for page in records:
        if summaries[(page["source_label"], page["summary"])] > SHARED_SUMMARY_PAGES:
            page["summary"] = ""
        # The same holds for keywords: a repository's topics or a channel's
        # tags sit on every page of the source, so a page carrying only
        # those is described by the keywords found in its own text.
        if keywords[(page["source_label"], page["keywords"])] > SHARED_SUMMARY_PAGES:
            page["keywords"] = page["own_keywords"]
    return records


def describe(page, limit=DESCRIPTION_CHARS):
    """
    What an index says about one page: its own summary, else its
    keywords, else the opening of its text.

    Args:
        page (dict): one record from page_records.
        limit (int): longest summary quoted, in characters.

    Returns:
        str: one line of text.
    """
    if page["summary"]:
        return excerpt(page["summary"], limit)
    if page["keywords"]:
        return f"Keywords: {', '.join(page['keywords'])}."
    return excerpt(page["text"])


### Output Folder ###

def prepare_out_dir(out_dir):
    """
    Makes sure the output folder exists and returns it as a path.

    Args:
        out_dir (str | pathlib.Path): the folder every adapter writes under.

    Returns:
        pathlib.Path: the folder, created along with any missing parents.
    """
    path = pathlib.Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


### Local Content Guardrail ###

def output_compendium(compendium, options):
    """
    The compendium as one output is allowed to write it.

    Content read from a local folder may hold things that were never
    published. Every output therefore drops it unless the operator wrote
    `include_local: true` on that output's entry.

    Dropping a parent drops its search windows, its vectors, and its share
    of the corpus statistics with it, so the keyword and calibration
    figures are rebuilt over what remains. A compendium with no local
    content is returned untouched, which is every build until a local
    source is configured.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        options (Mapping): the output's options; only `include_local` is
            read here.

    Returns:
        extractium.core.models.Compendium: the original, or a copy holding
        only the parents this output may write.
    """
    if options.get("include_local") or not compendium.local_parents():
        return compendium
    return without_parents(compendium, lambda parent: parent.local)


### Dropping Sections ###

def without_code(compendium):
    """
    The compendium without its code records.

    An output read inside a language model's context window, or searched
    by a small model in memory, leaves code analysis out. The outputs
    that keep it never call this.

    Args:
        compendium (extractium.core.models.Compendium): the build result.

    Returns:
        extractium.core.models.Compendium: the original when it holds no
        code record, else a copy without them.
    """
    return without_parents(compendium, lambda parent: parent.content_type in CODE_CONTENT_TYPES)


def without_parents(compendium, drop):
    """
    A copy of the compendium with some sections, and everything derived
    from them, removed.

    Dropping a section drops its search windows and their vectors. The
    keyword statistics and the calibration figures describe the whole
    corpus, so they are rebuilt over what remains.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        drop (Callable[[extractium.core.models.Parent], bool]): answers
            True for a section to remove.

    Returns:
        extractium.core.models.Compendium: the original, untouched, when
        nothing is dropped; else the copy.

    Raises:
        ValueError: when the search windows carry no offsets, so their
            text cannot be recovered to rebuild the statistics.
    """
    kept_pids = [i for i, parent in enumerate(compendium.parents) if not drop(parent)]
    if len(kept_pids) == len(compendium.parents):
        return compendium
    if len(compendium.children) and not compendium.children.start:
        # Without offsets there is no way to recover what each window's
        # text was, so the keyword statistics cannot be rebuilt over the
        # windows that remain. Refusing is the safe answer: the
        # alternative is publishing an output whose statistics still
        # describe content that was supposed to be dropped.
        raise ValueError(
            "cannot drop content from a compendium whose children carry no offsets; "
            "rebuild it, or set include_local on this output if local content is what "
            "was being dropped and you intend to publish it."
        )
    old_to_new = {old: new for new, old in enumerate(kept_pids)}
    parents = tuple(compendium.parents[old] for old in kept_pids)

    rows = [i for i, pid in enumerate(compendium.children.pid) if pid in old_to_new]
    children = Children(
        pid=tuple(old_to_new[compendium.children.pid[i]] for i in rows),
        start=tuple(compendium.children.start[i] for i in rows),
        end=tuple(compendium.children.end[i] for i in rows),
    )
    vectors = compendium.vectors[rows]

    # The keyword statistics index into the child list as it ships, so
    # they are rebuilt from the surviving windows rather than filtered.
    # The text of each window is what it was at build time: the parent's
    # heading and the slice of parent text the offsets name.
    surviving = [
        {
            "t": parents[pid].t,
            "x": utf16_slice(parents[pid].x, start, end),
        }
        for pid, start, end in zip(children.pid, children.start, children.end)
    ]

    return dataclasses.replace(
        compendium,
        parents=parents,
        children=children,
        vectors=vectors,
        bm25=build_bm25_index(surviving),
        calibration=compute_calibration_stats(_as_float(vectors, compendium.embedding)),
    )


def _as_float(vectors, embedding):
    """
    Vectors as unit-length floats, which is what the calibration figures
    are measured over. Stored int8 components are divided back by the
    scale they were multiplied by.
    """
    if embedding.dtype != "int8":
        return vectors
    return vectors.astype(np.float32) / float(embedding.scale)
