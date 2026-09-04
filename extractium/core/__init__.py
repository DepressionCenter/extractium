"""
Summary: Core engine package (not pluggable): fetch, cache, chunk, embed,
bm25, dedup, calibration, phi_lint, and the source/adapter registry. See
docs/extractium-spec.md section 2 for the architecture this package
implements.

This file is part of Extractium™
extractium/core/__init__.py

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

# TODO: nothing here composes the core's parts into a finished index. A
# build step is needed that embeds the children, drops near-duplicates,
# remaps parents, builds the BM25 postings, computes calibration
# statistics, and returns (parents, children, meta) for an adapter to
# serialize. embed, dedup, bm25, and calibration all exist as modules
# already; no code calls them in order.
