"""
Summary: Tests for the settings file as the local page sees it: the
form's description covers every setting the loader knows; a file round
trips through the form path unchanged in meaning; a saved form leaves
out what equals a default and keeps what a person set; a value the
loader refuses is refused with its message; a save keeps the previous
file with a date stamp; the file's own text is written as typed; the
welcome screen's first file loads with the page's outputs on and a
hostile name stays a name.

This file is part of Extractium™
tests/test_ui_settings.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-28
Last Modified: 2026-09-28
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
__date__ = "2026-09-28"

import json
import pathlib

import pytest
import yaml

from extractium import config
from extractium.ui import settings

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
EVERY_SOURCE_TYPE = REPO_ROOT / "examples" / "config.efdc.yaml"

MINIMAL = "sources:\n  - type: web\n    label: Docs\n    seed_url: https://example.edu/\n"


def form_of(text):
    """A file's text as the form receives it."""
    return settings.form_values(settings.mapping_from_text(text))


# ---------------------------------------------------------------------------
# The form's description
# ---------------------------------------------------------------------------

def test_the_description_names_every_global_setting_the_loader_knows():
    described = {field["key"] for field in settings.GLOBAL_FIELDS}

    assert described == config.KNOWN_KEYS - {"sources", "outputs"}


def test_the_description_names_every_option_of_every_built_in_source_type():
    for type_name, keys in config.SOURCE_OPTION_KEYS.items():
        described = {field["key"] for field in settings.SOURCE_TYPES[type_name]["fields"]}
        # One field holds where a crawl starts, whichever key the file used.
        expected = (keys - {"seed_url"}) if type_name == "web" else keys
        assert described == expected, type_name


def test_the_description_names_every_option_of_every_built_in_output_type():
    for type_name, keys in config.OUTPUT_OPTION_KEYS.items():
        described = {field["key"] for field in settings.OUTPUT_TYPES[type_name]["fields"]}
        assert described == keys, type_name


def test_every_field_has_a_label_help_text_and_a_kind_the_page_draws():
    kinds = {settings.KIND_TEXT, settings.KIND_INTEGER, settings.KIND_NUMBER, settings.KIND_BOOLEAN,
             settings.KIND_CHOICE, settings.KIND_LINES}
    fields = list(settings.GLOBAL_FIELDS) + list(settings.SOURCE_COMMON_FIELDS) + list(settings.OUTPUT_COMMON_FIELDS)
    for entry in list(settings.SOURCE_TYPES.values()) + list(settings.OUTPUT_TYPES.values()):
        fields.extend(entry["fields"])

    for field in fields:
        assert field["label"] and field["help"], field["key"]
        assert field["kind"] in kinds, field["key"]
        if field["kind"] == settings.KIND_CHOICE:
            assert field["default"] in field["choices"], field["key"]


def test_the_description_is_plain_json():
    text = json.dumps(settings.schema())

    assert '"globals"' in text and '"sourceTypes"' in text and '"outputTypes"' in text


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------

def test_a_missing_file_is_reported_as_absent(tmp_path):
    state = settings.settings_state(tmp_path / "config.yaml")

    assert state == {"exists": False, "text": None, "values": None, "error": None}


def test_a_file_the_loader_accepts_gives_its_text_and_form_values(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL, encoding="utf-8")

    state = settings.settings_state(path)

    assert state["exists"] and state["error"] is None
    assert state["text"] == MINIMAL
    assert state["values"]["sources"][0]["seed_urls"] == ["https://example.edu/"]
    assert "seed_url" not in state["values"]["sources"][0]
    assert state["values"]["outputs"] == [{"type": "container"}, {"type": "llmstxt"}]


def test_a_file_the_loader_refuses_still_shows_with_the_loaders_message(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL + "max_pages: 0\n", encoding="utf-8")

    state = settings.settings_state(path)

    assert state["values"]["max_pages"] == 0
    assert "max_pages must be 1 or greater" in state["error"]


def test_a_file_that_is_not_yaml_shows_its_text_and_no_form_values(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("sources: [\n", encoding="utf-8")

    state = settings.settings_state(path)

    assert state["text"] == "sources: [\n"
    assert state["values"] is None
    assert "not valid YAML" in state["error"]


# ---------------------------------------------------------------------------
# Saving the form
# ---------------------------------------------------------------------------

def test_a_settings_file_using_every_source_type_round_trips_through_the_form(tmp_path):
    original = config.load_config(EVERY_SOURCE_TYPE)

    text, kept = settings.save_form(tmp_path / "config.yaml", form_of(EVERY_SOURCE_TYPE.read_text(encoding="utf-8")))

    assert kept is None
    assert config.load_config(tmp_path / "config.yaml") == original


def test_a_saved_form_leaves_out_what_equals_a_default_and_keeps_what_was_set():
    form = form_of(MINIMAL)
    form["max_pages"] = config.DEFAULT_MAX_PAGES
    form["delay_seconds"] = 0.8
    form["rebuild"] = "full"
    form["keywords"] = True
    form["sources"][0]["read_documents"] = False
    form["sources"][0]["description"] = ""
    form["outputs"] = [{"type": "container", "gzip": True, "full": True, "include_local": False}]

    mapping = settings.file_mapping(form)

    assert mapping == {
        "delay_seconds": 0.8,
        "sources": [{"type": "web", "label": "Docs", "seed_url": "https://example.edu/"}],
        "outputs": [{"type": "container"}],
    }


def test_several_starting_pages_stay_a_list_and_one_becomes_seed_url():
    form = form_of(MINIMAL)
    form["sources"][0]["seed_urls"] = ["https://example.edu/a/", "https://example.edu/b/"]

    mapping = settings.file_mapping(form)

    assert mapping["sources"][0]["seed_urls"] == ["https://example.edu/a/", "https://example.edu/b/"]
    assert "seed_url" not in mapping["sources"][0]


def test_an_empty_list_is_kept_only_where_it_means_something():
    form = form_of(MINIMAL)
    form["sources"][0]["site_handlers"] = []
    form["sources"][0]["crawl_exclude_patterns"] = []
    form["sources"][0]["include_patterns"] = []
    form["github_owners"] = []

    mapping = settings.file_mapping(form)

    assert mapping["sources"][0]["site_handlers"] == []
    assert mapping["sources"][0]["crawl_exclude_patterns"] == []
    assert "include_patterns" not in mapping["sources"][0]
    assert "github_owners" not in mapping


def test_the_compression_setting_is_written_only_when_it_differs_from_the_file_name():
    form = form_of(MINIMAL)
    form["outputs"] = [
        {"type": "container", "file": "kb.json", "gzip": True},
        {"type": "container", "file": "kb.json.gz", "gzip": True},
        {"type": "container", "file": "kb.json", "gzip": False},
        {"type": "container", "gzip": False},
    ]

    outputs = settings.file_mapping(form)["outputs"]

    assert outputs == [
        {"type": "container", "file": "kb.json", "gzip": True},
        {"type": "container", "file": "kb.json.gz"},
        {"type": "container", "file": "kb.json"},
        {"type": "container", "gzip": False},
    ]


def test_a_plug_in_source_keeps_its_own_options_untouched():
    form = form_of(MINIMAL)
    form["sources"].append({"type": "faq", "label": "FAQ", "path": "faq.json", "nested": {"a": [1, 2]}})

    mapping = settings.file_mapping(form)

    assert mapping["sources"][1] == {"type": "faq", "label": "FAQ", "path": "faq.json", "nested": {"a": [1, 2]}}


def test_numbers_typed_as_text_are_read_as_numbers_and_nonsense_is_refused():
    form = form_of(MINIMAL)
    form["max_pages"] = "25"
    form["delay_seconds"] = "1.5"

    mapping = settings.file_mapping(form)
    assert mapping["max_pages"] == 25 and mapping["delay_seconds"] == 1.5

    form["max_pages"] = "many"
    with pytest.raises(settings.SettingsError, match="max_pages must be a number"):
        settings.file_mapping(form)


def test_a_value_the_loader_refuses_is_refused_with_the_loaders_message(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL, encoding="utf-8")
    form = form_of(MINIMAL)
    form["slug"] = "Not A Slug"

    with pytest.raises(settings.SettingsError, match="slug must be lowercase letters"):
        settings.save_form(path, form)
    assert path.read_text(encoding="utf-8") == MINIMAL, "a refused save leaves the file alone"


def test_a_hostile_name_is_written_as_a_quoted_string_and_read_back_unchanged(tmp_path):
    path = tmp_path / "config.yaml"
    for name in ('Evil: "name', "name\nsources: []\nmax_pages: 1", "#not a comment", "- list", "yes"):
        form = form_of(MINIMAL)
        form["name"] = name

        settings.save_form(path, form)

        loaded = config.load_config(path)
        assert loaded.name == name
        assert loaded.max_pages == config.DEFAULT_MAX_PAGES
        assert len(loaded.sources) == 1


def test_a_save_keeps_the_previous_file_with_a_date_stamp(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL + "# my note\n", encoding="utf-8")
    form = form_of(MINIMAL)
    form["max_pages"] = 7

    text, kept = settings.save_form(path, form, now="2026-09-28T14:05:33Z")

    assert kept == tmp_path / "config.yaml.2026-09-28T14-05-33Z.bak"
    assert kept.read_text(encoding="utf-8") == MINIMAL + "# my note\n"
    assert path.read_text(encoding="utf-8") == text
    assert text.startswith(settings.FILE_HEADER)
    assert config.load_config(path).max_pages == 7


def test_a_form_that_is_not_a_mapping_is_refused():
    with pytest.raises(settings.SettingsError):
        settings.file_mapping(["not", "a", "mapping"])
    with pytest.raises(settings.SettingsError, match="sources must be a list"):
        settings.file_mapping({"sources": "web"})
    with pytest.raises(settings.SettingsError, match="type is required"):
        settings.file_mapping({"sources": [{"label": "x"}]})


# ---------------------------------------------------------------------------
# Saving the text
# ---------------------------------------------------------------------------

def test_the_files_text_is_written_as_typed_comments_included(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL, encoding="utf-8")
    typed = "# keep this comment\n" + MINIMAL + "max_pages: 3   # and this one\n"

    kept = settings.save_text(path, typed, now="2026-09-28T14:05:33Z")

    assert path.read_text(encoding="utf-8") == typed
    assert kept.name == "config.yaml.2026-09-28T14-05-33Z.bak"
    assert config.load_config(path).max_pages == 3


def test_text_the_loader_refuses_is_refused_with_its_message_and_nothing_is_written(tmp_path):
    path = tmp_path / "config.yaml"

    with pytest.raises(settings.SettingsError, match="sources is required"):
        settings.save_text(path, "max_pages: 3\n")
    with pytest.raises(settings.SettingsError, match="not valid YAML"):
        settings.save_text(path, "sources: [\n")
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_the_first_save_keeps_no_previous_file(tmp_path):
    path = tmp_path / "config.yaml"

    assert settings.save_text(path, MINIMAL) is None
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["config.yaml"]


# ---------------------------------------------------------------------------
# The first file
# ---------------------------------------------------------------------------

def test_the_welcome_file_loads_with_the_pages_outputs_on(tmp_path):
    path = settings.write_first_settings(
        {"name": "My KB", "slug": "", "seed_url": "https://example.edu/"}, tmp_path / "config.yaml"
    )

    loaded = config.load_config(path)
    assert loaded.name == "My KB" and loaded.slug == "my-kb"
    assert [output.type for output in loaded.outputs] == ["container", "llmstxt", "okf"]
    assert loaded.outputs[0].options["gzip"] is True
    assert "Writing patterns safely" in path.read_text(encoding="utf-8"), "the commented example travels with the file"


def test_the_welcome_file_refuses_to_replace_an_existing_one(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("keep me\n", encoding="utf-8")

    with pytest.raises(settings.SettingsError, match="already exists"):
        settings.write_first_settings({"name": "x", "slug": "", "seed_url": "https://example.edu/"}, path)
    assert path.read_text(encoding="utf-8") == "keep me\n"


def test_the_welcome_file_refuses_a_bad_address_and_a_hostile_name_stays_a_name(tmp_path):
    with pytest.raises(settings.SettingsError, match="must start with http"):
        settings.write_first_settings({"name": "x", "slug": "", "seed_url": "ftp://x/"}, tmp_path / "a.yaml")

    # The init module folds a name onto one line, as the terminal does;
    # what matters is that none of it becomes a setting.
    path = settings.write_first_settings(
        {"name": "name\nsources: []\nmax_pages: 1", "slug": "", "seed_url": "https://example.edu/"},
        tmp_path / "b.yaml",
    )
    loaded = config.load_config(path)
    assert loaded.name == "name sources: [] max_pages: 1"
    assert loaded.max_pages == config.DEFAULT_MAX_PAGES
    assert len(loaded.sources) == 1


def test_the_written_text_is_valid_yaml_the_loader_reads_back_in_form_order():
    mapping = settings.file_mapping(form_of(MINIMAL + "max_pages: 4\nname: Docs\n"))

    text = settings.settings_text(mapping)

    assert list(yaml.safe_load(text)) == ["name", "max_pages", "sources", "outputs"]
