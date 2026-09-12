"""
Summary: Tests for the hosted MCP examples under examples/mcp/. The D1
export is checked statement by statement: the committed golden SQL still
matches a fresh export of the contract compendium, every literal kind is
escaped the way SQLite reads it back, a statement never passes D1's size
limit, and loading the export into a fresh SQLite database reproduces
every table. The Node suites of the shared core, the Val Town example,
and the Cloudflare example are run from the last tests, so one command
checks every runtime.

This file is part of Extractium™
tests/test_mcp_remote_servers.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-12
Last Modified: 2026-09-12
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
__date__ = "2026-09-12"

import importlib.util
import pathlib
import shutil
import sqlite3
import subprocess

import pytest

from extractium.adapters.sqlite_out import SqliteAdapter
from tests.contract_fixture import build_contract_compendium

# The repository root, from which the Node suites are run.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Where the hosted examples and their shared core live.
EXAMPLES_DIR = REPO_ROOT / "examples" / "mcp"
EXPORT_SCRIPT = EXAMPLES_DIR / "cloudflare" / "export_d1.py"

# The committed D1 export of the contract compendium.
D1_GOLDEN_FILE = "contract-d1.sql"

# How long one Node run may take before it is treated as a failure.
NODE_TEST_TIMEOUT_SECONDS = 300


def _load_export_module():
    """Imports the export script by path; it lives outside the package."""
    spec = importlib.util.spec_from_file_location("export_d1", EXPORT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export_d1 = _load_export_module()


@pytest.fixture
def contract_sqlite(fixtures_dir, fake_embed_chunks_core, tmp_path):
    """The contract compendium written as the SQLite output."""
    compendium = build_contract_compendium(fixtures_dir, fake_embed_chunks_core)
    (path,) = SqliteAdapter().write(compendium, tmp_path, {"file": "contract.sqlite"})
    return path


def load_export(sql_path):
    """A fresh in-memory database filled from one export."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(pathlib.Path(sql_path).read_text(encoding="utf-8"))
    return connection


# ---------------------------------------------------------------------------
# The golden export
# ---------------------------------------------------------------------------

def test_the_committed_export_still_matches_a_fresh_one(contract_sqlite, golden_dir, tmp_path):
    fresh = tmp_path / D1_GOLDEN_FILE
    export_d1.write_sql(contract_sqlite, fresh)

    committed = (golden_dir / D1_GOLDEN_FILE).read_text(encoding="utf-8")
    assert fresh.read_text(encoding="utf-8") == committed, (
        "tests/golden/contract-d1.sql no longer matches the export; regenerate it with "
        "examples/mcp/cloudflare/export_d1.py if the change is intended."
    )


def test_loading_the_export_reproduces_every_table(contract_sqlite, golden_dir):
    source = sqlite3.connect(contract_sqlite)
    loaded = load_export(golden_dir / D1_GOLDEN_FILE)
    try:
        for table in export_d1.TABLES:
            expected = source.execute(f"SELECT * FROM {table} ORDER BY rowid;").fetchall()
            actual = loaded.execute(f"SELECT * FROM {table} ORDER BY rowid;").fetchall()
            assert actual == expected, table
    finally:
        source.close()
        loaded.close()


def test_the_export_replaces_an_older_build_rather_than_adding_to_it(contract_sqlite, tmp_path):
    sql_path = tmp_path / "twice.sql"
    export_d1.write_sql(contract_sqlite, sql_path)
    statements = sql_path.read_text(encoding="utf-8")

    connection = sqlite3.connect(":memory:")
    connection.executescript(statements)
    connection.executescript(statements)
    parents = connection.execute("SELECT COUNT(*) FROM parents;").fetchone()[0]
    once = sqlite3.connect(contract_sqlite).execute("SELECT COUNT(*) FROM parents;").fetchone()[0]

    assert parents == once


def test_no_statement_passes_the_size_limit(golden_dir):
    for statement in (golden_dir / D1_GOLDEN_FILE).read_text(encoding="utf-8").split(";\n\n"):
        assert len(statement) <= export_d1.MAX_STATEMENT_CHARS + 4096


# ---------------------------------------------------------------------------
# Literals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (None, "NULL"),
    (0, "0"),
    (-12, "-12"),
    (1.5, "1.5"),
    (True, "1"),
    ("plain", "'plain'"),
    ("it's", "'it''s'"),
    ("semi; colon", "'semi; colon'"),
    ("two\nlines", "'two\nlines'"),
    (b"\xff\x01", "X'FF01'"),
])
def test_every_literal_kind_reads_back_as_itself(value, expected):
    literal = export_d1.sql_literal(value)

    assert literal == expected
    read_back = sqlite3.connect(":memory:").execute(f"SELECT {literal};").fetchone()[0]
    assert read_back == (int(value) if isinstance(value, bool) else value)


def test_a_value_the_output_never_holds_is_refused():
    with pytest.raises(TypeError):
        export_d1.sql_literal(object())


def test_text_that_reads_like_sql_stays_text():
    hostile = "'); DROP TABLE parents; --"
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE t (x TEXT);")
    connection.executescript(
        f"INSERT INTO t (x) VALUES ({export_d1.sql_literal(hostile)});"
    )

    assert connection.execute("SELECT x FROM t;").fetchone()[0] == hostile


def test_rows_are_batched_by_size_and_none_is_lost():
    rows = [(index, "x" * 1000) for index in range(200)]

    statements = list(export_d1.insert_statements("t", ["a", "b"], rows))

    assert len(statements) > 1
    assert all(len(statement) <= export_d1.MAX_STATEMENT_CHARS + 1100 for statement in statements)
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE t (a INTEGER, b TEXT);")
    for statement in statements:
        connection.execute(statement)
    assert connection.execute("SELECT COUNT(*) FROM t;").fetchone()[0] == 200


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def test_the_command_writes_the_file_and_reports_the_count(contract_sqlite, tmp_path, capsys):
    out = tmp_path / "out.sql"

    code = export_d1.main([str(contract_sqlite), str(out)])

    assert code == export_d1.EXIT_OK
    assert out.exists()
    assert "statements" in capsys.readouterr().out


def test_a_missing_input_is_a_distinct_exit_code(tmp_path, capsys):
    code = export_d1.main([str(tmp_path / "absent.sqlite"), str(tmp_path / "out.sql")])

    assert code == export_d1.EXIT_INPUT_MISSING
    assert "is not a file" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The Node suites
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed on this machine")
@pytest.mark.parametrize("folder", ["shared", "valtown", "cloudflare"])
def test_the_node_suite_passes(folder):
    completed = subprocess.run(
        ["node", "--test", f"examples/mcp/{folder}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=NODE_TEST_TIMEOUT_SECONDS,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
