"""
Summary: Will hold the Open Knowledge Format (OKF v0.2) adapter: one
Markdown file per source page with YAML front matter (type, title,
description, resource, tags, generated, sources), plus the reserved
index.md listing and log.md history. OKF defines no archive packaging, so
this adapter writes a directory only. See docs/extractium-spec.md
section 4.

This file is part of Extractium™
extractium/adapters/okf.py

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

# TODO: implement write(compendium, out_dir, options). Group parents by
# source URL into one concept file each; "type" is the only front-matter
# field OKF requires, the rest are recommended. Local parents are dropped
# unless the output opted in, as for every adapter.
