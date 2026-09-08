"""
Summary: What every Extractium adapter shares: preparing the output
folder, and the confidentiality guardrail that keeps content read from a
local folder out of an output unless that output asked for it. Publishing
is the normal use of every output, so the safe default is the one that
cannot leak by omission (docs/extractium-spec.md section 7).

This file is part of Extractium™
extractium/adapters/base.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
Last Modified: 2026-09-08
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
__date__ = "2026-09-08"

import dataclasses
import pathlib

import numpy as np

from extractium.core.bm25 import build_bm25_index
from extractium.core.build import utf16_slice
from extractium.core.calibration import compute_calibration_stats
from extractium.core.models import Children

### Output Folder ###

def prepare_out_dir(out_dir):
    """
    Makes sure the output folder exists and returns it as a path.

    Args:
        out_dir (str | pathlib.Path): the folder every adapter writes under.

    Returns:
        pathlib.Path: the folder, created along with any missing parents.
    """
    path = pathlib.Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


### Local Content Guardrail ###

def output_compendium(compendium, options):
    """
    The compendium as one output is allowed to write it.

    Content read from a local folder may hold things that were never
    published. Every output therefore drops it unless the operator wrote
    `include_local: true` on that output's entry.

    Dropping a parent drops its search windows, its vectors, and its share
    of the corpus statistics with it, so the keyword and calibration
    figures are rebuilt over what remains. A compendium with no local
    content is returned untouched, which is every build until a local
    source is configured.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        options (Mapping): the output's options; only `include_local` is
            read here.

    Returns:
        extractium.core.models.Compendium: the original, or a copy holding
        only the parents this output may write.
    """
    if options.get("include_local") or not compendium.local_parents():
        return compendium
    return _without_local(compendium)


def _without_local(compendium):
    """A copy of the compendium with every local parent, and everything derived from one, removed."""
    kept_pids = [i for i, parent in enumerate(compendium.parents) if not parent.local]
    old_to_new = {old: new for new, old in enumerate(kept_pids)}
    parents = tuple(compendium.parents[old] for old in kept_pids)

    rows = [i for i, pid in enumerate(compendium.children.pid) if pid in old_to_new]
    children = Children(
        pid=tuple(old_to_new[compendium.children.pid[i]] for i in rows),
        start=tuple(compendium.children.start[i] for i in rows),
        end=tuple(compendium.children.end[i] for i in rows),
    )
    vectors = compendium.vectors[rows]

    # The keyword statistics index into the child list as it ships, so
    # they are rebuilt from the surviving windows rather than filtered.
    # The text of each window is what it was at build time: the parent's
    # heading and the slice of parent text the offsets name.
    surviving = [
        {
            "t": parents[pid].t,
            "x": utf16_slice(parents[pid].x, start, end),
        }
        for pid, start, end in zip(children.pid, children.start, children.end)
    ]

    return dataclasses.replace(
        compendium,
        parents=parents,
        children=children,
        vectors=vectors,
        bm25=build_bm25_index(surviving),
        calibration=compute_calibration_stats(_as_float(vectors, compendium.embedding)),
    )


def _as_float(vectors, embedding):
    """
    Vectors as unit-length floats, which is what the calibration figures
    are measured over. Stored int8 components are divided back by the
    scale they were multiplied by.
    """
    if embedding.dtype != "int8":
        return vectors
    return vectors.astype(np.float32) / float(embedding.scale)
