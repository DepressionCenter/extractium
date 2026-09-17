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
from dataclasses import replace

import numpy as np
import pytest

from extractium.adapters.base import output_compendium
from extractium.adapters.container import ContainerAdapter, build_header, full_container_file_name
from extractium.core import build
from extractium.core.light import build_light_compendium
from extractium.core.models import CODE_CONTENT_TYPES, Document
from tests.test_build import document_from_fixture

# A build time fixed in the past, so the committed snapshot does not
# change every time the tests run.
FIXED_BUILT_AT = "2026-01-02T03:04:05Z"

# The two bytes every gzip stream begins with.
GZIP_SIGNATURE = b"\x1f\x8b"

CODE_TEXT = (
    "def summarize(nights): return sum(nights) / len(nights)  # the nightly mean, which "
    "is long enough here for the chunker to keep it as a section of its own."
)

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
    if data[:2] == GZIP_SIGNATURE:
        data = gzip.decompress(data)
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

    assert path == tmp_path / "compendium.json.gz"
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
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)
    (plain,) = ContainerAdapter().write(compendium, tmp_path, {"file": "compendium.json", "gzip": False})
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

def test_the_header_leaves_out_enrichment_fields_until_a_pass_sets_them(fixtures_dir, fake_embed_chunks_core):
    """
    A file with no enrichment is laid out exactly as before there was
    any, which is what keeps the version at 4 and the snapshot unchanged.
    """
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)

    plain = build_header(compendium)["parents"]

    assert all("keywords" not in record and "summary" not in record for record in plain)

    enriched = replace(
        compendium.parents[0], keywords=("sleep study", "smartwatch"), tags=("research",), enrich_ver="test-1",
    )
    record = build_header(replace(compendium, parents=(enriched, *compendium.parents[1:])))["parents"][0]

    assert record["keywords"] == ["sleep study", "smartwatch"]
    assert record["tags"] == ["research"]
    assert record["enrich_ver"] == "test-1"
    assert "summary" not in record and "enriched_at" not in record
    assert list(record)[:11] == list(plain[0])


# ---------------------------------------------------------------------------
# The light file and the full file
# ---------------------------------------------------------------------------

def compendium_with_code(fixtures_dir, embedder):
    """Two crawled pages and one code record, every section named with a keyword."""
    documents = [
        document_from_fixture(fixtures_dir, "page_boilerplate_a.html", "https://example.org/team"),
        document_from_fixture(fixtures_dir, "page_boilerplate_b.html", "https://example.org/project"),
        Document(url="https://github.com/example/tool/blob/main/run.py", title="run.py", content=CODE_TEXT,
                 source_type="github", content_type="code_file"),
    ]
    compendium = build.build_compendium(documents, name="Example Org", embedder=embedder,
                                        built_at=FIXED_BUILT_AT)
    return replace(compendium, parents=tuple(replace(p, keywords=("sleep",)) for p in compendium.parents))


def test_write_produces_a_light_and_a_full_container(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = compendium_with_code(fixtures_dir, fake_embed_chunks_core)

    written = ContainerAdapter().write(compendium, tmp_path, {
        "file": "kb.json.gz", "gzip": True, "full": True, "include_local": False,
        "light": build_light_compendium(compendium, embedder=fake_embed_chunks_core),
    })

    assert [path.name for path in written] == ["kb.json.gz", "kb-full.json.gz"]
    (light_header, light_vectors), (full_header, full_vectors) = (read_container(path) for path in written)
    assert (light_header["variant"], full_header["variant"]) == ("light", "full")
    assert light_header["v"] == full_header["v"] == 4
    assert any(parent.content_type in CODE_CONTENT_TYPES for parent in compendium.parents)
    assert all(p["content_type"] not in CODE_CONTENT_TYPES for p in full_header["parents"])
    assert all(p["content_type"] not in CODE_CONTENT_TYPES for p in light_header["parents"])
    assert [p["u"] for p in light_header["parents"]] == ["https://example.org/team", "https://example.org/project"]
    assert len(light_header["parents"]) < len(full_header["parents"])
    assert all(p["keywords"] == ["sleep"] for p in light_header["parents"])
    assert len(light_vectors) == len(light_header["children"]["pid"]) * 384
    assert len(full_vectors) == len(full_header["children"]["pid"]) * 384


def test_full_false_writes_only_the_light_file(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = compendium_with_code(fixtures_dir, fake_embed_chunks_core)

    written = ContainerAdapter().write(compendium, tmp_path, {
        "file": "kb.json", "gzip": False, "full": False, "include_local": False,
        "light": build_light_compendium(compendium, embedder=fake_embed_chunks_core),
    })

    assert [path.name for path in written] == ["kb.json"]
    assert read_container(written[0])[0]["variant"] == "light"
    assert not (tmp_path / "kb-full.json").exists()


def test_without_a_light_compendium_the_one_file_is_the_full_container(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = compendium_with_code(fixtures_dir, fake_embed_chunks_core)

    written = ContainerAdapter().write(compendium, tmp_path,
                                       {"file": "kb.json", "gzip": False, "include_local": False})

    assert [path.name for path in written] == ["kb.json"]
    header, _ = read_container(written[0])
    assert header["variant"] == "full"
    assert all(p["content_type"] not in CODE_CONTENT_TYPES for p in header["parents"])


def test_local_content_is_dropped_from_the_light_file_too(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)
    light = build_light_compendium(compendium, embedder=fake_embed_chunks_core)
    assert any(parent.local for parent in light.parents)

    written = ContainerAdapter().write(compendium, tmp_path, {"include_local": False, "light": light})

    for path in written:
        header, _ = read_container(path)
        assert header["parents"] and not any(p["local"] for p in header["parents"])


@pytest.mark.parametrize("name, expected", [
    ("kb.json.gz", "kb-full.json.gz"), ("kb.json", "kb-full.json"), ("index", "index-full"),
    ("nested/kb.json.gz", "nested/kb-full.json.gz"),
])
def test_the_full_file_is_named_after_the_light_one(name, expected):
    assert full_container_file_name(name) == expected
