"""
Summary: Will hold the local-filesystem source plugin: reads Markdown,
plain-text, and HTML files under a configured folder and yields one
Document per file with local set to true. Every parent from this source
is excluded from every output unless that output opts in with
include_local, and the PHI lint runs over its content by default. See
docs/extractium-spec.md section 7.

This file is part of Extractium™
extractium/sources/local.py

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

# TODO: implement the source protocol (see extractium.core.models).
# Rules that shape it:
#   - Document URLs are "local:" plus the path relative to the configured
#     folder, so an absolute path never reaches an output file.
#   - include_globs default to **/*.md, **/*.txt, and **/*.html. PDF and
#     Office formats need new dependencies and are not read.
#   - The exclusion of local parents from outputs is enforced in the
#     adapter base, not here, so no adapter can forget it.
