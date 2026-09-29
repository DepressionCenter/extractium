"""
Summary: The settings file as the local page sees it. Describes every
setting the form shows, with its kind, its default, and its help text,
so the page builds the form from one description and never guesses.
Reads the file into the shape the form edits, turns a saved form back
into a file that holds only what differs from the defaults, and writes
either the form or the file's own text through the settings loader, so
a value the loader would refuse is refused here with the same message.
A save keeps the previous file beside the new one with a date stamp.
The welcome screen's first file is written through the `init` module
with the outputs the page relies on switched on.

This file is part of Extractium™
extractium/ui/settings.py

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

import copy
import os
import pathlib
import tempfile
from collections.abc import Mapping

import yaml

from extractium import init as init_module
from extractium.config import (
    COMMON_SOURCE_KEYS,
    DEFAULT_CACHE_DIR,
    DEFAULT_DELAY_SECONDS,
    DEFAULT_DSPACE_INCLUDE_FULL_TEXT,
    DEFAULT_DSPACE_MAX_FILE_BYTES,
    DEFAULT_GITHUB_CTAGS_FALLBACK,
    DEFAULT_GITHUB_INCLUDE_ARCHIVED,
    DEFAULT_GITHUB_INCLUDE_CODE,
    DEFAULT_GITHUB_INCLUDE_FORKS,
    DEFAULT_GITHUB_MAX_FILE_BYTES,
    DEFAULT_GITHUB_MAX_FILES_PER_REPOSITORY,
    DEFAULT_GITHUB_MAX_REPOSITORIES,
    DEFAULT_KEYWORDS,
    DEFAULT_LOCAL_INCLUDE_GLOBS,
    DEFAULT_MAX_PAGES,
    DEFAULT_OUT_DIR,
    DEFAULT_OUTPUTS,
    DEFAULT_PARALLEL_PAGES,
    DEFAULT_PARALLEL_SOURCES,
    DEFAULT_PHI_LINT,
    DEFAULT_READ_DOCUMENTS,
    DEFAULT_REBUILD,
    DEFAULT_RESPECT_ROBOTS_TXT,
    DEFAULT_RUNS_DIR,
    DEFAULT_SLUG,
    DEFAULT_TRANSPORT,
    DEFAULT_USER_AGENT,
    DEFAULT_YOUTUBE_AUDIO_FALLBACK,
    DEFAULT_YOUTUBE_INCLUDE_PLAYLISTS,
    DEFAULT_YOUTUBE_LANGUAGES,
    DEFAULT_YOUTUBE_ONLY_CHANNEL_VIDEOS,
    PHI_LINT_MODES,
    REBUILD_MODES,
    TRANSPORT_MODES,
    ConfigError,
    config_from_mapping,
    load_config,
)
from extractium.core.build import utc_now

### Constants ###

# The outputs the page's first settings file switches on. The compressed
# container is what the search clients and Field Station AI read, and
# the Open Knowledge Format folder holds one Markdown file per page,
# which is what the page shows when a search result is opened. The
# terminal `init` command keeps the loader's own defaults.
PAGE_OUTPUTS = (
    {"type": "container", "gzip": True},
    {"type": "llmstxt"},
    {"type": "okf"},
)

# The comment at the top of a file the form writes. The form keeps no
# comment a person wrote, so the file says where the explanations are.
FILE_HEADER = (
    "# Extractium build settings. Every setting is explained in the\n"
    "# configuration reference: docs/configuration.md in the Extractium\n"
    "# repository. Keys and API tokens never go in this file.\n"
    "\n"
)

# The ending of a kept copy of the previous file. The date stamp is the
# time of the save in UTC, with the colons Windows refuses replaced.
BACKUP_SUFFIX = ".bak"

# Kinds of field the form knows how to draw.
KIND_TEXT = "text"
KIND_INTEGER = "integer"
KIND_NUMBER = "number"
KIND_BOOLEAN = "boolean"
KIND_CHOICE = "choice"
KIND_LINES = "lines"


class SettingsError(Exception):
    """A settings file, or a form, that cannot be saved. The message is safe to show."""


### The Form's Description ###

def _field(key, kind, label, help_text, default=None, choices=None, required=False,
           empty_list=None, group=None):
    """
    One setting as the form draws it.

    Args:
        key (str): the setting's name in the file.
        kind (str): one of the KIND_ constants.
        label (str): what the form calls it.
        help_text (str): one or two sentences beside the field.
        default: the value the loader uses when the setting is absent.
            A form value equal to it is left out of the file.
        choices (Sequence[str] | None): the allowed values of a choice.
        required (bool): whether the loader refuses the setting absent.
        empty_list (str | None): for a list, what an explicitly empty
            list means when that differs from leaving the setting out.
        group (str | None): the heading the field is shown under.

    Returns:
        dict: the description, ready to be sent to the page as JSON.
    """
    field = {"key": key, "kind": kind, "label": label, "help": help_text, "default": default,
             "required": required}
    if choices is not None:
        field["choices"] = list(choices)
    if empty_list is not None:
        field["emptyList"] = empty_list
    if group is not None:
        field["group"] = group
    return field


GLOBAL_FIELDS = (
    _field("name", KIND_TEXT, "Name",
           "The display name of the compendium, recorded in every output. Leave it blank to use "
           "the title of the first page crawled.", group="About the compendium"),
    _field("slug", KIND_TEXT, "Short name",
           "The short name the output files are named after: <short name>.json.gz, "
           "<short name>-full.json.gz, and <short name>.sqlite. Lowercase letters, digits, and "
           "hyphens, up to 64 characters.", default=DEFAULT_SLUG, group="About the compendium"),
    _field("out_dir", KIND_TEXT, "Output folder",
           "The folder every output is written under. A relative path starts from the folder the "
           "build runs in.", default=DEFAULT_OUT_DIR, group="Folders"),
    _field("cache_dir", KIND_TEXT, "Cache folder",
           "Where fetched pages are kept between builds, so a rerun only downloads what changed. "
           "Name a visible folder, such as kb-cache, if the build reads YouTube, because part of "
           "it has to be committed.", default=DEFAULT_CACHE_DIR, group="Folders"),
    _field("runs_dir", KIND_TEXT, "Run records folder",
           "Where every build leaves its record: one JSON file per build, on success and on "
           "failure. A history for this machine; keep it out of git.",
           default=DEFAULT_RUNS_DIR, group="Folders"),
    _field("max_pages", KIND_INTEGER, "Most pages per source",
           "The most a source may read: web pages for a crawl, videos, deposits, or files for the "
           "other kinds. A small value makes a quick trial. Must be 1 or more.",
           default=DEFAULT_MAX_PAGES, group="Crawling"),
    _field("delay_seconds", KIND_NUMBER, "Seconds between requests",
           "The least time between two requests to the same site, so the crawl stays polite. "
           "0.8 is kinder to a shared server; 0 waits not at all.",
           default=DEFAULT_DELAY_SECONDS, group="Crawling"),
    _field("parallel_sources", KIND_INTEGER, "Sources read at the same time",
           "How many sources run at once. 1 runs them one after another with a plain log.",
           default=DEFAULT_PARALLEL_SOURCES, group="Crawling"),
    _field("parallel_pages", KIND_INTEGER, "Pages fetched at the same time",
           "How many page fetches one web crawl keeps in flight. A site is never asked faster "
           "than the seconds between requests allow.", default=DEFAULT_PARALLEL_PAGES,
           group="Crawling"),
    _field("user_agent", KIND_TEXT, "User agent",
           "How the crawler introduces itself to each site. The default names the tool and its "
           "repository.", default=DEFAULT_USER_AGENT, group="Crawling"),
    _field("respect_robots_txt", KIND_BOOLEAN, "Honor robots.txt",
           "Whether each site's robots.txt rules are followed. Switch it off only for sites you "
           "own.", default=DEFAULT_RESPECT_ROBOTS_TXT, group="Crawling"),
    _field("transport", KIND_CHOICE, "Connection style",
           "auto makes an ordinary request and, only when a site answers a bot-protection "
           "challenge, asks once more over a browser-shaped connection. browser starts that way; "
           "plain never does.", default=DEFAULT_TRANSPORT, choices=TRANSPORT_MODES,
           group="Crawling"),
    _field("github_owners", KIND_LINES, "Extra GitHub accounts",
           "GitHub accounts this build may follow links into, one per line, beyond the ones its "
           "sources name. Exact account names only.", default=[], group="Crawling"),
    _field("rebuild", KIND_CHOICE, "Pages not seen this time",
           "full publishes exactly what was read. incremental also keeps the pages of the last "
           "build that this one did not reach, unless the site confirmed them gone.",
           default=DEFAULT_REBUILD, choices=REBUILD_MODES, group="Building"),
    _field("phi_lint", KIND_CHOICE, "Check for protected health information",
           "Which content the check scans: local folders only, all content, or off. The report "
           "is written where the build runs and never copies what it found.",
           default=DEFAULT_PHI_LINT, choices=PHI_LINT_MODES, group="Building"),
    _field("keywords", KIND_BOOLEAN, "Name sections with keywords",
           "Whether every section is named with keywords and every page with tags, from the text "
           "alone. Needs the keywords extra; without it the build says so once and goes on.",
           default=DEFAULT_KEYWORDS, group="Building"),
)

# Every source carries these two, whatever its type.
SOURCE_COMMON_FIELDS = (
    _field("label", KIND_TEXT, "Label",
           "The name a reader sees for this source, such as Staff Handbook. Required, because two "
           "sources of the same type cannot be told apart without it. At most 60 characters.",
           required=True),
    _field("description", KIND_TEXT, "Description",
           "One or two sentences saying what this source is, shown beside its name in llms.txt. "
           "At most 400 characters."),
)

_PATTERN_HELP = ("Regular expressions, one per line, each matched against a whole address without "
                 "regard to case. Escape a dot as \\.")

SOURCE_TYPES = {
    "web": {
        "label": "Website",
        "help": "Crawls a website from the page you name, staying inside that site.",
        "fields": (
            _field("seed_urls", KIND_LINES, "Pages to start from",
                   "The page the crawl starts from, beginning with https:// or http://. For a "
                   "site whose sections do not link to one another, one address per line; it is "
                   "still one crawl.", required=True),
            _field("include_patterns", KIND_LINES, "Pages allowed",
                   "Pages the crawl may visit. Leave it empty to work the scope out from the "
                   "starting page. " + _PATTERN_HELP, default=[]),
            _field("leaf_patterns", KIND_LINES, "Single pages on other hosts",
                   "Pages on other hosts that this site links to, such as a shared Google file. "
                   "Each is fetched and indexed, and its own links are never followed. "
                   + _PATTERN_HELP, default=[]),
            _field("extra_crawl_exclude_patterns", KIND_LINES, "Pages never fetched",
                   "Added to the built-in list of pages the crawl must not fetch. The usual way "
                   "to keep one site's own navigation out. " + _PATTERN_HELP, default=[]),
            _field("extra_index_exclude_patterns", KIND_LINES, "Pages visited but not indexed",
                   "Added to the built-in list of pages the crawl may visit but whose content "
                   "stays out. Use it for menu and category pages. " + _PATTERN_HELP, default=[]),
            _field("crawl_exclude_patterns", KIND_LINES, "Replace the never-fetched list",
                   "Replaces the built-in list of pages the crawl must not fetch rather than "
                   "adding to it. Leave it empty to keep the built-in list. " + _PATTERN_HELP,
                   empty_list="switch the built-in list off"),
            _field("index_exclude_patterns", KIND_LINES, "Replace the not-indexed list",
                   "Replaces the built-in list of pages whose content stays out rather than "
                   "adding to it. Leave it empty to keep the built-in list. " + _PATTERN_HELP,
                   empty_list="switch the built-in list off"),
            _field("site_handlers", KIND_LINES, "Site handlers",
                   "Which site handlers take part, one name per line, such as tdx or github. "
                   "Leave it empty to use every installed handler.",
                   empty_list="use the generic handler only"),
            _field("read_documents", KIND_BOOLEAN, "Read document files",
                   "Whether a link to a Word, OpenDocument, RTF, PDF, or slide file is fetched "
                   "and its text indexed.", default=DEFAULT_READ_DOCUMENTS),
        ),
    },
    "local": {
        "label": "Folder on this computer",
        "help": "Reads Markdown, text, and HTML files from a folder. Its content stays out of "
                "every output unless that output allows local content.",
        "fields": (
            _field("path", KIND_TEXT, "Folder", "The folder to read.", required=True),
            _field("include_globs", KIND_LINES, "Files to read",
                   "Which files under the folder are read, one pattern per line. Leave it empty "
                   "for Markdown, text, and HTML files, plus document files when they are read.",
                   default=list(DEFAULT_LOCAL_INCLUDE_GLOBS)),
            _field("read_documents", KIND_BOOLEAN, "Read document files",
                   "Whether Word, OpenDocument, RTF, PDF, and slide files are read into text.",
                   default=DEFAULT_READ_DOCUMENTS),
        ),
    },
    "okf": {
        "label": "Knowledge bundle",
        "help": "Reads an Open Knowledge Format folder another build wrote, from this tool or any "
                "other.",
        "fields": (
            _field("path", KIND_TEXT, "Bundle folder", "The folder holding the bundle.",
                   required=True),
        ),
    },
    "github_api": {
        "label": "GitHub account or repository",
        "help": "Reads repositories through the GitHub API. Give exactly one of the organization, "
                "the user, or the address. A token in GITHUB_TOKEN raises the request limit and "
                "is never written here.",
        "fields": (
            _field("org", KIND_TEXT, "Organization", "A GitHub organization to read."),
            _field("user", KIND_TEXT, "User", "A GitHub user whose own repositories are read."),
            _field("url", KIND_TEXT, "Address",
                   "A GitHub address: an owner, or one repository."),
            _field("include_repos", KIND_LINES, "Repositories to read",
                   "Repository names, one per line. Leave it empty to read every one that "
                   "matches.", default=[]),
            _field("exclude_repos", KIND_LINES, "Repositories to leave out",
                   "Repository names, one per line. An exclusion always wins.", default=[]),
            _field("include_forks", KIND_BOOLEAN, "Read forks",
                   "Forks fill the index with near-identical copies, so they are left out unless "
                   "this is on.", default=DEFAULT_GITHUB_INCLUDE_FORKS),
            _field("include_archived", KIND_BOOLEAN, "Read archived repositories",
                   "Archived documentation is still documentation.",
                   default=DEFAULT_GITHUB_INCLUDE_ARCHIVED),
            _field("include_code", KIND_BOOLEAN, "Read the structure of the code",
                   "What each file defines, imports, and calls, written to the sqlite and okf "
                   "outputs only.", default=DEFAULT_GITHUB_INCLUDE_CODE),
            _field("ctags_fallback", KIND_BOOLEAN, "Let Universal Ctags read other languages",
                   "When Ctags is installed, it reads the languages no grammar covers. Switch it "
                   "off to keep a build from launching any other program.",
                   default=DEFAULT_GITHUB_CTAGS_FALLBACK),
            _field("read_documents", KIND_BOOLEAN, "Read document files",
                   "Whether Word, OpenDocument, RTF, PDF, and slide files in a repository are "
                   "read, one request each.", default=DEFAULT_READ_DOCUMENTS),
            _field("max_file_bytes", KIND_INTEGER, "Largest file to download, in bytes",
                   "Anything larger is skipped and named in the log.",
                   default=DEFAULT_GITHUB_MAX_FILE_BYTES),
            _field("max_repositories", KIND_INTEGER, "Most repositories to read",
                   "In the order GitHub lists them, which is alphabetical. The rest are named in "
                   "the log.", default=DEFAULT_GITHUB_MAX_REPOSITORIES),
            _field("max_files_per_repository", KIND_INTEGER, "Most files per repository",
                   "The root README is read first and code last, so what a large repository "
                   "loses is code.", default=DEFAULT_GITHUB_MAX_FILES_PER_REPOSITORY),
        ),
    },
    "youtube": {
        "label": "YouTube channel or videos",
        "help": "Reads what is said in videos from their captions. Give a channel, playlists, or "
                "videos. A key in YOUTUBE_API_KEY lets a build list a whole channel and is never "
                "written here.",
        "fields": (
            _field("channel_id", KIND_TEXT, "Channel",
                   "A handle such as @ExampleChannel, the channel's address, or its id."),
            _field("playlist_ids", KIND_LINES, "Playlists",
                   "Playlist ids or addresses, one per line.", default=[]),
            _field("video_ids", KIND_LINES, "Single videos",
                   "Video ids or addresses, one per line.", default=[]),
            _field("languages", KIND_LINES, "Caption languages",
                   "Language codes in order of preference, one per line. The first track that "
                   "exists is used.", default=list(DEFAULT_YOUTUBE_LANGUAGES)),
            _field("include_playlists", KIND_BOOLEAN, "Read the channel's playlists too",
                   "As well as its uploads.", default=DEFAULT_YOUTUBE_INCLUDE_PLAYLISTS),
            _field("only_channel_videos", KIND_BOOLEAN, "Only the channel's own videos",
                   "A video found through a playlist is indexed only when the channel published "
                   "it.", default=DEFAULT_YOUTUBE_ONLY_CHANNEL_VIDEOS),
            _field("audio_fallback", KIND_BOOLEAN, "Transcribe from audio when captions are refused",
                   "Needs the audio packages the build scripts install.",
                   default=DEFAULT_YOUTUBE_AUDIO_FALLBACK),
            _field("delay_seconds", KIND_NUMBER, "Seconds between requests to YouTube",
                   "Leave it blank to use the build's own. Never less than 1 either way."),
        ),
    },
    "dspace": {
        "label": "Document repository (DSpace)",
        "help": "Reads named collections of a DSpace repository, such as a university library's, "
                "through the repository's own interface.",
        "fields": (
            _field("api_url", KIND_TEXT, "Interface address",
                   "Where the repository's interface lives, such as "
                   "https://repository.example.edu/server/api.", required=True),
            _field("site_url", KIND_TEXT, "Reader address",
                   "Where a reader opens a deposit, such as https://repository.example.edu.",
                   required=True),
            _field("collections", KIND_LINES, "Collections",
                   "One per line: the handle link the repository publishes, the handle, the "
                   "collection's address, or its identifier.", required=True),
            _field("include_full_text", KIND_BOOLEAN, "Index the deposited files' text",
                   "Off indexes each deposit's description alone.",
                   default=DEFAULT_DSPACE_INCLUDE_FULL_TEXT),
            _field("max_file_bytes", KIND_INTEGER, "Largest extracted text file, in bytes",
                   "Anything larger is skipped and named in the log.",
                   default=DEFAULT_DSPACE_MAX_FILE_BYTES),
        ),
    },
}

# Every output carries this, whatever its type.
OUTPUT_COMMON_FIELDS = (
    _field("include_local", KIND_BOOLEAN, "Allow content from local folders",
           "Lets content read from a folder on this computer into this output. Check the output "
           "before publishing it.", default=False),
)

OUTPUT_TYPES = {
    "container": {
        "label": "Search index (container files)",
        "help": "The two files the search clients read: a light one with one entry per page and "
                "a full one with the text of every section.",
        "fields": (
            _field("file", KIND_TEXT, "File name",
                   "The light file's name under the output folder. Leave it blank for <short "
                   "name>.json.gz; the full file takes the same name with -full added."),
            _field("gzip", KIND_BOOLEAN, "Compress",
                   "Off writes plain .json files. Field Station AI and the local page read the "
                   "compressed form.", default=True),
            _field("full", KIND_BOOLEAN, "Write the full file too",
                   "Off writes the light file only.", default=True),
        ),
    },
    "llmstxt": {
        "label": "llms.txt index files",
        "help": "llms.txt lists the sources, and the llms folder holds one index file per "
                "source, for an assistant that reads web pages.",
        "fields": (),
    },
    "sqlite": {
        "label": "SQLite database",
        "help": "Everything the build read, code analysis included, in tables a SQL consumer "
                "can query.",
        "fields": (
            _field("file", KIND_TEXT, "File name",
                   "The database's name under the output folder. Leave it blank for <short "
                   "name>.sqlite."),
        ),
    },
    "okf": {
        "label": "Markdown folder (Open Knowledge Format)",
        "help": "One Markdown file per page under okf/. The local page shows a search result's "
                "text from here.",
        "fields": (),
    },
}


def schema():
    """
    The whole form's description, as the page receives it.

    Returns:
        dict: `globals`, the global fields in form order; `sourceCommon`
        and `sourceTypes`, the fields every source has and the fields
        per built-in type; `outputCommon` and `outputTypes`, the same
        for outputs; and `defaultOutputs`, what a file with no outputs
        list writes.
    """
    return {
        "globals": list(GLOBAL_FIELDS),
        "sourceCommon": list(SOURCE_COMMON_FIELDS),
        "sourceTypes": {name: {"label": entry["label"], "help": entry["help"],
                               "fields": list(entry["fields"])}
                        for name, entry in SOURCE_TYPES.items()},
        "outputCommon": list(OUTPUT_COMMON_FIELDS),
        "outputTypes": {name: {"label": entry["label"], "help": entry["help"],
                               "fields": list(entry["fields"])}
                        for name, entry in OUTPUT_TYPES.items()},
        "defaultOutputs": [dict(entry) for entry in DEFAULT_OUTPUTS],
    }


### Reading The File ###

def settings_state(path):
    """
    The settings file as the page shows it.

    Args:
        path (str | pathlib.Path): the settings file.

    Returns:
        dict: `exists`; `text`, the file's own text, or None; `values`,
        the parsed mapping shaped for the form, or None when the text
        does not parse as a mapping; and `error`, the loader's message
        when the file exists but a build would refuse it, else None.
        The text is read as UTF-8 with any undecodable byte replaced,
        so a file saved in another encoding still shows.
    """
    path = pathlib.Path(path)
    if not path.is_file():
        return {"exists": False, "text": None, "values": None, "error": None}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return {"exists": True, "text": None, "values": None,
                "error": f"{path}: the settings file cannot be read ({error.strerror or error})."}
    values = None
    problem = None
    try:
        values = form_values(mapping_from_text(text))
    except SettingsError as error:
        problem = f"{path}: {error}"
    if problem is None:
        try:
            load_config(path)
        except ConfigError as error:
            problem = str(error)
    return {"exists": True, "text": text, "values": values, "error": problem}


def mapping_from_text(text):
    """
    The mapping a settings file's text holds.

    Args:
        text (str): the file's text.

    Returns:
        dict: the parsed settings; an empty file gives an empty mapping.

    Raises:
        SettingsError: if the text is not YAML, or holds something other
            than a mapping at the top.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise SettingsError(f"the file is not valid YAML ({error}).")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise SettingsError(f"the file must hold a mapping of key: value pairs, not {type(raw).__name__}.")
    return dict(raw)


def form_values(raw):
    """
    A file's mapping in the shape the form edits.

    The form has one field for where a crawl starts, holding one address
    or several, so a `seed_url` becomes a one-entry `seed_urls`. Every
    other value is passed as written, and an absent sources or outputs
    list becomes an empty list or the default outputs.

    Args:
        raw (Mapping): the parsed settings file.

    Returns:
        dict: a copy, shaped for the form.
    """
    values = copy.deepcopy(dict(raw))
    sources = values.get("sources")
    values["sources"] = [_form_source(entry) for entry in sources] if isinstance(sources, list) else []
    outputs = values.get("outputs")
    if isinstance(outputs, list):
        values["outputs"] = [dict(entry) if isinstance(entry, Mapping) else entry for entry in outputs]
    elif outputs is None:
        values["outputs"] = [dict(entry) for entry in DEFAULT_OUTPUTS]
    return values


def _form_source(entry):
    """One source entry shaped for the form."""
    if not isinstance(entry, Mapping):
        return entry
    shaped = dict(entry)
    if shaped.get("type") == "web" and "seed_url" in shaped and "seed_urls" not in shaped:
        shaped["seed_urls"] = [shaped.pop("seed_url")]
    return shaped


### Saving ###

def file_mapping(form):
    """
    The mapping to write from a saved form: what the form holds, less
    every value that equals its default, so the file stays as short as
    one written by hand.

    Args:
        form (Mapping): the form's values, in the shape `form_values`
            produces, with numbers and booleans already typed.

    Returns:
        dict: the settings to write, in form order.

    Raises:
        SettingsError: if the form is not a mapping, or its sources or
            outputs are not lists of mappings.
    """
    if not isinstance(form, Mapping):
        raise SettingsError("the form must be a mapping of settings.")
    mapping = {}
    for field in GLOBAL_FIELDS:
        value = _kept_value(field, form.get(field["key"]))
        if value is not None:
            mapping[field["key"]] = value
    mapping["sources"] = [_file_source(entry, position)
                          for position, entry in enumerate(_entries(form, "sources"), start=1)]
    mapping["outputs"] = [_file_output(entry, position)
                          for position, entry in enumerate(_entries(form, "outputs"), start=1)]
    return mapping


def _entries(form, key):
    """A list setting of the form, checked to be a list of mappings."""
    entries = form.get(key)
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise SettingsError(f"{key} must be a list.")
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, Mapping):
            raise SettingsError(f"{key} entry {position} must be a mapping with a type.")
    return entries


def _kept_value(field, value):
    """
    The value to write for one field, or None to leave the setting out.

    Blank text and a blank list mean "not set". A value equal to the
    field's default is left out, since the loader supplies it. An empty
    list is kept only where the field says an empty list means
    something, which is how a person switches a built-in list off.
    """
    kind = field["kind"]
    if value is None:
        return None
    if kind == KIND_LINES:
        if not isinstance(value, list):
            raise SettingsError(f"{field['key']} must be a list of lines.")
        lines = [str(line).strip() for line in value if str(line).strip()]
        if not lines:
            # The form sends an empty list only for a field where that
            # means something, and only when the person asked for it.
            return [] if field.get("emptyList") else None
        if field.get("default") is not None and lines == list(field["default"]):
            return None
        return lines
    if kind in (KIND_TEXT, KIND_CHOICE):
        text = str(value).strip()
        if not text:
            return None
        return None if text == field.get("default") else text
    if kind == KIND_BOOLEAN:
        if not isinstance(value, bool):
            raise SettingsError(f"{field['key']} must be true or false.")
        return None if value == field.get("default") else value
    if kind in (KIND_INTEGER, KIND_NUMBER):
        if isinstance(value, str):
            if not value.strip():
                return None
            try:
                value = int(value) if kind == KIND_INTEGER else float(value)
            except ValueError:
                raise SettingsError(f"{field['key']} must be a number.")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SettingsError(f"{field['key']} must be a number.")
        if kind == KIND_INTEGER and isinstance(value, float):
            if value != int(value):
                raise SettingsError(f"{field['key']} must be a whole number.")
            value = int(value)
        if kind == KIND_NUMBER and isinstance(value, float) and value == int(value):
            value = int(value)
        return None if value == field.get("default") else value
    return value


def _file_source(entry, position):
    """
    One source entry as written to the file. A built-in type is trimmed
    field by field; a plug-in type is written as the form holds it, since
    only the plug-in knows what its options mean.
    """
    type_name = entry.get("type")
    if not isinstance(type_name, str) or not type_name.strip():
        raise SettingsError(f"sources entry {position}: type is required.")
    written = {"type": type_name.strip()}
    for field in SOURCE_COMMON_FIELDS:
        value = _kept_value(field, entry.get(field["key"]))
        if value is not None:
            written[field["key"]] = value
    known = SOURCE_TYPES.get(type_name)
    if known is None:
        for key, value in entry.items():
            if key not in written and key not in COMMON_SOURCE_KEYS:
                written[key] = value
        return written
    for field in known["fields"]:
        value = _kept_value(field, entry.get(field["key"]))
        if value is None:
            continue
        # One starting address is written the short way, as a person
        # would write it; several stay a list.
        if field["key"] == "seed_urls" and len(value) == 1:
            written["seed_url"] = value[0]
        else:
            written[field["key"]] = value
    return written


def _file_output(entry, position):
    """One output entry as written to the file, trimmed to what differs from the defaults."""
    type_name = entry.get("type")
    if not isinstance(type_name, str) or not type_name.strip():
        raise SettingsError(f"outputs entry {position}: type is required.")
    written = {"type": type_name.strip()}
    for field in OUTPUT_COMMON_FIELDS:
        value = _kept_value(field, entry.get(field["key"]))
        if value is not None:
            written[field["key"]] = value
    known = OUTPUT_TYPES.get(type_name)
    if known is None:
        for key, value in entry.items():
            if key not in written and key not in ("type", "include_local"):
                written[key] = value
        return written
    for field in known["fields"]:
        value = _kept_value(field, entry.get(field["key"]))
        if value is not None:
            written[field["key"]] = value
    # The loader infers gzip from the file's name when the entry names
    # one, so the setting is written whenever the form's value differs
    # from that inference, and left out when it matches.
    if type_name == "container" and isinstance(entry.get("gzip"), bool):
        named = written.get("file")
        inferred = named.endswith(".gz") if isinstance(named, str) else True
        if entry["gzip"] != inferred:
            written["gzip"] = entry["gzip"]
        else:
            written.pop("gzip", None)
    return written


def settings_text(mapping):
    """
    The file text for one mapping: the header comment, then the settings
    in the order given. Every string is written the way the YAML library
    quotes it, so a name holding a colon or a line break stays one value.

    Args:
        mapping (Mapping): the settings to write.

    Returns:
        str: the file text.
    """
    body = yaml.safe_dump(dict(mapping), sort_keys=False, allow_unicode=True,
                          default_flow_style=False, width=10_000)
    return FILE_HEADER + body


def checked_text(text, source):
    """
    Runs a file's text through the settings loader.

    Args:
        text (str): the file text to check.
        source (str): the path, for the loader's messages.

    Returns:
        str: the same text, once the loader accepts it.

    Raises:
        SettingsError: with the loader's own message when it refuses.
    """
    try:
        config_from_mapping(mapping_from_text(text), source=source)
    except ConfigError as error:
        raise SettingsError(str(error))
    return text


def backup_name(path, now=None):
    """
    The name the previous file is kept under beside the new one.

    Args:
        path (pathlib.Path): the settings file.
        now (str | None): the time of the save as an ISO 8601 UTC
            timestamp; the current time when None.

    Returns:
        pathlib.Path: `<name>.<stamp>.bak`, the stamp with the colons
        Windows refuses replaced by hyphens.
    """
    stamp = (now or utc_now()).replace(":", "-")
    return path.with_name(f"{path.name}.{stamp}{BACKUP_SUFFIX}")


def save_text(path, text, now=None):
    """
    Writes a settings file from its text, once the loader accepts it.

    The previous file, when there is one, is kept beside the new one
    with a date stamp, and the new text lands whole or not at all,
    through a temporary file replaced into place.

    Args:
        path (str | pathlib.Path): the settings file.
        text (str): the file text, as a person typed it.
        now (str | None): the save time, for the kept copy's name.

    Returns:
        pathlib.Path | None: the kept copy's path, or None when there
        was no previous file.

    Raises:
        SettingsError: with the loader's message when the text is refused.
        OSError: if the file cannot be written.
    """
    path = pathlib.Path(path)
    checked_text(text, str(path))
    kept = None
    if path.is_file():
        kept = backup_name(path, now)
        kept.write_bytes(path.read_bytes())
    folder = path.parent if str(path.parent) else pathlib.Path(".")
    handle, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as tmp:
            tmp.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return kept


def save_form(path, form, now=None):
    """
    Writes a settings file from a saved form.

    Args:
        path (str | pathlib.Path): the settings file.
        form (Mapping): the form's values, in the shape `form_values`
            produces.
        now (str | None): the save time, for the kept copy's name.

    Returns:
        tuple[str, pathlib.Path | None]: the text written, and the kept
        copy's path or None.

    Raises:
        SettingsError: with the loader's message when a value is refused.
        OSError: if the file cannot be written.
    """
    text = settings_text(file_mapping(form))
    return text, save_text(path, text, now)


### The First File ###

def write_first_settings(values, output):
    """
    Writes the welcome screen's settings file through the `init` module,
    with the outputs the page relies on switched on.

    Args:
        values (Mapping): `name`, `slug`, and `seed_url` as typed.

    Returns:
        pathlib.Path: the path written.

    Raises:
        SettingsError: if a value is refused, or the file already exists.
        OSError: if the file cannot be written.
    """
    try:
        name = init_module.checked_name(str(values.get("name") or ""))
        slug = init_module.checked_slug(str(values.get("slug") or ""), name)
        seed_url = init_module.checked_seed_url(str(values.get("seed_url") or ""))
        return init_module.write_settings({"name": name, "slug": slug, "seed_url": seed_url},
                                          output, outputs=PAGE_OUTPUTS)
    except init_module.InitError as error:
        raise SettingsError(str(error))
