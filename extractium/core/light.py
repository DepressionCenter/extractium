"""
Summary: Turns the compendium a build produced into the light
compendium: one section per page, holding the page's description and
keywords in place of its text, with search windows, vectors, and
keyword statistics over that.

This file is part of Extractium™
extractium/core/light.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-17
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

from extractium.adapters.base import describe, page_address, page_records, prose_parents
from extractium.core.bm25 import build_bm25_index
from extractium.core.build import utf16_length
from extractium.core.calibration import compute_calibration_stats
from extractium.core.chunk import split_parent_into_children
from extractium.core.embed import quantize_int8
from extractium.core.models import Children

### Constants ###

# How a description that is a keyword list begins. A page described that
# way does not get its keywords written a second time under it.
KEYWORD_LINE_PREFIX = "Keywords: "


### Light Sections ###

def light_text(page):
    """
    The text of one light section: the page's description, then its
    keywords unless the description already is them.

    Args:
        page (dict): one record from extractium.adapters.base.page_records.

    Returns:
        str: the description, and a `Keywords:` line after a blank line
        when the page has keywords the description did not name.
    """
    description = describe(page)
    if page["keywords"] and not description.startswith(KEYWORD_LINE_PREFIX):
        return f"{description}\n\n{KEYWORD_LINE_PREFIX}{', '.join(page['keywords'])}."
    return description


def light_parents(compendium):
    """
    One section per page, in the order the pages first appear.

    Grain: one section per page. Code records contribute none. A page of
    several sections is represented by its first one, which gives the
    light section its identifier, source, content type, categories,
    weight, tags, and whether it is local. The heading is the page's
    title, the address is the page's, and the text is light_text.

    These sections are not chunked the way a fetched page is. A
    description shorter than the chunker's minimum is still the whole of
    what is known about its page, and two pages with the same description
    are still two pages, so nothing is dropped for being short or alike.

    Args:
        compendium (extractium.core.models.Compendium): the build result.

    Returns:
        tuple[extractium.core.models.Parent, ...]: the light sections.
    """
    parents = prose_parents(compendium.parents)
    first = {}
    for parent in parents:
        first.setdefault(page_address(parent), parent)
    return tuple(
        dataclasses.replace(
            first[page["url"]],
            t=page["title"],
            x=light_text(page),
            u=page["url"],
            # The description is already the text, so carrying it again
            # as the summary would store it twice.
            summary=None,
            keywords=tuple(page["keywords"]) or None,
        )
        for page in page_records(parents)
    )


### Light Compendium ###

def build_light_compendium(compendium, embedder=None, progress=None):
    """
    The light compendium of a build: the same pages, each as one short
    section, scored the same way as the full one.

    The vectors are stored in the form the full compendium stores its
    own, so one client setting reads both files.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        embedder (Callable[[list[dict]], numpy.ndarray] | None): embeds the
            search windows. None uses extractium.core.embed.embed_chunks,
            imported at that moment so a caller that supplies its own
            embedder never loads the model library.
        progress (Callable[[str], None] | None): receives one line per
            stage. None reports nothing.

    Returns:
        extractium.core.models.Compendium | None: the light compendium, or
        None when the build holds no page that is not a code record.
    """
    report = progress or (lambda message: None)
    parents = light_parents(compendium)
    if not parents:
        return None

    ### Windows ###
    windows = []
    for pid, parent in enumerate(parents):
        for window in split_parent_into_children({"t": parent.t, "x": parent.x}):
            windows.append({**window, "pid": pid})
    report(f"Light container: describing {len(parents)} page(s) in {len(windows)} search window(s).")

    ### Embed ###
    if embedder is None:
        from extractium.core.embed import embed_chunks

        def embedder(chunks):
            return embed_chunks(chunks, progress=report)

    vectors = embedder(windows)

    ### Score ###
    # Offsets are UTF-16 code units in a compendium, as the container stores them.
    starts = [utf16_length(parents[window["pid"]].x[:window["start"]]) for window in windows]
    children = Children(
        pid=tuple(window["pid"] for window in windows),
        start=tuple(starts),
        end=tuple(start + utf16_length(window["x"]) for start, window in zip(starts, windows)),
    )
    return dataclasses.replace(
        compendium,
        parents=parents,
        children=children,
        vectors=quantize_int8(vectors) if compendium.embedding.dtype == "int8" else vectors,
        bm25=build_bm25_index(windows),
        calibration=compute_calibration_stats(vectors, probe_vecs=compendium.probe_vectors),
    )
