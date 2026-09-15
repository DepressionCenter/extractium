"""
Summary: Readers that turn a document file's bytes into text with its
heading structure kept, so the chunker can cut a Word, OpenDocument,
RTF, or PDF file at its headings the way it cuts a web page. The Word,
OpenDocument, and RTF readers use the standard library alone; the PDF
reader uses pypdf, the optional pdf extra, and runs in a child process
that is ended if it runs too long. Every reader refuses input it cannot
account for and never writes a file. The web crawl, the GitHub source,
and the local source hand bytes to
`extractium.readers.documents.read_document` when their `read_documents`
setting is on. See docs/configuration.md under "Reading document files".

This file is part of Extractium™
extractium/readers/__init__.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-15
Last Modified: 2026-09-15
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
__date__ = "2026-09-15"
