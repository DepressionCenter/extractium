"""
Summary: What is indexed for one file or page whose text is too long to
index whole: a compact record made of its title, its opening paragraph,
its headings, and the terms it uses most. Every line of the record is
quoted or counted from the text; nothing is described that nobody
wrote, and no model is involved. Used by the web crawl, the GitHub
source, and the code analysis alike, so one ceiling holds everywhere.

This file is part of Extractium™
extractium/core/prose.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-15
Last Modified: 2026-09-15
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

from collections import Counter

from extractium.core.bm25 import tokenize

### Limits ###

# The most characters of one file's text indexed whole. Under this, a
# page or a document is chunked in full. Over it, a compact record
# stands in for the text: the title, the opening paragraph, the
# headings, and the terms used most, with a line saying so. A search
# still finds the file by what it is about, and the index does not
# grow by thousands of chunks for one file, which at this length is
# generated far more often than written. About 35,000 words, so a
# manual passes and a rendered data table does not.
MAX_PROSE_CHARS = 200_000

# How much of a long file its compact record quotes.
MAX_RECORD_HEADINGS = 40
MAX_RECORD_TERMS = 40
MAX_RECORD_OPENING_CHARS = 1_000

# English function words, left out of a compact record's term list
# because they say nothing about what a file holds. Kept short on
# purpose: a term that survives this list and is still frequent is a
# term the file is about.
STOPWORDS = frozenset("""
the and for with that this from are was were not but all any can has have
had its our your their they them then than when what which who whom will
would should could may might must shall into onto out over under about
above below between after before during each every some such only also
more most other another same very just here there where how why been being
does did done use used using one two three you his her she him let get got
per via etc see set new off own too yes non
""".split())


### The Record ###

def first_paragraph(prose, skipping=()):
    """
    The first paragraph of a file's text, which is what its author wrote
    to introduce it. Markdown heading marks are dropped.

    Args:
        prose (str): the text, paragraphs separated by a blank line.
        skipping (Iterable[str]): paragraphs to pass over, such as a
            heading that merely repeats the title.
    """
    for block in (prose or "").split("\n\n"):
        cleaned = " ".join(line.strip("# ").strip() for line in block.splitlines()).strip()
        if cleaned and cleaned not in skipping:
            return cleaned
    return ""


def headings_in(prose):
    """The Markdown headings a text carries, in order."""
    found = []
    for line in (prose or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                found.append(heading)
    return tuple(found)


def frequent_terms(text, limit=MAX_RECORD_TERMS):
    """
    The terms a text uses most, most frequent first, with function words
    and bare numbers left out. Tokenized the way the keyword index is,
    so a term listed here is a term a search can match.
    """
    counts = Counter(
        term for term in tokenize(text) if term not in STOPWORDS and not term.isdigit()
    )
    return tuple(term for term, _ in counts.most_common(limit))


def compact_record(title, prose, headings=()):
    """
    A stand-in for a file too long to index whole.

    Args:
        title (str): the file's title, or an empty string.
        prose (str): the whole text.
        headings (Iterable[str]): the headings a reader collected; the
            Markdown headings in the prose are used when it is empty.

    Returns:
        str: the title, the opening paragraph, the headings, the terms
        used most, and a line saying the file was indexed this way.
        Every sentence in it is quoted or counted from the file; nothing
        is described that nobody wrote.
    """
    lines = [title] if title else []
    opening = first_paragraph(prose, skipping=(title,))[:MAX_RECORD_OPENING_CHARS].strip()
    if opening:
        lines += ["", opening]
    found = tuple(headings) or headings_in(prose)
    if found:
        lines += ["", "Headings: " + "; ".join(found[:MAX_RECORD_HEADINGS])]
    terms = frequent_terms(prose)
    if terms:
        lines += ["", "Terms used most: " + ", ".join(terms)]
    lines += ["", (
        f"This file holds {len(prose):,} characters of text, more than the "
        f"{MAX_PROSE_CHARS:,} this index takes whole, so only this outline was "
        "indexed. Open the file for the rest."
    )]
    return "\n".join(lines).strip()


def prose_for_index(title, prose, headings=()):
    """
    The text to index for one file: the text itself when it is under
    MAX_PROSE_CHARS, and its compact record when it is not.
    """
    if len(prose) <= MAX_PROSE_CHARS:
        return prose
    return compact_record(title, prose, headings)
