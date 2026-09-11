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
__date__ = "2026-09-08"

import dataclasses
import pathlib
import re
import urllib.parse

import numpy as np

from extractium.core.bm25 import build_bm25_index
from extractium.core.build import utf16_slice
from extractium.core.calibration import compute_calibration_stats
from extractium.core.models import Children

### Constants ###

# A parent heading is "Page title -- Section heading". Outputs that list
# pages rather than sections keep the part before the separator.
HEADING_SEPARATOR = " -- "

# Collapses every run of whitespace, including newlines, into one space.
WHITESPACE_RUN = re.compile(r"\s+")

# Longest one-line excerpt of a page's text. Long enough to tell two
# similarly named pages apart, short enough to stay a single line.
EXCERPT_CHARS = 180

# The query parameter a video's address carries the moment in, and the
# source type whose addresses carry it. A video's sections are each
# addressed at the moment they begin, which is what makes a citation
# open the video at the quoted words; an output that lists pages wants
# the video itself, so it drops this one parameter and keeps the rest.
# Scoped to that source type because "t" means something else elsewhere,
# and dropping it from another site's address would break the link.
MOMENT_PARAM = "t"
MOMENT_SOURCE_TYPE = "youtube"


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
    if getattr(parent, "source_type", "") != MOMENT_SOURCE_TYPE:
        return parent.u
    split = urllib.parse.urlsplit(parent.u)
    kept = [
        (name, value)
        for name, value in urllib.parse.parse_qsl(split.query, keep_blank_values=True)
        if name != MOMENT_PARAM
    ]
    return urllib.parse.urlunsplit(
        (split.scheme, split.netloc, split.path, urllib.parse.urlencode(kept), split.fragment)
    )


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
    return _without_local(compendium)


def _without_local(compendium):
    """A copy of the compendium with every local parent, and everything derived from one, removed."""
    if len(compendium.children) and not compendium.children.start:
        # Without offsets there is no way to recover what each window's
        # text was, so the keyword statistics cannot be rebuilt over the
        # windows that remain. Refusing is the safe answer: the
        # alternative is publishing an output whose statistics still
        # describe content that was supposed to be dropped.
        raise ValueError(
            "cannot drop local content from a compendium whose children carry no offsets; "
            "rebuild it, or set include_local on this output if that is what you intend."
        )
    kept_pids = [i for i, parent in enumerate(compendium.parents) if not parent.local]
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
