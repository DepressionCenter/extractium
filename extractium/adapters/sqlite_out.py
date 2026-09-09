"""
Summary: The SQLite adapter. Writes the whole compendium to one database
file with the standard library's sqlite3 module and no new dependency: build
metadata, sections, search windows, keyword statistics, and the vectors as
blobs. It holds the same content as the binary container, in a shape a SQL
consumer can query without parsing anything, which is how a hosted service
answers searches from a small runtime. See docs/extractium-spec.md sections
4 and 9.2.

This file is part of Extractium™
extractium/adapters/sqlite_out.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-09
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

import json
import sqlite3

import numpy as np

from extractium import __version__
from extractium.adapters.base import output_compendium, prepare_out_dir
from extractium.adapters.container import (
    CONTAINER_FORMAT,
    CONTAINER_VERSION,
    LICENSE_NOTICE,
    OFFSET_UNIT,
    STORAGE_DTYPES,
)

### Constants ###

# File name written when the output's entry gives none.
DEFAULT_FILE = "compendium.sqlite"

# The schema. The grain of every table is stated above it, because a
# consumer joining these tables has to know what one row means before the
# join is safe. Column names match the container header's field names
# wherever one exists, so a reader of docs/container-format.md recognises
# them; `start` and `end` are the exception, spelled out because `end` is a
# reserved word in SQL.
SCHEMA = """
-- Grain: one row per key. Everything about the build that is not a section,
-- a window, a term, or a vector.
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Grain: one row per section of text. A section is the unit a search result
-- cites and the unit shown to a language model. `pid` is the position the
-- windows, the postings, and the vectors all refer to; `id` is the stable
-- identifier that survives a rebuild.
CREATE TABLE parents (
    pid          INTEGER PRIMARY KEY,
    id           TEXT NOT NULL UNIQUE,
    t            TEXT NOT NULL,
    x            TEXT NOT NULL,
    u            TEXT NOT NULL,
    host         TEXT NOT NULL,
    source_type  TEXT NOT NULL,
    content_type TEXT NOT NULL,
    categories   TEXT NOT NULL,
    local        INTEGER NOT NULL,
    weight       REAL NOT NULL
);

-- Grain: one row per search window. A window is a slice of one section's
-- text, and it is what is embedded and what the keyword statistics count.
-- `cid` is the row number the postings and the vectors use. The offsets are
-- UTF-16 code units into the parent's `x`, the unit JavaScript strings
-- index by, so a browser can cut the window out without converting.
CREATE TABLE children (
    cid          INTEGER PRIMARY KEY,
    pid          INTEGER NOT NULL REFERENCES parents(pid),
    start_offset INTEGER NOT NULL,
    end_offset   INTEGER NOT NULL,
    doc_len      INTEGER NOT NULL
);

-- Grain: one row per distinct term in the corpus, with the number of
-- windows it appears in.
CREATE TABLE bm25_terms (
    term TEXT PRIMARY KEY,
    df   INTEGER NOT NULL
);

-- Grain: one row per (term, window) pair, with how often that term appears
-- in that window.
CREATE TABLE bm25_postings (
    term TEXT NOT NULL REFERENCES bm25_terms(term),
    cid  INTEGER NOT NULL REFERENCES children(cid),
    tf   INTEGER NOT NULL,
    PRIMARY KEY (term, cid)
);

-- Grain: one row per search window. The vector for that window, as raw
-- little-endian bytes in the dtype the meta table names, so a file built on
-- one machine reads on another.
CREATE TABLE vectors (
    cid INTEGER PRIMARY KEY REFERENCES children(cid),
    v   BLOB NOT NULL
);

CREATE INDEX children_pid ON children(pid);
CREATE INDEX bm25_postings_term ON bm25_postings(term);
"""


### Metadata Rows ###

def meta_rows(compendium):
    """
    Every row of the meta table, in a fixed order.

    A consumer compares the embedding rows against the embedder it will use
    for queries before it trusts a single vector, which is why the model,
    the width, and both prefixes travel with the data rather than being
    assumed.

    Args:
        compendium (extractium.core.models.Compendium): the build result,
            already filtered to what this output may write.

    Returns:
        list[tuple[str, str]]: (key, value) pairs. Numbers are stored as
        text so one column can hold every setting; a reader converts the few
        it needs.
    """
    embedding = compendium.embedding
    calibration = compendium.calibration
    bm25 = compendium.bm25
    rows = [
        ("_license", LICENSE_NOTICE),
        ("format", CONTAINER_FORMAT),
        ("v", str(CONTAINER_VERSION)),
        ("extractium", __version__),
        ("builtAt", compendium.built_at),
        ("site", compendium.name),
        ("sourceCount", str(compendium.source_count)),
        ("offsetUnit", OFFSET_UNIT),
        ("embedding.model", embedding.model),
        ("embedding.browserModel", embedding.browser_model),
        ("embedding.dims", str(embedding.dims)),
        ("embedding.normalized", str(int(embedding.normalized))),
        ("embedding.queryPrefix", embedding.query_prefix),
        ("embedding.passagePrefix", embedding.passage_prefix),
        ("embedding.dtype", embedding.dtype),
        ("bm25.k", str(bm25["k"])),
        ("bm25.b", str(bm25["b"])),
        ("bm25.d", str(bm25["d"])),
        ("bm25.avgDocLen", str(bm25["avgDocLen"])),
        ("calibration.mean", str(calibration["mean"])),
        ("calibration.std", str(calibration["std"])),
        ("calibration.sampleSize", str(calibration["sampleSize"])),
    ]
    if embedding.scale is not None:
        rows.append(("embedding.scale", str(embedding.scale)))
    return rows


### Table Rows ###

def parent_rows(compendium):
    """One row per section, in build order, categories as a JSON array."""
    return [
        (
            pid, parent.id, parent.t, parent.x, parent.u, parent.host,
            parent.source_type, parent.content_type,
            json.dumps(list(parent.categories), ensure_ascii=False),
            int(parent.local), parent.weight,
        )
        for pid, parent in enumerate(compendium.parents)
    ]


def child_rows(compendium):
    """
    One row per search window, in the order the vectors and the postings
    use. The token count comes from the keyword statistics, which counted it
    over the same window.
    """
    children = compendium.children
    doc_len = compendium.bm25["docLen"]
    return [
        (cid, pid, start, end, doc_len[cid])
        for cid, (pid, start, end) in enumerate(zip(children.pid, children.start, children.end))
    ]


def term_rows(compendium):
    """One row per term, with the number of windows it appears in."""
    return sorted(compendium.bm25["df"].items())


def posting_rows(compendium):
    """One row per (term, window) pair, with the term's count in that window."""
    return [
        (term, cid, tf)
        for term, postings in sorted(compendium.bm25["postings"].items())
        for cid, tf in postings
    ]


def vector_rows(compendium):
    """
    One row per window, holding that window's vector as raw little-endian
    bytes in the stored dtype.
    """
    stored = np.ascontiguousarray(
        compendium.vectors, dtype=STORAGE_DTYPES[compendium.embedding.dtype]
    )
    return [(cid, row.tobytes()) for cid, row in enumerate(stored)]


### Adapter ###

class SqliteAdapter:
    """
    Writes the compendium as one SQLite database.

    The file holds the section text, not a description of it: a service that
    answers a search has to return the text it matched. Its confidentiality
    behaviour is therefore the container's, and it goes through the same
    guardrail, so content read from a local folder is dropped unless this
    output's entry set `include_local: true`.

    Each run writes a fresh file. Adding to a database left over from an
    earlier build would leave rows describing sections that no longer exist,
    and every row number here is a position in a list that the new build
    renumbered.

    This adapter never fetches a URL and never runs the embedding model: it
    serializes the compendium it is given and nothing else.
    """

    name = "sqlite"

    def write(self, compendium, out_dir, options):
        """
        Writes one database file.

        Args:
            compendium (extractium.core.models.Compendium): the build result.
            out_dir (str | pathlib.Path): folder to write under; created
                when it does not exist.
            options (Mapping): the output's validated options: `file` for
                the name, `include_local` for the local-content guardrail.

        Returns:
            tuple[pathlib.Path, ...]: the one path written.

        Raises:
            OSError: if the file cannot be replaced or written.
        """
        compendium = output_compendium(compendium, options)
        path = prepare_out_dir(out_dir) / options.get("file", DEFAULT_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)

        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON;")
            connection.executescript(SCHEMA)
            connection.executemany("INSERT INTO meta (key, value) VALUES (?, ?);",
                                   meta_rows(compendium))
            connection.executemany(
                "INSERT INTO parents (pid, id, t, x, u, host, source_type, content_type, "
                "categories, local, weight) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                parent_rows(compendium),
            )
            connection.executemany(
                "INSERT INTO children (cid, pid, start_offset, end_offset, doc_len) "
                "VALUES (?, ?, ?, ?, ?);",
                child_rows(compendium),
            )
            connection.executemany("INSERT INTO bm25_terms (term, df) VALUES (?, ?);",
                                   term_rows(compendium))
            connection.executemany("INSERT INTO bm25_postings (term, cid, tf) VALUES (?, ?, ?);",
                                   posting_rows(compendium))
            connection.executemany("INSERT INTO vectors (cid, v) VALUES (?, ?);",
                                   vector_rows(compendium))
            connection.commit()
        finally:
            connection.close()
        return (path,)
