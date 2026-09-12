"""
Summary: Turns the SQLite output of a build into the SQL statements that
load it into a Cloudflare D1 database. D1 is filled through statements
rather than by copying a file, so every row of every table is written out
as an INSERT, in batches small enough for D1's statement limit, with text
quoted and vectors written as hexadecimal blobs. Run it after a build and
hand the result to `wrangler d1 execute`.

This file is part of Extractium™
examples/mcp/cloudflare/export_d1.py

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

import argparse
import pathlib
import sqlite3
import sys

from extractium.adapters.sqlite_out import SCHEMA

### Constants ###

# The tables, in an order that satisfies the foreign keys between them.
# Dropped in reverse before the schema is created again, so an import onto
# an older build replaces it rather than piling rows on top.
TABLES = ("meta", "parents", "children", "bm25_terms", "bm25_postings", "vectors")

# One INSERT is flushed once its text passes this size. D1 refuses a
# statement past 100 KB, and a section's text can run to several KB.
MAX_STATEMENT_CHARS = 64 * 1024

# Exit codes. 2 is what argparse uses for a bad command line.
EXIT_OK = 0
EXIT_INPUT_MISSING = 3


### Literals ###

def sql_literal(value):
    """
    One value as a SQL literal.

    Text is single-quoted with the quote doubled, which is the only
    escaping SQLite defines; bytes become a hexadecimal blob; numbers are
    written as Python prints them, which SQLite reads back exactly.

    Args:
        value: a value read from the SQLite output.

    Returns:
        str: the literal.

    Raises:
        TypeError: for a type the SQLite output never holds.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "X'" + bytes(value).hex().upper() + "'"
    raise TypeError(f"cannot write a {type(value).__name__} as SQL")


### Statements ###

def insert_statements(table, columns, rows):
    """
    The INSERT statements for one table, batched by size.

    Args:
        table (str): the table name.
        columns (list[str]): its columns, in the order the rows follow.
        rows (Iterable[tuple]): the rows.

    Yields:
        str: one complete statement, semicolon included.
    """
    head = f"INSERT INTO {table} ({', '.join(columns)}) VALUES\n"
    batch = []
    size = len(head)
    for row in rows:
        literal = "(" + ", ".join(sql_literal(value) for value in row) + ")"
        if batch and size + len(literal) + 2 > MAX_STATEMENT_CHARS:
            yield head + ",\n".join(batch) + ";"
            batch = []
            size = len(head)
        batch.append(literal)
        size += len(literal) + 2
    if batch:
        yield head + ",\n".join(batch) + ";"


def schema_statements():
    """The CREATE statements, with the grain comments kept."""
    return SCHEMA.strip()


def dump(sqlite_path):
    """
    Every statement that rebuilds the compendium in D1.

    Args:
        sqlite_path (str | pathlib.Path): the SQLite output of a build.

    Yields:
        str: statements, in an order the foreign keys accept.

    Raises:
        sqlite3.DatabaseError: if the file is not a SQLite database or
            does not hold the expected tables.
    """
    connection = sqlite3.connect(f"file:{pathlib.Path(sqlite_path).as_posix()}?mode=ro", uri=True)
    try:
        for table in reversed(TABLES):
            yield f"DROP TABLE IF EXISTS {table};"
        yield schema_statements()
        for table in TABLES:
            cursor = connection.execute(f"SELECT * FROM {table} ORDER BY rowid;")
            columns = [description[0] for description in cursor.description]
            yield from insert_statements(table, columns, cursor)
    finally:
        connection.close()


def write_sql(sqlite_path, out_path):
    """
    Writes the statements to one file.

    Args:
        sqlite_path (str | pathlib.Path): the SQLite output of a build.
        out_path (str | pathlib.Path): where to write the SQL.

    Returns:
        int: how many statements were written.
    """
    count = 0
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        for statement in dump(sqlite_path):
            handle.write(statement + "\n\n")
            count += 1
    return count


### Command Line ###

def main(argv=None):
    """
    Parses the command line and writes the SQL file.

    Returns:
        int: the exit code.
    """
    parser = argparse.ArgumentParser(
        description="Write the SQL that loads an Extractium SQLite output into Cloudflare D1.",
    )
    parser.add_argument("sqlite_path", help="the compendium.sqlite a build wrote")
    parser.add_argument("out_path", help="the .sql file to write")
    args = parser.parse_args(argv)

    source = pathlib.Path(args.sqlite_path)
    if not source.is_file():
        print(f"export_d1: {source} is not a file.", file=sys.stderr)
        return EXIT_INPUT_MISSING
    count = write_sql(source, args.out_path)
    print(f"wrote {count} statements to {args.out_path}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
