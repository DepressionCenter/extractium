"""
Summary: Will hold the plugin registry that resolves the three plugin
kinds an Extractium build uses: sources (produce documents), site
handlers (extract content from web pages the crawler visits), and
adapters (write output formats). Resolution order: the operator's local
plugins/ directory, then installed entry points, then the built-ins that
ship with the package. See docs/extractium-spec.md section 2.

This file is part of Extractium™
extractium/core/registry.py

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

# TODO: implement the registry. Three kinds, each a name -> class map:
#   - sources: name, __init__(options), fetch(session, cache, progress)
#     yielding Document records.
#   - site_handlers: name, matches(url), fetch_url(url), expects_html,
#     extract(soup, url), source_type, content_type(url), and the default
#     crawl/index exclude patterns the handler contributes when enabled.
#   - adapters: name, write(compendium, out_dir, options).
# Resolution order, first match wins: modules in the operator's plugins/
# directory that expose register(); entry points in the groups
# extractium.sources, extractium.site_handlers, extractium.adapters; the
# built-ins, which are declared through those same entry-point groups so
# they take the identical path. Loading plugins/ executes operator-owned
# code, the same trust level as config.yaml; that is documented, not
# sandboxed.
