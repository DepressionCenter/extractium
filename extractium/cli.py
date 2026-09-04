"""
Summary: Command-line entry point for the Extractium build tool
(console script `extractium`, per pyproject.toml [project.scripts]).

This file is part of Extractium™
extractium/cli.py

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


def main():
    """
    Entry point for the `extractium` console script.

    TODO: parse `build --config config.yaml` (plus --out-dir, --max-pages,
    and --float32-vecs as overrides passed to
    extractium.config.load_config), resolve sources, site handlers, and
    adapters through extractium.core.registry, run each source, hand the
    documents to the build step in extractium.core, and call each
    adapter. Progress goes to stderr through a callback. The summary at
    the end names every output file and any output that includes local
    content. A failed step exits non-zero with a message naming the step.
    """
    print("Extractium is not yet implemented -- package skeleton only (see docs/extractium-spec.md).")


if __name__ == "__main__":
    main()
