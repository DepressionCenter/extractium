"""
Summary: Configuration schema for an Extractium build. Defines the allowed
keys of an organization's config.yaml, their defaults, the validation rules
applied to operator-supplied values, and the immutable Config record the
build pipeline reads. This replaces the block of module-level constants an
operator used to edit inside the original single-file build script.

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

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

import yaml

# Imported for BINARY_EXTENSIONS / SOURCE_EXTENSIONS, from which the
# default exclude patterns below are derived. Deriving them here, instead
# of retyping the extension list, keeps the crawl-scope asset check in
# extractium.core.fetch and these operator-visible exclude lists from
# drifting apart.
from extractium.core import fetch


### Defaults ###

# Where the binary-container index is written. A relative path resolves
# against the working directory the build runs from, so one config file
# works the same on a laptop and on a CI runner.
# TODO: the OKF, llms.txt, and SQLite adapters each write their own
# artifact and will need their own output settings (or one output
# directory shared by every adapter) once those adapters exist.
DEFAULT_OUT_PATH = "dist/kb-index.json"

# Safety ceiling for one crawl, so an over-broad include pattern cannot
# walk an entire public website.
DEFAULT_MAX_PAGES = 10000

# Polite pause between requests, in seconds. 0 disables the pause.
DEFAULT_DELAY_SECONDS = 0.5

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

# Non-content pages common to knowledge-base portals and code-hosting
# sites: search forms, logins, print views, tag listings, and the
# repository housekeeping views (issues, commits, settings, and the like)
# that hold no documentation. Excluded from both crawling and indexing.
_COMMON_EXCLUDE_PATTERNS = (
    r"/Search[/?$]",
    r"/Login[/?$]",
    r"/Login\.aspx",
    r"/Tags[/?$]",
    r"/Print[/?$]",
    r"/PrintArticle\?ID=",
    r"\?print=",
    r"/Archive[/?$]",
    r"/FileOpen[/?$]",
    r"/FileDownload[/?$]",
    r"/pulse$",
    r"/tags$",
    r"/tagged$",
    r"/TagID=",
    r"/TagID/[0-9]+",
    r"&tab=",
    r"/issues?[/?]",
    r"/projects?[/?]",
    r"/pulls?[/?]",
    r"/pushes?[/?]",
    r"/forks?[/?]",
    r"/network[/?]",
    r"/commits?[/?]",
    r"/discussions?[/?]",
    r"/categories[/?]",
    r"/announcements?[/?]",
    r"/settings[/?]",
    r"/contribs?[/?]",
    r"/contributions?[/?]",
    r"/checks?[/?]",
    r"/comments?[/?]",
    r"/author[/?]",
    r"/profile[/?]",
    r"/watchers[/?]",
    r"/stargazers[/?]",
    r"/stars[/?]",
    r"/graphs[/?]",         # contributors, commit-activity, code-frequency, punch-card, traffic
    r"/actions[/?]",        # CI workflow runs
    r"/security[/?]",       # security advisories -- not KB content; /releases stays indexable
    r"/compare[/?]",
    r"/blame/",
    r"/raw/",               # Markdown and text file bodies are fetched from the raw content
                            # host instead (see extractium.core.fetch is_git_blob_text_url /
                            # to_git_raw_url), so this only avoids re-crawling the redirect
                            # URL when a page happens to link to it.
    r"/find/",
    r"/deployments[/?]",
    r"/environments[/?]",
    r"/packages[/?]",
    r"/sponsors[/?]",
    r"/people[/?]",
    r"/followers[/?]",
    r"/following[/?]",
    # Wiki housekeeping actions (edit form, revision history, new-page
    # draft, access settings) -- not real content.
    r"/_edit$",
    r"/_history$",
    r"/_new$",
    r"/_access$",
)

# Navigation-only pages: worth following, because they link to real
# articles, but holding no content of their own worth indexing.
_INDEX_ONLY_EXCLUDE_PATTERNS = (
    r"/CategoryID=",
    r"/CategoryID/[0-9]+",
    r"/Category/",
    r"/tree/",              # directory listings -- pure navigation, no server-rendered content
)

# Files whose bytes are not indexable text. Order within an exclude list
# carries no meaning: a URL is excluded when any one pattern matches it.
_ASSET_EXTENSION_PATTERNS = tuple(
    rf"\.{ext}$" for ext in fetch.BINARY_EXTENSIONS + fetch.SOURCE_EXTENSIONS
)

DEFAULT_CRAWL_EXCLUDE_PATTERNS = _COMMON_EXCLUDE_PATTERNS + _ASSET_EXTENSION_PATTERNS
DEFAULT_INDEX_EXCLUDE_PATTERNS = (
    _COMMON_EXCLUDE_PATTERNS + _INDEX_ONLY_EXCLUDE_PATTERNS + _ASSET_EXTENSION_PATTERNS
)

# Every key an Extractium configuration file may contain. Anything else is
# refused: silently ignoring an unrecognized key turns a typo such as
# "max_page" into a crawl that quietly runs with the wrong ceiling.
KNOWN_KEYS = frozenset({
    "seed_url",
    "out_path",
    "max_pages",
    "delay_seconds",
    "include_patterns",
    "crawl_exclude_patterns",
    "index_exclude_patterns",
})


class ConfigError(Exception):
    """
    Raised when a configuration file cannot be read, is not valid YAML, or
    holds a value the build cannot safely act on. The message names the
    configuration source and the offending setting, and is safe to show a
    user: it quotes only values that user supplied.
    """


### Configuration Record ###

@dataclass(frozen=True)
class Config:
    """
    One validated Extractium build configuration.

    Immutable, and holding tuples rather than lists, so no build step can
    accidentally mutate settings shared with another step or with the
    module-level defaults.

    Attributes:
        seed_url (str): URL the crawl starts from. Always http or https.
        out_path (str): file path the binary-container index is written to.
        max_pages (int): hard ceiling on pages visited in one crawl; 1 or more.
        delay_seconds (float): pause between requests, in seconds; 0 or more.
        include_patterns (tuple[str, ...]): case-insensitive regular
            expressions; a URL must match at least one to be crawled. Empty
            means "scope automatically to the seed URL's prefix".
        crawl_exclude_patterns (tuple[str, ...]): case-insensitive regular
            expressions; a matching URL is never fetched. Checked after the
            include patterns, so an exclusion always wins.
        index_exclude_patterns (tuple[str, ...]): case-insensitive regular
            expressions; a matching URL is still fetched, and its links are
            still followed, but its content stays out of the index.
    """

    seed_url: str
    out_path: str = DEFAULT_OUT_PATH
    max_pages: int = DEFAULT_MAX_PAGES
    delay_seconds: float = DEFAULT_DELAY_SECONDS
    include_patterns: tuple = DEFAULT_INCLUDE_PATTERNS
    crawl_exclude_patterns: tuple = DEFAULT_CRAWL_EXCLUDE_PATTERNS
    index_exclude_patterns: tuple = DEFAULT_INDEX_EXCLUDE_PATTERNS


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


def _read_text(data, key, default, source):
    """
    Reads an optional non-blank text setting.

    Args:
        data (Mapping): the raw configuration mapping.
        key (str): setting name.
        default (str): value used when the setting is absent.
        source (str): configuration source, for error messages.

    Returns:
        str: the supplied value, stripped of surrounding whitespace, or the
        default.

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
        _fail(source, f"{key} cannot be blank. Remove the setting to use the default ({default}).")
    return value


def _read_seed_url(data, source):
    """
    Reads and validates the required seed_url setting.

    Args:
        data (Mapping): the raw configuration mapping.
        source (str): configuration source, for error messages.

    Returns:
        str: an absolute http or https URL.

    Raises:
        ConfigError: if seed_url is absent, blank, not text, missing a host
            name, or uses a scheme other than http or https.
    """
    value = data.get("seed_url")
    if _is_missing(value):
        _fail(source, "seed_url is required (the URL the crawl starts from).")
    if not isinstance(value, str):
        _fail(source, f"seed_url must be text, not {type(value).__name__}.")
    value = value.strip()
    if not value:
        _fail(source, "seed_url cannot be blank.")
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ALLOWED_SEED_SCHEMES:
        _fail(
            source,
            "seed_url must start with http:// or https:// "
            f"(got {parsed.scheme.lower() or 'no scheme'}).",
        )
    if not parsed.netloc:
        _fail(source, "seed_url must include a host name, for example https://example.edu/kb/.")
    return value


def _read_positive_int(data, key, default, source):
    """
    Reads an optional whole-number setting that must be greater than zero.
    Booleans are refused even though Python counts them as integers:
    `max_pages: true` is a mistake, not a ceiling of one page.

    Args:
        data (Mapping): the raw configuration mapping.
        key (str): setting name.
        default (int): value used when the setting is absent.
        source (str): configuration source, for error messages.

    Returns:
        int: the validated value, or the default.

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

    Args:
        data (Mapping): the raw configuration mapping.
        key (str): setting name.
        default (float): value used when the setting is absent.
        source (str): configuration source, for error messages.

    Returns:
        float: the validated value, or the default.

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


def _read_patterns(data, key, default, source):
    """
    Reads an optional list of regular expressions, each matched
    case-insensitively against a whole URL.

    An absent setting yields the default list. An explicitly empty list
    yields an empty tuple, which is how an operator switches a default
    list off.

    Args:
        data (Mapping): the raw configuration mapping.
        key (str): setting name.
        default (tuple[str, ...]): value used when the setting is absent.
        source (str): configuration source, for error messages.

    Returns:
        tuple[str, ...]: the validated patterns, or the default.

    Raises:
        ConfigError: if the value is not a list, holds a non-text or blank
            entry, or holds an entry that is not a valid regular
            expression.
    """
    value = data.get(key)
    if _is_missing(value):
        return default
    # To a person, one string is a list of one pattern; to Python it is a
    # list of single characters. Refuse it with an explanation instead of
    # crawling with dozens of one-character patterns.
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail(
            source,
            f"{key} must be a list of patterns, not {type(value).__name__}. "
            "Write a single pattern as a one-item list.",
        )
    patterns = []
    for position, entry in enumerate(value, start=1):
        if not isinstance(entry, str):
            _fail(source, f"{key} entry {position} must be text, not {type(entry).__name__}.")
        if not entry.strip():
            _fail(source, f"{key} entry {position} is blank.")
        try:
            re.compile(entry, re.IGNORECASE)
        except re.error as e:
            _fail(
                source,
                f"{key} entry {position} is not a valid regular expression: {entry!r} ({e}).",
            )
        patterns.append(entry)
    return tuple(patterns)


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

    unknown = sorted(str(k) for k in data if k not in KNOWN_KEYS)
    if unknown:
        _fail(
            source,
            f"unrecognized setting(s): {', '.join(unknown)}. "
            f"Known settings are: {', '.join(sorted(KNOWN_KEYS))}.",
        )

    return Config(
        seed_url=_read_seed_url(data, source),
        out_path=_read_text(data, "out_path", DEFAULT_OUT_PATH, source),
        max_pages=_read_positive_int(data, "max_pages", DEFAULT_MAX_PAGES, source),
        delay_seconds=_read_non_negative_number(
            data, "delay_seconds", DEFAULT_DELAY_SECONDS, source
        ),
        include_patterns=_read_patterns(
            data, "include_patterns", DEFAULT_INCLUDE_PATTERNS, source
        ),
        crawl_exclude_patterns=_read_patterns(
            data, "crawl_exclude_patterns", DEFAULT_CRAWL_EXCLUDE_PATTERNS, source
        ),
        index_exclude_patterns=_read_patterns(
            data, "index_exclude_patterns", DEFAULT_INDEX_EXCLUDE_PATTERNS, source
        ),
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
        overrides (Mapping | None): settings that win over the file's own,
            keyed the same way (command-line arguments, for example).
            Entries whose value is None are ignored, so an argument the
            user did not supply leaves the file's value in place.

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
