"""
Summary: The keyword step of a build. Names what every section is about
without a language model: YAKE proposes candidate phrases from the
section's own text, the vector the build already computed for the section
ranks those candidates by how close each sits to the section's meaning,
and the keywords most of a page's sections share become the page's tags,
after the categories the source recorded and the tags the source itself
gave the page, which stand first and unchanged. What was found is kept under
the cache folder keyed by section, so a later build recomputes only the
sections whose text changed. See docs/extractium-spec.md section 10.

This file is part of Extractium™
extractium/core/keywords.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-15
Last Modified: 2026-09-16
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
__date__ = "2026-09-15"

import functools
import hashlib
import importlib.util
import math

import numpy as np

from extractium.core.models import page_address_of

### Constants ###

# The extractor library, the optional `keywords` extra. It is imported
# only when candidates are wanted, so a build that has switched keywords
# off never loads it, and a machine without it is told what is missing.
KEYWORD_LIBRARY = "yake"

# The language the candidate extractor's stop-word list is for. The
# indexed content is English; a phrase in another language still yields
# candidates, but its function words are not recognised as such.
LANGUAGE = "en"

# A keyword is one to three words. Longer phrases read as clauses rather
# than as names for a subject, and the extractor's own scores favour
# them less anyway.
MAX_PHRASE_WORDS = 3

# How many of the extractor's best candidates each section keeps for the
# vector to rank, and how many of those it is finally named with. The
# candidate pool is wider than the result so that a phrase the extractor
# rated a little lower but which names the section's subject can still
# win, and so that a phrase repeating one already chosen can be passed
# over for the next.
CANDIDATES_PER_SECTION = 15
KEYWORDS_PER_SECTION = 5

# The most keyword tags a page carries, after its categories.
TAGS_PER_PAGE = 8

# Two candidates this similar, by the extractor's own string comparison,
# are one candidate: "high school" and "high schools" are not two
# keywords.
DEDUPLICATION_THRESHOLD = 0.9

# What this step writes into every section's `enrich_ver`. Change it
# whenever the way keywords are chosen changes, because a stored result
# from an earlier version is then recomputed rather than reused.
PASS_VERSION = "keywords-1"

# The stored results are keyed by section id and checked against this
# many hexadecimal characters of the section text's SHA-256, so a section
# whose text changed under the same id is named afresh.
TEXT_DIGEST_CHARS = 16


### The Extractor Library ###

def keyword_library_available():
    """
    Whether the candidate extractor can be imported.

    Returns:
        bool: True when the `keywords` extra is installed.
    """
    return importlib.util.find_spec(KEYWORD_LIBRARY) is not None


@functools.lru_cache(maxsize=1)
def _extractor(limit):
    """
    One configured extractor, built once: constructing it reads the
    stop-word list from disk, which need not happen per section.
    """
    import yake

    return yake.KeywordExtractor(
        lan=LANGUAGE,
        n=MAX_PHRASE_WORDS,
        dedup_lim=DEDUPLICATION_THRESHOLD,
        top=limit,
    )


def candidate_phrases(text, limit=CANDIDATES_PER_SECTION):
    """
    The phrases the extractor rates as the best names for what a text is
    about, best first, as they are written in the text.

    The extractor scores a phrase by statistics of the text alone: how
    often its words occur, where in the text they first appear, whether
    they are capitalised, how many different sentences they occur in, and
    how many different words surround them. No model, no network, and no
    reference corpus is involved, so the same text always yields the same
    candidates.

    Args:
        text (str): the section text.
        limit (int): the most candidates to return.

    Returns:
        list[str]: the candidates, best first; empty for a text too short
        to hold any.

    Raises:
        ImportError: if the `keywords` extra is not installed. Callers
            check keyword_library_available first.
    """
    return [phrase for phrase, _ in _extractor(limit).extract_keywords(text or "")]


### Section Vectors ###

def text_digest(text):
    """The short content digest a stored result is checked against."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:TEXT_DIGEST_CHARS]


def section_vectors(section_count, children, vecs):
    """
    One unit vector per section: the mean of its windows' vectors, which
    the build has already computed, normalised back to unit length.

    Grain: one row per section, in section order. A section with no
    window left, which compaction has already removed, would get a zero
    row rather than a division error.

    Args:
        section_count (int): how many sections there are.
        children (list[dict]): the windows, each with a "pid" naming its
            section.
        vecs (numpy.ndarray): the windows' unit vectors, one row per
            window, in the same order.

    Returns:
        numpy.ndarray: shape (section_count, dims), float32.
    """
    sums = np.zeros((section_count, vecs.shape[1]), dtype=np.float32)
    for row, child in enumerate(children):
        sums[child["pid"]] += vecs[row]
    norms = np.linalg.norm(sums, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (sums / norms).astype(np.float32)


def rank_by_similarity(candidates, section_vector, phrase_vectors):
    """
    The candidates ordered by how close each one's vector sits to the
    section's, closest first, so a phrase that names what the section is
    about outranks one that merely occurs often in it.

    Args:
        candidates (Sequence[str]): the extractor's candidates, best
            first. That order breaks ties.
        section_vector (numpy.ndarray): the section's unit vector.
        phrase_vectors (Mapping[str, numpy.ndarray]): a unit vector for
            every candidate.

    Returns:
        list[str]: the same candidates, reordered.
    """
    scored = [
        (-float(phrase_vectors[phrase] @ section_vector), position, phrase)
        for position, phrase in enumerate(candidates)
    ]
    scored.sort()
    return [phrase for _, _, phrase in scored]


def distinct_phrases(ranked, limit):
    """
    The first phrases of a ranked list that do not repeat one another,
    up to the limit.

    The extractor keeps "Mobile Tech FAQs" and "Tech FAQs" as two
    candidates, and the vector rates them alike because they mean the
    same thing. A phrase whose words all lie inside a phrase already
    chosen, or that contains one, adds nothing a reader can use, so it
    is skipped in favour of the next phrase that does.

    Args:
        ranked (Sequence[str]): candidates, best first.
        limit (int): the most phrases to keep.

    Returns:
        list[str]: the phrases kept, in the order given.
    """
    kept = []
    kept_words = []
    for phrase in ranked:
        words = frozenset(phrase.casefold().split())
        if not words or any(words <= other or words >= other for other in kept_words):
            continue
        kept.append(phrase)
        kept_words.append(words)
        if len(kept) >= limit:
            break
    return kept


### Page Tags ###

def page_tags(sections, limit=TAGS_PER_PAGE, provided=()):
    """
    The tags for one page: the categories its source recorded, outermost
    first, then the tags the source itself gave the page, then the
    keywords at least half of its sections share, the most widely shared
    first, until the page holds `limit` tags beyond its categories.

    A source's own tags are what the page's author chose, so they come
    first and unchanged. The keywords are added after them because an
    author tags a page once and rarely again, while the text is read as
    it stands today; a page tagged years ago gains a few current terms
    without losing what its author said. A keyword whose words all lie
    inside an author's tag, or that contains one, adds nothing a reader
    can use and is passed over, so "sleep" is not added beside "sleep
    research". A category is a place in a hierarchy rather than a
    description, so it rules out only its exact repeat. A one-section page shares every keyword
    with itself, so it is tagged with all of its keywords that fit. A
    page whose sections have nothing in common gains none. Tags are
    compared without regard to case, and a tag that repeats an earlier
    one is not added again.

    Args:
        sections (Sequence[dict]): the page's sections, each with
            "categories" and "keywords" keys.
        limit (int): the most tags a page holds beyond its categories,
            the source's and the computed ones together.
        provided (Sequence[str]): the tags the source gave the page.

    Returns:
        tuple[str, ...]: the tags, in that order.
    """
    tags = {}
    for category in sections[0].get("categories") or ():
        if isinstance(category, str) and category.strip():
            tags.setdefault(category.strip().casefold(), category.strip())
    category_count = len(tags)
    for tag in provided or ():
        if isinstance(tag, str) and tag.strip():
            tags.setdefault(tag.strip().casefold(), tag.strip())
    # A category is a place in a hierarchy, not a description, so a
    # keyword inside one ("sleep hygiene" under "Sleep") still adds
    # something; only the source's own tags rule out their relatives.
    taken_words = [frozenset(key.split()) for key in list(tags)[category_count:]]
    room = limit - (len(tags) - category_count)
    if room <= 0:
        return tuple(tags.values())
    counts = {}
    spelling = {}
    for section in sections:
        for keyword in dict.fromkeys(section.get("keywords") or ()):
            key = keyword.casefold()
            counts[key] = counts.get(key, 0) + 1
            spelling.setdefault(key, keyword)
    needed = math.ceil(len(sections) / 2)
    order = list(spelling)
    shared = [key for key in order if counts[key] >= needed and key not in tags]
    shared.sort(key=lambda key: (-counts[key], order.index(key)))
    added = 0
    for key in shared:
        words = frozenset(key.split())
        if any(words <= other or words >= other for other in taken_words):
            continue
        tags[key] = spelling[key]
        taken_words.append(words)
        added += 1
        if added >= room:
            break
    return tuple(tags.values())


def tag_pages(sections, provided=None):
    """
    Writes each page's tags onto every one of its sections.

    A page is every section sharing one address, with a video's
    per-moment addresses folded back into the video. The tags are the
    same on every section of a page, so an output that lists pages can
    read them from whichever section it meets first.

    Args:
        sections (list[dict]): every section, in build order; each gains
            a "tags" key.
        provided (Mapping[int, Sequence[str]] | None): the tags a
            source gave, keyed by the position of the section carrying
            them. None reads them from each section's "tags" key as it
            stands, which is how a caller that has not touched the key
            since the chunker set it says the same thing.

    Returns:
        int: how many pages were tagged.
    """
    if provided is None:
        provided = {
            position: section.get("tags") or ()
            for position, section in enumerate(sections)
        }
    pages = {}
    for position, section in enumerate(sections):
        address = page_address_of(section["u"], section["source_type"])
        pages.setdefault(address, []).append(position)
    for positions in pages.values():
        given = next((provided[position] for position in positions if provided.get(position)), ())
        tags = page_tags([sections[position] for position in positions], provided=given)
        for position in positions:
            sections[position]["tags"] = tags
    return len(pages)


### The Pass ###

class KeywordPass:
    """
    Names every section with keywords and every page with tags, reusing
    what an earlier build stored for a section whose text has not
    changed.

    The stored results are one JSON document, keyed by section id, each
    entry holding the digest of the text it was computed from, the
    keywords, and when they were computed. The document names the
    version of this step that wrote it, and a document from another
    version is ignored whole, so a change in how keywords are chosen
    reaches every section on the next build.

    Args:
        load (Callable[[], dict]): returns the stored document, or an
            empty mapping when there is none.
        save (Callable[[dict], None]): writes the document for the next
            build.
        candidates (Callable[[str], list[str]] | None): the candidate
            extractor; None means candidate_phrases, which a test may
            replace on this module.
        per_section (int): how many keywords a section is named with.
    """

    def __init__(self, load, save, candidates=None, per_section=KEYWORDS_PER_SECTION):
        self.load = load
        self.save = save
        self.candidates = candidates if candidates is not None else candidate_phrases
        self.per_section = per_section

    def run(self, sections, children, vecs, embedder, computed_at, progress):
        """
        Fills the keyword and tag fields of every section, in place.

        Every section gains "keywords", "tags", "enriched_at", and
        "enrich_ver". A section reused from the store keeps the time it
        was first named; a section named now carries computed_at. The
        candidate phrases of every section named now are embedded in one
        call, so the model is asked once however many sections there are.

        Args:
            sections (list[dict]): every section, in build order, after
                compaction.
            children (list[dict]): the surviving windows, their "pid"
                values naming sections.
            vecs (numpy.ndarray): the windows' unit vectors, one row each.
            embedder (Callable[[list[dict]], numpy.ndarray]): embeds
                chunks with "t" and "x" keys, as the build embeds windows.
            computed_at (str): the build time, ISO 8601 UTC.
            progress (Callable[[str], None]): receives one line per stage.

        Side effects:
            Writes the store through `save`, holding exactly the sections
            of this build.
        """
        stored = self.load() or {}
        remembered = stored.get("sections", {}) if stored.get("version") == PASS_VERSION else {}
        # The tags a section carries before this pass are its source's
        # own, or the ones a page carried forward unchanged from the
        # last build. Either way they stand first, and the keywords the
        # text yields fill whatever room the page has left.
        provided = {
            position: tuple(section.get("tags") or ())
            for position, section in enumerate(sections)
        }
        vectors = section_vectors(len(sections), children, vecs)
        kept = {}
        pending = []
        for position, section in enumerate(sections):
            digest = text_digest(section["x"])
            record = remembered.get(section["id"])
            if isinstance(record, dict) and record.get("hash") == digest:
                section["keywords"] = tuple(record.get("keywords") or ())
                section["enriched_at"] = record.get("enriched_at")
                section["enrich_ver"] = PASS_VERSION
                kept[section["id"]] = record
                continue
            pending.append((position, digest, self.candidates(section["x"])))

        if pending:
            phrases = sorted({phrase for _, _, candidates in pending for phrase in candidates})
            progress(
                f"Naming {len(pending)} section(s) with keywords "
                f"({len(kept)} reused from the cache); embedding {len(phrases)} candidate phrase(s)..."
            )
            matrix = embedder([{"t": "", "x": phrase} for phrase in phrases]) if phrases else np.zeros((0, vecs.shape[1]))
            phrase_vectors = {phrase: matrix[row] for row, phrase in enumerate(phrases)}
            for position, digest, candidates in pending:
                ranked = distinct_phrases(
                    rank_by_similarity(candidates, vectors[position], phrase_vectors), self.per_section
                )
                section = sections[position]
                section["keywords"] = tuple(ranked)
                section["enriched_at"] = computed_at
                section["enrich_ver"] = PASS_VERSION
                kept[section["id"]] = {"hash": digest, "keywords": list(ranked), "enriched_at": computed_at}

        pages = tag_pages(sections, provided)
        self.save({"version": PASS_VERSION, "sections": kept})
        progress(
            f"Named {len(sections)} section(s) with keywords, {len(pending)} of them afresh, "
            f"and tagged {pages} page(s)."
        )
