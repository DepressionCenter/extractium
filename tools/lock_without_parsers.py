"""
Summary: Writes a copy of the pinned dependency list without the code
parser packages, for a Python that cannot install them. The build
scripts run this for a free-threaded interpreter, which has no wheels
for the tree-sitter grammars, so that everything else still installs
with its hash checked. Every other line of the lock file is copied as
it is. Standard library only, because it runs before anything is
installed.

This file is part of Extractium™
tools/lock_without_parsers.py

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

import sys

### Constants ###

# Every parser package, and the parser library itself, is named with this
# prefix on PyPI. Nothing else in the lock file is.
PARSER_PREFIX = "tree-sitter"


### Filter ###

def without_parsers(text):
    """
    The lock file's text with every parser package's block removed.

    A block is a package line at the start of a line, followed by its
    indented hash lines and the indented comment saying what required it.
    Comments and blank lines at the start of a line are kept, so the
    license header and the record of how the file was generated survive.

    Args:
        text (str): the lock file as pip reads it.

    Returns:
        str: the same text without the parser blocks.
    """
    kept = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if not line.startswith((" ", "\t")):
            skipping = line.lower().startswith(PARSER_PREFIX)
        if not skipping:
            kept.append(line)
    return "".join(kept)


def main(argv):
    """
    Reads the lock file named first and writes the filtered copy to the
    path named second.

    Args:
        argv (Sequence[str]): the two paths.

    Returns:
        int: 0 on success, 2 when the arguments are wrong.
    """
    if len(argv) != 3:
        print("usage: lock_without_parsers.py <requirements-lock.txt> <output>", file=sys.stderr)
        return 2
    with open(argv[1], "r", encoding="utf-8") as source:
        text = source.read()
    with open(argv[2], "w", encoding="utf-8") as target:
        target.write(without_parsers(text))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
