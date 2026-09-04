"""
Summary: Will hold the heuristic PHI (Protected Health Information) linter
for local-filesystem source content (see docs/extractium-spec.md section 6).
Flag-only: this module must never claim or imply an absence of PHI, only
report suspected matches for human review.

This file is part of Extractium™
extractium/core/phi_lint.py

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

# TODO: implement the linter. Pattern checks for likely identifiers (SSN,
# phone, email, MRN-style labels, dates near "DOB" or "birth"); a mode
# from the phi_lint setting: local (default) | all | off; a
# phi-lint-report.json written to the working directory, never under the
# output directory, so it cannot be published by accident; and one
# summary line for the operator. Zero matches must read "0 pattern
# matches (this does not confirm absence of PHI)". The phrase "no PHI"
# must never be emitted, and a test pins that.
