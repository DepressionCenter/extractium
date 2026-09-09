"""
Summary: Tests for the SQLite adapter. Checks that every table's row count
matches the compendium it was written from, that the vector bytes are the
same ones the binary container stores, that a rerun replaces the database
rather than adding to it, and that content read from a local folder reaches
this output only when the output asked for it.

This file is part of Extractium™
tests/test_adapter_sqlite.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-09
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
__date__ = "2026-09-09"

import json
import sqlite3

import numpy as np
import pytest

from extractium.adapters.container import ContainerAdapter
from extractium.adapters.sqlite_out import DEFAULT_FILE, SqliteAdapter
from extractium.core.models import Adapter
from tests.test_adapter_container import (
    LOCAL_TEXT,
    mixed_compendium,
    read_container,
    sample_compendium,
)


def write(compendium, out_dir, **options):
    """Writes the database the way the command line does, and returns its path."""
    return SqliteAdapter().write(compendium, out_dir, options)[0]


def query(path, sql, *parameters):
    """Every row one statement returns."""
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()


def count(path, table):
    """How many rows one table holds."""
    return query(path, f"SELECT COUNT(*) FROM {table};")[0][0]


def meta(path):
    """The meta table as a dictionary."""
    return dict(query(path, "SELECT key, value FROM meta;"))


@pytest.fixture
def compendium(fixtures_dir, fake_embed_chunks_core):
    """Two crawled pages, built with the deterministic test embedder."""
    return sample_compendium(fixtures_dir, fake_embed_chunks_core)


@pytest.fixture
def mixed(fixtures_dir, fake_embed_chunks_core):
    """One crawled page and one local file."""
    return mixed_compendium(fixtures_dir, fake_embed_chunks_core)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_the_adapter_satisfies_the_adapter_protocol():
    assert isinstance(SqliteAdapter(), Adapter)
    assert SqliteAdapter.name == "sqlite"


def test_write_honors_the_configured_file_name(tmp_path, compendium):
    path = write(compendium, tmp_path, file="kb.sqlite")

    assert path.name == "kb.sqlite"


def test_write_creates_a_missing_output_folder(tmp_path, compendium):
    path = write(compendium, tmp_path / "dist" / "nested")

    assert path.exists()
    assert path.name == DEFAULT_FILE


# ---------------------------------------------------------------------------
# Row counts match the compendium
# ---------------------------------------------------------------------------

def test_every_table_holds_one_row_per_thing_it_describes(tmp_path, compendium):
    path = write(compendium, tmp_path)

    assert count(path, "parents") == len(compendium.parents)
    assert count(path, "children") == len(compendium.children)
    assert count(path, "vectors") == len(compendium.children)
    assert count(path, "bm25_terms") == len(compendium.bm25["df"])
    assert count(path, "bm25_postings") == sum(
        len(postings) for postings in compendium.bm25["postings"].values()
    )


def test_a_parent_row_carries_its_stable_id_and_its_metadata(tmp_path, compendium):
    path = write(compendium, tmp_path)
    first = compendium.parents[0]

    row = query(
        path,
        "SELECT id, t, x, u, host, source_type, content_type, categories, local, weight "
        "FROM parents WHERE pid = 0;",
    )[0]

    assert row[:7] == (first.id, first.t, first.x, first.u, first.host,
                       first.source_type, first.content_type)
    assert json.loads(row[7]) == list(first.categories)
    assert row[8] == int(first.local)
    assert row[9] == first.weight


def test_a_child_row_points_at_its_parent_and_carries_its_window(tmp_path, compendium):
    path = write(compendium, tmp_path)

    rows = query(path, "SELECT cid, pid, start_offset, end_offset, doc_len FROM children ORDER BY cid;")

    assert [row[1] for row in rows] == list(compendium.children.pid)
    assert [row[2] for row in rows] == list(compendium.children.start)
    assert [row[3] for row in rows] == list(compendium.children.end)
    assert [row[4] for row in rows] == list(compendium.bm25["docLen"])


def test_the_keyword_statistics_are_stored_term_by_term(tmp_path, compendium):
    path = write(compendium, tmp_path)
    term, postings = sorted(compendium.bm25["postings"].items())[0]

    df = query(path, "SELECT df FROM bm25_terms WHERE term = ?;", term)[0][0]
    stored = query(path, "SELECT cid, tf FROM bm25_postings WHERE term = ? ORDER BY cid;", term)

    assert df == compendium.bm25["df"][term]
    assert stored == [tuple(posting) for posting in sorted(postings)]


def test_every_posting_points_at_a_window_that_exists(tmp_path, compendium):
    path = write(compendium, tmp_path)

    orphans = query(
        path,
        "SELECT COUNT(*) FROM bm25_postings p LEFT JOIN children c ON c.cid = p.cid "
        "WHERE c.cid IS NULL;",
    )[0][0]

    assert orphans == 0


# ---------------------------------------------------------------------------
# Metadata and vectors
# ---------------------------------------------------------------------------

def test_the_meta_table_records_how_the_vectors_were_made(tmp_path, compendium):
    """A consumer compares these against its own embedder before trusting a vector."""
    rows = meta(write(compendium, tmp_path))

    assert rows["embedding.model"] == compendium.embedding.model
    assert rows["embedding.dims"] == str(compendium.embedding.dims)
    assert rows["embedding.queryPrefix"] == compendium.embedding.query_prefix
    assert rows["embedding.dtype"] == "int8"
    assert rows["embedding.scale"] == str(compendium.embedding.scale)


def test_the_meta_table_records_the_build_and_the_licence(tmp_path, compendium):
    rows = meta(write(compendium, tmp_path))

    assert rows["site"] == compendium.name
    assert rows["builtAt"] == compendium.built_at
    assert rows["sourceCount"] == str(compendium.source_count)
    assert rows["offsetUnit"] == "utf16"
    assert "GNU General Public License" in rows["_license"]


def test_float32_vectors_leave_out_the_int8_scale(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core, float32_vecs=True)

    rows = meta(write(compendium, tmp_path))

    assert rows["embedding.dtype"] == "float32"
    assert "embedding.scale" not in rows


def test_the_vector_bytes_are_the_ones_the_container_stores(tmp_path, compendium):
    """
    Both outputs are serializations of one build, so a consumer that reads
    the database gets the same vectors as one that parses the container.
    """
    database = write(compendium, tmp_path)
    container = ContainerAdapter().write(compendium, tmp_path, {})[0]

    blobs = b"".join(row[0] for row in query(database, "SELECT v FROM vectors ORDER BY cid;"))
    _, vector_bytes = read_container(container)

    assert blobs == vector_bytes


def test_a_stored_vector_reads_back_as_the_row_it_came_from(tmp_path, compendium):
    path = write(compendium, tmp_path)

    blob = query(path, "SELECT v FROM vectors WHERE cid = 0;")[0][0]

    assert np.array_equal(np.frombuffer(blob, dtype="<i1"), compendium.vectors[0])


# ---------------------------------------------------------------------------
# Rerunning a build
# ---------------------------------------------------------------------------

def test_a_second_build_replaces_the_database_rather_than_adding_to_it(tmp_path, compendium):
    """
    Every row number here is a position in a list the new build renumbered,
    so rows left over from an earlier build would point at the wrong text.
    """
    first = write(compendium, tmp_path)
    before = {table: count(first, table) for table in
              ("parents", "children", "vectors", "bm25_terms", "bm25_postings")}

    second = write(compendium, tmp_path)

    assert second == first
    assert {table: count(second, table) for table in before} == before


# ---------------------------------------------------------------------------
# The local content guardrail
# ---------------------------------------------------------------------------

def test_local_content_is_absent_from_a_database_that_did_not_opt_in(tmp_path, mixed):
    path = write(mixed, tmp_path)

    assert query(path, "SELECT COUNT(*) FROM parents WHERE local = 1;")[0][0] == 0
    assert LOCAL_TEXT not in path.read_bytes().decode("utf-8", errors="replace")


def test_local_content_is_written_to_a_database_that_opted_in(tmp_path, mixed):
    path = write(mixed, tmp_path, include_local=True)

    assert query(path, "SELECT COUNT(*) FROM parents WHERE local = 1;")[0][0] == 1
    assert LOCAL_TEXT in path.read_bytes().decode("utf-8", errors="replace")


def test_dropping_local_content_leaves_every_table_consistent(tmp_path, mixed):
    """
    Dropping a section drops its windows, its vectors, and its share of the
    keyword statistics, so nothing left behind points at content that is gone.
    """
    path = write(mixed, tmp_path)

    assert count(path, "children") == count(path, "vectors")
    assert query(
        path,
        "SELECT COUNT(*) FROM children c LEFT JOIN parents p ON p.pid = c.pid "
        "WHERE p.pid IS NULL;",
    )[0][0] == 0
    assert query(
        path,
        "SELECT COUNT(*) FROM bm25_postings WHERE cid >= (SELECT COUNT(*) FROM children);",
    )[0][0] == 0
