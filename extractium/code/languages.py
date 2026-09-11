"""
Summary: Which language a source file is written in, which grammar reads
it, and how completely it can be read. One registry, so adding a language
is a table entry rather than another branch somewhere in the GitHub code.
Each entry records the grammar package and its license, because a grammar
is a dependency and its license travels with it. See
docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/code/languages.py

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

import os
import posixpath
import re
from dataclasses import dataclass


### How Completely A File Can Be Read ###

# A parser read the file and produced symbols, imports, and calls.
TIER_TREE_SITTER = "tree-sitter"

# Universal Ctags read the file and produced symbols. It produces no
# import graph and no call graph, and none is ever invented for it.
TIER_CTAGS = "ctags"

# Nothing parsed the file. It is still recorded: path, language, size,
# and a link. A file nobody can parse is far better named than missing.
TIER_METADATA = "file metadata only"

# The tiers, best first.
TIER_ORDER = (TIER_TREE_SITTER, TIER_CTAGS, TIER_METADATA)


### The Registry ###

@dataclass(frozen=True)
class LanguageSpec:
    """
    One language: what its files are called, which grammar reads it, and
    what that grammar can be asked for.

    Attributes:
        name (str): the registry key, lowercase, used in records and in
            the name of the query file.
        display (str): the name a reader sees, such as "C#".
        extensions (tuple[str, ...]): file extensions, with the dot,
            lowercase.
        filenames (tuple[str, ...]): whole file names this language
            claims whatever extension they carry, such as "Makefile".
        module (str): the Python module holding the compiled grammar, or
            an empty string when no grammar is published for this
            language.
        factory (str): the function in that module returning the grammar.
        distribution (str): the package to install for the grammar.
        grammar_license (str): the license that package is published
            under, recorded because a grammar is a dependency.
        comment_nodes (tuple[str, ...]): the grammar's node types for
            comments, so documentation written above a definition can be
            collected without a language-specific rule in the engine.
        captures (tuple[str, ...]): the capture kinds this language's
            query file supports. Asking a shell grammar for class
            inheritance should return nothing, not an error.
        ctags_language (str): the Universal Ctags language name, or an
            empty string when Ctags does not read this language either.
        query_name (str): the language whose query file this one uses,
            when two grammars are the same language in two dialects.
            Empty means it has a query file of its own.
    """

    name: str
    display: str
    extensions: tuple = ()
    filenames: tuple = ()
    module: str = ""
    factory: str = "language"
    distribution: str = ""
    grammar_license: str = ""
    comment_nodes: tuple = ()
    captures: tuple = ()
    ctags_language: str = ""
    query_name: str = ""

    @property
    def best_tier(self):
        """
        The most complete way this language can be read, before checking
        what is installed on this machine.

        Returns:
            str: one of TIER_ORDER.
        """
        if self.module:
            return TIER_TREE_SITTER
        if self.ctags_language:
            return TIER_CTAGS
        return TIER_METADATA

    @property
    def query_file(self):
        """The file name of this language's extraction rules."""
        return f"{self.query_name or self.name}.scm"


# The capture kinds a query file may use. The engine reads these names
# and nothing else, so a query capturing something outside this set is
# ignored rather than misread.
CAPTURE_KINDS = (
    "definition.class", "definition.function", "definition.method",
    "definition.constant", "definition.type", "definition.module",
    "name", "doc", "import", "import.source", "import.name", "call", "call.name",
)

# The whole set, for a language whose query file supports everything.
ALL_CAPTURES = CAPTURE_KINDS

# Every language Extractium can name. A language with no module is not an
# oversight: it is a language nobody has published a grammar for, written
# down so its files are still indexed at a lower tier with the reason
# visible. Every license below was read from the package's own metadata
# on 2026-09-10; the gate table in docs/github-repository-indexing.md
# records what else was checked.
LANGUAGES = (
    LanguageSpec(
        name="python", display="Python",
        extensions=(".py", ".pyi"),
        module="tree_sitter_python", distribution="tree-sitter-python",
        grammar_license="MIT",
        comment_nodes=("comment",),
        captures=ALL_CAPTURES,
        ctags_language="Python",
    ),
    LanguageSpec(
        name="javascript", display="JavaScript",
        extensions=(".js", ".jsx", ".mjs", ".cjs"),
        module="tree_sitter_javascript", distribution="tree-sitter-javascript",
        grammar_license="MIT",
        comment_nodes=("comment",),
        captures=ALL_CAPTURES,
        ctags_language="JavaScript",
    ),
    LanguageSpec(
        name="typescript", display="TypeScript",
        extensions=(".ts", ".mts", ".cts"),
        module="tree_sitter_typescript", factory="language_typescript",
        distribution="tree-sitter-typescript", grammar_license="MIT",
        comment_nodes=("comment",),
        captures=ALL_CAPTURES,
        ctags_language="TypeScript",
    ),
    LanguageSpec(
        name="tsx", display="TypeScript with JSX",
        extensions=(".tsx",),
        module="tree_sitter_typescript", factory="language_tsx",
        distribution="tree-sitter-typescript", grammar_license="MIT",
        comment_nodes=("comment",),
        captures=ALL_CAPTURES,
        ctags_language="TypeScript",
        query_name="typescript",
    ),
    LanguageSpec(
        name="bash", display="Shell",
        extensions=(".sh", ".bash", ".zsh", ".ksh"),
        module="tree_sitter_bash", distribution="tree-sitter-bash",
        grammar_license="MIT",
        comment_nodes=("comment",),
        captures=("definition.function", "name", "doc", "import", "call"),
        ctags_language="Sh",
    ),
    LanguageSpec(
        name="lua", display="Lua",
        extensions=(".lua",),
        module="tree_sitter_lua", distribution="tree-sitter-lua",
        grammar_license="MIT",
        comment_nodes=("comment",),
        captures=("definition.function", "definition.method", "name", "doc", "import", "call"),
        ctags_language="Lua",
    ),
    LanguageSpec(
        name="csharp", display="C#",
        extensions=(".cs",),
        module="tree_sitter_c_sharp", distribution="tree-sitter-c-sharp",
        grammar_license="MIT",
        comment_nodes=("comment",),
        captures=ALL_CAPTURES,
        ctags_language="C#",
    ),
    LanguageSpec(
        name="html", display="HTML",
        extensions=(".html", ".htm", ".xhtml"),
        module="tree_sitter_html", distribution="tree-sitter-html",
        grammar_license="MIT",
        comment_nodes=("comment",),
        ctags_language="HTML",
    ),
    LanguageSpec(
        name="markdown", display="Markdown",
        module="tree_sitter_markdown", distribution="tree-sitter-markdown",
        grammar_license="MIT",
    ),
    LanguageSpec(
        name="sql", display="SQL",
        extensions=(".sql",),
        module="tree_sitter_sql", distribution="tree-sitter-sql",
        grammar_license="MIT",
        comment_nodes=("comment", "marginalia"),
        captures=("definition.function", "definition.type", "name", "doc"),
        ctags_language="SQL",
    ),
    LanguageSpec(
        name="kotlin", display="Kotlin",
        extensions=(".kt", ".kts"),
        module="tree_sitter_kotlin", distribution="tree-sitter-kotlin",
        grammar_license="MIT",
        comment_nodes=("line_comment", "multiline_comment"),
        captures=ALL_CAPTURES,
        ctags_language="Kotlin",
    ),
    LanguageSpec(
        name="swift", display="Swift",
        extensions=(".swift",),
        module="tree_sitter_swift", distribution="tree-sitter-swift",
        grammar_license="MIT",
        comment_nodes=("comment", "multiline_comment"),
        captures=ALL_CAPTURES,
        ctags_language="Swift",
    ),
    LanguageSpec(
        name="powershell", display="PowerShell",
        extensions=(".ps1", ".psm1", ".psd1"),
        module="tree_sitter_powershell", distribution="tree-sitter-powershell",
        grammar_license="MIT",
        comment_nodes=("comment",),
        captures=("definition.class", "definition.function", "name", "doc", "import", "call"),
    ),
    LanguageSpec(
        name="matlab", display="MATLAB",
        extensions=(".m",),
        module="tree_sitter_matlab", distribution="tree-sitter-matlab",
        grammar_license="MIT",
        comment_nodes=("comment",),
        captures=("definition.class", "definition.function", "name", "doc", "call"),
        ctags_language="MatLab",
    ),
    # R is the gap in this table, and not a small one: a great deal of
    # the analysis code in health research is written in R. No R grammar
    # is published to the Python package index, so R files are read by
    # Universal Ctags where it is installed and recorded at the
    # file-metadata tier where it is not.
    LanguageSpec(
        name="r", display="R",
        extensions=(".r",),
        ctags_language="R",
    ),
    # Stata has neither a maintained grammar nor a Ctags parser, so its
    # files carry their path, language, and link and nothing more. A
    # pattern-matching reader was considered and left out: it would be a
    # parser that lies at the edges of the language.
    LanguageSpec(name="stata", display="Stata", extensions=(".do", ".ado")),
    # The languages below are here so a file written in one is named
    # rather than dropped. Extractium parses none of them; Universal
    # Ctags reads them when it is installed.
    LanguageSpec(name="c", display="C", extensions=(".c", ".h"), ctags_language="C"),
    LanguageSpec(
        name="cpp", display="C++",
        extensions=(".cpp", ".cc", ".cxx", ".hpp", ".hh"), ctags_language="C++",
    ),
    LanguageSpec(name="java", display="Java", extensions=(".java",), ctags_language="Java"),
    LanguageSpec(name="go", display="Go", extensions=(".go",), ctags_language="Go"),
    LanguageSpec(name="ruby", display="Ruby", extensions=(".rb",), ctags_language="Ruby"),
    LanguageSpec(name="php", display="PHP", extensions=(".php",), ctags_language="PHP"),
    LanguageSpec(name="rust", display="Rust", extensions=(".rs",), ctags_language="Rust"),
    LanguageSpec(name="perl", display="Perl", extensions=(".pl", ".pm"), ctags_language="Perl"),
    LanguageSpec(name="julia", display="Julia", extensions=(".jl",), ctags_language="Julia"),
    LanguageSpec(name="sas", display="SAS", extensions=(".sas",), ctags_language="SAS"),
    LanguageSpec(name="vba", display="Visual Basic", extensions=(".vb", ".bas")),
)

_BY_NAME = {spec.name: spec for spec in LANGUAGES}
_BY_EXTENSION = {extension: spec for spec in LANGUAGES for extension in spec.extensions}
_BY_FILENAME = {filename.lower(): spec for spec in LANGUAGES for filename in spec.filenames}


### Files That Hold Another Language Inside Them ###

# A container is not a language. Its prose is indexed as documentation
# and the code inside it is handed to the grammar it belongs to.
CONTAINER_EXTENSIONS = {
    ".ipynb": "notebook",
    ".rmd": "rmarkdown",
    ".qmd": "rmarkdown",
    ".lsp": "lua_server_pages",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
}

# Objective-C and MATLAB share the .m extension. These openings appear in
# Objective-C and in no MATLAB file, so a file carrying one is left
# unparsed rather than parsed as the wrong language.
OBJECTIVE_C_MARKERS = re.compile(
    r"^\s*(#import\b|#include\s*[<\"]|@interface\b|@implementation\b|@protocol\b)",
    re.M,
)


### Lookups ###

def _extension_of(path):
    """The lowercase extension of a repository path, with its dot."""
    return posixpath.splitext(path)[1].lower()


def language_for_path(path):
    """
    The language a file is written in, from its name alone.

    Args:
        path (str): a repository-relative path, with forward slashes.

    Returns:
        LanguageSpec | None: the language, or None when the name says
        nothing about it.
    """
    if not path:
        return None
    name = posixpath.basename(path).lower()
    if name in _BY_FILENAME:
        return _BY_FILENAME[name]
    return _BY_EXTENSION.get(_extension_of(name))


def language_named(name):
    """The LanguageSpec registered under a name, or None."""
    return _BY_NAME.get(name)


def container_for_path(path):
    """
    The kind of container a file is, or None when it holds one language.

    Returns:
        str | None: "notebook", "rmarkdown", "lua_server_pages", or
        "html".
    """
    return CONTAINER_EXTENSIONS.get(_extension_of(path or ""))


def is_code_path(path):
    """
    True when a file is source code worth a record of its own.

    A notebook, an R Markdown file, and a Lua Server Pages file all count,
    because code is pulled out of them. Markdown does not: it is prose,
    and the documentation path already indexes it in full.
    """
    if not path or path.endswith("/"):
        return False
    if container_for_path(path):
        return True
    return language_for_path(path) is not None


def looks_like_objective_c(text):
    """
    True when a .m file is Objective-C rather than MATLAB.

    The two languages share the extension, and parsing one as the other
    produces confident nonsense. A file that answers True here is
    recorded at the file-metadata tier instead.
    """
    return bool(OBJECTIVE_C_MARKERS.search(text or ""))


def query_path(spec):
    """
    Where a language's extraction rules live.

    Args:
        spec (LanguageSpec): the language.

    Returns:
        str: an absolute path to the query file. The file need not exist;
        a language with no query file is read at a lower tier.
    """
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries")
    return os.path.join(folder, spec.query_file)


def grammar_report():
    """
    One line per language, naming the grammar that reads it and the
    license that grammar is published under.

    Returns:
        tuple[str, ...]: lines in registry order, for a build report or a
        documentation page that has to state what was actually checked.
    """
    lines = []
    for spec in LANGUAGES:
        if spec.module:
            lines.append(f"{spec.display}: {spec.distribution} ({spec.grammar_license})")
        elif spec.ctags_language:
            lines.append(f"{spec.display}: no published grammar; Universal Ctags reads it")
        else:
            lines.append(f"{spec.display}: no published grammar and no Ctags parser")
    return tuple(lines)
