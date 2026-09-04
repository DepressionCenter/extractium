"""
Summary: Will hold the web-crawl source, the one crawler in Extractium:
the queue-driven crawl loop and the same-origin/prefix scope rules
described in docs/extractium-spec.md section 5. Host-specific reading of
pages is delegated to site-handler plugins (generic, tdx, github), so
this module never branches on a host name.

This file is part of Extractium™
extractium/sources/web.py

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

# TODO: port the crawl loop that walks a seed URL's site -- work queue,
# visited set, link discovery filtered through
# extractium.core.fetch.in_scope -- as a source whose fetch() yields
# Document records. Properties it needs that the original single-file
# script did not have:
#   - Take the HTTP session as a parameter. A crawl that constructs its
#     own session can only be tested by monkeypatching the requests
#     module, which reaches past the code under test.
#   - Report progress through a callback supplied by the caller instead
#     of print(), so a library consumer, a CI log, and a double-click run
#     can each present it differently.
#   - Ask the enabled site handlers, in registration order with generic
#     last, which one reads each URL: the handler supplies the URL to
#     request, whether to expect HTML, the title, the content node, and
#     the categories. Chunking of the returned content stays in core.
#   - Send the configured User-Agent and honor robots.txt when
#     respect_robots_txt is on.
