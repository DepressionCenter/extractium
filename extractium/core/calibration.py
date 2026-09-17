"""
Summary: Computes sample-based relevance-calibration statistics
(mean/std of each sampled chunk's best cosine match against the rest of
the corpus) for a corpus-relative relevance threshold.

This file is part of Extractium™
extractium/core/calibration.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
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

import numpy as np

### Constants ###

# Sample-based corpus statistics letting a downstream consumer threshold
# on a z-score instead of an absolute cosine cutoff hand-tuned for one
# specific corpus/embedding model.
CALIBRATION_SAMPLE_SIZE = 500

# Everyday questions that have nothing to do with the documentation,
# research, or reference material a compendium is built from. The build
# embeds them as queries and records the best score each one reaches in
# the finished corpus. That is what an unrelated question scores here, and
# a search client sets its relevance floor just above it.
#
# The best score of an unrelated question rises with the size of the
# corpus, because the best of more windows is higher, and it differs
# between a file of page text and a file of page descriptions. A floor
# measured this way follows both. A fixed number does neither.
#
# A few of these will be on topic for some corpus, a recipe question for
# a cooking site. The figures are therefore a median and a spread taken
# from the median, which a handful of high scores barely move. Changing
# this list changes every compendium's figures, so treat it as data.
UNRELATED_PROBES = (
    "how to bake sourdough bread",
    "best pizza in Chicago",
    "who won the 1998 world cup",
    "how to change a flat tire",
    "capital of Australia",
    "stock price of a technology company today",
    "chocolate cake recipe",
    "basketball finals schedule",
    "current mortgage interest rates",
    "how to grow tomatoes",
    "concert tour dates this summer",
    "how do volcanoes erupt",
    "cheap flights to Paris",
    "rules of chess",
    "how to knit a scarf",
    "causes of the French revolution",
    "best hiking boots",
    "how to fix a leaky faucet",
    "how to install a ceiling fan",
    "pizza",
    "weather tomorrow",
    "football scores",
    "car insurance quotes",
    "used cars for sale",
    "lasagna",
    "how to tie a bow tie",
    "symptoms of a bad alternator",
    "how to brew beer at home",
    "history of the Roman empire",
    "best laptops for gaming",
    "how to play guitar chords",
    "how to file taxes online",
    "what is the speed of light",
    "how to make pancakes",
    "dog training tips",
    "how to paint a room",
    "train schedule to Boston",
    "what time does the championship game start",
    "how to get a passport",
    "video game building ideas",
    "how to start a vegetable garden",
    "cryptocurrency prices",
    "how to write a cover letter",
    "how to remove red wine stains",
    "best science fiction novels",
    "how does a jet engine work",
    "how to replace a phone screen",
    "recipe for guacamole",
    "what is the tallest mountain",
    "how to clean a cast iron pan",
    "bird watching tips",
    "how to learn Spanish fast",
    "how to build a bookshelf",
    "electric car charging stations",
    "how to make cold brew coffee",
    "fantasy football rankings",
    "how to whistle",
    "marathon world record",
    "how to invest in index funds",
    "wedding planning checklist",
    "how to jump start a car",
    "how to make sushi rice",
    "when was the Eiffel tower built",
    "how to apply for a mortgage",
)

# Scales a median absolute deviation to the standard deviation of a
# normal distribution, the usual constant, so a client can read the
# spread the way it would read a standard deviation.
MAD_TO_SIGMA = 1.4826


### Calibration ###

def probe_chunks(query_prefix):
    """
    The unrelated probe questions in the shape an embedder takes, each
    carrying the query prefix, because a probe stands in for a search
    query and the model embeds queries and passages differently.

    Args:
        query_prefix (str): the text the model expects before a query.

    Returns:
        list[dict]: one chunk per probe, with an empty heading.
    """
    return [{"t": "", "x": query_prefix + probe} for probe in UNRELATED_PROBES]


def unrelated_stats(vecs, probe_vecs):
    """
    What an unrelated question scores in this corpus.

    Grain: one best score per probe, the highest cosine similarity
    between that probe and any window.

    Args:
        vecs (np.ndarray): shape (n, dims), the windows, L2-normalized.
        probe_vecs (np.ndarray): shape (probes, dims), the embedded probe
            questions, L2-normalized.

    Returns:
        dict: `unrelatedMedian`, the median of the best scores;
        `unrelatedSpread`, their median absolute deviation scaled to a
        standard deviation; `unrelatedProbes`, how many probes there
        were. Empty when there are no windows or no probes.
    """
    if vecs.shape[0] == 0 or probe_vecs is None or len(probe_vecs) == 0:
        return {}
    best = (np.asarray(probe_vecs, dtype=np.float32) @ vecs.T).max(axis=1)
    median = float(np.median(best))
    spread = float(np.median(np.abs(best - median)) * MAD_TO_SIGMA)
    return {"unrelatedMedian": median, "unrelatedSpread": spread, "unrelatedProbes": int(len(best))}


def compute_calibration_stats(vecs, sample_size=CALIBRATION_SAMPLE_SIZE, probe_vecs=None):
    """
    Two sets of figures about the scores in one corpus.

    The first samples up to `sample_size` embedded children (all of them,
    if fewer) and computes each sampled row's best (max) cosine similarity
    against every OTHER child. Its mean and std say how similar the
    windows are to each other. They are no guide to what a query scores,
    which is far lower, and no client thresholds on them.

    The second, written when `probe_vecs` is given, is what an unrelated
    question scores here; see unrelated_stats. A client sets its relevance
    floor from it.

    Vectors are already L2-normalized, so cosine similarity is a single
    dot product.

    Args:
        vecs (np.ndarray): shape (n, dims), L2-normalized embeddings.
        sample_size (int): maximum number of rows to sample.
        probe_vecs (np.ndarray | None): the embedded unrelated probe
            questions, or None to leave the second set out.

    Returns:
        dict: {"mean": float, "std": float, "sampleSize": int}, zeros with
        sampleSize 0 if fewer than 2 vectors are given (no meaningful
        "other" match to compare against); plus the unrelated_stats keys
        when probes were given.
    """
    n = vecs.shape[0]
    if n < 2:
        return {"mean": 0.0, "std": 0.0, "sampleSize": 0, **unrelated_stats(vecs, probe_vecs)}
    rng = np.random.default_rng(seed=42)  # deterministic across rebuilds of the same corpus
    sample_idx = rng.choice(n, size=min(sample_size, n), replace=False)
    sims = vecs[sample_idx] @ vecs.T  # (sample_size, n)
    for row_pos, doc_idx in enumerate(sample_idx):
        sims[row_pos, doc_idx] = -1.0  # exclude self-match
    best = sims.max(axis=1)
    return {"mean": float(best.mean()), "std": float(best.std()), "sampleSize": int(len(sample_idx)),
            **unrelated_stats(vecs, probe_vecs)}
