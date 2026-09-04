"""
Summary: Will hold the llms.txt adapter: llms.txt (an H1 title, a summary
blockquote, and H2 sections per source listing each page as a Markdown
link) and llms-full.txt (every parent's heading, URL, and text in one
file), the two files web-browsing language models look for at a site
root. See docs/extractium-spec.md section 4.

This file is part of Extractium™
extractium/adapters/llmstxt.py

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
# source URL so each page appears once in llms.txt; write parents in
# crawl order to llms-full.txt. Local parents are dropped unless the
# output opted in, as for every adapter.
