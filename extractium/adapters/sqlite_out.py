"""
Summary: Will hold the SQLite adapter (compendium.sqlite, Python standard
library sqlite3, no new dependency): tables for build metadata, parents,
children, BM25 terms and postings, and int8 vectors as BLOBs, for
consumers that prefer SQL to parsing the container, including a remote
server that imports the file into a hosted SQLite service. See
docs/extractium-spec.md section 4.

This file is part of Extractium™
extractium/adapters/sqlite_out.py

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

# TODO: implement write(compendium, out_dir, options). Grain of each
# table: meta is one row per key; parents is one row per parent, keyed by
# the stable id; children is one row per child, keyed by parent id and
# ordinal; bm25_terms is one row per term with its document frequency;
# bm25_postings is one row per (term, child) pair with the term
# frequency; vectors is one row per child holding the int8 bytes. Local
# parents and their children are dropped unless the output opted in.
