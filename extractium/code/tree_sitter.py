"""
Summary: Loads a compiled grammar, runs one language's query file over a
file's bytes, and turns the captures into symbol and import records. The
engine holds no knowledge of any particular language: what to look for
lives in the query files beside it, and which grammar reads what lives in
the registry. Nothing here executes, compiles, or imports the code it
reads -- Tree-sitter parses bytes. See docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/code/tree_sitter.py

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

import hashlib
import importlib
import os
import re

from extractium.code import languages
from extractium.code.records import Call, FileFacts, Import, Symbol

### Optional Parser Dependency ###

# The parser set is an optional install. A build without it still indexes
# a repository's documentation, and its code files are recorded at a
# lower tier, so the import failing is an ordinary condition rather than
# an error.
try:  # pragma: no cover - exercised by whichever install is in use
    import tree_sitter
except ImportError:  # pragma: no cover - exercised by whichever install is in use
    tree_sitter = None

# The name to install to get the engine itself, quoted in the one message
# that tells an operator what is missing.
PARSER_EXTRA = "extractium[code]"


### Limits ###

# Records carry structure, not source. These ceilings keep one enormous
# signature or one book-length docstring from crowding out the rest of an
# index, and they are generous: almost nothing real reaches them.
MAX_SIGNATURE_CHARS = 400
MAX_DOC_CHARS = 800

# A constant's value is kept only when it is short enough to be the
# answer rather than the source. A longer one becomes an ellipsis, so a
# table of several hundred entries is never copied into the index.
MAX_CONSTANT_VALUE_CHARS = 80

# A definition found deeper than this is a closure or a helper inside a
# helper. Recording it adds noise without adding a thing anybody searches
# for by name. Three levels rather than two because C# and Java put every
# class inside a namespace or a package, which spends one level before
# any code is reached.
MAX_NESTING = 3

# Node types that begin a definition's body in the grammars used here.
# Everything before the body is the signature, which is how a signature is
# read without a rule per language.
BODY_NODE_TYPES = frozenset({
    "block", "statement_block", "class_body", "function_body", "enum_body",
    "declaration_list", "compound_statement", "body", "do_statement",
    "class_declaration_list", "function_definition_body", "accessor_list",
    "create_query", "class_body_list", "protocol_body", "enum_class_body",
    "script_block_body",
})

# Comment markers, removed so documentation reads as prose. Kept in one
# place because every language spells the same idea differently.
COMMENT_MARKERS = re.compile(
    r"^\s*(?:///?!?|#+|--+|%+|;+|<#|#>|/\*+|\*+/|\*|\"\"\"|''')|(?:\*/|\"\"\"|''')\s*$"
)
WHITESPACE_RUN = re.compile(r"\s+")

# A name a language reserves for itself, such as __author__ in Python.
DUNDER_NAME = re.compile(r"^__[A-Za-z0-9_]+__$")

# Languages whose documentation is the first string inside the body,
# rather than a comment above the definition. Python is the only one in
# the registry that does this, and it is much the most common language in
# the repositories this reads.
DOCSTRING_LANGUAGES = frozenset({"python"})


### The Engine ###

class Engine:
    """
    Parses files with Tree-sitter and reports what they define.

    One engine is built per build and reused, because loading a grammar
    and compiling a query are the expensive parts and neither changes
    while a build runs.

    Args:
        progress (Callable[[str], None] | None): receives one line the
            first time a language cannot be loaded. A language that is
            missing is reported once, not once per file.

    Attributes:
        unavailable (dict[str, str]): language name to the reason it
            could not be used, so a report can say what was missed.
    """

    def __init__(self, progress=None):
        self.progress = progress or (lambda message: None)
        self._languages = {}
        self._queries = {}
        self._digests = {}
        self.unavailable = {}

    def query_digest(self, spec):
        """
        A short fingerprint of one language's extraction rules.

        The rules are this project's own, and changing them changes what
        a parse produces, so the fingerprint travels in the cache key: an
        edited query file reparses rather than reading back what the old
        one found.

        Args:
            spec (languages.LanguageSpec): the language.

        Returns:
            str: twelve hexadecimal characters, or an empty string when
            the language has no query file.
        """
        self.query(spec)
        return self._digests.get(spec.name, "")

    @property
    def installed(self):
        """True when the Tree-sitter engine itself is available."""
        return tree_sitter is not None

    ### Loading ###

    def language(self, spec):
        """
        The compiled grammar for one language.

        Args:
            spec (languages.LanguageSpec): the language to load.

        Returns:
            tree_sitter.Language | None: the grammar, or None when it is
            not installed, not published, or refuses to load. A grammar
            that will not load is a reason to read the file at a lower
            tier, never a reason to fail a build.
        """
        if spec.name in self._languages:
            return self._languages[spec.name]
        grammar = None
        if not self.installed:
            self._note(spec, f"the parser set is not installed; install {PARSER_EXTRA} to use it")
        elif not spec.module:
            self._note(spec, "no grammar is published for this language")
        else:
            try:
                module = importlib.import_module(spec.module)
                grammar = tree_sitter.Language(getattr(module, spec.factory)())
            except (ImportError, AttributeError, TypeError, ValueError) as e:
                self._note(spec, f"its grammar could not be loaded ({e})")
        self._languages[spec.name] = grammar
        return grammar

    def query(self, spec):
        """
        The compiled extraction rules for one language.

        Returns:
            tree_sitter.Query | None: the query, or None when the
            language has no query file or the file does not match the
            installed grammar. A query written for a different version of
            a grammar fails here, loudly once, rather than silently
            returning nothing for every file.
        """
        if spec.name in self._queries:
            return self._queries[spec.name]
        compiled = None
        grammar = self.language(spec)
        if grammar is not None:
            path = languages.query_path(spec)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                self._digests[spec.name] = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
                compiled = tree_sitter.Query(grammar, text)
            except OSError:
                # A language that declares no captures has no extraction
                # rules on purpose: HTML and Markdown are read for the
                # code inside them, not for definitions of their own.
                if spec.captures:
                    self._note(spec, "it has no query file, so only its outline is recorded")
            except Exception as e:  # tree_sitter.QueryError and anything it wraps
                self._note(spec, f"its query file does not match the installed grammar ({e})")
        self._queries[spec.name] = compiled
        return compiled

    def _note(self, spec, reason):
        """Records why a language cannot be read, and says so once."""
        if spec.name in self.unavailable:
            return
        self.unavailable[spec.name] = reason
        self.progress(f"  {spec.display}: {reason}")

    ### Reading One File ###

    def analyze(self, path, text, spec=None):
        """
        Reads one file and reports what it defines, imports, and calls.

        Args:
            path (str): the repository-relative path, used in the record
                and to name the language when spec is not given.
            text (str): the file's decoded content.
            spec (languages.LanguageSpec | None): the language to parse
                it as. Taken from the path when not given, which is what
                an ordinary file wants; an embedded block passes the
                language its fence declared.

        Returns:
            records.FileFacts: the file's records, at the best tier this
            machine could reach. A file that cannot be parsed still comes
            back, carrying its path, its language, and its length. A
            missing grammar is reported through the tier on that record
            rather than raised, because one unreadable file must not end
            a build.
        """
        spec = spec or languages.language_for_path(path)
        line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        if spec is None:
            return FileFacts(path=path, line_count=line_count, tier=languages.TIER_METADATA)

        outline = FileFacts(
            path=path, language=spec.name, display=spec.display,
            tier=languages.TIER_METADATA, line_count=line_count,
        )
        query = self.query(spec)
        if query is None:
            return outline
        # A .m file that opens like Objective-C is left alone: the MATLAB
        # grammar would parse it into confident nonsense.
        if spec.name == "matlab" and languages.looks_like_objective_c(text):
            return outline

        source = text.encode("utf-8", "replace")
        try:
            tree = tree_sitter.Parser(self.language(spec)).parse(source)
            matches = tree_sitter.QueryCursor(query).matches(tree.root_node)
        except (ValueError, TypeError, RecursionError) as e:
            self._note(spec, f"a file could not be parsed ({e})")
            return outline

        symbols, imports, top_level = self._records(matches, source, spec)
        return FileFacts(
            path=path, language=spec.name, display=spec.display,
            tier=languages.TIER_TREE_SITTER,
            symbols=symbols, imports=imports,
            calls=tuple(Call(caller="", name=name) for name in top_level),
            doc=_file_documentation(tree.root_node, source, spec),
            line_count=line_count,
            recovered=bool(tree.root_node.has_error),
        )

    ### Turning Captures Into Records ###

    def _records(self, matches, source, spec):
        """
        Sorts one file's query matches into symbols and imports.

        Definitions are collected first so that a call or a nested
        definition can be attributed to the definition it sits inside,
        which is a question about byte ranges rather than about any
        particular language.
        """
        definitions = []
        calls = []
        imports = []
        for _, captures in matches:
            kind = _definition_kind(captures)
            if kind:
                node = _first(captures, f"definition.{kind}")
                name = _text(_first(captures, "name"), source)
                if node is not None and name:
                    definitions.append((node, kind, name, _first(captures, "doc")))
                continue
            if "call" in captures or "call.name" in captures:
                node = _first(captures, "call.name") or _first(captures, "call")
                name = _text(node, source)
                if name:
                    calls.append((node.start_byte, _call_name(name)))
                continue
            if "import" in captures:
                statement = _first(captures, "import")
                target = _text(_first(captures, "import.source"), source)
                brought = _text(_first(captures, "import.name"), source)
                imports.append(_import_record(statement, target, brought, source))

        definitions.sort(key=lambda item: (item[0].start_byte, -item[0].end_byte))
        symbols = self._symbols(definitions, calls, source, spec)
        top_level = _calls_within_file(definitions, calls)
        return symbols, _merge_imports(imports), top_level

    def _symbols(self, definitions, calls, source, spec):
        """
        One symbol per definition, each carrying what it calls.

        A definition inside another is recorded with its enclosing symbol
        named, so a method reads as belonging to its class rather than as
        a loose function that happens to share a file with one.
        """
        symbols = []
        for index, (node, kind, name, doc_node) in enumerate(definitions):
            ancestors = [
                other for other in definitions[:index]
                if other[0].start_byte <= node.start_byte and other[0].end_byte >= node.end_byte
            ]
            if len(ancestors) > MAX_NESTING:
                continue
            # Names like __author__ and __license__ hold a file's header
            # boilerplate. Every file in a project carries the same ones,
            # so indexing them buries the definitions somebody searched for.
            if kind == "constant" and DUNDER_NAME.match(name):
                continue
            parent = ancestors[-1] if ancestors else None
            if kind == "function" and parent is not None and parent[1] == "class":
                kind = "method"
            inner = [
                other[0] for other in definitions[index + 1:]
                if other[0].start_byte >= node.start_byte and other[0].end_byte <= node.end_byte
            ]
            own_calls = _calls_within(node, inner, calls)
            symbols.append(Symbol(
                name=name,
                kind=kind,
                signature=_signature(node, source, kind, spec.comment_nodes),
                doc=_documentation(node, doc_node, source, spec),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent=_qualified(parent, definitions) if parent else "",
                calls=own_calls,
                language=spec.name,
                tier=languages.TIER_TREE_SITTER,
            ))
        return tuple(symbols)


### Reading Nodes ###

def _first(captures, name):
    """The first node captured under a name, or None."""
    nodes = captures.get(name) or ()
    return nodes[0] if nodes else None


def _text(node, source):
    """The source text of a node, collapsed to one line, or an empty string."""
    if node is None:
        return ""
    return WHITESPACE_RUN.sub(" ", source[node.start_byte:node.end_byte].decode("utf-8", "replace")).strip()


def _definition_kind(captures):
    """Which kind of definition a match is, or an empty string when it is not one."""
    for name in captures:
        if name.startswith("definition."):
            return name.split(".", 1)[1]
    return ""


def _call_name(text):
    """
    The name a call names, without its receiver.

    A call written as `self.save()` or `utils.clean()` is recorded under
    the name being called. The receiver is kept out because nothing
    static says what it holds, and a name is what a reader searches for.
    """
    bare = text.split("(", 1)[0].strip()
    for separator in (".", "::", ":", "->", "$", "@"):
        bare = bare.rsplit(separator, 1)[-1]
    return bare.strip()


def _calls_within(node, inner, calls):
    """
    The names called inside a definition but not inside one nested in it,
    in the order they first appear, each recorded once.
    """
    seen = []
    for start, name in calls:
        if not (node.start_byte <= start < node.end_byte):
            continue
        if any(child.start_byte <= start < child.end_byte for child in inner):
            continue
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def _calls_within_file(definitions, calls):
    """
    The names called at the top level of a file, outside every
    definition, in the order they first appear.

    This is what a file does when it is loaded rather than when it is
    called, which is often the most important thing about a script.
    """
    seen = []
    for start, name in calls:
        if any(node.start_byte <= start < node.end_byte for node, _, _, _ in definitions):
            continue
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def _qualified(parent, definitions):
    """The enclosing symbol's name, with its own enclosing symbol when it has one."""
    node, _, name, _ = parent
    outer = [
        other for other in definitions
        if other[0].start_byte < node.start_byte and other[0].end_byte >= node.end_byte
    ]
    return f"{outer[-1][2]}.{name}" if outer else name


def _body_of(node):
    """
    The node's body, or None when the grammar does not mark one.

    A definition written as an assignment -- `const load = async () => ...`
    in JavaScript, `f <- function() ...` in R -- holds its body one level
    down, on the function it was given, so that level is looked at too.
    """
    body = node.child_by_field_name("body")
    if body is not None:
        return body
    for child in node.named_children:
        if child.type in BODY_NODE_TYPES:
            return child
    for child in node.named_children:
        inner = child.child_by_field_name("body")
        if inner is not None:
            return inner
        for grandchild in child.named_children:
            if grandchild.type in BODY_NODE_TYPES:
                return grandchild
    return None


def _declaration_of(node):
    """
    The whole declaration a definition belongs to.

    A class written `export class Compendium` and a function written
    `@app.route(...)` above `def index()` are both one declaration to a
    reader, and the comment that documents them sits above the first
    line of it, not above the definition inside it.
    """
    current = node
    parent = current.parent
    while parent is not None and parent.parent is not None and (
        parent.start_byte == current.start_byte or parent.end_byte == current.end_byte
    ):
        current = parent
        parent = current.parent
    return current


def _signature(node, source, kind="", comment_nodes=()):
    """
    Everything the source writes before the body: the name, the
    parameters, and any declared types.

    Reading the signature as "the definition up to its body" is what
    keeps this file free of a rule per language, and it is also what
    guarantees no body is ever recorded.

    A constant has no body to stop at, and its value can be a table of
    several hundred lines, so a long value is replaced by an ellipsis. A
    short one is kept: "PAGE_SIZE = 100" answers the question a reader
    came with.
    """
    body = _body_of(node)
    end = body.start_byte if body is not None else node.end_byte
    # MATLAB puts a function's documentation between the signature and
    # the body, so a comment inside the definition ends the signature too.
    for child in node.named_children:
        if child.type in comment_nodes and child.start_byte < end:
            end = child.start_byte
            break
    text = source[node.start_byte:min(end, node.end_byte)].decode("utf-8", "replace")
    text = WHITESPACE_RUN.sub(" ", text).strip().rstrip("{").strip()
    if kind == "constant":
        name, separator, value = text.partition("=")
        if separator and len(value.strip()) > MAX_CONSTANT_VALUE_CHARS:
            text = f"{name.strip()} = ..."
    if len(text) > MAX_SIGNATURE_CHARS:
        text = text[:MAX_SIGNATURE_CHARS].rstrip() + "..."
    return text


def _documentation(node, doc_node, source, spec):
    """
    The documentation a person wrote for a definition.

    Three places are read, in this order: what the query captured, the
    string a docstring language puts at the top of the body, and the
    comment block directly above the definition. Nothing is written that
    a person did not.
    """
    if doc_node is not None:
        return _clean_documentation(source[doc_node.start_byte:doc_node.end_byte])
    if spec.name in DOCSTRING_LANGUAGES:
        docstring = _docstring_of(node)
        if docstring is not None:
            return _clean_documentation(source[docstring.start_byte:docstring.end_byte])
    return _clean_documentation(_comments_above(node, source, spec))


def _file_documentation(root, source, spec):
    """
    The documentation a file opens with.

    A Python module writes it as a string at the top; most other
    languages write it as the comment block before anything else. Both
    are quotations from the file, which is what makes them safe to use as
    a summary.
    """
    if spec.name in DOCSTRING_LANGUAGES:
        docstring = _string_opening(root)
        if docstring is not None:
            return _clean_documentation(source[docstring.start_byte:docstring.end_byte])
    collected = []
    for child in root.named_children:
        if child.type not in spec.comment_nodes:
            break
        if collected and child.start_point[0] - collected[-1][1] > 1:
            break
        line = source[child.start_byte:child.end_byte]
        # The first line of a script names the program that runs it. It
        # is a comment to the grammar and documentation to nobody.
        if line.startswith(b"#!") and not collected:
            continue
        collected.append((line, child.end_point[0]))
    return _clean_documentation(b"\n".join(text for text, _ in collected))


def _docstring_of(node):
    """The string opening a definition's body, or None."""
    body = _body_of(node)
    return _string_opening(body) if body is not None else None


def _string_opening(node):
    """The string a block starts with, or None when it starts with anything else."""
    if node is None or not node.named_children:
        return None
    first = node.named_children[0]
    if first.type == "string":
        return first
    if first.type == "expression_statement" and first.named_children:
        inner = first.named_children[0]
        return inner if inner.type == "string" else None
    return None


def _comments_above(node, source, spec):
    """
    The run of comment lines directly above a definition.

    "Directly above" means no blank line between them, which is how a
    person signals that a comment belongs to what follows rather than to
    what came before.
    """
    if not spec.comment_nodes:
        return b""
    collected = []
    current = _declaration_of(node)
    while True:
        previous = current.prev_named_sibling
        if previous is None or previous.type not in spec.comment_nodes:
            break
        if current.start_point[0] - previous.end_point[0] > 1:
            break
        collected.append(source[previous.start_byte:previous.end_byte])
        current = previous
    return b"\n".join(reversed(collected))


def _clean_documentation(raw):
    """
    Documentation as prose: comment markers removed, blank lines dropped,
    and cut to a length an index can carry.
    """
    if not raw:
        return ""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    lines = []
    for line in text.splitlines():
        stripped = COMMENT_MARKERS.sub("", line).strip()
        stripped = COMMENT_MARKERS.sub("", stripped).strip()
        if stripped:
            lines.append(stripped)
    documentation = " ".join(lines).strip()
    if len(documentation) > MAX_DOC_CHARS:
        documentation = documentation[:MAX_DOC_CHARS].rstrip() + "..."
    return documentation


def _import_record(statement, target, brought, source):
    """
    One Import from a captured statement and what it brings in.

    "from package import module" names two things, and the file it means
    is the pair of them, so both are joined here when the query captured
    both.
    """
    target = (target or "").strip("\"'`")
    brought = (brought or "").strip("\"'`")
    if brought and not target.startswith(("/", "\"", "'")):
        target = f"{target}.{brought}" if target and not target.endswith(".") else target + brought
    return Import(
        statement=_text(statement, source),
        target=target,
        line=(statement.start_point[0] + 1) if statement is not None else 1,
    )


def _merge_imports(imports):
    """
    One record per import statement, keeping the most specific target.

    A statement that names a package and a module inside it matches twice,
    once for each half. The half that names more is the one worth keeping:
    "package.module" can be matched to a file, while "package" alone
    cannot.
    """
    best = {}
    for item in imports:
        current = best.get((item.line, item.statement))
        if current is None or len(item.target) > len(current.target):
            best[(item.line, item.statement)] = item
    return tuple(best.values())


def available_languages():
    """
    The languages whose grammar and query file are both present on this
    machine.

    Returns:
        tuple[str, ...]: registry names, in registry order. Useful in a
        report and in a test that must know what this install can do
        rather than what the registry wishes for.
    """
    engine = Engine()
    ready = []
    for spec in languages.LANGUAGES:
        if spec.module and os.path.exists(languages.query_path(spec)) and engine.query(spec):
            ready.append(spec.name)
    return tuple(ready)
