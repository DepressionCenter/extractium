"""
Summary: Runs code analysis over one repository. Chooses the best reader
for each file -- a grammar, then Universal Ctags, then the file's own
outline -- pulls code out of the files that hold another language inside
them, resolves the relationships across the repository, and caches every
parse against everything that could change it. Nothing a repository
contains is executed, installed, or treated as an instruction. See
docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/code/indexer.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-10
Last Modified: 2026-09-10
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
__date__ = "2026-09-10"

import importlib.metadata as metadata
import posixpath
from dataclasses import replace

from extractium.code import embedded, languages, relationships, render
from extractium.code.ctags import Ctags
from extractium.code.records import FileFacts, RepositoryFacts, SCHEMA_VERSION, as_data, from_data
from extractium.code.tree_sitter import Engine
from extractium.core import cache as caching

### Limits ###

# The most code files analyzed in one repository. A repository larger
# than this is a monorepo or a vendored tree, and the files past the
# ceiling are named in the report rather than dropped in silence.
MAX_FILES = 3_000

# A file longer than this is generated -- a bundled library, a compiled
# template, a data table written as source. Parsing one costs a great
# deal and tells a reader nothing.
MAX_FILE_CHARS = 1_500_000


class CodeIndexer:
    """
    Reads the code in one repository and reports what it holds.

    Args:
        progress (Callable[[str], None] | None): receives one line per
            event worth a reader's attention.
        use_ctags (bool): whether Universal Ctags may be used for the
            languages no grammar covers. An operator switches it off with
            the `ctags_fallback` setting.
        engine (tree_sitter.Engine | None): the parser to use. A test
            passes one in; a build lets one be made here.
        ctags (ctags.Ctags | None): the second parser, likewise.

    Attributes:
        engine (tree_sitter.Engine): the grammar-driven parser.
        ctags (ctags.Ctags): the fallback parser.
    """

    def __init__(self, progress=None, use_ctags=True, engine=None, ctags=None):
        self.progress = progress or (lambda message: None)
        self.use_ctags = bool(use_ctags)
        self.engine = engine or Engine(progress=self.progress)
        self.ctags = ctags or Ctags(progress=self.progress)
        self._versions = {}
        self._readmes = {}

    ### One Repository ###

    def analyze(self, repository, entries):
        """
        Reads every code file in one repository.

        Args:
            repository (str): "owner/name", for the records.
            entries (Iterable[tuple[str, str, str]]): path, content, and
                the file's Git object name. The object name may be empty,
                which only means the parse is not cached.

        Returns:
            records.RepositoryFacts: one record per analyzed file, with
            imports resolved, calls labelled, and reverse edges filled
            in; plus the prose pulled out of any notebook, R Markdown
            file, or page, keyed by path.
        """
        entries = [tuple(entry) for entry in entries]
        content = {path: text for path, text, _ in entries}
        analyzed = []
        documentation = {}
        skipped = []
        for path, text, blob_sha in entries:
            if len(analyzed) >= MAX_FILES:
                skipped.append(f"{path}: past the ceiling of {MAX_FILES} code files")
                continue
            if not languages.is_code_path(path):
                continue
            if text is None or len(text) > MAX_FILE_CHARS:
                skipped.append(f"{path}: too long to parse")
                continue
            facts = self.analyze_file(path, text, blob_sha)
            if facts is None:
                continue
            contents = embedded.read(path, text)
            if contents is not None and contents.prose.strip():
                documentation[path] = (contents.title, contents.prose)
            analyzed.append(facts)

        summarized = []
        for facts in relationships.resolve(analyzed):
            summary, source = render.summary_for(
                facts,
                text=content.get(facts.path, ""),
                readme=self._readmes.get(posixpath.dirname(facts.path), ""),
            )
            summarized.append(replace(facts, summary=summary, summary_source=source))
        summarized = tuple(summarized)

        tiers = {}
        for facts in summarized:
            tiers[facts.tier] = tiers.get(facts.tier, 0) + 1
        return RepositoryFacts(
            repository=repository, files=summarized, tiers=tiers, skipped=tuple(skipped),
        ), documentation

    ### One File ###

    def analyze_file(self, path, text, blob_sha=""):
        """
        Reads one file at the best tier this machine can reach.

        A stored parse is used when the file, the engine, the grammar,
        and the shape of the records are all the ones it was made with.
        Otherwise the file is parsed, and the result is stored under
        exactly those things.

        Args:
            path (str): the repository-relative path.
            text (str): the file's content.
            blob_sha (str): the file's Git object name, or an empty
                string when there is none to cache against.

        Returns:
            records.FileFacts | None: what the file holds, or None when
            the path is not code at all.
        """
        if not languages.is_code_path(path):
            return None
        key = self._cache_key(path)
        stored = _cached(blob_sha, key)
        if stored is not None:
            return stored

        facts = self._read(path, text)
        _store(blob_sha, key, facts)
        return facts

    def _read(self, path, text):
        """The best records this machine can produce for one file."""
        container = languages.container_for_path(path)
        if container:
            return self._read_container(path, text)

        spec = languages.language_for_path(path)
        facts = self.engine.analyze(path, text, spec)
        if facts.tier != languages.TIER_METADATA:
            return facts
        if self.use_ctags:
            tagged = self.ctags.analyze(path, text, spec)
            if tagged is not None and tagged.symbols:
                return tagged
        return facts

    def _read_container(self, path, text):
        """
        The records for a file that holds another language inside it.

        Each block is parsed with the grammar its own fence, kernel, or
        delimiter named, and every line number is moved to where the
        block sits in the file a reader will open.
        """
        contents = embedded.read(path, text)
        outline = FileFacts(
            path=path,
            language=contents.kind if contents else "",
            display=_container_display(contents.kind if contents else ""),
            tier=languages.TIER_METADATA,
            line_count=text.count("\n") + (1 if text and not text.endswith("\n") else 0),
        )
        if contents is None:
            return outline

        symbols = []
        imports = []
        calls = []
        parsed = False
        spoken = []
        for block in contents.blocks:
            spec = languages.language_named(block.language)
            if spec is None:
                continue
            block_facts = self.engine.analyze(path, block.text, spec)
            if block_facts.tier == languages.TIER_METADATA:
                continue
            parsed = True
            if spec.display not in spoken:
                spoken.append(spec.display)
            offset = block.start_line - 1
            symbols += [
                replace(symbol, start_line=symbol.start_line + offset,
                        end_line=symbol.end_line + offset)
                for symbol in block_facts.symbols
            ]
            imports += [replace(item, line=item.line + offset) for item in block_facts.imports]
            calls += list(block_facts.calls)

        return replace(
            outline,
            tier=languages.TIER_TREE_SITTER if parsed else languages.TIER_METADATA,
            display=_container_display(contents.kind, spoken),
            symbols=tuple(symbols), imports=tuple(imports), calls=tuple(calls),
            doc=_first_paragraph(contents.prose),
        )

    ### Summaries ###

    def with_readmes(self, readmes):
        """
        Tells the indexer where each folder's README is, so a file with
        no documentation of its own can quote the one beside it.

        Args:
            readmes (Mapping[str, str]): folder path to README text. The
                repository root is the empty string.

        Returns:
            CodeIndexer: this indexer, so a caller can chain the call.
        """
        self._readmes = dict(readmes or {})
        return self

    ### The Cache Key ###

    def _cache_key(self, path):
        """
        Everything a stored parse depends on.

        The file itself is the cache's name; this is the rest: which
        engine read it, which version of it, which grammar, which version
        of that, and the shape of the records. A change to any of them
        makes a stored result stale.
        """
        spec = languages.language_for_path(path)
        container = languages.container_for_path(path)
        return {
            "engine": "tree-sitter" if self.engine.installed else "none",
            "engine_version": self._version("tree-sitter"),
            "grammar": (spec.distribution if spec else "") or "",
            "grammar_version": self._version(spec.distribution) if spec else "",
            "queries": self.engine.query_digest(spec) if spec else "",
            "language": (spec.name if spec else "") or container or "",
            "ctags": self.ctags.version if self.use_ctags else "",
            "schema": SCHEMA_VERSION,
        }

    def _version(self, distribution):
        """The installed version of one package, or an empty string."""
        if not distribution:
            return ""
        if distribution not in self._versions:
            try:
                self._versions[distribution] = metadata.version(distribution)
            except metadata.PackageNotFoundError:
                self._versions[distribution] = ""
        return self._versions[distribution]


### Helpers ###

def _cached(blob_sha, key):
    """A stored parse, or None when there is none that applies."""
    if not blob_sha:
        return None
    try:
        stored = caching.load_analysis(blob_sha, key)
    except ValueError:
        return None
    return from_data(stored) if stored else None


def _store(blob_sha, key, facts):
    """
    Stores one parse for the next build.

    A cache that cannot be written costs a slower next build. It must
    never cost this one its records.
    """
    if not blob_sha or facts is None:
        return
    try:
        caching.save_analysis(blob_sha, key, as_data(facts))
    except (OSError, ValueError):
        pass


def _container_display(kind, spoken=()):
    """What a container file is called, with the languages found inside it."""
    names = {
        "notebook": "Jupyter notebook",
        "rmarkdown": "R Markdown",
        "lua_server_pages": "Lua Server Page",
        "html": "HTML page",
    }
    base = names.get(kind, "File")
    return f"{base} ({', '.join(spoken)})" if spoken else base


def _first_paragraph(prose):
    """
    The first paragraph of a container's prose, which is what its author
    wrote to introduce it.
    """
    for block in (prose or "").split("\n\n"):
        cleaned = " ".join(line.strip("# ").strip() for line in block.splitlines()).strip()
        if cleaned:
            return cleaned
    return ""
