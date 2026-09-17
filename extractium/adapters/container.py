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
Last Modified: 2026-09-17
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
__date__ = "2026-09-17"

import gzip
import json
import struct

import numpy as np

from extractium import __version__
from extractium.adapters.base import output_compendium, prepare_out_dir, without_code
from extractium.core.models import ENRICHMENT_FIELDS

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
DEFAULT_FILE = "compendium.json.gz"

# The header's `variant` field. A light container holds one section per
# page whose text is the page's description and keywords; a full one
# holds every section. Neither holds code records.
VARIANT_LIGHT = "light"
VARIANT_FULL = "full"

# What the full container's name gains, before the endings below, so the
# two files sort together and the longer name is the larger file.
FULL_SUFFIX = "-full"
CONTAINER_ENDINGS = (".json.gz", ".json")

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


def parent_record(parent):
    """
    One parent as the header writes it: every field the format lists on
    every parent, and an enrichment field only when a pass has set it,
    so a file with no enrichment is laid out exactly as before there was
    any.

    Args:
        parent (extractium.core.models.Parent): the section.

    Returns:
        dict: the parent's fields, in the order docs/container-format.md
        lists them.
    """
    record = {
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
    for field in ENRICHMENT_FIELDS:
        value = getattr(parent, field)
        if value is not None:
            record[field] = list(value) if isinstance(value, tuple) else value
    return record


def full_container_file_name(file):
    """
    The full container's file name, given the light one's.

    Args:
        file (str): the light container's name, which may include folders.

    Returns:
        str: the same name with `-full` before its `.json.gz` or `.json`
        ending, or at the end of a name with neither.
    """
    for ending in CONTAINER_ENDINGS:
        if file.endswith(ending):
            return f"{file[:-len(ending)]}{FULL_SUFFIX}{ending}"
    return f"{file}{FULL_SUFFIX}"


def build_header(compendium, variant=VARIANT_FULL):
    """
    The complete JSON header of one container.

    Args:
        compendium (extractium.core.models.Compendium): the build result,
            already filtered to what this output may write.
        variant (str): VARIANT_LIGHT or VARIANT_FULL. A reader that does
            not know the field ignores it, so it is not a layout change.

    Returns:
        dict: every header field, in the order docs/container-format.md
        lists them.
    """
    return {
        "_license": LICENSE_NOTICE,
        "format": CONTAINER_FORMAT,
        "v": CONTAINER_VERSION,
        "variant": variant,
        "extractium": __version__,
        "builtAt": compendium.built_at,
        "site": compendium.name,
        "sourceCount": compendium.source_count,
        "embedding": embedding_header(compendium.embedding),
        "offsetUnit": OFFSET_UNIT,
        "parents": [parent_record(parent) for parent in compendium.parents],
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
    Writes the binary container, as a light file and a full file.

    The light file holds one section per page, whose text is the page's
    description and keywords. It is small enough for a browser, a hosted
    function with a small store, or a small model searching in memory.
    The full file holds the text of every section. Neither holds code
    records: both are read inside a language model's context window or
    searched in memory, and the sqlite and okf outputs carry the code.

    A file keeps `.json` in its name so a static host such as GitHub
    Pages serves it with a plain content type and no configuration, even
    though everything after the header is binary. With the `gzip` option
    the same bytes are written through gzip, under a `.json.gz` name by
    default; a client inflates the file before reading it.

    This adapter never fetches a URL and never runs the embedding model:
    it serializes the compendium it is given and nothing else.
    """

    name = "container"

    def write(self, compendium, out_dir, options):
        """
        Writes the light container and, unless told not to, the full one.

        A caller that hands over no light compendium, such as a script
        that builds and writes on its own, gets the full container under
        the name `file` gives.

        Args:
            compendium (extractium.core.models.Compendium): the build result.
            out_dir (str | pathlib.Path): folder to write under; created
                when it does not exist.
            options (Mapping): the output's validated options: `file` for
                the light file's name, `gzip` to compress both files,
                `full` to write the full file, `include_local` for the
                local-content guardrail, and `light`, the light
                compendium of the same build or None.

        Returns:
            tuple[pathlib.Path, ...]: the paths written, the light file first.
        """
        out_dir = prepare_out_dir(out_dir)
        file = options.get("file", DEFAULT_FILE)
        gzipped = options.get("gzip", True)
        full = without_code(output_compendium(compendium, options))
        light = options.get("light")
        if light is None:
            return (self._write_file(out_dir / file, full, VARIANT_FULL, gzipped),)

        written = [self._write_file(out_dir / file, output_compendium(light, options), VARIANT_LIGHT, gzipped)]
        if options.get("full", True):
            written.append(self._write_file(out_dir / full_container_file_name(file), full, VARIANT_FULL, gzipped))
        return tuple(written)

    @staticmethod
    def _write_file(path, compendium, variant, gzipped):
        """Writes one container file and returns its path."""
        header = json.dumps(
            build_header(compendium, variant), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        vectors = np.ascontiguousarray(
            compendium.vectors, dtype=STORAGE_DTYPES[compendium.embedding.dtype]
        ).tobytes()

        path.parent.mkdir(parents=True, exist_ok=True)
        # The gzip header carries no timestamp, so two builds of the same
        # compendium produce the same bytes and a rebuild changes nothing.
        opener = (lambda p: gzip.GzipFile(p, "wb", mtime=0)) if gzipped else (lambda p: open(p, "wb"))
        with opener(path) as f:
            f.write(struct.pack("<I", len(header)))
            f.write(header)
            f.write(vectors)
        return path
