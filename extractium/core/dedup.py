"""
Summary: Collapses near-duplicate embedded chunks and compacts the parent
list to drop parents orphaned by that collapse.

This file is part of Extractium™
extractium/core/dedup.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-08-17
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

import numpy as np

### Constants ###

# Near-duplicate collapse at build time. Boilerplate (nav sidebars, footers,
# repeated disclaimers) crawls into many chunks that are near-identical after
# embedding; collapsing them here means every query-time retrieval benefits,
# instead of filtering the same boilerplate out of every top-k result forever.
NEAR_DUP_COSINE_THRESHOLD = 0.95


### Near-Duplicate Collapse ###

def drop_near_duplicates(chunks, vecs, threshold=NEAR_DUP_COSINE_THRESHOLD):
    """
    Greedy sequential near-duplicate collapse. Vectors are already
    L2-normalized (embed_chunks uses normalize_embeddings=True), so cosine
    similarity between any two rows is a single dot product -- one matrix
    multiply against the kept set per chunk, cheap at this corpus size.
    Keeps the first occurrence encountered (crawl order) of each
    near-duplicate cluster and drops the rest.

    **Two chunks from the same page are never collapsed into each other.**
    What this step exists to remove is boilerplate repeated across many
    pages; two passages of one article are not that, however alike they
    look. The comparison sees a vector of the section heading followed by
    the passage, so without this rule an article with a long title would
    have every one of its passages sharing a long identical prefix, which
    raises their similarity until real content is discarded as duplicated.
    A page's own repetitions are left in place, at a cost of a handful of
    chunks in a corpus.

    Args:
        chunks (list[dict]): child chunks, in crawl order, each with the
            "u" of the page it came from.
        vecs (np.ndarray): shape (len(chunks), dims), L2-normalized embeddings.
        threshold (float): cosine similarity above which a chunk is
            considered a duplicate of an already-kept chunk from another page.

    Returns:
        tuple[list[dict], np.ndarray, int]: (kept_chunks, kept_vecs, dropped_count).
    """
    if len(chunks) == 0:
        return chunks, vecs, 0

    # Pages as small integers, so "is this the page I am on?" is one
    # vectorized comparison against the kept set rather than a string
    # compare per candidate.
    page_numbers = {}
    page_of = np.fromiter(
        (page_numbers.setdefault(chunk["u"], len(page_numbers)) for chunk in chunks),
        dtype=np.int64, count=len(chunks),
    )

    kept_rows = []                                        # indices into chunks/vecs
    kept_matrix = np.empty_like(vecs)                     # kept vectors, filled in order
    kept_pages = np.empty(len(chunks), dtype=np.int64)    # their pages, same order
    for i in range(len(chunks)):
        v = vecs[i]
        count = len(kept_rows)
        if count:
            sims = kept_matrix[:count] @ v
            # A chunk from this same page cannot make this one a duplicate.
            sims = np.where(kept_pages[:count] == page_of[i], -1.0, sims)
            if float(sims.max()) > threshold:
                continue  # near-duplicate of a chunk kept from another page -- drop
        kept_matrix[count] = v
        kept_pages[count] = page_of[i]
        kept_rows.append(i)

    dropped = len(chunks) - len(kept_rows)
    kept_chunks = [chunks[i] for i in kept_rows]
    kept_vecs = vecs[kept_rows]
    return kept_chunks, kept_vecs, dropped


### Parent Compaction ###

def remap_parents_after_dedup(parents, children):
    """
    drop_near_duplicates can remove every child of a parent (e.g. an
    entirely-boilerplate section), orphaning that parent. Rebuilds the
    parent list to include only parents with at least one surviving
    child, and rewrites every child's `pid` to the new, compacted index.
    Must build the old->new map over surviving parents FIRST, then rewrite
    children in a second pass -- children still hold old-parent indices
    until this function returns.

    Args:
        parents (list[dict]): the full, pre-compaction parent list.
        children (list[dict]): surviving children, each with a `pid`
            indexing into `parents`. Mutated in place (pid rewritten).

    Returns:
        tuple[list[dict], list[dict]]: (new_parents, children), with
        children's pids now indexing into new_parents.
    """
    live_pids = {c["pid"] for c in children}
    old_to_new = {}
    new_parents = []
    for old_pid, p in enumerate(parents):
        if old_pid in live_pids:
            old_to_new[old_pid] = len(new_parents)
            new_parents.append(p)
    for c in children:
        c["pid"] = old_to_new[c["pid"]]
    return new_parents, children
