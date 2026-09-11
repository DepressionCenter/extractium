"""
Summary: What code analysis produces: a record per symbol and a record
per file. Every field here is structure a parser observed -- a name, a
kind, a signature, documentation somebody wrote, a line range -- and
never a source body and never a guess. The rule comes from the
specification, section 5; the reason it matters is in
docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/code/records.py

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

import posixpath
import re
from dataclasses import dataclass, field, replace


### What A Symbol Is ###

# The kinds a symbol record may carry. They are deliberately few: a
# reader searching an index wants to know whether a thing is a type or a
# routine, not which of eleven ways a language spells either.
SYMBOL_KINDS = frozenset({
    "class", "function", "method", "constant", "type", "module",
})

# How sure the analysis is that one symbol calls another.
CONFIDENCE_RESOLVED = "resolved"
CONFIDENCE_PROBABLE = "probable"
CONFIDENCE_UNRESOLVED = "unresolved"

# A name that says the routine is a test. Tests are indexed rather than
# skipped: a test is often the clearest statement of what something is
# meant to do and how it is meant to fail.
TEST_NAME_RE = re.compile(r"^(test[_A-Z0-9]|.*[_.]test$|.*Test$|.*Tests$|.*Spec$)")
TEST_PATH_RE = re.compile(r"(^|/)(tests?|spec|__tests__)(/|$)|(^|/)test_[^/]+$|_test\.[^/]+$", re.I)


@dataclass(frozen=True)
class Symbol:
    """
    One definition found in one file.

    Attributes:
        name (str): the symbol as it is written in the source.
        kind (str): one of SYMBOL_KINDS.
        signature (str): everything the source writes before the body,
            whitespace collapsed: the name, its parameters, and its
            declared types. Never the body.
        doc (str): documentation a person wrote for this symbol -- a
            docstring, or the comment block directly above it -- with the
            comment markers removed. Empty when there is none.
        start_line (int): first line of the definition, counting from 1.
        end_line (int): last line of the definition.
        parent (str): the symbol this one is defined inside, or an empty
            string at the top level.
        calls (tuple[str, ...]): the names this symbol calls, in the
            order they first appear.
        language (str): the language registry name.
        tier (str): which analysis produced this record.
    """

    name: str
    kind: str
    signature: str = ""
    doc: str = ""
    start_line: int = 1
    end_line: int = 1
    parent: str = ""
    calls: tuple = ()
    language: str = ""
    tier: str = ""

    def __post_init__(self):
        object.__setattr__(self, "calls", tuple(self.calls))

    @property
    def qualified_name(self):
        """The symbol with its enclosing symbol, as a reader would write it."""
        return f"{self.parent}.{self.name}" if self.parent else self.name

    def is_test(self, path=""):
        """
        True when this symbol is a test.

        Args:
            path (str): the file's repository-relative path, because many
                languages mark tests by where the file lives rather than
                by what the routine is called.
        """
        if TEST_NAME_RE.match(self.name or ""):
            return True
        return bool(path) and bool(TEST_PATH_RE.search(path))


@dataclass(frozen=True)
class Import:
    """
    One thing a file brings in from somewhere else.

    Attributes:
        statement (str): the line as written, whitespace collapsed.
        target (str): what it names -- a module path, a package, a file,
            or a relative path. Empty when the statement names nothing
            that can be read out of it statically.
        line (int): where it appears, counting from 1.
        path (str): the repository file it resolves to, filled in after
            the whole repository is parsed. Empty until then, and empty
            forever for anything outside the repository.
        external (bool): True when the target is a package the repository
            does not contain.
    """

    statement: str
    target: str = ""
    line: int = 1
    path: str = ""
    external: bool = False


@dataclass(frozen=True)
class Call:
    """
    One symbol calling another, with how sure the analysis is.

    Attributes:
        caller (str): the qualified name of the calling symbol, or an
            empty string for a call at the top level of a file.
        name (str): the name called.
        confidence (str): CONFIDENCE_RESOLVED when the target is a
            uniquely named symbol in the same file, CONFIDENCE_PROBABLE
            when it is reached through an import this file declares, and
            CONFIDENCE_UNRESOLVED when nothing static says what it is.
        path (str): the file holding the called symbol, when one was
            found.
    """

    caller: str
    name: str
    confidence: str = CONFIDENCE_UNRESOLVED
    path: str = ""


@dataclass(frozen=True)
class FileFacts:
    """
    Everything the analysis observed about one file.

    Attributes:
        path (str): the repository-relative path.
        language (str): the language registry name, or an empty string
            when the file's language is unknown.
        display (str): the language as a reader writes it.
        tier (str): which analysis produced this, from
            extractium.code.languages.TIER_ORDER.
        symbols (tuple[Symbol, ...]): what the file defines.
        imports (tuple[Import, ...]): what it brings in.
        calls (tuple[Call, ...]): what it calls, filled in once
            relationships are resolved.
        doc (str): the documentation the file opens with -- a module
            docstring, or the comment block at the top -- with the
            comment markers removed. Empty when it opens with neither.
        line_count (int): how long the file is.
        recovered (bool): True when the parser met a syntax error and
            carried on. The records are then what could be read, and the
            record says so rather than pretending the file was clean.
        summary (str): a plain sentence about the file, quoted from its
            own documentation or counted off the parse. Never a guess.
        summary_source (str): where the summary came from, so a reader
            can weigh it: "documentation", "header", "readme", or
            "structure".
        imported_by (tuple[str, ...]): paths that import this file,
            computed from the finished graph.
        called_by (tuple[str, ...]): paths that call into this file,
            computed from the finished graph.
    """

    path: str
    language: str = ""
    display: str = ""
    tier: str = ""
    symbols: tuple = ()
    imports: tuple = ()
    calls: tuple = ()
    doc: str = ""
    line_count: int = 0
    recovered: bool = False
    summary: str = ""
    summary_source: str = ""
    imported_by: tuple = ()
    called_by: tuple = ()

    def __post_init__(self):
        for name in ("symbols", "imports", "calls", "imported_by", "called_by"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def module_name(self):
        """
        The name other files in the repository import this file by.

        It is the path without its extension and with separators turned
        into dots, which is how Python, Java, Kotlin, and C# all spell a
        module. A language that spells it differently is matched on the
        path instead.
        """
        stem = posixpath.splitext(self.path)[0]
        return stem.replace("/", ".")

    def with_relationships(self, imports=None, calls=None, imported_by=None, called_by=None):
        """A copy carrying resolved relationships, leaving this one unchanged."""
        return replace(
            self,
            imports=tuple(self.imports if imports is None else imports),
            calls=tuple(self.calls if calls is None else calls),
            imported_by=tuple(self.imported_by if imported_by is None else imported_by),
            called_by=tuple(self.called_by if called_by is None else called_by),
        )


@dataclass(frozen=True)
class RepositoryFacts:
    """
    Every file the analysis read in one repository, and how it was read.

    Attributes:
        repository (str): "owner/name".
        files (tuple[FileFacts, ...]): one per analyzed file, in path
            order.
        tiers (dict[str, int]): how many files each analysis tier
            produced, so a report can say what was actually achieved
            rather than what was attempted.
        skipped (tuple[str, ...]): paths that hold code but were not
            analyzed, with the reason.
    """

    repository: str
    files: tuple = ()
    tiers: dict = field(default_factory=dict)
    skipped: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "files", tuple(self.files))
        object.__setattr__(self, "skipped", tuple(self.skipped))

    @property
    def symbol_count(self):
        """How many definitions the analysis found across the repository."""
        return sum(len(f.symbols) for f in self.files)


### Storing And Reading Back ###

# The shape of a stored record. A change to any field below changes what
# a cached parse means, so this number travels in the cache key and an
# older stored result is reparsed rather than misread.
SCHEMA_VERSION = 1


def as_data(facts):
    """
    One file's records as plain data, for the cache.

    Args:
        facts (FileFacts): the records.

    Returns:
        dict: nested lists and strings only, so it round-trips through
        JSON unchanged.
    """
    return {
        "path": facts.path,
        "language": facts.language,
        "display": facts.display,
        "tier": facts.tier,
        "doc": facts.doc,
        "line_count": facts.line_count,
        "recovered": facts.recovered,
        "symbols": [
            {
                "name": s.name, "kind": s.kind, "signature": s.signature, "doc": s.doc,
                "start_line": s.start_line, "end_line": s.end_line, "parent": s.parent,
                "calls": list(s.calls), "language": s.language, "tier": s.tier,
            }
            for s in facts.symbols
        ],
        "imports": [
            {"statement": i.statement, "target": i.target, "line": i.line}
            for i in facts.imports
        ],
        "calls": [{"caller": c.caller, "name": c.name} for c in facts.calls],
    }


def from_data(data):
    """
    One file's records, read back from the cache.

    The stored file was written by an earlier run of this program, but it
    is still read as data rather than trusted: a field of the wrong type
    takes its default instead of reaching a record that promises
    otherwise.

    Args:
        data (Mapping): what as_data wrote.

    Returns:
        FileFacts | None: the records, or None when the stored shape is
        not one this can read.
    """
    if not isinstance(data, dict) or not isinstance(data.get("path"), str):
        return None
    symbols = []
    for stored in data.get("symbols") or ():
        if not isinstance(stored, dict) or stored.get("kind") not in SYMBOL_KINDS:
            continue
        if not isinstance(stored.get("name"), str):
            continue
        symbols.append(Symbol(
            name=stored["name"], kind=stored["kind"],
            signature=_text_or_blank(stored.get("signature")),
            doc=_text_or_blank(stored.get("doc")),
            start_line=_counting_number(stored.get("start_line")),
            end_line=_counting_number(stored.get("end_line")),
            parent=_text_or_blank(stored.get("parent")),
            calls=tuple(c for c in (stored.get("calls") or ()) if isinstance(c, str)),
            language=_text_or_blank(stored.get("language")),
            tier=_text_or_blank(stored.get("tier")),
        ))
    imports = tuple(
        Import(
            statement=_text_or_blank(stored.get("statement")),
            target=_text_or_blank(stored.get("target")),
            line=_counting_number(stored.get("line")),
        )
        for stored in (data.get("imports") or ())
        if isinstance(stored, dict)
    )
    calls = tuple(
        Call(caller=_text_or_blank(stored.get("caller")), name=_text_or_blank(stored.get("name")))
        for stored in (data.get("calls") or ())
        if isinstance(stored, dict) and isinstance(stored.get("name"), str)
    )
    return FileFacts(
        path=data["path"],
        language=_text_or_blank(data.get("language")),
        display=_text_or_blank(data.get("display")),
        tier=_text_or_blank(data.get("tier")),
        symbols=tuple(symbols),
        imports=imports,
        calls=calls,
        doc=_text_or_blank(data.get("doc")),
        line_count=_counting_number(data.get("line_count"), least=0),
        recovered=bool(data.get("recovered")),
    )


def _text_or_blank(value):
    """The value when it is text, and an empty string when it is anything else."""
    return value if isinstance(value, str) else ""


def _counting_number(value, least=1):
    """The value when it is a whole number at or above least, and least otherwise."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= least else least
