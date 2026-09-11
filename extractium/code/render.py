"""
Summary: Turns code records into the text a search index holds. Every
line here is either a quotation from the file or a count off the parse,
which is what keeps a file summary honest without a language model. The
same records always render the same text, so an unchanged repository
produces an unchanged index. See docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/code/render.py

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

from extractium.code import languages
from extractium.code.records import CONFIDENCE_UNRESOLVED

### Where A Summary Comes From ###

# The four places a summary may be taken from, best first. They are
# recorded on the file record so a reader can weigh what they are given.
SUMMARY_DOCUMENTATION = "documentation"
SUMMARY_HEADER = "header"
SUMMARY_README = "readme"
SUMMARY_STRUCTURE = "structure"

# This organization's file header carries a written summary. A repository
# following the convention therefore already holds a sentence about every
# file, written by the person who wrote the file.
HEADER_SUMMARY = re.compile(
    r"^[^\n]*?Summary:\s*(.+?)"
    r"(?=\n\s*\S*\s*(?:Notes|Author|Author\(s\)|Created|Last Modified|Copyright):|\n\s*\n|\Z)",
    re.S | re.M,
)

# How much of a README is quoted when nothing closer to the file exists.
MAX_README_CHARS = 400

# How much of a file's own documentation becomes its summary.
MAX_SUMMARY_CHARS = 600

WHITESPACE_RUN = re.compile(r"\s+")

# A summary written in a header runs over several comment lines, and each
# one carries its language's comment marker. They are not part of the
# sentence.
LEADING_MARKER = re.compile(r"^\s*(?://+|#+|--+|%+|\*+|;+)\s?", re.M)


def _without_markers(text):
    """A run of comment lines as one sentence, with the markers removed."""
    return LEADING_MARKER.sub("", text or "")


def summary_for(facts, text="", readme=""):
    """
    A plain sentence about one file, and where it came from.

    Four sources are read, in order: the file's own documentation, the
    `Summary:` line in its header, the README in its folder, and a count
    of what the parser found. The first three are quotations and the
    fourth is arithmetic. **None of them is a guess**: a summary must
    never assert something nobody observed.

    Args:
        facts (records.FileFacts): what the analysis found.
        text (str): the file's content, read for its header.
        readme (str): the README in the file's own folder, when there is
            one.

    Returns:
        tuple[str, str]: the summary, and which of the SUMMARY_ values it
        came from.
    """
    if facts.doc:
        return _shorten(facts.doc, MAX_SUMMARY_CHARS), SUMMARY_DOCUMENTATION
    header = HEADER_SUMMARY.search(text or "")
    if header:
        return _shorten(_without_markers(header.group(1)), MAX_SUMMARY_CHARS), SUMMARY_HEADER
    if readme and readme.strip():
        quoted = _shorten(readme, MAX_README_CHARS)
        folder = posixpath.dirname(facts.path) or "the repository root"
        return f"From the README in {folder}: {quoted}", SUMMARY_README
    return _structure_summary(facts), SUMMARY_STRUCTURE


def _structure_summary(facts):
    """
    A sentence counted off the parse, for a file that documents itself
    nowhere.

    It says only what was observed: how many of each kind of definition
    the file holds, how many files it brings in, and whether it runs
    anything when it is loaded.
    """
    language = facts.display or "Unknown-language"
    if facts.tier == languages.TIER_METADATA:
        return f"{language} file of {facts.line_count} line(s). It was not parsed, so nothing inside it is recorded."

    counts = {}
    for symbol in facts.symbols:
        counts[symbol.kind] = counts.get(symbol.kind, 0) + 1
    pieces = [
        f"{counts[kind]} {kind}{'es' if kind == 'class' and counts[kind] != 1 else 's' if counts[kind] != 1 else ''}"
        for kind in ("class", "function", "method", "type", "constant", "module")
        if counts.get(kind)
    ]
    sentence = f"{language} file of {facts.line_count} line(s)"
    sentence += f" defining {', '.join(pieces)}." if pieces else " defining nothing by name."
    local = [item for item in facts.imports if item.path]
    external = [item for item in facts.imports if item.external]
    if local:
        sentence += f" It brings in {len(local)} other file(s) from this repository."
    if external:
        sentence += f" It uses {len(external)} package(s) from outside it."
    if facts.calls and any(not call.caller for call in facts.calls):
        sentence += " It runs code when it is loaded rather than only when it is called."
    return sentence


def _shorten(text, ceiling):
    """One line of text, cut to a ceiling on a word boundary."""
    single = WHITESPACE_RUN.sub(" ", text or "").strip()
    if len(single) <= ceiling:
        return single
    cut = single[:ceiling].rsplit(" ", 1)[0]
    return f"{cut}..."


### One File ###

def file_text(facts, repository, url):
    """
    The indexed text of one code file.

    Args:
        facts (records.FileFacts): the file's records.
        repository (str): "owner/name".
        url (str): where a reader can open the file.

    Returns:
        str: the record, as plain text. No source body appears in it.
    """
    lines = [
        f"{repository}: {facts.path}",
        "",
        facts.summary,
        "",
        f"Language: {facts.display or 'not recognized'}",
        f"Read by: {facts.tier}",
        f"Length: {facts.line_count} line(s)",
        f"Address: {url}",
    ]
    if facts.recovered:
        lines.append(
            "The parser met a syntax error in this file and carried on, so what "
            "follows is what could be read rather than the whole file."
        )

    definitions = [f"{symbol.kind} {symbol.signature or symbol.name}" for symbol in facts.symbols]
    lines += _section("Defines", definitions)
    lines += _section("Brings in", [_import_line(item) for item in facts.imports])
    lines += _section("Reaches into", sorted({
        call.path for call in facts.calls if call.path and call.path != facts.path
    }))
    lines += _section("Imported by", facts.imported_by)
    lines += _section("Called by", facts.called_by)
    lines += _section("Tests here", [
        symbol.qualified_name for symbol in facts.symbols if symbol.is_test(facts.path)
    ])
    return "\n".join(lines).strip() + "\n"


def _import_line(item):
    """One import, as a reader would want it read back."""
    if item.path:
        return f"{item.target or item.statement} (this repository: {item.path})"
    if item.external:
        return f"{item.target} (a package from outside this repository)"
    return item.statement


def _section(heading, items):
    """A headed list, or nothing at all when there is nothing to list."""
    kept = [item for item in items if item]
    if not kept:
        return []
    return ["", f"{heading}:"] + [f"- {item}" for item in kept]


### One Symbol ###

def symbol_text(symbol, facts, repository, url):
    """
    The indexed text of one definition.

    Args:
        symbol (records.Symbol): the definition.
        facts (records.FileFacts): the file it was found in.
        repository (str): "owner/name".
        url (str): where a reader can open its lines.

    Returns:
        str: the record. It holds the signature, the documentation
        somebody wrote, and where to read the rest; never the body.
    """
    lines = [
        f"{repository}: {symbol.qualified_name} ({symbol.kind} in {facts.path})",
        "",
        symbol.doc or f"No documentation is written for this {symbol.kind}.",
        "",
        f"Signature: {symbol.signature or symbol.name}",
        f"Language: {facts.display or 'not recognized'}",
        f"Defined in: {facts.path}, line(s) {symbol.start_line} to {symbol.end_line}",
        f"Read by: {symbol.tier or facts.tier}",
        f"Address: {url}",
    ]
    if symbol.parent:
        lines.append(f"Defined inside: {symbol.parent}")
    if symbol.is_test(facts.path):
        lines.append("This is a test, so it also describes how the thing it tests is meant to behave.")

    calls = [_call_line(call) for call in facts.calls if call.caller == symbol.qualified_name]
    lines += _section("Calls", calls)
    lines += _section("Available to this file", [
        item.target or item.statement for item in facts.imports
    ])
    return "\n".join(lines).strip() + "\n"


def _call_line(call):
    """One call, with how sure the analysis is about where it lands."""
    if call.confidence == CONFIDENCE_UNRESOLVED:
        return f"{call.name} (unresolved: nothing static says where this lands)"
    return f"{call.name} ({call.confidence}: {call.path})"


### One Repository ###

def repository_lines(facts_list, unavailable=()):
    """
    What the repository map says about the code in a repository.

    Args:
        facts_list (Sequence[records.FileFacts]): every analyzed file.
        unavailable (Iterable[str]): languages that could not be read on
            this machine, and why.

    Returns:
        list[str]: lines to append to the repository summary. A reader
        searching the finished index sees the coverage without going back
        to the build log.
    """
    if not facts_list:
        return []
    tiers = {}
    for facts in facts_list:
        tiers[facts.tier] = tiers.get(facts.tier, 0) + 1
    symbols = sum(len(facts.symbols) for facts in facts_list)
    spoken = {facts.display for facts in facts_list if facts.display}

    lines = [
        "",
        f"Code files analyzed: {len(facts_list)}, holding {symbols} definition(s).",
        "Languages: " + (", ".join(sorted(spoken)) or "none recognized") + ".",
    ]
    for tier in languages.TIER_ORDER:
        if tiers.get(tier):
            lines.append(f"Read by {tier}: {tiers[tier]} file(s).")
    for reason in sorted(unavailable):
        lines.append(f"Not read: {reason}")

    entries = [
        f"{facts.path} -- {facts.summary}"
        for facts in sorted(facts_list, key=lambda f: (-len(f.symbols), f.path))[:40]
    ]
    lines += _section("Main files", entries)
    return lines
