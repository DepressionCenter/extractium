"""
Summary: The binary-container adapter, Extractium's flagship output. Writes
the version 3 container: a 4-byte little-endian header length, a minified
UTF-8 JSON header, then the raw vector bytes. It is the one file every
Extractium client reads, and it is specified byte by byte in
docs/container-format.md.

This file is part of Extractium™
extractium/adapters/container.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-12
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

import json
import struct

import numpy as np

from extractium import __version__
from extractium.adapters.base import output_compendium, prepare_out_dir

### Constants ###

# Refused by a reader that finds any other value, so a file of some other
# shape with a .json name cannot be mistaken for a compendium.
CONTAINER_FORMAT = "extractium-compendium"

# Layout version. Bumped only when a reader cannot ignore the change.
CONTAINER_VERSION = 4

# Unit of the child start and end columns. UTF-16 code units, because
# browsers are the first consumer and JavaScript strings index that way.
OFFSET_UNIT = "utf16"

# File name written when the output's entry gives none.
DEFAULT_FILE = "compendium.json"

# The vector bytes are little-endian, whatever the machine that built
# them is, so a file built on one architecture reads on another.
STORAGE_DTYPES = {"int8": "<i1", "float32": "<f4"}

# The container is a JSON document with nowhere else to carry a license
# notice, so it carries one in a leading key. Readers ignore fields they
# do not know, so this costs them nothing.
LICENSE_NOTICE = (
    "This file was produced by Extractium. Copyright © 2026 The Regents of the "
    "University of Michigan. Extractium is free software: you can redistribute it "
    "and/or modify it under the terms of the GNU General Public License as published "
    "by the Free Software Foundation, either version 3 of the License, or (at your "
    "option) any later version. It is distributed in the hope that it will be useful, "
    "but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or "
    "FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more "
    "details. You should have received a copy of the GNU General Public License along "
    "with this program. If not, see https://www.gnu.org/licenses/. The indexed content "
    "remains under the license of the site it was read from."
)


### Header ###

def embedding_header(embedding):
    """
    The `embedding` object of the header.

    A reader compares these against the embedder it will use for queries.
    The query prefix travels with the file because a model id alone does
    not catch a change of prefix, and the wrong prefix silently degrades
    every result rather than failing.

    Args:
        embedding (extractium.core.models.EmbeddingInfo): how the vectors
            were produced.

    Returns:
        dict: the header fields, with `scale` present only for int8.
    """
    header = {
        "model": embedding.model,
        "browserModel": embedding.browser_model,
        "dims": embedding.dims,
        "normalized": embedding.normalized,
        "queryPrefix": embedding.query_prefix,
        "passagePrefix": embedding.passage_prefix,
        "dtype": embedding.dtype,
    }
    if embedding.scale is not None:
        header["scale"] = embedding.scale
    return header


def build_header(compendium):
    """
    The complete JSON header of one container.

    Args:
        compendium (extractium.core.models.Compendium): the build result,
            already filtered to what this output may write.

    Returns:
        dict: every header field, in the order docs/container-format.md
        lists them.
    """
    return {
        "_license": LICENSE_NOTICE,
        "format": CONTAINER_FORMAT,
        "v": CONTAINER_VERSION,
        "extractium": __version__,
        "builtAt": compendium.built_at,
        "site": compendium.name,
        "sourceCount": compendium.source_count,
        "embedding": embedding_header(compendium.embedding),
        "offsetUnit": OFFSET_UNIT,
        "parents": [
            {
                "id": parent.id,
                "t": parent.t,
                "x": parent.x,
                "u": parent.u,
                "host": parent.host,
                "source_type": parent.source_type,
                "content_type": parent.content_type,
                "source_label": parent.source_label,
                "categories": list(parent.categories),
                "local": parent.local,
                "weight": parent.weight,
            }
            for parent in compendium.parents
        ],
        "children": {
            "pid": list(compendium.children.pid),
            "start": list(compendium.children.start),
            "end": list(compendium.children.end),
        },
        "bm25": compendium.bm25,
        "calibration": compendium.calibration,
    }


### Adapter ###

class ContainerAdapter:
    """
    Writes the version 3 binary container.

    The file keeps a `.json` extension so a static host such as GitHub
    Pages serves it with a plain content type and no configuration, even
    though everything after the header is binary.

    This adapter never fetches a URL and never runs the embedding model:
    it serializes the compendium it is given and nothing else.
    """

    name = "container"

    def write(self, compendium, out_dir, options):
        """
        Writes one container file.

        Args:
            compendium (extractium.core.models.Compendium): the build result.
            out_dir (str | pathlib.Path): folder to write under; created
                when it does not exist.
            options (Mapping): the output's validated options: `file` for
                the name, `include_local` for the local-content guardrail.

        Returns:
            tuple[pathlib.Path, ...]: the one path written.
        """
        compendium = output_compendium(compendium, options)
        path = prepare_out_dir(out_dir) / options.get("file", DEFAULT_FILE)

        header = json.dumps(
            build_header(compendium), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        vectors = np.ascontiguousarray(
            compendium.vectors, dtype=STORAGE_DTYPES[compendium.embedding.dtype]
        ).tobytes()

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(struct.pack("<I", len(header)))
            f.write(header)
            f.write(vectors)
        return (path,)
