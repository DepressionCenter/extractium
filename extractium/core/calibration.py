"""
Summary: Computes sample-based relevance-calibration statistics
(mean/std of each sampled chunk's best cosine match against the rest of
the corpus) for a corpus-relative relevance threshold.

This file is part of Extractium™
extractium/core/calibration.py

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

# Sample-based corpus statistics letting a downstream consumer threshold
# on a z-score instead of an absolute cosine cutoff hand-tuned for one
# specific corpus/embedding model.
CALIBRATION_SAMPLE_SIZE = 500


### Calibration ###

def compute_calibration_stats(vecs, sample_size=CALIBRATION_SAMPLE_SIZE):
    """
    Samples up to `sample_size` embedded children (all of them, if fewer)
    and computes each sampled row's best (max) cosine similarity against
    every OTHER child -- a proxy for "the best score a real query is
    likely to achieve against this corpus." mean/std of those maxes is
    what a consumer calibrates its relevance threshold against. Vectors
    are already L2-normalized, so cosine similarity is a single dot
    product.

    Args:
        vecs (np.ndarray): shape (n, dims), L2-normalized embeddings.
        sample_size (int): maximum number of rows to sample.

    Returns:
        dict: {"mean": float, "std": float, "sampleSize": int}. Zeros with
        sampleSize 0 if fewer than 2 vectors are given (no meaningful
        "other" match to compare against).
    """
    n = vecs.shape[0]
    if n < 2:
        return {"mean": 0.0, "std": 0.0, "sampleSize": 0}
    rng = np.random.default_rng(seed=42)  # deterministic across rebuilds of the same corpus
    sample_idx = rng.choice(n, size=min(sample_size, n), replace=False)
    sims = vecs[sample_idx] @ vecs.T  # (sample_size, n)
    for row_pos, doc_idx in enumerate(sample_idx):
        sims[row_pos, doc_idx] = -1.0  # exclude self-match
    best = sims.max(axis=1)
    return {"mean": float(best.mean()), "std": float(best.std()), "sampleSize": int(len(sample_idx))}
