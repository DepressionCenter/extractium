"""
Summary: Configuration schema for an Extractium build. Defines the allowed
keys of an organization's config.yaml: the global settings, the sources
list (each entry a plugin type plus its options), and the outputs list
(each entry an adapter type plus its options), their defaults, the
validation rules applied to operator-supplied values, and the immutable
Config record the build pipeline reads. Target schema:
docs/extractium-spec.md section 12.

This file is part of Extractium™
extractium/config.py

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

import pathlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import urlparse

import yaml

# The default User-Agent is owned by the fetch layer that sends it;
# re-exported here so the settings documentation has one name for it.
from extractium.core.fetch import DEFAULT_USER_AGENT


### Global Defaults ###

# Folder every adapter writes under. A relative path resolves against the
# working directory the build runs from, so one config file works the
# same on a laptop and on a CI runner.
DEFAULT_OUT_DIR = "dist"

# Folder for fetched pages and their validators between builds.
DEFAULT_CACHE_DIR = ".kb_cache"

# Safety ceiling for one crawl, so an over-broad include pattern cannot
# walk an entire public website.
DEFAULT_MAX_PAGES = 10000

# Polite pause between requests, in seconds. 0 disables the pause.
DEFAULT_DELAY_SECONDS = 0.5

# robots.txt is honored unless the operator switches it off for a site
# they own.
DEFAULT_RESPECT_ROBOTS_TXT = True

# Which content the PHI lint scans: local sources only, everything, or
# nothing. Local content is the default because it is the content that
# was never published.
PHI_LINT_MODES = ("local", "all", "off")
DEFAULT_PHI_LINT = "local"

# Outputs written when the file lists none: the flagship container and
# the two llms.txt files.
DEFAULT_OUTPUTS = ({"type": "container"}, {"type": "llmstxt"})

# File names the container and SQLite adapters write when none is given.
DEFAULT_CONTAINER_FILE = "kb-index.json"
DEFAULT_SQLITE_FILE = "compendium.sqlite"

# Files a local source reads when no include_globs are given. PDF and
# Office formats need extra dependencies and are not read.
DEFAULT_LOCAL_INCLUDE_GLOBS = ("**/*.md", "**/*.txt", "**/*.html")

# Caption languages a YouTube source asks for when none are given.
DEFAULT_YOUTUBE_LANGUAGES = ("en",)

# An empty include list is meaningful, not missing: the crawler then scopes
# itself to the seed URL's origin, or, for a TeamDynamix portal URL, to its
# /TDClient/<digits>/<slug>/ prefix. See
# extractium.core.fetch.derive_auto_prefix.
DEFAULT_INCLUDE_PATTERNS = ()

# Only these URL schemes may seed a crawl. Anything else (file:, ftp:,
# data:, javascript:) is refused rather than filtered later: a file: seed
# would pull local disk content into an index whose web-facing outputs
# assume every page in it was already published on the web.
ALLOWED_SEED_SCHEMES = ("http", "https")

# A plugin type is a short identifier: letters, digits, and underscores.
TYPE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


### Default Exclude Patterns ###

# An omitted exclude list is stored as None and completed by the web
# source at crawl time: the host-independent asset patterns
# (extractium.core.fetch.ASSET_EXCLUDE_PATTERNS) plus the patterns each
# enabled site handler contributes. The default depends on which
# handlers are enabled, so it cannot be filled in here. An explicit list,
# including an empty one, is used exactly as written.
DEFAULT_CRAWL_EXCLUDE_PATTERNS = None
DEFAULT_INDEX_EXCLUDE_PATTERNS = None


### Allowed Keys ###

# Every top-level key a configuration file may contain. Anything else is
# refused: silently ignoring an unrecognized key turns a typo such as
# "max_page" into a crawl that quietly runs with the wrong ceiling.
KNOWN_KEYS = frozenset({
    "name",
    "out_dir",
    "cache_dir",
    "max_pages",
    "delay_seconds",
    "user_agent",
    "respect_robots_txt",
    "phi_lint",
    "sources",
    "outputs",
})

# Option keys per built-in source type, beyond "type" itself. A type not
# listed here belongs to a plugin, and its options are passed through for
# that plugin to check.
SOURCE_OPTION_KEYS = {
    "web": frozenset({
        "seed_url", "include_patterns", "crawl_exclude_patterns",
        "index_exclude_patterns", "site_handlers",
    }),
    "local": frozenset({"path", "include_globs"}),
    "github_api": frozenset({"org"}),
    "youtube": frozenset({"channel_id", "playlist_ids", "video_ids", "languages"}),
}

# Option keys per built-in output type, beyond "type" and "include_local",
# which every output accepts.
OUTPUT_OPTION_KEYS = {
    "container": frozenset({"file"}),
    "llmstxt": frozenset(),
    "sqlite": frozenset({"file"}),
    "okf": frozenset(),
}


class ConfigError(Exception):
    """
    Raised when a configuration file cannot be read, is not valid YAML, or
    holds a value the build cannot safely act on. The message names the
    configuration source and the offending setting, and is safe to show a
    user: it quotes only values that user supplied.
    """


### Configuration Records ###

@dataclass(frozen=True)
class SourceConfig:
    """
    One entry of the sources list.

    Attributes:
        type (str): registry name of the source plugin.
        options (Mapping): the entry's validated options, read-only. For a
            built-in type every option is present with its default filled
            in; for a plugin type the options are as written.
    """

    type: str
    options: Mapping


@dataclass(frozen=True)
class OutputConfig:
    """
    One entry of the outputs list.

    Attributes:
        type (str): registry name of the adapter plugin.
        include_local (bool): whether this output may contain parents
            from local sources. False by default for every output.
        options (Mapping): the entry's remaining validated options,
            read-only.
    """

    type: str
    include_local: bool
    options: Mapping


@dataclass(frozen=True)
class Config:
    """
    One validated Extractium build configuration.

    Immutable, and holding tuples and read-only mappings rather than
    lists and dicts, so no build step can accidentally mutate settings
    shared with another step or with the module-level defaults.

    Attributes:
        name (str | None): display name of the knowledge base; None means
            "use the title of the first crawled page".
        out_dir (str): folder every adapter writes under.
        cache_dir (str): folder for the fetch cache.
        max_pages (int): hard ceiling on pages visited in one crawl; 1 or more.
        delay_seconds (float): pause between requests, in seconds; 0 or more.
        user_agent (str): the User-Agent header the crawler sends.
        respect_robots_txt (bool): whether robots.txt disallow rules are honored.
        phi_lint (str): one of PHI_LINT_MODES.
        sources (tuple[SourceConfig, ...]): at least one source, in file order.
        outputs (tuple[OutputConfig, ...]): at least one output, in file order.
    """

    sources: tuple
    outputs: tuple
    name: object = None
    out_dir: str = DEFAULT_OUT_DIR
    cache_dir: str = DEFAULT_CACHE_DIR
    max_pages: int = DEFAULT_MAX_PAGES
    delay_seconds: float = DEFAULT_DELAY_SECONDS
    user_agent: str = DEFAULT_USER_AGENT
    respect_robots_txt: bool = DEFAULT_RESPECT_ROBOTS_TXT
    phi_lint: str = DEFAULT_PHI_LINT


### Validate Settings ###

def _fail(source, message):
    """Raises a ConfigError naming the configuration source and the problem."""
    raise ConfigError(f"{source}: {message}")


def _is_missing(value):
    """
    True when a setting was absent, or written with no value at all
    (`max_pages:` alone on a line parses as None). Both mean "use the
    default", which keeps a configuration file short. An explicitly empty
    list is NOT missing: that is how an operator turns a default list off.
    """
    return value is None


def _check_known_keys(data, known, source):
    """Raises ConfigError naming any key of data that is not in known."""
    unknown = sorted(str(k) for k in data if k not in known)
    if unknown:
        _fail(
            source,
            f"unrecognized setting(s): {', '.join(unknown)}. "
            f"Known settings are: {', '.join(sorted(known))}.",
        )


def _read_text(data, key, default, source):
    """
    Reads an optional non-blank text setting.

    Args:
        data (Mapping): the raw configuration mapping.
        key (str): setting name.
        default (str | None): value used when the setting is absent.
        source (str): configuration source, for error messages.

    Returns:
        str | None: the supplied value, stripped of surrounding
        whitespace, or the default.

    Raises:
        ConfigError: if the value is not text, or is blank.
    """
    value = data.get(key)
    if _is_missing(value):
        return default
    if not isinstance(value, str):
        _fail(source, f"{key} must be text, not {type(value).__name__}.")
    value = value.strip()
    if not value:
        hint = f" Remove the setting to use the default ({default})." if default is not None else ""
        _fail(source, f"{key} cannot be blank.{hint}")
    return value


def _read_required_text(data, key, source, hint=""):
    """
    Reads a required non-blank text setting.

    Raises:
        ConfigError: if the value is absent, not text, or blank.
    """
    if _is_missing(data.get(key)):
        _fail(source, f"{key} is required{hint}.")
    return _read_text(data, key, None, source)


def _read_url(data, key, source, hint=""):
    """
    Reads a required absolute http or https URL.

    Raises:
        ConfigError: if the value is absent, blank, not text, missing a
            host name, or uses a scheme other than http or https.
    """
    value = _read_required_text(data, key, source, hint)
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ALLOWED_SEED_SCHEMES:
        _fail(
            source,
            f"{key} must start with http:// or https:// "
            f"(got {parsed.scheme.lower() or 'no scheme'}).",
        )
    if not parsed.netloc:
        _fail(source, f"{key} must include a host name, for example https://example.edu/kb/.")
    return value


def _read_positive_int(data, key, default, source):
    """
    Reads an optional whole-number setting that must be greater than zero.
    Booleans are refused even though Python counts them as integers:
    `max_pages: true` is a mistake, not a ceiling of one page.

    Raises:
        ConfigError: if the value is not a whole number, or is below 1.
    """
    value = data.get(key)
    if _is_missing(value):
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(source, f"{key} must be a whole number, not {type(value).__name__}.")
    if value < 1:
        _fail(source, f"{key} must be 1 or greater (got {value}).")
    return value


def _read_non_negative_number(data, key, default, source):
    """
    Reads an optional numeric setting that must be zero or greater.

    Raises:
        ConfigError: if the value is not a number, or is negative.
    """
    value = data.get(key)
    if _is_missing(value):
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(source, f"{key} must be a number, not {type(value).__name__}.")
    if value < 0:
        _fail(source, f"{key} cannot be negative (got {value}).")
    return float(value)


def _read_bool(data, key, default, source):
    """
    Reads an optional true/false setting. Only real booleans are accepted:
    the strings "yes" and "no" are refused rather than guessed at.

    Raises:
        ConfigError: if the value is not a boolean.
    """
    value = data.get(key)
    if _is_missing(value):
        return default
    if not isinstance(value, bool):
        _fail(source, f"{key} must be true or false, not {type(value).__name__}.")
    return value


def _read_choice(data, key, default, allowed, source):
    """
    Reads an optional text setting that must be one of a fixed set.

    Raises:
        ConfigError: if the value is not one of the allowed values.
    """
    value = _read_text(data, key, default, source)
    if value not in allowed:
        _fail(source, f"{key} must be one of {', '.join(sorted(allowed))} (got {value!r}).")
    return value


def _read_text_list(data, key, default, source, label="names"):
    """
    Reads an optional list of non-blank strings.

    An absent setting yields the default. An explicitly empty list yields
    an empty tuple.

    Raises:
        ConfigError: if the value is not a list, or holds a non-text or
            blank entry.
    """
    value = data.get(key)
    if _is_missing(value):
        return default
    # To a person, one string is a list of one entry; to Python it is a
    # list of single characters. Refuse it with an explanation.
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail(
            source,
            f"{key} must be a list of {label}, not {type(value).__name__}. "
            "Write a single entry as a one-item list.",
        )
    entries = []
    for position, entry in enumerate(value, start=1):
        if not isinstance(entry, str):
            _fail(source, f"{key} entry {position} must be text, not {type(entry).__name__}.")
        if not entry.strip():
            _fail(source, f"{key} entry {position} is blank.")
        entries.append(entry)
    return tuple(entries)


def _read_patterns(data, key, default, source):
    """
    Reads an optional list of regular expressions, each matched
    case-insensitively against a whole URL.

    Raises:
        ConfigError: if the list is malformed, or an entry is not a valid
            regular expression.
    """
    patterns = _read_text_list(data, key, default, source, label="patterns")
    if patterns is None:
        return None
    for position, entry in enumerate(patterns, start=1):
        try:
            re.compile(entry, re.IGNORECASE)
        except re.error as e:
            _fail(
                source,
                f"{key} entry {position} is not a valid regular expression: {entry!r} ({e}).",
            )
    return patterns


def _read_output_file(data, key, default, source):
    """
    Reads an optional output file name, which must stay under out_dir.

    Every adapter writes under out_dir. An absolute path, or one that
    climbs out with "..", could overwrite a file anywhere on the disk, so
    both are refused.

    Raises:
        ConfigError: if the value is not text, is blank, or escapes out_dir.
    """
    value = _read_text(data, key, default, source)
    path = pathlib.PureWindowsPath(value) if "\\" in value or re.match(r"^[A-Za-z]:", value) else pathlib.PurePosixPath(value)
    if path.is_absolute() or path.drive or ".." in path.parts:
        _fail(source, f"{key} must be a relative path inside out_dir, without '..' (got {value!r}).")
    return value


### Validate Sources ###

def _read_type(entry, source):
    """Reads and validates the type key of a sources or outputs entry."""
    if _is_missing(entry.get("type")):
        _fail(source, "type is required.")
    type_name = _read_text(entry, "type", None, source)
    if not TYPE_NAME_RE.match(type_name):
        _fail(source, f"type must be a short name of letters, digits, and underscores (got {type_name!r}).")
    return type_name


def _read_web_source(entry, source):
    """Validates the options of a web source entry."""
    return {
        "seed_url": _read_url(entry, "seed_url", source, hint=" (the URL the crawl starts from)"),
        "include_patterns": _read_patterns(entry, "include_patterns", DEFAULT_INCLUDE_PATTERNS, source),
        # None for either exclude list means "asset patterns plus the
        # enabled handlers' defaults", completed by the web source.
        "crawl_exclude_patterns": _read_patterns(
            entry, "crawl_exclude_patterns", DEFAULT_CRAWL_EXCLUDE_PATTERNS, source
        ),
        "index_exclude_patterns": _read_patterns(
            entry, "index_exclude_patterns", DEFAULT_INDEX_EXCLUDE_PATTERNS, source
        ),
        # None means "every installed handler"; an empty tuple means "the
        # generic fallback only".
        "site_handlers": _read_text_list(entry, "site_handlers", None, source),
    }


def _read_local_source(entry, source):
    """Validates the options of a local source entry."""
    return {
        "path": _read_required_text(entry, "path", source, hint=" (the folder to read)"),
        "include_globs": _read_text_list(
            entry, "include_globs", DEFAULT_LOCAL_INCLUDE_GLOBS, source, label="glob patterns"
        ),
    }


def _read_github_api_source(entry, source):
    """Validates the options of a github_api source entry."""
    return {"org": _read_required_text(entry, "org", source, hint=" (the organization to list)")}


def _read_youtube_source(entry, source):
    """Validates the options of a youtube source entry."""
    options = {
        "channel_id": _read_text(entry, "channel_id", None, source),
        "playlist_ids": _read_text_list(entry, "playlist_ids", (), source, label="ids"),
        "video_ids": _read_text_list(entry, "video_ids", (), source, label="ids"),
        "languages": _read_text_list(entry, "languages", DEFAULT_YOUTUBE_LANGUAGES, source, label="language codes"),
    }
    if not (options["channel_id"] or options["playlist_ids"] or options["video_ids"]):
        _fail(source, "give at least one of channel_id, playlist_ids, video_ids.")
    return options


_SOURCE_READERS = {
    "web": _read_web_source,
    "local": _read_local_source,
    "github_api": _read_github_api_source,
    "youtube": _read_youtube_source,
}


def _read_sources(data, source):
    """
    Validates the sources list.

    Returns:
        tuple[SourceConfig, ...]: one record per entry, in file order.

    Raises:
        ConfigError: if the list is absent, empty, not a list, or an entry
            is malformed. Messages name the entry position and type.
    """
    value = data.get("sources")
    if _is_missing(value):
        _fail(source, "sources is required (a list with at least one source, such as a web seed URL).")
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        _fail(source, f"sources must be a list, not {type(value).__name__}.")
    if not value:
        _fail(source, "sources must list at least one source.")

    sources = []
    for position, entry in enumerate(value, start=1):
        label = f"{source}: sources entry {position}"
        if not isinstance(entry, Mapping):
            raise ConfigError(f"{label} must be a mapping with a type, not {type(entry).__name__}.")
        type_name = _read_type(entry, label)
        label = f"{label} ({type_name})"
        options = {k: v for k, v in entry.items() if k != "type"}
        reader = _SOURCE_READERS.get(type_name)
        if reader is not None:
            _check_known_keys(options, SOURCE_OPTION_KEYS[type_name], label)
            options = reader(entry, label)
        sources.append(SourceConfig(type=type_name, options=MappingProxyType(options)))
    return tuple(sources)


### Validate Outputs ###

def _read_container_output(entry, source):
    return {"file": _read_output_file(entry, "file", DEFAULT_CONTAINER_FILE, source)}


def _read_sqlite_output(entry, source):
    return {"file": _read_output_file(entry, "file", DEFAULT_SQLITE_FILE, source)}


def _read_no_options(entry, source):
    return {}


_OUTPUT_READERS = {
    "container": _read_container_output,
    "llmstxt": _read_no_options,
    "sqlite": _read_sqlite_output,
    "okf": _read_no_options,
}


def _read_outputs(data, source):
    """
    Validates the outputs list, or supplies the default outputs.

    Returns:
        tuple[OutputConfig, ...]: one record per entry, in file order.

    Raises:
        ConfigError: if the list is empty, not a list, or an entry is
            malformed. Messages name the entry position and type.
    """
    value = data.get("outputs")
    if _is_missing(value):
        value = DEFAULT_OUTPUTS
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        _fail(source, f"outputs must be a list, not {type(value).__name__}.")
    if not value:
        _fail(source, "outputs must list at least one output. Remove the setting to write the defaults.")

    outputs = []
    for position, entry in enumerate(value, start=1):
        label = f"{source}: outputs entry {position}"
        if not isinstance(entry, Mapping):
            raise ConfigError(f"{label} must be a mapping with a type, not {type(entry).__name__}.")
        type_name = _read_type(entry, label)
        label = f"{label} ({type_name})"
        include_local = _read_bool(entry, "include_local", False, label)
        options = {k: v for k, v in entry.items() if k not in ("type", "include_local")}
        reader = _OUTPUT_READERS.get(type_name)
        if reader is not None:
            _check_known_keys(options, OUTPUT_OPTION_KEYS[type_name], label)
            options = reader(entry, label)
        outputs.append(
            OutputConfig(type=type_name, include_local=include_local, options=MappingProxyType(options))
        )
    return tuple(outputs)


### Build Configuration ###

def config_from_mapping(data, source="configuration"):
    """
    Validates an already-parsed configuration mapping and returns a Config.

    Every key is checked against KNOWN_KEYS first, so an unrecognized or
    misspelled setting stops the build instead of being ignored. Call this
    directly when the settings come from somewhere other than a YAML file
    (a test, or a caller that assembled them itself); call load_config for
    a file on disk.

    Args:
        data (Mapping): setting name -> value, as parsed from YAML.
        source (str): label used in error messages, usually a file path.

    Returns:
        Config: the validated, immutable configuration.

    Raises:
        ConfigError: if data is not a mapping, holds an unknown key, or
            holds a value that fails validation.
    """
    if not isinstance(data, Mapping):
        _fail(source, f"settings must be a mapping of key: value pairs, not {type(data).__name__}.")

    if "seed_url" in data:
        _fail(
            source,
            "seed_url belongs inside a sources entry: write\n"
            "  sources:\n    - type: web\n      seed_url: https://...",
        )
    _check_known_keys(data, KNOWN_KEYS, source)

    user_agent = _read_text(data, "user_agent", DEFAULT_USER_AGENT, source)
    # A line break in a header value would end the header and let the
    # file inject further request headers.
    if "\n" in user_agent or "\r" in user_agent:
        _fail(source, "user_agent cannot contain line breaks.")

    return Config(
        name=_read_text(data, "name", None, source),
        out_dir=_read_text(data, "out_dir", DEFAULT_OUT_DIR, source),
        cache_dir=_read_text(data, "cache_dir", DEFAULT_CACHE_DIR, source),
        max_pages=_read_positive_int(data, "max_pages", DEFAULT_MAX_PAGES, source),
        delay_seconds=_read_non_negative_number(
            data, "delay_seconds", DEFAULT_DELAY_SECONDS, source
        ),
        user_agent=user_agent,
        respect_robots_txt=_read_bool(data, "respect_robots_txt", DEFAULT_RESPECT_ROBOTS_TXT, source),
        phi_lint=_read_choice(data, "phi_lint", DEFAULT_PHI_LINT, PHI_LINT_MODES, source),
        sources=_read_sources(data, source),
        outputs=_read_outputs(data, source),
    )


### Load Configuration ###

def load_config(path, overrides=None):
    """
    Reads, parses, and validates a configuration file.

    The file is parsed with yaml.safe_load, which understands plain YAML
    data only and never constructs arbitrary Python objects, so a
    configuration file cannot run code.

    Args:
        path (str): path to the YAML configuration file.
        overrides (Mapping | None): top-level settings that win over the
            file's own, keyed the same way (command-line arguments, for
            example). Entries whose value is None are ignored, so an
            argument the user did not supply leaves the file's value in
            place.

    Returns:
        Config: the validated, immutable configuration.

    Raises:
        ConfigError: if the file cannot be read, is not valid YAML, is not
            a mapping, or holds a value that fails validation.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except OSError as e:
        _fail(path, f"configuration file cannot be read ({e.strerror or e}).")
    except yaml.YAMLError as e:
        _fail(path, f"configuration file is not valid YAML ({e}).")

    # An empty file parses to None. Treat that as "no settings supplied",
    # so the error names the setting the operator actually has to add.
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        _fail(path, f"file must hold a mapping of key: value pairs, not {type(raw).__name__}.")

    if overrides:
        raw = {**raw, **{k: v for k, v in overrides.items() if v is not None}}

    return config_from_mapping(raw, source=path)
