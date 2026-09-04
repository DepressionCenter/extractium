"""
Summary: Will hold the binary-container adapter that writes the version 3
container (kb-index.json: 4-byte little-endian header length, minified
JSON header, raw int8 or float32 vector bytes), the flagship output format
specified byte by byte in docs/container-format.md.

This file is part of Extractium™
extractium/adapters/container.py

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

# TODO: serialize the version 3 container from a Compendium that is
# already embedded and scored. Children are columnar (pid, plus start and
# end offsets in UTF-16 code units) and carry no text; parents carry the
# stable id, source_type, content_type, categories, and local flag; the
# header records the embedding model, dimensions, query prefix, and
# quantization scale. This adapter never fetches a URL or runs the
# embedding model, because one crawl and one embedding pass feed every
# output format (docs/extractium-spec.md section 2).
