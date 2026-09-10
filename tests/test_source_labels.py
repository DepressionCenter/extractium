"""
Summary: Tests for the source label: the name a reader sees for the
collection a section came from. Covers the configuration rule that every
source must name itself, the generic names records fall back to when they
are built outside a build, the label travelling from the configuration
through to each record, and the outputs that carry it.

This file is part of Extractium™
tests/test_source_labels.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-09
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
__date__ = "2026-09-09"

import json
import sqlite3

import pytest

from extractium import config
from extractium.adapters.container import build_header
from extractium.adapters.sqlite_out import SqliteAdapter
from extractium.core import build
from extractium.core.models import (
    DEFAULT_SOURCE_LABELS,
    MAX_SOURCE_LABEL_CHARS,
    Document,
    Parent,
)

SEED = "https://example.org/"


def source(**extra):
    """One web source entry, labelled, with anything else the test needs."""
    return {"type": "web", "label": "Example Website", "seed_url": SEED, **extra}


def a_document(**extra):
    """One web document, long enough that the chunker keeps a section."""
    text = (
        "Synthetic page text that is comfortably longer than the smallest chunk "
        "the chunker will keep, so this document produces one section."
    )
    fields = {
        "url": "https://example.org/team",
        "title": "Team Directory",
        "content": text,
        "source_type": "web",
        "content_type": "page",
    }
    fields.update(extra)
    return Document(**fields)


# ---------------------------------------------------------------------------
# The configuration must name every source
# ---------------------------------------------------------------------------

def test_a_source_without_a_label_is_refused():
    with pytest.raises(config.ConfigError, match="label is required"):
        config.config_from_mapping({"sources": [{"type": "web", "seed_url": SEED}]})


def test_the_error_suggests_a_label_for_the_type_that_is_missing_one():
    """The fix should be one line to copy, not a guess at what is wanted."""
    with pytest.raises(config.ConfigError, match="YouTube Channel"):
        config.config_from_mapping({
            "sources": [{"type": "youtube", "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx"}],
        })


def test_a_blank_label_is_refused_rather_than_treated_as_absent():
    with pytest.raises(config.ConfigError, match="label cannot be blank"):
        config.config_from_mapping({"sources": [source(label="   ")]})


def test_a_label_that_is_not_text_is_refused():
    with pytest.raises(config.ConfigError, match="label must be text, not int"):
        config.config_from_mapping({"sources": [source(label=7)]})


def test_an_overlong_label_is_refused_with_its_length_named():
    long_label = "A" * (MAX_SOURCE_LABEL_CHARS + 1)

    with pytest.raises(config.ConfigError, match=f"got {MAX_SOURCE_LABEL_CHARS + 1}"):
        config.config_from_mapping({"sources": [source(label=long_label)]})


def test_a_label_of_the_greatest_allowed_length_is_accepted():
    label = "A" * MAX_SOURCE_LABEL_CHARS

    cfg = config.config_from_mapping({"sources": [source(label=label)]})

    assert cfg.sources[0].label == label


def test_surrounding_blanks_are_trimmed_from_a_label():
    cfg = config.config_from_mapping({"sources": [source(label="  Example Website  ")]})

    assert cfg.sources[0].label == "Example Website"


def test_the_label_is_not_passed_on_as_a_source_option():
    """A source reads its own options; the label is applied for it."""
    cfg = config.config_from_mapping({"sources": [source()]})

    assert "label" not in cfg.sources[0].options


def test_a_plugin_source_type_is_labelled_like_any_other():
    cfg = config.config_from_mapping({
        "sources": [{"type": "confluence", "label": "Team Wiki", "space": "DOCS"}],
    })

    assert cfg.sources[0].label == "Team Wiki"
    assert dict(cfg.sources[0].options) == {"space": "DOCS"}


def test_two_sources_of_one_type_keep_their_own_labels():
    cfg = config.config_from_mapping({"sources": [
        {"type": "web", "label": "Main Website", "seed_url": "https://example.org/"},
        {"type": "web", "label": "Peer Program", "seed_url": "https://peer.example.org/"},
    ]})

    assert [s.label for s in cfg.sources] == ["Main Website", "Peer Program"]


# ---------------------------------------------------------------------------
# Records always carry a label
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source_type", sorted(DEFAULT_SOURCE_LABELS))
def test_every_source_type_has_a_generic_name_to_fall_back_on(source_type):
    """
    A record built outside a build -- by a plugin under test, or by a
    program using this package as a library -- still carries a label, so
    no client has to decide what to show when the field is missing.
    """
    url = "local:notes/internal.txt" if source_type == "local" else "https://example.org/a"
    document = a_document(
        url=url, source_type=source_type, content_type="text", local=source_type == "local"
    )

    assert document.source_label == DEFAULT_SOURCE_LABELS[source_type]


def test_a_teamdynamix_page_falls_back_to_knowledge_base_not_website():
    """
    The fallback follows source_type, which the site handler sets, not the
    configured source type. A web source pointed at a TeamDynamix portal
    yields "kb" records, and labelling those "Website" would be wrong.
    """
    assert a_document(source_type="kb", content_type="article").source_label == "Knowledge Base"


def test_a_supplied_label_wins_over_the_generic_one():
    assert a_document(source_label="Peer Program").source_label == "Peer Program"


def test_a_blank_label_on_a_record_falls_back_rather_than_staying_empty():
    assert a_document(source_label="   ").source_label == "Website"


def test_a_record_refuses_an_overlong_label():
    with pytest.raises(ValueError, match="characters or fewer"):
        a_document(source_label="A" * (MAX_SOURCE_LABEL_CHARS + 1))


def test_a_record_refuses_a_label_that_is_not_text():
    with pytest.raises(ValueError, match="source_label must be text"):
        a_document(source_label=7)


def test_a_parent_carries_a_label_the_same_way_a_document_does():
    parent = Parent(
        id="0123456789abcdef", t="Team Directory", x="Section text.",
        u="https://example.org/team", host="example.org",
        source_type="web", content_type="page",
    )

    assert parent.source_label == "Website"


# ---------------------------------------------------------------------------
# The label travels to the outputs
# ---------------------------------------------------------------------------

def compendium_with(label, embedder):
    """One built compendium whose single document carries the given label."""
    return build.build_compendium(
        [a_document(source_label=label)],
        name="Example Org",
        embedder=embedder,
        built_at="2026-01-02T03:04:05Z",
    )


def test_chunking_copies_the_label_onto_every_section(fake_embed_chunks_core):
    compendium = compendium_with("Peer Program", fake_embed_chunks_core)

    assert compendium.parents
    assert all(p.source_label == "Peer Program" for p in compendium.parents)


def test_the_container_header_carries_the_label_for_each_section(fake_embed_chunks_core):
    header = build_header(compendium_with("Peer Program", fake_embed_chunks_core))

    assert all(p["source_label"] == "Peer Program" for p in header["parents"])


def test_the_sqlite_output_stores_the_label_in_its_own_column(
    tmp_path, fake_embed_chunks_core
):
    compendium = compendium_with("Peer Program", fake_embed_chunks_core)

    (path,) = SqliteAdapter().write(compendium, tmp_path, {"file": "compendium.sqlite"})

    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT DISTINCT source_label FROM parents;").fetchall()
    finally:
        connection.close()
    assert rows == [("Peer Program",)]


def test_the_container_still_reads_back_as_json_with_the_new_field(
    tmp_path, fake_embed_chunks_core
):
    """The added field must not break the header's own round trip."""
    header = build_header(compendium_with("Peer Program", fake_embed_chunks_core))

    assert json.loads(json.dumps(header))["parents"][0]["source_label"] == "Peer Program"
