"""
Summary: Tests for extractium.config: default values, the settings
allowlist, per-setting validation and error messages, YAML loading
(including refusal of unsafe YAML tags), override merging, and proof that
the built-in exclude patterns still match the frozen reference script's
USER CONFIG lists. Also checks that the shipped examples/config.example.yaml
actually validates.

This file is part of Extractium™
tests/test_config.py

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
import pathlib

import pytest

from extractium import config

EXAMPLE_CONFIG_PATH = pathlib.Path(__file__).parent.parent / "examples" / "config.example.yaml"

SEED = "https://example.edu/TDClient/000/ExampleOrg/Home/"


def write_config(tmp_path, text):
    """Writes text to a config.yaml under tmp_path and returns its path as a string."""
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_minimal_config_supplies_every_default():
    cfg = config.config_from_mapping({"seed_url": SEED})
    assert cfg.seed_url == SEED
    assert cfg.out_path == config.DEFAULT_OUT_PATH
    assert cfg.max_pages == config.DEFAULT_MAX_PAGES
    assert cfg.delay_seconds == config.DEFAULT_DELAY_SECONDS
    assert cfg.include_patterns == ()
    assert cfg.crawl_exclude_patterns == config.DEFAULT_CRAWL_EXCLUDE_PATTERNS
    assert cfg.index_exclude_patterns == config.DEFAULT_INDEX_EXCLUDE_PATTERNS


def test_default_crawl_exclude_patterns_match_reference_script(reference):
    """The ported defaults must exclude exactly what the frozen original excluded."""
    assert list(config.DEFAULT_CRAWL_EXCLUDE_PATTERNS) == list(reference.CRAWL_EXCLUDE_PATTERNS)


def test_default_index_exclude_patterns_match_reference_script(reference):
    # Order carries no meaning here (any single match excludes a URL), so the
    # comparison is set-based; the reference interleaves its extra
    # navigation-only patterns rather than appending them.
    assert set(config.DEFAULT_INDEX_EXCLUDE_PATTERNS) == set(reference.INDEX_EXCLUDE_PATTERNS)


def test_index_excludes_are_a_superset_of_crawl_excludes():
    """A page never worth fetching is never worth indexing either."""
    assert set(config.DEFAULT_CRAWL_EXCLUDE_PATTERNS) <= set(config.DEFAULT_INDEX_EXCLUDE_PATTERNS)


def test_asset_extension_patterns_cover_binary_and_source_extensions():
    from extractium.core import fetch

    for ext in fetch.BINARY_EXTENSIONS + fetch.SOURCE_EXTENSIONS:
        assert rf"\.{ext}$" in config.DEFAULT_CRAWL_EXCLUDE_PATTERNS


def test_config_is_immutable_and_holds_tuples():
    cfg = config.config_from_mapping({"seed_url": SEED})
    assert isinstance(cfg.crawl_exclude_patterns, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.max_pages = 5


# ---------------------------------------------------------------------------
# Supplied values
# ---------------------------------------------------------------------------

def test_every_setting_can_be_supplied():
    cfg = config.config_from_mapping({
        "seed_url": "https://example.org/docs/",
        "out_path": "build/example-index.json",
        "max_pages": 25,
        "delay_seconds": 0,
        "include_patterns": [r"/docs/"],
        "crawl_exclude_patterns": [r"/login"],
        "index_exclude_patterns": [r"/tags"],
    })
    assert cfg.out_path == "build/example-index.json"
    assert cfg.max_pages == 25
    assert cfg.delay_seconds == 0.0
    assert cfg.include_patterns == (r"/docs/",)
    assert cfg.crawl_exclude_patterns == (r"/login",)
    assert cfg.index_exclude_patterns == (r"/tags",)


def test_empty_pattern_list_switches_a_default_off():
    """An explicit [] is a real setting; only an absent key falls back to the default."""
    cfg = config.config_from_mapping({"seed_url": SEED, "crawl_exclude_patterns": []})
    assert cfg.crawl_exclude_patterns == ()


def test_value_written_with_no_value_falls_back_to_the_default(tmp_path):
    path = write_config(tmp_path, f"seed_url: {SEED}\nmax_pages:\ncrawl_exclude_patterns:\n")
    cfg = config.load_config(path)
    assert cfg.max_pages == config.DEFAULT_MAX_PAGES
    assert cfg.crawl_exclude_patterns == config.DEFAULT_CRAWL_EXCLUDE_PATTERNS


def test_surrounding_whitespace_is_trimmed_from_text_settings():
    cfg = config.config_from_mapping({"seed_url": f"  {SEED}  ", "out_path": " out.json "})
    assert cfg.seed_url == SEED
    assert cfg.out_path == "out.json"


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------

def test_max_pages_of_one_is_accepted():
    assert config.config_from_mapping({"seed_url": SEED, "max_pages": 1}).max_pages == 1


def test_max_pages_of_zero_is_rejected():
    with pytest.raises(config.ConfigError, match="max_pages must be 1 or greater"):
        config.config_from_mapping({"seed_url": SEED, "max_pages": 0})


def test_delay_of_zero_is_accepted():
    assert config.config_from_mapping({"seed_url": SEED, "delay_seconds": 0}).delay_seconds == 0.0


def test_negative_delay_is_rejected():
    with pytest.raises(config.ConfigError, match="delay_seconds cannot be negative"):
        config.config_from_mapping({"seed_url": SEED, "delay_seconds": -0.5})


# ---------------------------------------------------------------------------
# Invalid values
# ---------------------------------------------------------------------------

def test_missing_seed_url_is_rejected():
    with pytest.raises(config.ConfigError, match="seed_url is required"):
        config.config_from_mapping({})


def test_blank_seed_url_is_rejected():
    with pytest.raises(config.ConfigError, match="seed_url cannot be blank"):
        config.config_from_mapping({"seed_url": "   "})


def test_seed_url_without_a_host_is_rejected():
    with pytest.raises(config.ConfigError, match="must include a host name"):
        config.config_from_mapping({"seed_url": "https:///docs/"})


def test_non_text_seed_url_is_rejected():
    with pytest.raises(config.ConfigError, match="seed_url must be text, not int"):
        config.config_from_mapping({"seed_url": 42})


def test_blank_out_path_is_rejected():
    with pytest.raises(config.ConfigError, match="out_path cannot be blank"):
        config.config_from_mapping({"seed_url": SEED, "out_path": " "})


def test_quoted_number_is_rejected_rather_than_coerced():
    with pytest.raises(config.ConfigError, match="max_pages must be a whole number, not str"):
        config.config_from_mapping({"seed_url": SEED, "max_pages": "500"})


def test_boolean_is_not_accepted_as_a_number():
    """Python counts True as 1; `max_pages: true` is a mistake, not a ceiling of one."""
    with pytest.raises(config.ConfigError, match="max_pages must be a whole number, not bool"):
        config.config_from_mapping({"seed_url": SEED, "max_pages": True})


def test_single_pattern_written_as_a_bare_string_is_rejected():
    """A bare string would iterate as single characters, silently crawling almost nothing."""
    with pytest.raises(config.ConfigError, match="include_patterns must be a list of patterns"):
        config.config_from_mapping({"seed_url": SEED, "include_patterns": "/docs/"})


def test_non_text_pattern_entry_is_rejected():
    with pytest.raises(config.ConfigError, match="include_patterns entry 2 must be text, not int"):
        config.config_from_mapping({"seed_url": SEED, "include_patterns": ["/docs/", 7]})


def test_blank_pattern_entry_is_rejected():
    """A blank pattern matches every URL, which would silently disable a whole list."""
    with pytest.raises(config.ConfigError, match="include_patterns entry 1 is blank"):
        config.config_from_mapping({"seed_url": SEED, "include_patterns": ["  "]})


def test_invalid_regular_expression_is_reported_with_its_position():
    with pytest.raises(config.ConfigError, match="crawl_exclude_patterns entry 1 is not a valid"):
        config.config_from_mapping({"seed_url": SEED, "crawl_exclude_patterns": ["/docs/["]})


def test_settings_that_are_not_a_mapping_are_rejected():
    with pytest.raises(config.ConfigError, match="must be a mapping"):
        config.config_from_mapping(["seed_url", SEED])


# ---------------------------------------------------------------------------
# Unknown settings (fail closed)
# ---------------------------------------------------------------------------

def test_misspelled_setting_is_rejected_rather_than_ignored():
    with pytest.raises(config.ConfigError, match="unrecognized setting"):
        config.config_from_mapping({"seed_url": SEED, "max_page": 10})


def test_unknown_setting_error_lists_the_known_settings():
    with pytest.raises(config.ConfigError) as excinfo:
        config.config_from_mapping({"seed_url": SEED, "delay": 1})
    message = str(excinfo.value)
    assert "delay" in message
    for key in config.KNOWN_KEYS:
        assert key in message


# ---------------------------------------------------------------------------
# Loading files
# ---------------------------------------------------------------------------

def test_load_config_reads_a_file(tmp_path):
    path = write_config(
        tmp_path,
        f"seed_url: '{SEED}'\nmax_pages: 12\ninclude_patterns:\n  - '/docs/'\n",
    )
    cfg = config.load_config(path)
    assert cfg.seed_url == SEED
    assert cfg.max_pages == 12
    assert cfg.include_patterns == ("/docs/",)


def test_missing_file_reports_a_readable_error(tmp_path):
    missing = str(tmp_path / "does-not-exist.yaml")
    with pytest.raises(config.ConfigError, match="cannot be read"):
        config.load_config(missing)


def test_empty_file_reports_the_missing_required_setting(tmp_path):
    path = write_config(tmp_path, "")
    with pytest.raises(config.ConfigError, match="seed_url is required"):
        config.load_config(path)


def test_broken_yaml_reports_a_readable_error(tmp_path):
    path = write_config(tmp_path, "seed_url: 'unclosed\n  - [\n")
    with pytest.raises(config.ConfigError, match="not valid YAML"):
        config.load_config(path)


def test_top_level_list_is_rejected(tmp_path):
    path = write_config(tmp_path, "- seed_url\n- https://example.edu/\n")
    with pytest.raises(config.ConfigError, match="must hold a mapping"):
        config.load_config(path)


def test_error_messages_name_the_configuration_file(tmp_path):
    path = write_config(tmp_path, "seed_url: 'https://example.edu/'\nmax_pages: 0\n")
    with pytest.raises(config.ConfigError) as excinfo:
        config.load_config(path)
    assert path in str(excinfo.value)


def test_shipped_example_config_validates():
    """A shipped example that fails validation is a documentation defect."""
    cfg = config.load_config(str(EXAMPLE_CONFIG_PATH))
    assert cfg.seed_url.startswith("https://")
    assert cfg.out_path == config.DEFAULT_OUT_PATH


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

def test_overrides_win_over_the_file(tmp_path):
    path = write_config(tmp_path, f"seed_url: '{SEED}'\nmax_pages: 12\n")
    cfg = config.load_config(path, overrides={"max_pages": 3})
    assert cfg.max_pages == 3


def test_overrides_that_are_none_are_ignored(tmp_path):
    """An argument the user did not supply must leave the file's value alone."""
    path = write_config(tmp_path, f"seed_url: '{SEED}'\nmax_pages: 12\n")
    cfg = config.load_config(path, overrides={"max_pages": None, "out_path": None})
    assert cfg.max_pages == 12
    assert cfg.out_path == config.DEFAULT_OUT_PATH


def test_overrides_are_validated_like_file_settings(tmp_path):
    path = write_config(tmp_path, f"seed_url: '{SEED}'\n")
    with pytest.raises(config.ConfigError, match="max_pages must be 1 or greater"):
        config.load_config(path, overrides={"max_pages": -1})


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

def test_yaml_object_tags_are_refused(tmp_path):
    """
    A configuration file must never be able to run code. yaml.safe_load
    understands plain data only, so a Python object tag fails to parse
    instead of constructing (and here, calling) anything.
    """
    path = write_config(
        tmp_path,
        "seed_url: !!python/object/apply:os.system ['echo should-never-run']\n",
    )
    with pytest.raises(config.ConfigError, match="not valid YAML"):
        config.load_config(path)


def test_file_scheme_seed_url_is_refused():
    """
    Local disk content must not enter a crawl through the seed URL: the
    web-facing outputs assume everything indexed was already published.
    """
    with pytest.raises(config.ConfigError, match="must start with http:// or https://"):
        config.config_from_mapping({"seed_url": "file:///etc/passwd"})


@pytest.mark.parametrize("seed", [
    "ftp://example.edu/docs/",
    "javascript:alert(1)",
    "data:text/html,<p>hi</p>",
    "example.edu/docs/",
])
def test_only_http_and_https_seeds_are_accepted(seed):
    with pytest.raises(config.ConfigError, match="must start with http:// or https://"):
        config.config_from_mapping({"seed_url": seed})
