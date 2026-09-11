"""
Summary: Ties one repository's files together. Builds a symbol table out
of everything the parsers found, resolves each import to the file it
names, labels every call resolved, probable, or unresolved, and computes
the reverse edges from the finished graph. A call whose target cannot be
proved is labelled as such rather than guessed at: a wrong edge reported
with confidence is worse than a missing one. See
docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/code/relationships.py

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
from dataclasses import replace

from extractium.code.records import (
    CONFIDENCE_PROBABLE, CONFIDENCE_RESOLVED, CONFIDENCE_UNRESOLVED, Call,
)

### How An Import Is Matched To A File ###

# A leading dot means "beside me", in Python, JavaScript, and TypeScript
# alike. How many dots there are says how far up to go.
RELATIVE_PREFIXES = (".", "/")

# Extensions tried when an import names a file without one. A relative
# import in JavaScript rarely writes the extension, and the file it means
# may be any of these, or a folder's index.
IMPLIED_EXTENSIONS = (
    "", ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".lua", ".sh", ".R", ".r",
    "/__init__.py", "/index.js", "/index.ts", "/init.lua",
)


class SymbolTable:
    """
    Every definition one repository holds, indexed by the ways a caller
    might name it.

    Args:
        files (Iterable[records.FileFacts]): the analyzed files.

    Attributes:
        by_path (dict[str, records.FileFacts]): file records by path.
        defined_in (dict[str, list[str]]): symbol name to the paths
            defining it. A name defined in two files is ambiguous, and
            the confidence on any call to it says so.
    """

    def __init__(self, files):
        self.by_path = {facts.path: facts for facts in files}
        self.by_module = {}
        self.defined_in = {}
        for facts in files:
            self.by_module.setdefault(facts.module_name, facts.path)
            self.by_module.setdefault(posixpath.splitext(facts.path)[0], facts.path)
            for symbol in facts.symbols:
                self.defined_in.setdefault(symbol.name, []).append(facts.path)

    def file_for_module(self, target, source_path):
        """
        The repository file an import names, or an empty string.

        Args:
            target (str): what the import statement named -- a dotted
                module, a relative path, or a package.
            source_path (str): the file the import was written in, which
                is what a relative import is relative to.

        Returns:
            str: a repository path, or an empty string when the import
            names something outside this repository.
        """
        if not target:
            return ""
        # "from package import thing" names a module when thing is a file
        # and a name inside one when it is a function, and the statement
        # reads the same either way. The longer form is tried first.
        found = self._one_target(target, source_path)
        if not found and "." in target.strip("."):
            found = self._one_target(target.rsplit(".", 1)[0], source_path)
        return found

    def _one_target(self, target, source_path):
        """The file one written name resolves to, or an empty string."""
        if target.startswith(RELATIVE_PREFIXES):
            return self._relative(target, source_path)
        # A dotted name is a module path in Python, Java, Kotlin, and C#
        # alike, so it is matched against the module name of every file,
        # and then against the tail of one, which is what an installed
        # package's own imports look like.
        dotted = target.replace("::", ".").strip(".")
        if dotted in self.by_module:
            return self.by_module[dotted]
        as_path = dotted.replace(".", "/")
        for candidate in self._candidates(as_path):
            if candidate in self.by_path:
                return candidate
        for module, path in self.by_module.items():
            if module.endswith(f".{dotted}") or module == dotted:
                return path
        return ""

    def _relative(self, target, source_path):
        """The file a relative import names, resolved against the importing file."""
        folder = posixpath.dirname(source_path)
        cleaned = target
        while cleaned.startswith(".."):                 # Python writes "..module"
            folder = posixpath.dirname(folder)
            cleaned = cleaned[1:]
        cleaned = cleaned.lstrip("./")
        joined = posixpath.normpath(posixpath.join(folder, cleaned.replace(".", "/")))
        if joined.startswith(".."):
            return ""                                  # outside the repository
        for candidate in self._candidates(joined):
            if candidate in self.by_path:
                return candidate
        return ""

    def _candidates(self, stem):
        """Every file name one import could mean, best first."""
        return tuple(f"{stem}{extension}" for extension in IMPLIED_EXTENSIONS)


def resolve(files):
    """
    Fills in every relationship across one repository.

    Imports are resolved first, because they are cheap and usually
    reliable, and because a resolved import is what makes a cross-file
    call probable rather than unknown. Reverse edges are computed last,
    from the finished graph, so nothing is parsed twice.

    Args:
        files (Iterable[records.FileFacts]): one repository's analyzed
            files.

    Returns:
        tuple[records.FileFacts, ...]: the same files, in the same order,
        each carrying resolved imports, labelled calls, and the files
        that reach into it.
    """
    files = list(files)
    table = SymbolTable(files)

    resolved = []
    for facts in files:
        imports = []
        for item in facts.imports:
            path = table.file_for_module(item.target, facts.path)
            imports.append(replace(item, path=path, external=bool(item.target) and not path))
        imports = tuple(imports)
        calls = _calls_for(facts, imports, table)
        resolved.append(facts.with_relationships(imports=imports, calls=calls))

    return _reverse_edges(resolved)


def _calls_for(facts, imports, table):
    """
    Every call one file makes, each labelled with how sure the analysis
    is about where it lands.

    A call to a name defined once in the same file is resolved. A call to
    a name defined in a file this one imports is probable. Everything
    else is unresolved, including a call through a variable, because
    nothing static says what a variable holds.
    """
    reachable = {item.path for item in imports if item.path}
    own = {symbol.name for symbol in facts.symbols}
    calls = []
    seen = set()

    def record(caller, name):
        if not name or (caller, name) in seen:
            return
        seen.add((caller, name))
        defining = table.defined_in.get(name, ())
        if name in own and defining.count(facts.path) == 1 and len(set(defining)) == 1:
            calls.append(Call(caller, name, CONFIDENCE_RESOLVED, facts.path))
            return
        imported = [path for path in defining if path in reachable]
        if len(set(imported)) == 1:
            calls.append(Call(caller, name, CONFIDENCE_PROBABLE, imported[0]))
            return
        calls.append(Call(caller, name, CONFIDENCE_UNRESOLVED))

    for symbol in facts.symbols:
        for name in symbol.calls:
            record(symbol.qualified_name, name)
    for call in facts.calls:
        record(call.caller, call.name)
    return tuple(calls)


def _reverse_edges(files):
    """
    Who imports and who calls into each file, computed from the finished
    graph.

    Reverse edges are worth their small cost: "what would break if I
    changed this" is one of the few questions a reader cannot answer by
    reading the file in front of them.
    """
    imported_by = {}
    called_by = {}
    for facts in files:
        for item in facts.imports:
            if item.path and item.path != facts.path:
                imported_by.setdefault(item.path, set()).add(facts.path)
        for call in facts.calls:
            if call.path and call.path != facts.path:
                called_by.setdefault(call.path, set()).add(facts.path)
    return tuple(
        facts.with_relationships(
            imported_by=tuple(sorted(imported_by.get(facts.path, ()))),
            called_by=tuple(sorted(called_by.get(facts.path, ()))),
        )
        for facts in files
    )
