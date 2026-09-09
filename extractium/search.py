"""
Summary: The Python client for a version 3 compendium: reads the binary
container back, checks it against the reader checklist, and runs the
hybrid search over it -- cosine similarity, BM25, reciprocal rank fusion,
a corpus-relative relevance threshold, diversity selection, and
resolution of each matched window to the section that contains it. The
caller supplies the query embedder, so this module never loads a model.
The JavaScript client in clients/js/extractium-client.js implements the
same algorithm with the same constants; tests/test_search_contract.py
holds them to the same ranking. See docs/container-format.md and
docs/how-to/search-a-compendium.md.

This file is part of Extractium™
extractium/search.py

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

import json
import math
import re
import struct
from dataclasses import dataclass

import numpy as np

### Constants ###

# The only container this reader accepts. Both values are checked before
# anything else is read, so a file of some other shape that happens to
# carry a .json name is refused rather than half-parsed.
CONTAINER_FORMAT = "extractium-compendium"
CONTAINER_VERSION = 3

# Width in bytes of one stored vector component, by container dtype.
DTYPE_WIDTHS = {"int8": 1, "float32": 4}

# How the stored bytes are read back. Little-endian whatever the machine
# reading them is, matching what the container adapter writes.
DTYPE_CODES = {"int8": "<i1", "float32": "<f4"}

# Query tokens are runs of three or more ASCII letters or digits, in
# lowercase. This MUST stay identical to the build-side rule in
# extractium/core/bm25.py: postings built under one tokenization cannot
# be looked up under another, and the failure is silent -- keyword
# matching simply stops working.
TOKEN_RE = re.compile(r"[a-z0-9]{3,}")

# Absolute similarity floor. Below this, a window is never relevant no
# matter how it compares with the rest of the pool. The value suits
# bge-small-en-v1.5, whose cosine similarities run high even for
# unrelated text; a different embedding model needs it retuned.
SCORE_MIN = 0.44

# A hit must also beat the median of its own candidate pool by this
# much. Self-relative, so it keeps working on a corpus whose absolute
# scores sit somewhere else entirely.
SCORE_MARGIN = 0.03

# How far above the corpus calibration mean, in standard deviations, a
# score must sit to count as relevant. Used only when the file carries
# calibration statistics.
ZSCORE_MARGIN = 1.0

# Raw candidates pulled per query, before thresholding and diversity.
CANDIDATE_POOL = 50

# How many of those candidates the diversity pass considers.
MMR_POOL_CAP = 20

# Relevance against variety in the diversity pass. 1.0 would be pure
# relevance, which lets several near-copies of one page fill the answer.
MMR_LAMBDA = 0.7

# Most windows kept from any one section, so a long article cannot take
# every slot.
SOURCE_CAP = 2

# Sections returned per search when the caller names no other number.
TOP_K = 4

# Reciprocal rank fusion. 60 is the constant from the literature, and
# the two weights are the trust split between the vector list and the
# keyword list. Fusion uses rank alone, never the raw scores, which is
# what makes a cosine list and a BM25 list comparable without
# normalizing either.
RRF_K = 60
RRF_VECTOR_WEIGHT = 0.5
RRF_BM25_WEIGHT = 0.5


class ContainerError(ValueError):
    """Raised when a file is not a readable version 3 compendium."""


### Container Reader ###

def _header_of(data):
    """
    Splits the raw bytes into the parsed header and the vector bytes.

    Args:
        data (bytes): the whole file.

    Returns:
        tuple[dict, bytes]: the header object and the bytes after it.

    Raises:
        ContainerError: if the file is too short, the header length runs
            past the end of the file, or the header is not JSON.
    """
    if len(data) < 4:
        raise ContainerError("file is too short to hold a container header length.")
    (header_length,) = struct.unpack("<I", data[:4])
    if 4 + header_length > len(data):
        raise ContainerError(
            f"header length ({header_length}) runs past the end of the file ({len(data)} bytes)."
        )
    try:
        header = json.loads(data[4:4 + header_length].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContainerError(f"header is not valid UTF-8 JSON: {error}") from error
    if not isinstance(header, dict):
        raise ContainerError("header must be a JSON object.")
    return header, data[4 + header_length:]


def _checked_vectors(header, vector_bytes):
    """
    Reads the vector bytes into one array of floats, one row per child.

    int8 vectors are divided by the header's scale to recover the floats
    they were quantized from. The byte count is checked first, because a
    truncated file would otherwise produce a shorter array whose rows no
    longer line up with the children.

    Args:
        header (dict): the parsed container header.
        vector_bytes (bytes): everything after the header.

    Returns:
        numpy.ndarray: shape (child count, dims), float32.

    Raises:
        ContainerError: if the dtype is unknown, the scale is missing or
            not usable, or the byte count does not match the children.
    """
    embedding = header["embedding"]
    dtype = embedding.get("dtype")
    if dtype not in DTYPE_WIDTHS:
        raise ContainerError(f"unknown vector dtype {dtype!r}.")

    dims = embedding["dims"]
    child_count = len(header["children"]["pid"])
    expected = child_count * dims * DTYPE_WIDTHS[dtype]
    if len(vector_bytes) != expected:
        raise ContainerError(
            f"vector bytes ({len(vector_bytes)}) do not match {child_count} children "
            f"x {dims} dims x {DTYPE_WIDTHS[dtype]} bytes ({expected})."
        )

    # A fresh copy, because the bytes start at an offset that is not
    # guaranteed to suit a 32-bit read.
    values = np.frombuffer(bytes(vector_bytes), dtype=DTYPE_CODES[dtype])
    vectors = np.array(values, dtype=np.float32).reshape(child_count, dims)
    if dtype == "int8":
        scale = embedding.get("scale")
        if not isinstance(scale, (int, float)) or scale <= 0:
            raise ContainerError(f"int8 vectors need a positive scale; got {scale!r}.")
        vectors /= float(scale)
    return vectors


### Search Results ###

@dataclass(frozen=True)
class Hit:
    """
    One section a search returned, with the window that matched it.

    Attributes:
        parent (dict): the section record from the container header, with
            its heading (`t`), text (`x`), URL (`u`), and the rest of the
            per-section fields the container format lists.
        score (float): fused relevance score. Comparable within one
            result list; not a probability and not a cosine similarity
            once keyword and vector results have been fused.
        child_index (int): position of the matched window in the
            container's child columns.
        start (int | None): start of the matched window inside the
            section text, in UTF-16 code units; None when the file keeps
            no offsets.
        end (int | None): exclusive end of the matched window.
    """

    parent: dict
    score: float
    child_index: int
    start: object = None
    end: object = None

    @property
    def window_text(self):
        """
        The matched window's own text, or the whole section when the file
        keeps no offsets. Offsets are counted in UTF-16 code units, so the
        slice is taken in that encoding rather than in Python characters.
        """
        text = self.parent.get("x", "")
        if self.start is None or self.end is None:
            return text
        encoded = text.encode("utf-16-le")
        return encoded[self.start * 2:self.end * 2].decode("utf-16-le", errors="ignore")


### Scoring ###

def tokenize(text):
    """
    Splits text into BM25 terms: lowercased runs of three or more ASCII
    letters or digits.

    Args:
        text (str): a query, or any text to match the build-side rule.

    Returns:
        list[str]: the terms, in the order they appear.
    """
    return TOKEN_RE.findall((text or "").lower())


def rrf_fuse(ranked_lists, weight_of=None):
    """
    Fuses ranked result lists by reciprocal rank.

    Each list must already be sorted best first. Only the position of a
    candidate inside its own list counts, never its score, which is what
    lets a cosine list and a BM25 list combine with no rescaling.

    Args:
        ranked_lists (Sequence[tuple[Sequence[dict], float]]): pairs of
            a ranked list and how much to trust it. Each entry of a list
            is a mapping with an `i` key naming the child it scores.
        weight_of (Callable[[int], float] | None): per-child multiplier
            applied after fusion, used for the per-section `weight` field.

    Returns:
        list[dict]: one entry per distinct child, best first, with `s`
        holding the fused score.
    """
    fused = {}
    for items, list_weight in ranked_lists:
        for rank, item in enumerate(items):
            contribution = list_weight * (RRF_K / (RRF_K + rank + 1))
            index = item["i"]
            if index in fused:
                fused[index]["s"] += contribution
            else:
                fused[index] = {"i": index, "s": contribution}
    out = list(fused.values())
    if weight_of is not None:
        for entry in out:
            entry["s"] *= weight_of(entry["i"])
    # Ties break on the child index so two clients, and two runs, agree
    # on the order of equally scored windows.
    out.sort(key=lambda entry: (-entry["s"], entry["i"]))
    return out


def vector_candidates(query_vector, vectors, pool_size=CANDIDATE_POOL):
    """
    Ranks every window by cosine similarity to the query.

    Stored vectors have unit length, so a dot product is the cosine
    similarity. The query vector is normalized here rather than trusted,
    because an embedder that skipped normalization would otherwise
    change every score.

    Args:
        query_vector (Sequence[float]): the embedded query.
        vectors (numpy.ndarray): shape (child count, dims).
        pool_size (int): how many candidates to keep.

    Returns:
        list[dict]: `{"i": child index, "s": cosine similarity}`, best
        first, at most pool_size entries.
    """
    if vectors.shape[0] == 0:
        return []
    query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(query))
    if norm > 0:
        query = query / norm
    scores = vectors @ query
    keep = min(pool_size, scores.shape[0])
    # A stable sort leaves equally scored windows in child order, so this
    # client and the JavaScript one return the same pool for the same file.
    ranked = np.argsort(-scores, kind="stable")[:keep]
    return [{"i": int(i), "s": float(scores[i])} for i in ranked]


def bm25_candidates(terms, bm25, child_count, pool_size=CANDIDATE_POOL):
    """
    Ranks windows by keyword match, walking only the postings lists of
    terms the query actually contains. The cost follows the query, not
    the size of the corpus, which is what makes this practical to run in
    a browser on every keystroke.

    The formula and its constants come from the file itself, so an index
    rebuilt with different tuning needs no client change.

    Args:
        terms (Iterable[str]): query terms from `tokenize`.
        bm25 (Mapping | None): the container's keyword statistics.
        child_count (int): number of windows in the corpus.
        pool_size (int): how many candidates to keep.

    Returns:
        list[dict]: `{"i": child index, "s": BM25 score}`, best first.
    """
    if not bm25 or not terms:
        return []
    k = bm25.get("k", 1.2)
    b = bm25.get("b", 0.75)
    d = bm25.get("d", 0.5)
    avg_doc_len = bm25.get("avgDocLen") or 1.0
    doc_len = bm25.get("docLen") or []
    df = bm25.get("df") or {}
    postings = bm25.get("postings") or {}

    scores = {}
    for term in dict.fromkeys(terms):
        posting = postings.get(term)
        if not posting:
            continue
        doc_freq = df.get(term, len(posting))
        idf = math.log(1 + (child_count - doc_freq + 0.5) / (doc_freq + 0.5))
        for child_index, term_frequency in posting:
            length = doc_len[child_index] if child_index < len(doc_len) else 0
            denominator = term_frequency + k * (1 - b + b * length / avg_doc_len)
            if denominator == 0:
                continue
            gain = idf * (d + term_frequency * (k + 1)) / denominator
            scores[child_index] = scores.get(child_index, 0.0) + gain

    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    return [{"i": int(i), "s": float(s)} for i, s in ranked[:pool_size]]


def relevance_cutoff(candidates, calibration=None):
    """
    The score a candidate must reach to count as relevant.

    Three tests, whichever is strictest: an absolute floor, the median of
    this query's own candidate pool plus a margin, and, when the file
    carries calibration statistics, a fixed number of standard deviations
    above the corpus mean. The relative test is the one that survives a
    change of corpus or embedding model; the other two are safety nets.

    Note that once vector and keyword results have been fused, a
    candidate's score is a fused rank score rather than a cosine
    similarity, so the two absolute tests are approximations on that
    scale. The relative test is unaffected, because it moves with the
    pool.

    Args:
        candidates (Sequence[Mapping]): the scored candidate pool.
        calibration (Mapping | None): the container's calibration object.

    Returns:
        float: the cutoff, or negative infinity for an empty pool.
    """
    if not candidates:
        return -math.inf
    scores = sorted(candidate["s"] for candidate in candidates)
    median = scores[len(scores) // 2]
    cutoff = max(SCORE_MIN, median + SCORE_MARGIN)
    if calibration and calibration.get("std"):
        cutoff = max(cutoff, calibration["mean"] + ZSCORE_MARGIN * calibration["std"])
    return cutoff


def diversify(candidates, vectors, k, source_key_of, no_threshold=False, calibration=None):
    """
    Picks the windows to return: relevant, varied, and spread across
    sections.

    Runs in three passes. First the relevance cutoff drops weak
    candidates. Then a greedy maximal-marginal-relevance pass prefers a
    candidate that is both similar to the query and unlike what is
    already chosen, so several near-copies of one paragraph cannot fill
    the answer. Finally a per-section cap keeps one long article from
    taking every slot.

    Args:
        candidates (Sequence[Mapping]): scored candidates, best first.
        vectors (numpy.ndarray): the corpus vectors, for the similarity
            comparisons between candidates.
        k (int): how many windows to select.
        source_key_of (Callable[[int], str]): identity of the section a
            child belongs to, for the per-section cap.
        no_threshold (bool): skip the relevance cutoff, for a caller that
            wants the closest windows whether or not they are relevant.
        calibration (Mapping | None): the container's calibration object.

    Returns:
        list[dict]: the selected candidates, in the order chosen.
    """
    if not candidates:
        return []
    if no_threshold:
        surviving = list(candidates)
    else:
        cutoff = relevance_cutoff(candidates, calibration)
        surviving = [candidate for candidate in candidates if candidate["s"] >= cutoff]
    if not surviving:
        return []

    remaining = surviving[:MMR_POOL_CAP]
    selected = []
    source_counts = {}
    while len(selected) < k and remaining:
        best_position, best_score = -1, -math.inf
        for position, candidate in enumerate(remaining):
            key = source_key_of(candidate["i"])
            if source_counts.get(key, 0) >= SOURCE_CAP:
                continue
            highest_similarity = 0.0
            for chosen in selected:
                similarity = float(vectors[candidate["i"]] @ vectors[chosen["i"]])
                highest_similarity = max(highest_similarity, similarity)
            mmr = MMR_LAMBDA * candidate["s"] - (1 - MMR_LAMBDA) * highest_similarity
            if mmr > best_score:
                best_position, best_score = position, mmr
        if best_position == -1:
            break  # every remaining candidate is already at its section cap
        chosen = remaining.pop(best_position)
        selected.append(chosen)
        key = source_key_of(chosen["i"])
        source_counts[key] = source_counts.get(key, 0) + 1
    return selected


### Index ###

class SearchIndex:
    """
    One compendium, loaded and ready to search.

    Build one with `load_container`. The object holds the parsed header,
    the dequantized vectors, and the keyword statistics; it never fetches
    anything and never loads an embedding model.
    """

    def __init__(self, header, vectors):
        """
        Args:
            header (dict): the parsed container header.
            vectors (numpy.ndarray): shape (child count, dims), float32.
        """
        self.header = header
        self.vectors = vectors
        self.parents = header["parents"]
        self.children = header["children"]
        self.embedding = header["embedding"]
        self.bm25 = header.get("bm25")
        self.calibration = header.get("calibration")

    @property
    def name(self):
        """Display name of the knowledge base."""
        return self.header.get("site", "")

    @property
    def query_prefix(self):
        """
        Text the embedding model expects in front of a search query. The
        model this format ships with was trained for asymmetric search:
        the prefix goes on queries only, never on indexed text.
        """
        return self.embedding.get("queryPrefix", "")

    def __len__(self):
        """Number of search windows in the corpus."""
        return len(self.children["pid"])

    def parent_of(self, child_index):
        """
        The section a window belongs to.

        Args:
            child_index (int): position in the child columns.

        Returns:
            dict: the section record.
        """
        return self.parents[self.children["pid"][child_index]]

    def _source_key_of(self, child_index):
        """
        Identity used by the per-section cap. The section's stable id,
        so two windows of the same section share it and two sections of
        one long page do not.
        """
        parent = self.parent_of(child_index)
        return parent.get("id") or f"{parent.get('u', '')}#{self.children['pid'][child_index]}"

    def _weight_of(self, child_index):
        """The per-section weight, applied after fusion. Defaults to 1.0."""
        weight = self.parent_of(child_index).get("weight", 1.0)
        return float(weight) if isinstance(weight, (int, float)) else 1.0

    def candidates(self, query, query_vector, pool_size=CANDIDATE_POOL):
        """
        The scored candidate pool for one query, before thresholding and
        diversity selection.

        Vector and keyword results are fused by reciprocal rank when the
        file carries keyword statistics and the query has terms that
        appear in them. Otherwise the vector ranking stands alone. Either
        way the per-section weight is applied, so a weighted source does
        not quietly lose its weight on a query with no keyword matches.

        Args:
            query (str): the query text, for keyword matching.
            query_vector (Sequence[float]): the embedded query.
            pool_size (int): how many candidates to keep.

        Returns:
            list[dict]: `{"i": child index, "s": score}`, best first.
        """
        vector_ranked = vector_candidates(query_vector, self.vectors, pool_size)
        terms = tokenize(query) if self.bm25 else []
        keyword_ranked = bm25_candidates(terms, self.bm25, len(self), pool_size)
        if not keyword_ranked:
            weighted = [
                {"i": entry["i"], "s": entry["s"] * self._weight_of(entry["i"])}
                for entry in vector_ranked
            ]
            weighted.sort(key=lambda entry: (-entry["s"], entry["i"]))
            return weighted
        return rrf_fuse(
            [(vector_ranked, RRF_VECTOR_WEIGHT), (keyword_ranked, RRF_BM25_WEIGHT)],
            self._weight_of,
        )

    def search(self, query, embed_query, k=TOP_K, no_threshold=False):
        """
        Searches the compendium and returns whole sections.

        Small windows are searched and whole sections are returned, so a
        match is precise but the text handed to a reader or a language
        model still has enough context to answer from.

        Args:
            query (str): what the user asked, unprefixed. The query
                prefix this file records is added before embedding.
            embed_query (Callable[[str], Sequence[float]]): embeds one
                string with the model named in the file's `embedding`
                object. Called once per search.
            k (int): how many sections to return.
            no_threshold (bool): return the closest sections even when
                none clears the relevance cutoff. Use it to show a reader
                what was nearest, never to answer from.

        Returns:
            list[Hit]: the selected sections, best first. Empty when
            nothing clears the cutoff.
        """
        query_vector = embed_query(self.query_prefix + query)
        pool = self.candidates(query, query_vector)
        selected = diversify(
            pool, self.vectors, k, self._source_key_of, no_threshold, self.calibration
        )
        return [self._hit_of(candidate) for candidate in selected]

    def _hit_of(self, candidate):
        """Resolves one selected window to the section that contains it."""
        child_index = candidate["i"]
        starts = self.children.get("start") or []
        ends = self.children.get("end") or []
        return Hit(
            parent=self.parent_of(child_index),
            score=candidate["s"],
            child_index=child_index,
            start=starts[child_index] if child_index < len(starts) else None,
            end=ends[child_index] if child_index < len(ends) else None,
        )


### Loading ###

def load_container(source, model=None, dims=None):
    """
    Reads a version 3 container and returns an index ready to search.

    Every check in the container format's reader checklist runs here, so
    a truncated, altered, or foreign file is refused with a message that
    names the problem instead of failing somewhere deep in a search.

    Args:
        source (str | pathlib.Path | bytes | bytearray): the file to
            read, or its bytes.
        model (str | None): the Hugging Face model id of the embedder
            that will embed queries. When given, a file built with
            another model is refused, because vectors from two models
            are not comparable.
        dims (int | None): the vector length that embedder produces.
            When given, a file of another width is refused.

    Returns:
        SearchIndex: the loaded compendium.

    Raises:
        ContainerError: if the file is not a readable version 3
            compendium, or does not match the embedder named above.
        OSError: if the path cannot be read.
    """
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        with open(source, "rb") as handle:
            data = handle.read()

    header, vector_bytes = _header_of(data)
    if header.get("format") != CONTAINER_FORMAT:
        raise ContainerError(
            f"not an Extractium compendium: format is {header.get('format')!r}."
        )
    if header.get("v") != CONTAINER_VERSION:
        raise ContainerError(
            f"container version {header.get('v')!r} is not supported; this client reads "
            f"version {CONTAINER_VERSION}."
        )
    for required in ("embedding", "parents", "children"):
        if required not in header:
            raise ContainerError(f"header is missing the {required!r} field.")
    if "pid" not in header["children"]:
        raise ContainerError("children columns are missing 'pid'.")

    embedding = header["embedding"]
    if model is not None and embedding.get("model") != model:
        raise ContainerError(
            f"file was built with {embedding.get('model')!r}, but queries will be embedded "
            f"with {model!r}; the vectors are not comparable."
        )
    if dims is not None and embedding.get("dims") != dims:
        raise ContainerError(
            f"file has {embedding.get('dims')!r}-dimensional vectors, but the query embedder "
            f"produces {dims}."
        )

    parent_count = len(header["parents"])
    for position, pid in enumerate(header["children"]["pid"]):
        if not isinstance(pid, int) or pid < 0 or pid >= parent_count:
            raise ContainerError(
                f"child {position} points at section {pid!r}, outside the {parent_count} sections."
            )

    return SearchIndex(header, _checked_vectors(header, vector_bytes))
