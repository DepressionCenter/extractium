"""
Summary: Will hold the GitHub site handler: an on-by-default plugin the
web source consults for github.com, github.io, and generic git-host URLs.
It rewrites Markdown and text blob URLs to their raw-content equivalent,
extracts server-rendered wiki and release-notes pages, treats repository
root and tree pages as link-discovery hops with no indexable content, and
owns the code-host exclude patterns (issues, commits, settings, and the
like). Enumerating an organization through the GitHub API is a separate
source plugin, extractium.sources.github_api, not this handler. See
docs/extractium-spec.md section 5.

This file is part of Extractium™
extractium/sources/github.py

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
# for git hosts. The logic that moves here lives today in
# extractium.core.fetch (is_git_host_url, is_git_blob_text_url,
# to_git_raw_url) and extractium.core.chunk (the Git-host branches of
# extract_content and get_title, derive_title_from_blob_path, chunk_kind);
# the code-host exclude patterns live in extractium.config
# (_COMMON_EXCLUDE_PATTERNS, the /tree/ index-only pattern). Parents read
# through this handler carry source_type "github" and a content_type of
# "readme", "wiki", "release_notes", or "text" by URL. Categories are the
# repository path segments, outermost first.
