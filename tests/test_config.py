"""
Summary: Tests for extractium.config: global settings and their defaults,
the sources and outputs lists with per-type validation, the settings
allowlist at every level, error messages, YAML loading (including
refusal of unsafe YAML tags), override merging, and proof that the
built-in exclude patterns still match the frozen reference script's
USER CONFIG lists. Also checks that the shipped
examples/config.example.yaml validates.

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


def web(**options):
    """One web source entry with the standard seed URL."""
    return {"type": "web", "seed_url": SEED, **options}


def minimal(**extra):
    """The smallest valid configuration mapping, with optional extra top-level keys."""
    return {"sources": [web()], **extra}


def write_config(tmp_path, text):
    """Writes text to a config.yaml under tmp_path and returns its path as a string."""
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Global defaults
# ---------------------------------------------------------------------------

def test_minimal_config_supplies_every_global_default():
    cfg = config.config_from_mapping(minimal())
    assert cfg.name is None
    assert cfg.out_dir == config.DEFAULT_OUT_DIR
    assert cfg.cache_dir == config.DEFAULT_CACHE_DIR
    assert cfg.max_pages == config.DEFAULT_MAX_PAGES
    assert cfg.delay_seconds == config.DEFAULT_DELAY_SECONDS
    assert cfg.user_agent == config.DEFAULT_USER_AGENT
    assert cfg.respect_robots_txt is True
    assert cfg.phi_lint == "local"


def test_default_user_agent_names_the_tool_and_its_repository():
    from extractium import __version__

    assert config.DEFAULT_USER_AGENT.startswith(f"Extractium/{__version__} ")
    assert "github.com/DepressionCenter/extractium" in config.DEFAULT_USER_AGENT


def test_omitted_outputs_default_to_container_and_llmstxt():
    cfg = config.config_from_mapping(minimal())
    assert [o.type for o in cfg.outputs] == ["container", "llmstxt"]
    assert cfg.outputs[0].options["file"] == config.DEFAULT_CONTAINER_FILE
    assert all(o.include_local is False for o in cfg.outputs)


def test_config_is_immutable_and_holds_tuples():
    cfg = config.config_from_mapping(minimal())
    assert isinstance(cfg.sources, tuple)
    assert isinstance(cfg.outputs, tuple)
    assert isinstance(cfg.sources[0].options["crawl_exclude_patterns"], tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.max_pages = 5
    with pytest.raises(TypeError):
        cfg.sources[0].options["seed_url"] = "https://elsewhere.example/"


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


# ---------------------------------------------------------------------------
# Global settings supplied
# ---------------------------------------------------------------------------

def test_every_global_setting_can_be_supplied():
    cfg = config.config_from_mapping(minimal(
        name="Example Org Knowledge Base",
        out_dir="build",
        cache_dir=".cache",
        max_pages=25,
        delay_seconds=0,
        user_agent="ExampleBot/1.0 (+https://example.edu/bot)",
        respect_robots_txt=False,
        phi_lint="all",
    ))
    assert cfg.name == "Example Org Knowledge Base"
    assert cfg.out_dir == "build"
    assert cfg.cache_dir == ".cache"
    assert cfg.max_pages == 25
    assert cfg.delay_seconds == 0.0
    assert cfg.user_agent == "ExampleBot/1.0 (+https://example.edu/bot)"
    assert cfg.respect_robots_txt is False
    assert cfg.phi_lint == "all"


def test_setting_written_with_no_value_falls_back_to_the_default(tmp_path):
    path = write_config(tmp_path, f"max_pages:\nout_dir:\nsources:\n  - type: web\n    seed_url: {SEED}\n")
    cfg = config.load_config(path)
    assert cfg.max_pages == config.DEFAULT_MAX_PAGES
    assert cfg.out_dir == config.DEFAULT_OUT_DIR


def test_surrounding_whitespace_is_trimmed_from_text_settings():
    cfg = config.config_from_mapping({"out_dir": " out ", "sources": [web(seed_url=f"  {SEED}  ")]})
    assert cfg.out_dir == "out"
    assert cfg.sources[0].options["seed_url"] == SEED


def test_max_pages_of_one_is_accepted():
    assert config.config_from_mapping(minimal(max_pages=1)).max_pages == 1


def test_max_pages_of_zero_is_rejected():
    with pytest.raises(config.ConfigError, match="max_pages must be 1 or greater"):
        config.config_from_mapping(minimal(max_pages=0))


def test_negative_delay_is_rejected():
    with pytest.raises(config.ConfigError, match="delay_seconds cannot be negative"):
        config.config_from_mapping(minimal(delay_seconds=-0.5))


def test_quoted_number_is_rejected_rather_than_coerced():
    with pytest.raises(config.ConfigError, match="max_pages must be a whole number, not str"):
        config.config_from_mapping(minimal(max_pages="500"))


def test_boolean_is_not_accepted_as_a_number():
    """Python counts True as 1; `max_pages: true` is a mistake, not a ceiling of one."""
    with pytest.raises(config.ConfigError, match="max_pages must be a whole number, not bool"):
        config.config_from_mapping(minimal(max_pages=True))


def test_blank_out_dir_is_rejected():
    with pytest.raises(config.ConfigError, match="out_dir cannot be blank"):
        config.config_from_mapping(minimal(out_dir=" "))


def test_respect_robots_txt_must_be_a_boolean():
    with pytest.raises(config.ConfigError, match="respect_robots_txt must be true or false, not str"):
        config.config_from_mapping(minimal(respect_robots_txt="yes"))


def test_phi_lint_must_be_a_known_mode():
    with pytest.raises(config.ConfigError, match="phi_lint must be one of all, local, off"):
        config.config_from_mapping(minimal(phi_lint="always"))


def test_settings_that_are_not_a_mapping_are_rejected():
    with pytest.raises(config.ConfigError, match="must be a mapping"):
        config.config_from_mapping(["sources"])


# ---------------------------------------------------------------------------
# Unknown settings (fail closed)
# ---------------------------------------------------------------------------

def test_misspelled_global_setting_is_rejected_rather_than_ignored():
    with pytest.raises(config.ConfigError, match="unrecognized setting"):
        config.config_from_mapping(minimal(max_page=10))


def test_unknown_setting_error_lists_the_known_settings():
    with pytest.raises(config.ConfigError) as excinfo:
        config.config_from_mapping(minimal(delay=1))
    message = str(excinfo.value)
    assert "delay" in message
    for key in config.KNOWN_KEYS:
        assert key in message


def test_old_flat_seed_url_is_rejected_with_a_pointer_to_sources():
    """The single-seed form is gone; a file in that form must say where the seed goes now."""
    with pytest.raises(config.ConfigError, match="seed_url.*sources"):
        config.config_from_mapping({"seed_url": SEED})


# ---------------------------------------------------------------------------
# The sources list
# ---------------------------------------------------------------------------

def test_sources_is_required():
    with pytest.raises(config.ConfigError, match="sources is required"):
        config.config_from_mapping({})


def test_sources_must_be_a_list():
    with pytest.raises(config.ConfigError, match="sources must be a list"):
        config.config_from_mapping({"sources": web()})


def test_sources_must_not_be_empty():
    with pytest.raises(config.ConfigError, match="sources must list at least one source"):
        config.config_from_mapping({"sources": []})


def test_source_entry_must_be_a_mapping():
    with pytest.raises(config.ConfigError, match="sources entry 1 must be a mapping"):
        config.config_from_mapping({"sources": ["web"]})


def test_source_entry_needs_a_type():
    with pytest.raises(config.ConfigError, match="sources entry 1: type is required"):
        config.config_from_mapping({"sources": [{"seed_url": SEED}]})


def test_source_type_must_be_a_plain_name():
    with pytest.raises(config.ConfigError, match="sources entry 1: type must be a short name"):
        config.config_from_mapping({"sources": [{"type": "web source!"}]})


def test_errors_name_the_source_position_and_type():
    with pytest.raises(config.ConfigError, match=r"sources entry 2 \(web\): seed_url is required"):
        config.config_from_mapping({"sources": [web(), {"type": "web"}]})


def test_several_sources_keep_their_order():
    cfg = config.config_from_mapping({"sources": [
        web(),
        {"type": "local", "path": "./internal-docs"},
        {"type": "github_api", "org": "example-org"},
    ]})
    assert [s.type for s in cfg.sources] == ["web", "local", "github_api"]


# ---------------------------------------------------------------------------
# Web source
# ---------------------------------------------------------------------------

def test_web_source_defaults():
    source = config.config_from_mapping(minimal()).sources[0]
    assert source.type == "web"
    assert source.options["seed_url"] == SEED
    assert source.options["include_patterns"] == ()
    assert source.options["crawl_exclude_patterns"] == config.DEFAULT_CRAWL_EXCLUDE_PATTERNS
    assert source.options["index_exclude_patterns"] == config.DEFAULT_INDEX_EXCLUDE_PATTERNS
    assert source.options["site_handlers"] is None


def test_web_source_accepts_every_option():
    source = config.config_from_mapping({"sources": [web(
        include_patterns=[r"/docs/"],
        crawl_exclude_patterns=[r"/login"],
        index_exclude_patterns=[r"/tags"],
        site_handlers=["tdx"],
    )]}).sources[0]
    assert source.options["include_patterns"] == (r"/docs/",)
    assert source.options["crawl_exclude_patterns"] == (r"/login",)
    assert source.options["index_exclude_patterns"] == (r"/tags",)
    assert source.options["site_handlers"] == ("tdx",)


def test_empty_pattern_list_switches_a_default_off():
    """An explicit [] is a real setting; only an absent key falls back to the default."""
    source = config.config_from_mapping({"sources": [web(crawl_exclude_patterns=[])]}).sources[0]
    assert source.options["crawl_exclude_patterns"] == ()


def test_empty_site_handlers_list_means_generic_only():
    """Omitted means every installed handler; [] means none but the generic fallback."""
    source = config.config_from_mapping({"sources": [web(site_handlers=[])]}).sources[0]
    assert source.options["site_handlers"] == ()


def test_site_handlers_must_be_a_list_of_names():
    with pytest.raises(config.ConfigError, match="site_handlers must be a list of names"):
        config.config_from_mapping({"sources": [web(site_handlers="tdx")]})
    with pytest.raises(config.ConfigError, match="site_handlers entry 1 must be text"):
        config.config_from_mapping({"sources": [web(site_handlers=[3])]})


def test_web_source_rejects_unknown_option():
    with pytest.raises(config.ConfigError, match=r"sources entry 1 \(web\): unrecognized setting\(s\): seed"):
        config.config_from_mapping({"sources": [{"type": "web", "seed": SEED}]})


def test_missing_seed_url_is_rejected():
    with pytest.raises(config.ConfigError, match="seed_url is required"):
        config.config_from_mapping({"sources": [{"type": "web"}]})


def test_blank_seed_url_is_rejected():
    with pytest.raises(config.ConfigError, match="seed_url cannot be blank"):
        config.config_from_mapping({"sources": [web(seed_url="   ")]})


def test_seed_url_without_a_host_is_rejected():
    with pytest.raises(config.ConfigError, match="must include a host name"):
        config.config_from_mapping({"sources": [web(seed_url="https:///docs/")]})


def test_non_text_seed_url_is_rejected():
    with pytest.raises(config.ConfigError, match="seed_url must be text, not int"):
        config.config_from_mapping({"sources": [web(seed_url=42)]})


def test_single_pattern_written_as_a_bare_string_is_rejected():
    """A bare string would iterate as single characters, silently crawling almost nothing."""
    with pytest.raises(config.ConfigError, match="include_patterns must be a list of patterns"):
        config.config_from_mapping({"sources": [web(include_patterns="/docs/")]})


def test_non_text_pattern_entry_is_rejected():
    with pytest.raises(config.ConfigError, match="include_patterns entry 2 must be text, not int"):
        config.config_from_mapping({"sources": [web(include_patterns=["/docs/", 7])]})


def test_blank_pattern_entry_is_rejected():
    """A blank pattern matches every URL, which would silently disable a whole list."""
    with pytest.raises(config.ConfigError, match="include_patterns entry 1 is blank"):
        config.config_from_mapping({"sources": [web(include_patterns=["  "])]})


def test_invalid_regular_expression_is_reported_with_its_position():
    with pytest.raises(config.ConfigError, match="crawl_exclude_patterns entry 1 is not a valid"):
        config.config_from_mapping({"sources": [web(crawl_exclude_patterns=["/docs/["])]})


# ---------------------------------------------------------------------------
# Other built-in source types
# ---------------------------------------------------------------------------

def test_local_source_defaults_and_options():
    source = config.config_from_mapping({"sources": [{"type": "local", "path": "./internal-docs"}]}).sources[0]
    assert source.options["path"] == "./internal-docs"
    assert source.options["include_globs"] == config.DEFAULT_LOCAL_INCLUDE_GLOBS
    custom = config.config_from_mapping({"sources": [
        {"type": "local", "path": "docs", "include_globs": ["**/*.md"]},
    ]}).sources[0]
    assert custom.options["include_globs"] == ("**/*.md",)


def test_local_source_requires_a_path():
    with pytest.raises(config.ConfigError, match=r"sources entry 1 \(local\): path is required"):
        config.config_from_mapping({"sources": [{"type": "local"}]})


def test_local_source_globs_must_be_a_list_of_text():
    with pytest.raises(config.ConfigError, match="include_globs must be a list"):
        config.config_from_mapping({"sources": [{"type": "local", "path": "docs", "include_globs": "**/*.md"}]})


def test_github_api_source_requires_an_org():
    source = config.config_from_mapping({"sources": [{"type": "github_api", "org": "example-org"}]}).sources[0]
    assert source.options["org"] == "example-org"
    with pytest.raises(config.ConfigError, match=r"\(github_api\): org is required"):
        config.config_from_mapping({"sources": [{"type": "github_api"}]})


def test_youtube_source_defaults_and_options():
    source = config.config_from_mapping({"sources": [
        {"type": "youtube", "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx"},
    ]}).sources[0]
    assert source.options["channel_id"] == "UCxxxxxxxxxxxxxxxxxxxxxx"
    assert source.options["playlist_ids"] == ()
    assert source.options["video_ids"] == ()
    assert source.options["languages"] == ("en",)


def test_youtube_source_needs_at_least_one_id():
    with pytest.raises(config.ConfigError, match=r"\(youtube\): give at least one of channel_id, playlist_ids, video_ids"):
        config.config_from_mapping({"sources": [{"type": "youtube"}]})


def test_unknown_source_type_passes_its_options_through_unchecked():
    """A plugin in plugins/ can add a type; its options are checked by the plugin, not here."""
    source = config.config_from_mapping({"sources": [
        {"type": "confluence", "space": "DOCS", "depth": 3},
    ]}).sources[0]
    assert source.type == "confluence"
    assert dict(source.options) == {"space": "DOCS", "depth": 3}


# ---------------------------------------------------------------------------
# The outputs list
# ---------------------------------------------------------------------------

def test_outputs_accept_every_built_in_type():
    cfg = config.config_from_mapping(minimal(outputs=[
        {"type": "container", "file": "index.bin", "include_local": True},
        {"type": "llmstxt"},
        {"type": "sqlite"},
        {"type": "okf"},
    ]))
    assert [o.type for o in cfg.outputs] == ["container", "llmstxt", "sqlite", "okf"]
    assert cfg.outputs[0].options["file"] == "index.bin"
    assert cfg.outputs[0].include_local is True
    assert cfg.outputs[1].include_local is False
    assert cfg.outputs[2].options["file"] == config.DEFAULT_SQLITE_FILE


def test_outputs_must_be_a_list_of_mappings():
    with pytest.raises(config.ConfigError, match="outputs must be a list"):
        config.config_from_mapping(minimal(outputs={"type": "container"}))
    with pytest.raises(config.ConfigError, match="outputs entry 1 must be a mapping"):
        config.config_from_mapping(minimal(outputs=["container"]))


def test_empty_outputs_list_is_rejected():
    """A build that writes nothing is a mistake, not a choice."""
    with pytest.raises(config.ConfigError, match="outputs must list at least one output"):
        config.config_from_mapping(minimal(outputs=[]))


def test_output_entry_needs_a_type():
    with pytest.raises(config.ConfigError, match="outputs entry 1: type is required"):
        config.config_from_mapping(minimal(outputs=[{"file": "x.json"}]))


def test_output_rejects_unknown_option():
    with pytest.raises(config.ConfigError, match=r"outputs entry 1 \(llmstxt\): unrecognized setting\(s\): file"):
        config.config_from_mapping(minimal(outputs=[{"type": "llmstxt", "file": "llms.txt"}]))


def test_include_local_must_be_a_boolean():
    with pytest.raises(config.ConfigError, match="include_local must be true or false"):
        config.config_from_mapping(minimal(outputs=[{"type": "container", "include_local": "yes"}]))


@pytest.mark.parametrize("file", ["/etc/index.json", "C:\\index.json", "../index.json", "sub/../../x.json"])
def test_output_file_must_stay_under_out_dir(file):
    """Every adapter writes under out_dir; a file name that escapes it could overwrite anything."""
    with pytest.raises(config.ConfigError, match="file must be a relative path inside out_dir"):
        config.config_from_mapping(minimal(outputs=[{"type": "container", "file": file}]))


def test_output_file_may_use_a_subfolder():
    cfg = config.config_from_mapping(minimal(outputs=[{"type": "container", "file": "v3/kb-index.json"}]))
    assert cfg.outputs[0].options["file"] == "v3/kb-index.json"


def test_unknown_output_type_passes_its_options_through_unchecked():
    output = config.config_from_mapping(minimal(outputs=[
        {"type": "parquet", "compression": "zstd", "include_local": True},
    ])).outputs[0]
    assert output.type == "parquet"
    assert output.include_local is True
    assert dict(output.options) == {"compression": "zstd"}


# ---------------------------------------------------------------------------
# Loading files
# ---------------------------------------------------------------------------

def test_load_config_reads_a_file(tmp_path):
    path = write_config(tmp_path, (
        "max_pages: 12\n"
        "sources:\n"
        f"  - type: web\n    seed_url: '{SEED}'\n    include_patterns:\n      - '/docs/'\n"
        "outputs:\n  - type: container\n    file: kb.json\n"
    ))
    cfg = config.load_config(path)
    assert cfg.max_pages == 12
    assert cfg.sources[0].options["include_patterns"] == ("/docs/",)
    assert cfg.outputs[0].options["file"] == "kb.json"


def test_missing_file_reports_a_readable_error(tmp_path):
    missing = str(tmp_path / "does-not-exist.yaml")
    with pytest.raises(config.ConfigError, match="cannot be read"):
        config.load_config(missing)


def test_empty_file_reports_the_missing_required_setting(tmp_path):
    path = write_config(tmp_path, "")
    with pytest.raises(config.ConfigError, match="sources is required"):
        config.load_config(path)


def test_broken_yaml_reports_a_readable_error(tmp_path):
    path = write_config(tmp_path, "sources: 'unclosed\n  - [\n")
    with pytest.raises(config.ConfigError, match="not valid YAML"):
        config.load_config(path)


def test_top_level_list_is_rejected(tmp_path):
    path = write_config(tmp_path, "- type: web\n")
    with pytest.raises(config.ConfigError, match="must hold a mapping"):
        config.load_config(path)


def test_error_messages_name_the_configuration_file(tmp_path):
    path = write_config(tmp_path, f"max_pages: 0\nsources:\n  - type: web\n    seed_url: '{SEED}'\n")
    with pytest.raises(config.ConfigError) as excinfo:
        config.load_config(path)
    assert path in str(excinfo.value)


def test_shipped_example_config_has_one_web_source_and_two_outputs():
    """A shipped example that fails validation is a documentation defect."""
    cfg = config.load_config(str(EXAMPLE_CONFIG_PATH))
    assert [s.type for s in cfg.sources] == ["web"]
    assert cfg.sources[0].options["seed_url"].startswith("https://")
    assert [o.type for o in cfg.outputs] == ["container", "llmstxt"]
    assert cfg.out_dir == config.DEFAULT_OUT_DIR


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

def test_overrides_win_over_the_file(tmp_path):
    path = write_config(tmp_path, f"max_pages: 12\nsources:\n  - type: web\n    seed_url: '{SEED}'\n")
    cfg = config.load_config(path, overrides={"max_pages": 3, "out_dir": "elsewhere"})
    assert cfg.max_pages == 3
    assert cfg.out_dir == "elsewhere"


def test_overrides_that_are_none_are_ignored(tmp_path):
    """An argument the user did not supply must leave the file's value alone."""
    path = write_config(tmp_path, f"max_pages: 12\nsources:\n  - type: web\n    seed_url: '{SEED}'\n")
    cfg = config.load_config(path, overrides={"max_pages": None, "out_dir": None})
    assert cfg.max_pages == 12
    assert cfg.out_dir == config.DEFAULT_OUT_DIR


def test_overrides_are_validated_like_file_settings(tmp_path):
    path = write_config(tmp_path, f"sources:\n  - type: web\n    seed_url: '{SEED}'\n")
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
        "sources: !!python/object/apply:os.system ['echo should-never-run']\n",
    )
    with pytest.raises(config.ConfigError, match="not valid YAML"):
        config.load_config(path)


def test_file_scheme_seed_url_is_refused():
    """
    Local disk content must not enter a crawl through the seed URL: the
    web-facing outputs assume everything indexed was already published.
    """
    with pytest.raises(config.ConfigError, match="must start with http:// or https://"):
        config.config_from_mapping({"sources": [web(seed_url="file:///etc/passwd")]})


@pytest.mark.parametrize("seed", [
    "ftp://example.edu/docs/",
    "javascript:alert(1)",
    "data:text/html,<p>hi</p>",
    "example.edu/docs/",
])
def test_only_http_and_https_seeds_are_accepted(seed):
    with pytest.raises(config.ConfigError, match="must start with http:// or https://"):
        config.config_from_mapping({"sources": [web(seed_url=seed)]})


def test_user_agent_cannot_carry_header_injection():
    """A newline in the User-Agent would let a config file inject extra request headers."""
    with pytest.raises(config.ConfigError, match="user_agent cannot contain line breaks"):
        config.config_from_mapping(minimal(user_agent="Bot/1.0\r\nX-Injected: yes"))
