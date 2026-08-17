"""
Summary: Builds BM25 corpus statistics (postings, document frequency,
document lengths) over the final child-chunk list for hybrid retrieval.

This file is part of Extractium™
extractium/core/bm25.py

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

import re
from collections import Counter

### Constants ###

# Formula and default constants (k, b, d) read from oramasearch/orama's
# BM25() implementation as a design reference -- not vendored/imported.
# `d` is a Lucene-style smoothing term Orama adds on top of classical
# Robertson BM25; kept here because it prevents a zero score for a single
# sparse-term match. Fusion with vector scores (Reciprocal Rank Fusion) is
# computed query-time downstream, NOT here -- this only emits the
# corpus-wide statistics (document frequency, postings, average doc
# length) a query can't compute on its own.
BM25_K1 = 1.2
BM25_B = 0.75
BM25_D = 0.5

# MUST match the query-side tokenizer used at retrieval time exactly -- a
# mismatch here silently degrades every BM25 match, since postings built
# with one tokenization rule can't be looked up correctly with another.
TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


### Tokenization ###

def tokenize(text):
    """Lowercases text and returns all runs of 3+ alphanumeric characters."""
    return TOKEN_RE.findall(text.lower())


### BM25 Index ###

def build_bm25_index(children):
    """
    Builds BM25 corpus statistics over the final child list. MUST run
    after near-duplicate collapse and parent remapping -- postings' doc
    indices are positions into `children` as shipped in the index, so
    building this against a pre-dedup list would point at chunks that no
    longer exist (or the wrong ones) once dedup runs afterward.

    Args:
        children (list[dict]): the final child chunk list, each with "t"
            (heading, optional) and "x" (body text).

    Returns:
        dict: BM25 parameters (k, b, d), avgDocLen, per-document token
        counts (docLen), document frequency per term (df), and postings
        (term -> list of [doc_index, term_frequency]).
    """
    doc_len = []
    df = {}
    postings = {}
    for i, c in enumerate(children):
        tokens = tokenize((c.get("t") or "") + " " + c["x"])
        doc_len.append(len(tokens))
        for term, tf in Counter(tokens).items():
            df[term] = df.get(term, 0) + 1
            postings.setdefault(term, []).append([i, tf])
    avg_doc_len = (sum(doc_len) / len(doc_len)) if doc_len else 0.0
    return {
        "k": BM25_K1,
        "b": BM25_B,
        "d": BM25_D,
        "avgDocLen": avg_doc_len,
        "docLen": doc_len,
        "df": df,
        "postings": postings,
    }
