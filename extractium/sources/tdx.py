"""
Summary: Will hold the TeamDynamix (TDX) client-portal site handler: an
on-by-default plugin the web source consults for teamdynamix.* URLs. It
owns the portal's content selectors (#divMainContent, #questionsContent),
the "Article - " and "Question Detail - " title prefix stripping,
breadcrumb categories, the /TDClient/<n>/<slug>/ scope prefix, and the
portal exclude patterns (search, login, print, tag, and category views).
It is not a crawler: link discovery stays in extractium.sources.web. See
docs/extractium-spec.md section 5.

This file is part of Extractium™
extractium/sources/tdx.py

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

# TODO: implement the site-handler protocol (see extractium.core.registry)
# for TeamDynamix portals. The selector, title, and kind logic that moves
# here lives today in extractium.core.chunk (extract_content, get_title,
# normalise_page_title, chunk_kind); the portal exclude patterns live in
# extractium.config (_COMMON_EXCLUDE_PATTERNS, _INDEX_ONLY_EXCLUDE_PATTERNS).
# Parents read through this handler carry source_type "kb" and
# content_type "article". Breadcrumb categories are new: read the portal's
# breadcrumb trail into the categories list, outermost first. If the
# portal serves different HTML to a non-browser User-Agent, document the
# user_agent override here and in the example configuration.
