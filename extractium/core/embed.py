"""
Summary: Embeds chunks with bge-small-en-v1.5 and quantizes the resulting
vectors to int8 for compact storage.

This file is part of Extractium™
extractium/core/embed.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-04
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

# sentence_transformers is imported inside embed_chunks, not here: it pulls
# in torch, several hundred megabytes that the adapters, the search client,
# and anything reading a finished index never need.

### Constants ###

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_MODEL_BROWSER_ID = "Xenova/bge-small-en-v1.5"
DIMS = 384

# The model was trained for asymmetric retrieval: a query is prefixed with
# this instruction (trailing space included) and indexed passages get no
# prefix. Both are recorded in every output, because a model-id check
# alone would not catch a prefix change.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
PASSAGE_PREFIX = ""

# int8 vector quantization. Vectors are L2-normalized, so every component
# already lies in roughly [-1, 1] -- round(v * INT8_SCALE) loses negligible
# precision at 384 dims and needs no per-vector calibration. Reversed by
# consumers by dividing back by the same scale.
INT8_SCALE = 127


### Embedding ###

def embed_chunks(chunks, progress=None):
    """
    Embeds a list of child chunks with the configured sentence-transformer
    model. Each chunk's embedded text is its heading ("t") followed by its
    body ("x"), matching the asymmetric retrieval convention: indexed
    passages get no query-side prefix.

    The model library is imported here rather than at module level, so a
    caller that only reads a finished index never loads torch.

    Args:
        chunks (list[dict]): child chunks with "t" (heading, optional) and
            "x" (body text) keys.
        progress (Callable[[str], None] | None): receives one line per
            stage. None reports nothing, which is what a library caller
            and a test want.

    Returns:
        np.ndarray: shape (len(chunks), DIMS), float32, L2-normalized.
    """
    from sentence_transformers import SentenceTransformer

    report = progress or (lambda message: None)
    report(f"Loading embedding model: {EMBED_MODEL}")
    model = SentenceTransformer(EMBED_MODEL)
    texts = [((c["t"] + "\n") if c.get("t") else "") + c["x"] for c in chunks]
    report(f"Embedding {len(texts)} chunk(s)...")
    vecs = model.encode(texts, normalize_embeddings=True,
                        batch_size=64, show_progress_bar=False)
    return vecs.astype(np.float32)


### Quantization ###

def quantize_int8(vecs):
    """
    Quantizes L2-normalized float32 vectors to int8 by scaling and
    clipping to [-INT8_SCALE, INT8_SCALE].

    Args:
        vecs (np.ndarray): float32 vectors, components in roughly [-1, 1].

    Returns:
        np.ndarray: same shape, dtype int8.
    """
    return np.clip(np.round(vecs * INT8_SCALE), -INT8_SCALE, INT8_SCALE).astype(np.int8)
