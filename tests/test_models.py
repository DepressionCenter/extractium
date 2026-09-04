"""
Summary: Tests for extractium.core.models: the Document record a source
yields, the Parent, Children, EmbeddingInfo, and Compendium records the
build step returns, the Extraction record a site handler returns, and
the three runtime-checkable plugin protocols (Source, SiteHandler,
Adapter). Covers defaults, immutability, the invariants each record
enforces, and protocol conformance.

This file is part of Extractium™
tests/test_models.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-04
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
__date__ = "2026-09-04"

import dataclasses

import numpy as np
import pytest

from extractium.core import models

URL = "https://example.edu/TDClient/000/ExampleOrg/KB/ArticleDet?ID=1"


def make_document(**overrides):
    fields = {
        "url": URL,
        "title": "Example article",
        "content": "Plain text body.",
        "source_type": "kb",
        "content_type": "article",
    }
    fields.update(overrides)
    return models.Document(**fields)


def make_parent(**overrides):
    fields = {
        "id": "0123456789abcdef",
        "t": "Example article -- Section",
        "x": "Section text.",
        "u": URL,
        "host": "example.edu",
        "source_type": "kb",
        "content_type": "article",
    }
    fields.update(overrides)
    return models.Parent(**fields)


def make_compendium(**overrides):
    parents = (make_parent(), make_parent(id="fedcba9876543210", t="Example article -- Other"))
    fields = {
        "name": "Example Org Knowledge Base",
        "built_at": "2026-09-04T12:00:00Z",
        "parents": parents,
        "children": models.Children(pid=(0, 0, 1), start=(0, 5, 0), end=(9, 13, 13)),
        "vectors": np.zeros((3, 4), dtype=np.int8),
        "embedding": models.EmbeddingInfo(dims=4),
        "bm25": {"k": 1.2, "b": 0.75, "d": 0.5, "avgDocLen": 2.0, "docLen": [2, 2, 2], "df": {}, "postings": {}},
        "calibration": {"mean": 0.0, "std": 0.0, "sampleSize": 0},
    }
    fields.update(overrides)
    return models.Compendium(**fields)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

def test_document_defaults():
    doc = make_document()
    assert doc.categories == ()
    assert doc.local is False
    assert doc.weight == 1.0


def test_document_is_immutable():
    doc = make_document()
    with pytest.raises(dataclasses.FrozenInstanceError):
        doc.title = "changed"


def test_document_categories_are_stored_as_a_tuple():
    """A list would let one build step mutate metadata another step reads."""
    doc = make_document(categories=["Outer", "Inner"])
    assert doc.categories == ("Outer", "Inner")


def test_document_rejects_blank_url():
    with pytest.raises(ValueError, match="url"):
        make_document(url="  ")


def test_document_rejects_unknown_source_type():
    with pytest.raises(ValueError, match="source_type"):
        make_document(source_type="wiki")


def test_document_rejects_unknown_content_type():
    with pytest.raises(ValueError, match="content_type"):
        make_document(content_type="pdf")


def test_document_rejects_non_positive_weight():
    with pytest.raises(ValueError, match="weight"):
        make_document(weight=0)


def test_local_document_uses_a_local_url():
    doc = make_document(url="local:notes/readme.md", source_type="local", content_type="text", local=True)
    assert doc.local is True


def test_local_flag_requires_a_local_url():
    """A local document with a web URL would be published as if it were public."""
    with pytest.raises(ValueError, match="local"):
        make_document(source_type="local", content_type="text", local=True)


def test_local_url_requires_the_local_flag():
    """An absolute path disguised as a URL must never reach an output unflagged."""
    with pytest.raises(ValueError, match="local"):
        make_document(url="local:notes/readme.md", source_type="local", content_type="text", local=False)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def test_extraction_defaults_and_tuple_categories():
    extraction = models.Extraction(title="Page", node="node", categories=["A", "B"])
    assert extraction.categories == ("A", "B")
    assert models.Extraction(title="Page", node="node").categories == ()


# ---------------------------------------------------------------------------
# Parent
# ---------------------------------------------------------------------------

def test_parent_defaults():
    parent = make_parent()
    assert parent.categories == ()
    assert parent.local is False
    assert parent.weight == 1.0


def test_parent_rejects_malformed_id():
    """Identifiers are 16 lowercase hexadecimal characters; anything else breaks the derived child ids."""
    with pytest.raises(ValueError, match="id"):
        make_parent(id="ABC")


def test_parent_rejects_unknown_source_type():
    with pytest.raises(ValueError, match="source_type"):
        make_parent(source_type="portal")


# ---------------------------------------------------------------------------
# Children
# ---------------------------------------------------------------------------

def test_children_columns_are_tuples_of_the_same_length():
    children = models.Children(pid=[0, 1], start=[0, 0], end=[5, 5])
    assert children.pid == (0, 1)
    assert len(children) == 2


def test_children_offsets_may_be_omitted():
    children = models.Children(pid=(0, 1))
    assert children.start == ()
    assert children.end == ()


def test_children_rejects_offset_columns_of_a_different_length():
    with pytest.raises(ValueError, match="start"):
        models.Children(pid=(0, 1), start=(0,), end=(5, 5))


def test_children_rejects_end_before_start():
    with pytest.raises(ValueError, match="end"):
        models.Children(pid=(0,), start=(5,), end=(4,))


# ---------------------------------------------------------------------------
# EmbeddingInfo
# ---------------------------------------------------------------------------

def test_embedding_info_defaults_match_the_shipped_model():
    from extractium.core import embed

    info = models.EmbeddingInfo()
    assert info.model == embed.EMBED_MODEL
    assert info.browser_model == embed.EMBED_MODEL_BROWSER_ID
    assert info.dims == embed.DIMS
    assert info.normalized is True
    assert info.query_prefix.endswith(": ")
    assert info.passage_prefix == ""
    assert info.dtype == "int8"
    assert info.scale == embed.INT8_SCALE


def test_embedding_info_rejects_unknown_dtype():
    with pytest.raises(ValueError, match="dtype"):
        models.EmbeddingInfo(dtype="float16")


def test_float32_embedding_info_has_no_scale():
    assert models.EmbeddingInfo(dtype="float32").scale is None


# ---------------------------------------------------------------------------
# Compendium
# ---------------------------------------------------------------------------

def test_compendium_holds_its_parts():
    compendium = make_compendium()
    assert len(compendium.parents) == 2
    assert len(compendium.children) == 3
    assert compendium.vectors.shape == (3, 4)
    assert compendium.source_count == 1


def test_compendium_is_immutable():
    compendium = make_compendium()
    with pytest.raises(dataclasses.FrozenInstanceError):
        compendium.name = "changed"


def test_compendium_rejects_vector_count_that_differs_from_child_count():
    with pytest.raises(ValueError, match="vectors"):
        make_compendium(vectors=np.zeros((2, 4), dtype=np.int8))


def test_compendium_rejects_vector_width_that_differs_from_dims():
    with pytest.raises(ValueError, match="dims"):
        make_compendium(vectors=np.zeros((3, 5), dtype=np.int8))


def test_compendium_rejects_child_pointing_past_the_last_parent():
    with pytest.raises(ValueError, match="pid"):
        make_compendium(children=models.Children(pid=(0, 0, 2)))


def test_compendium_rejects_offsets_past_the_parent_text():
    with pytest.raises(ValueError, match="end"):
        make_compendium(children=models.Children(pid=(0, 0, 1), start=(0, 0, 0), end=(9, 9, 99)))


def test_compendium_rejects_duplicate_parent_ids():
    with pytest.raises(ValueError, match="id"):
        make_compendium(parents=(make_parent(), make_parent()))


def test_compendium_rejects_non_utc_build_time():
    with pytest.raises(ValueError, match="built_at"):
        make_compendium(built_at="2026-09-04T12:00:00+02:00")


def test_compendium_source_count_counts_distinct_urls():
    other = make_parent(id="fedcba9876543210", u="https://example.edu/other")
    compendium = make_compendium(parents=(make_parent(), other))
    assert compendium.source_count == 2


def test_compendium_local_parents_are_listed():
    local = make_parent(
        id="fedcba9876543210", u="local:notes.md", host="", source_type="local", content_type="text", local=True
    )
    compendium = make_compendium(parents=(make_parent(), local))
    assert [p.u for p in compendium.local_parents()] == ["local:notes.md"]


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

class GoodSource:
    name = "good"

    def __init__(self, options):
        self.options = options

    def fetch(self, session, cache, progress):
        yield make_document()


class GoodHandler:
    name = "good"
    source_type = "web"
    default_crawl_exclude_patterns = ()
    default_index_exclude_patterns = ()

    def matches(self, url):
        return True

    def fetch_url(self, url):
        return url

    def expects_html(self, url):
        return True

    def extract(self, soup, url):
        return models.Extraction(title="Page", node=soup)

    def content_type(self, url):
        return "page"


class GoodAdapter:
    name = "good"

    def write(self, compendium, out_dir, options):
        return ()


def test_conforming_classes_satisfy_the_protocols():
    assert isinstance(GoodSource({}), models.Source)
    assert isinstance(GoodHandler(), models.SiteHandler)
    assert isinstance(GoodAdapter(), models.Adapter)


def test_missing_member_fails_the_protocol_check():
    class NoFetch:
        name = "broken"

    class NoWrite:
        name = "broken"

    assert not isinstance(NoFetch(), models.Source)
    assert not isinstance(NoWrite(), models.Adapter)
    assert not isinstance(GoodSource({}), models.SiteHandler)


def test_protocols_are_distinct_kinds():
    """An adapter must never be mistaken for a source, whatever its name."""
    assert not isinstance(GoodAdapter(), models.Source)
    assert not isinstance(GoodSource({}), models.Adapter)
