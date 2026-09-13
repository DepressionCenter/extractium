"""
Summary: Tests for the version 3 binary container adapter and the local
content guardrail every adapter shares. Pins the JSON header against a
committed snapshot, checks the byte layout and the vector bytes against
the frozen reference script's quantization, and checks that content read
from a local folder never reaches an output that did not ask for it.

This file is part of Extractium™
tests/test_adapter_container.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
Last Modified: 2026-09-09
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

import json
import struct

import numpy as np
import pytest

from extractium.adapters.base import output_compendium
from extractium.adapters.container import ContainerAdapter, build_header
from extractium.core import build
from extractium.core.models import Document
from tests.test_build import document_from_fixture

# A build time fixed in the past, so the committed snapshot does not
# change every time the tests run.
FIXED_BUILT_AT = "2026-01-02T03:04:05Z"

LOCAL_TEXT = (
    "Internal note that is comfortably longer than the minimum chunk size, so the "
    "chunker keeps it as one section of its own."
)


def sample_compendium(fixtures_dir, embedder, **kwargs):
    """Two crawled pages, built with the deterministic test embedder."""
    documents = [
        document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team"),
        document_from_fixture(fixtures_dir, "page_boilerplate_b.html", "https://example.org/project"),
    ]
    return build.build_compendium(
        documents, name="Example Org", embedder=embedder, built_at=FIXED_BUILT_AT, **kwargs
    )


def mixed_compendium(fixtures_dir, embedder):
    """One crawled page and one local file, for the guardrail tests."""
    documents = [
        document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team"),
        Document(url="local:notes/internal.txt", title="Internal Notes", content=LOCAL_TEXT,
                 source_type="local", content_type="text", local=True),
    ]
    return build.build_compendium(
        documents, name="Example Org", embedder=embedder, built_at=FIXED_BUILT_AT
    )


def read_container(path):
    """Reads a container back the way docs/container-format.md tells a client to."""
    data = path.read_bytes()
    (length,) = struct.unpack("<I", data[:4])
    header = json.loads(data[4:4 + length].decode("utf-8"))
    return header, data[4 + length:]


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def test_header_matches_the_committed_snapshot(fixtures_dir, golden_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    header = build_header(compendium)

    expected = json.loads((golden_dir / "container_v4_header.json").read_text(encoding="utf-8"))
    assert header == expected


def test_header_declares_the_format_the_version_and_the_offset_unit(
    fixtures_dir, fake_embed_chunks_core
):
    header = build_header(sample_compendium(fixtures_dir, fake_embed_chunks_core))

    assert header["format"] == "extractium-compendium"
    assert header["v"] == 4
    assert header["offsetUnit"] == "utf16"
    assert header["_license"].startswith("This file was produced by Extractium.")


def test_header_carries_the_query_prefix_so_a_client_cannot_guess_it_wrong(
    fixtures_dir, fake_embed_chunks_core
):
    embedding = build_header(sample_compendium(fixtures_dir, fake_embed_chunks_core))["embedding"]

    assert embedding["queryPrefix"] == "Represent this sentence for searching relevant passages: "
    assert embedding["passagePrefix"] == ""
    assert embedding["dims"] == 384
    assert embedding["normalized"] is True


def test_header_children_are_columns_and_carry_no_text(fixtures_dir, fake_embed_chunks_core):
    header = build_header(sample_compendium(fixtures_dir, fake_embed_chunks_core))

    children = header["children"]
    assert set(children) == {"pid", "start", "end"}
    assert len(children["pid"]) == len(children["start"]) == len(children["end"])
    assert "chunks" not in header  # the version 2 field is gone


def test_header_float32_has_no_scale_field(fixtures_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core, float32_vecs=True)

    embedding = build_header(compendium)["embedding"]

    assert embedding["dtype"] == "float32"
    assert "scale" not in embedding


# ---------------------------------------------------------------------------
# Byte layout
# ---------------------------------------------------------------------------

def test_write_produces_the_documented_byte_layout(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    (path,) = ContainerAdapter().write(compendium, tmp_path, {})

    assert path == tmp_path / "compendium.json"
    header, vectors = read_container(path)
    assert header["site"] == "Example Org"
    assert len(vectors) == len(compendium.children) * header["embedding"]["dims"]


def test_write_float32_vectors_are_four_bytes_wide(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core, float32_vecs=True)

    (path,) = ContainerAdapter().write(compendium, tmp_path, {})

    header, vectors = read_container(path)
    assert len(vectors) == len(compendium.children) * header["embedding"]["dims"] * 4
    restored = np.frombuffer(vectors, dtype="<f4").reshape(len(compendium.children), 384)
    assert np.allclose(restored, compendium.vectors)


def test_write_stores_the_scored_vectors_unchanged_and_little_endian(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    (path,) = ContainerAdapter().write(compendium, tmp_path, {})

    _, vectors = read_container(path)
    assert vectors == compendium.vectors.astype("<i1").tobytes()
    restored = np.frombuffer(vectors, dtype="<i1").reshape(len(compendium.children), 384)
    assert np.array_equal(restored, compendium.vectors)


def test_write_honors_the_configured_file_name(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    (path,) = ContainerAdapter().write(compendium, tmp_path, {"file": "nested/index.json"})

    assert path == tmp_path / "nested" / "index.json"
    assert path.exists()


def test_write_creates_a_missing_output_folder(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    (path,) = ContainerAdapter().write(compendium, tmp_path / "dist", {})

    assert path.exists()


# ---------------------------------------------------------------------------
# Local content guardrail
# ---------------------------------------------------------------------------

def test_a_build_with_a_local_source_has_local_parents(fixtures_dir, fake_embed_chunks_core):
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)

    assert len(compendium.local_parents()) == 1


def test_local_parents_are_dropped_from_an_output_that_did_not_opt_in(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)

    (path,) = ContainerAdapter().write(compendium, tmp_path, {"include_local": False})

    header, vectors = read_container(path)
    assert not any(parent["local"] for parent in header["parents"])
    assert not any("local:" in parent["u"] for parent in header["parents"])
    assert "Internal note" not in json.dumps(header)
    # The windows, the vectors, and the corpus statistics shrink with them.
    assert len(header["children"]["pid"]) == len(header["bm25"]["docLen"])
    assert len(vectors) == len(header["children"]["pid"]) * 384


def test_local_parents_are_written_to_an_output_that_opted_in(
    tmp_path, fixtures_dir, fake_embed_chunks_core
):
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)

    (path,) = ContainerAdapter().write(compendium, tmp_path, {"include_local": True})

    header, _ = read_container(path)
    assert any(parent["local"] for parent in header["parents"])


def test_the_guardrail_leaves_a_build_with_no_local_content_untouched(
    fixtures_dir, fake_embed_chunks_core
):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    assert output_compendium(compendium, {"include_local": False}) is compendium


def test_dropping_local_parents_keeps_every_child_pointing_at_the_right_parent(
    fixtures_dir, fake_embed_chunks_core
):
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)

    filtered = output_compendium(compendium, {"include_local": False})

    assert len(filtered.parents) == len(compendium.parents) - 1
    for pid, start, end in zip(filtered.children.pid, filtered.children.start, filtered.children.end):
        window = build.utf16_slice(filtered.parents[pid].x, start, end)
        assert window in filtered.parents[pid].x


def test_dropping_local_parents_rebuilds_the_keyword_statistics(
    fixtures_dir, fake_embed_chunks_core
):
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)

    filtered = output_compendium(compendium, {"include_local": False})

    # "internal" occurs only in the local note, so its term must be gone
    # rather than left pointing at a window that no longer exists.
    assert "internal" in compendium.bm25["df"]
    assert "internal" not in filtered.bm25["df"]
    assert max(row[0] for rows in filtered.bm25["postings"].values() for row in rows) < len(
        filtered.children
    )


def test_dropping_local_parents_refuses_a_compendium_that_has_no_offsets(
    fixtures_dir, fake_embed_chunks_core
):
    """
    The window offsets are optional in the container format. Without them
    a dropped window's text cannot be recovered, so the keyword statistics
    cannot be rebuilt, and shipping the old ones would describe content
    that was meant to be gone.
    """
    import dataclasses

    from extractium.core.models import Children

    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)
    without_offsets = dataclasses.replace(
        compendium, children=Children(pid=compendium.children.pid)
    )

    with pytest.raises(ValueError, match="no offsets"):
        output_compendium(without_offsets, {})


@pytest.mark.parametrize("dtype_flag", [False, True])
def test_dropping_local_parents_leaves_a_valid_compendium(
    fixtures_dir, fake_embed_chunks_core, dtype_flag
):
    documents = [
        document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team"),
        Document(url="local:notes/internal.txt", title="Internal Notes", content=LOCAL_TEXT,
                 source_type="local", content_type="text", local=True),
    ]
    compendium = build.build_compendium(
        documents, name="Example Org", embedder=fake_embed_chunks_core,
        built_at=FIXED_BUILT_AT, float32_vecs=dtype_flag,
    )

    filtered = output_compendium(compendium, {})

    assert filtered.vectors.shape[0] == len(filtered.children)
    assert set(filtered.calibration) == {"mean", "std", "sampleSize"}


def test_write_with_gzip_produces_the_same_bytes_compressed(tmp_path, fixtures_dir, fake_embed_chunks_core):
    import gzip

    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)
    (plain,) = ContainerAdapter().write(compendium, tmp_path, {"file": "compendium.json"})
    (packed,) = ContainerAdapter().write(compendium, tmp_path, {"file": "compendium.json.gz", "gzip": True})

    assert packed.name == "compendium.json.gz"
    assert packed.read_bytes()[:2] == b"\x1f\x8b"
    assert gzip.decompress(packed.read_bytes()) == plain.read_bytes()
    assert packed.stat().st_size < plain.stat().st_size


def test_write_with_gzip_is_reproducible(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)
    (first,) = ContainerAdapter().write(compendium, tmp_path / "a", {"file": "c.json.gz", "gzip": True})
    (second,) = ContainerAdapter().write(compendium, tmp_path / "b", {"file": "c.json.gz", "gzip": True})

    assert first.read_bytes() == second.read_bytes()
