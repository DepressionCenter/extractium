"""
Summary: Will hold the binary-container adapter (kb-index.json: 4-byte LE
header length + minified JSON header + raw int8/float32 vector bytes), the
flagship output format per docs/extractium-spec.md section 4.

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

# TODO: serialize a container from data that is already embedded and
# scored. This adapter takes (parents, children, meta) and writes bytes;
# it must never fetch a URL or run the embedding model, because one crawl
# and one embedding pass feed every output format
# (docs/extractium-spec.md section 2).
