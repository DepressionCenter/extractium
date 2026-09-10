"""
Summary: The one build step. Turns the documents every source produced
into a single scored Compendium: chunk into parents and children, embed
the children once, drop near-duplicates, compact orphaned parents, build
the BM25 keyword statistics, compute the calibration statistics, and
quantize the vectors. Every adapter serializes the record this returns,
so one crawl and one embedding pass feed every output format. See
docs/extractium-spec.md section 2 and docs/container-format.md.

This file is part of Extractium™
extractium/core/build.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
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
__date__ = "2026-09-08"

from datetime import datetime, timezone

from extractium.core.bm25 import build_bm25_index
from extractium.core.calibration import compute_calibration_stats
from extractium.core.chunk import chunk_document
from extractium.core.fetch import normalise
from extractium.core.dedup import drop_near_duplicates, remap_parents_after_dedup
from extractium.core.embed import quantize_int8
from extractium.core.models import Children, Compendium, EmbeddingInfo, Parent

### Constants ###

# Display name used when the build has no `name` setting and the first
# document carries no title of its own.
DEFAULT_SITE_NAME = "Knowledge Base"

# The parent fields a Parent record is built from, in the order the
# dataclass declares them.
PARENT_FIELDS = (
    "id", "t", "x", "u", "host", "source_type", "content_type",
    "categories", "local", "weight",
)


### Offsets ###

def utf16_length(text):
    """
    Length of text in UTF-16 code units, the unit the container's child
    offsets are counted in because JavaScript strings index that way.
    Equal to len(text) for text with no characters outside the Basic
    Multilingual Plane, which is most text; emoji are the exception.
    """
    return len(text.encode("utf-16-le")) // 2


def utf16_slice(text, start, end):
    """
    The part of text between two UTF-16 code-unit offsets, which is how a
    client recovers a child's window from its parent. Goes through the
    encoded form rather than Python's own character indexing, because the
    two agree only for text inside the Basic Multilingual Plane.
    """
    encoded = text.encode("utf-16-le")
    return encoded[start * 2:end * 2].decode("utf-16-le")


### Timestamps ###

def utc_now():
    """The current time as an ISO 8601 UTC timestamp with a Z suffix, to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


### Chunk Documents ###

def chunk_documents(documents, progress):
    """
    Chunks every document into one flat parent list and one flat child
    list, in document order.

    Each document's chunker numbers its children against that page's own
    parents, so each page's `pid` values are shifted by however many
    parents had already accumulated when the page was reached.

    One page is indexed once, however many sources reached it. Two sources
    can cover overlapping ground -- a site and a section of it, a portal
    and a short link to one of its articles -- and a page they both reach
    would otherwise be chunked twice into sections with identical
    identifiers, which is not a document the container format can hold.
    The first source to produce a page keeps it and the later ones are
    told they were too late, because the alternative is a build that stops
    on a configuration a person could reasonably write.

    Pages are compared by their normalised address, the same form the
    identifiers are built from, so two addresses differing only by a
    trailing slash or a fragment count as one page.

    Args:
        documents (Iterable[extractium.core.models.Document]): what the
            sources produced, in the order they produced them.
        progress (Callable[[str], None]): receives one line per document
            that contributed content, and one per page already indexed.

    Returns:
        tuple[list[dict], list[dict], str]: (parents, children, site_name),
        where site_name is the first document's title.
    """
    parents = []
    children = []
    site_name = ""
    indexed_pages = set()
    repeated = 0
    for position, document in enumerate(documents):
        if position == 0:
            site_name = document.title
        page = normalise(document.url)
        if page in indexed_pages:
            repeated += 1
            progress(f"  already indexed by an earlier source, skipped: {document.url}")
            continue
        page_parents, page_children = chunk_document(document)
        if not page_parents:
            # Nothing was indexed, so the page is not spoken for: another
            # source reaching it later still gets its chance.
            continue
        indexed_pages.add(page)
        pid_offset = len(parents)
        for child in page_children:
            child["pid"] += pid_offset
        parents.extend(page_parents)
        children.extend(page_children)
        progress(
            f"  +{len(page_parents)} section(s), +{len(page_children)} window(s): "
            f"{document.title[:70]}"
        )
    if repeated:
        progress(
            f"Skipped {repeated} page(s) an earlier source had already indexed. "
            "Two sources are covering the same ground."
        )
    return parents, children, site_name


### Assemble The Compendium ###

def _parent_records(parents):
    """Validated Parent records from the chunker's parent dicts, in build order."""
    return tuple(Parent(**{field: parent[field] for field in PARENT_FIELDS}) for parent in parents)


def _children_columns(parents, children):
    """
    The child column arrays, with offsets converted from Python character
    positions to UTF-16 code units.

    Args:
        parents (list[dict]): the final, compacted parent list.
        children (list[dict]): the surviving children, pids already
            remapped into parents.

    Returns:
        extractium.core.models.Children: parallel pid, start, and end columns.
    """
    pid, start, end = [], [], []
    for child in children:
        text = parents[child["pid"]]["x"]
        begin = utf16_length(text[:child["start"]])
        pid.append(child["pid"])
        start.append(begin)
        end.append(begin + utf16_length(child["x"]))
    return Children(pid=tuple(pid), start=tuple(start), end=tuple(end))


def build_compendium(documents, name=None, embedder=None, float32_vecs=False,
                     progress=None, built_at=None):
    """
    Builds one scored Compendium from the documents a build's sources
    produced. This is the only place embedding runs.

    The order of the steps matters. Near-duplicate collapse must precede
    the BM25 statistics, because the postings index into the child list as
    it is finally shipped; parent compaction must follow the collapse,
    because a section whose every window was a duplicate has no content
    left to cite.

    Args:
        documents (Iterable[extractium.core.models.Document]): what the
            sources produced, in order.
        name (str | None): display name of the knowledge base. None uses
            the first document's title.
        embedder (Callable[[list[dict]], numpy.ndarray] | None): embeds the
            child chunks. None uses extractium.core.embed.embed_chunks,
            imported at that moment so a caller that supplies its own
            embedder never loads the model library.
        float32_vecs (bool): store vectors as float32 instead of the
            default int8 quantization. Four times the bytes, marginally
            more precision.
        progress (Callable[[str], None] | None): receives one line per
            stage. None reports nothing.
        built_at (str | None): build time, ISO 8601 UTC with a Z suffix.
            None uses the current time.

    Returns:
        Compendium | None: the scored result, or None when the documents
        yielded no indexable content, which the caller reports rather than
        writing empty output files.
    """
    report = progress or (lambda message: None)

    ### Chunk ###
    parents, children, first_title = chunk_documents(documents, report)
    if not children:
        report("No indexable content: nothing to score.")
        return None
    report(f"Chunked into {len(parents)} section(s) and {len(children)} search window(s).")

    ### Embed ###
    if embedder is None:
        from extractium.core.embed import embed_chunks

        def embedder(chunks):
            return embed_chunks(chunks, progress=report)

    vecs = embedder(children)

    ### Collapse And Compact ###
    children, vecs, dropped = drop_near_duplicates(children, vecs)
    if dropped:
        report(f"Dropped {dropped} near-duplicate window(s).")
    parents, children = remap_parents_after_dedup(parents, children)
    report(f"Kept {len(parents)} section(s) and {len(children)} search window(s).")

    ### Score ###
    bm25 = build_bm25_index(children)
    calibration = compute_calibration_stats(vecs)

    ### Quantize ###
    if float32_vecs:
        stored_vecs = vecs
        dtype = "float32"
    else:
        stored_vecs = quantize_int8(vecs)
        dtype = "int8"

    return Compendium(
        name=name or first_title or DEFAULT_SITE_NAME,
        built_at=built_at or utc_now(),
        parents=_parent_records(parents),
        children=_children_columns(parents, children),
        vectors=stored_vecs,
        embedding=EmbeddingInfo(dtype=dtype),
        bm25=bm25,
        calibration=calibration,
    )
