"""
Summary: The second parser. Universal Ctags reads the languages no
published grammar covers -- R above all -- and is used only where
Tree-sitter cannot go. It is optional and never bundled: a machine
without it still indexes those files at the file-metadata tier. Ctags
produces symbols and nothing else, so no import graph and no call graph
is ever built from its output. See docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/code/ctags.py

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

import json
import os
import shutil
import subprocess
import tempfile
import uuid

from extractium.code import languages
from extractium.code.records import FileFacts, Symbol

### How Ctags Is Run ###

# The program looked for on the path. Several unrelated programs have
# been called ctags over the years, so finding one proves nothing until
# it says which it is.
EXECUTABLE = "ctags"

# The banner Universal Ctags prints. Exuberant Ctags and the ctags that
# ships with some editors print something else, speak no JSON, and are
# not used.
UNIVERSAL_BANNER = "Universal Ctags"

# Reading one file must never hang a build.
TIMEOUT_SECONDS = 20

# A file producing more tags than this is generated, and its tags are of
# no use to a reader searching for a name.
MAX_TAGS = 2_000

# What Ctags calls a kind of symbol, mapped to the kinds a record may
# carry. A kind not listed here is not recorded: an invented mapping
# would put a claim in the index that nothing observed.
KIND_MAP = {
    "function": "function", "func": "function", "subroutine": "function",
    "procedure": "function", "macro": "function", "singletonMethod": "method",
    "method": "method", "member": "method", "property": "method",
    "class": "class", "struct": "class", "record": "class", "object": "class",
    "interface": "type", "enum": "type", "typedef": "type", "type": "type",
    "union": "type", "alias": "type", "table": "type", "view": "type",
    "constant": "constant", "const": "constant", "enumerator": "constant",
    "namespace": "module", "module": "module", "package": "module",
    "library": "module",
}


class Ctags:
    """
    Finds Universal Ctags and reads files with it.

    The answer to "is it here, and is it the right program?" is worked
    out once and kept for the build, because the question costs a process
    launch and the answer cannot change while a build runs.

    Args:
        progress (Callable[[str], None] | None): receives one line when
            Ctags is looked for and one line when a file cannot be read.
        executable (str | Sequence[str] | None): the program to run,
            either as a path or as the front of an argument array. A
            caller passes this in a test; a build leaves it alone and the
            program is found on the path.

    Attributes:
        version (str): the banner the program printed, or an empty string
            when none was found.
    """

    def __init__(self, progress=None, executable=None):
        self.progress = progress or (lambda message: None)
        self._command = _as_command(executable)
        self._checked = False
        self._usable = False
        self.version = ""

    ### Finding It ###

    @property
    def available(self):
        """
        True when Universal Ctags is installed and speaks JSON.

        Three things are confirmed, in order: a program called ctags is
        on the path, it says it is Universal Ctags, and it offers JSON
        output. A program failing any of them is not used, because
        reading another program's output as if it were this one's is how
        invented records get into an index.
        """
        if self._checked:
            return self._usable
        self._checked = True
        if not self._command:
            found = shutil.which(EXECUTABLE)
            if not found:
                self.progress(
                    "  Universal Ctags is not installed; unparsed files keep their outline"
                )
                return False
            self._command = [found]
        try:
            result = subprocess.run(
                self._command + ["--version"],
                capture_output=True, text=True, timeout=TIMEOUT_SECONDS, shell=False,
            )
        except (OSError, subprocess.SubprocessError) as e:
            self.progress(f"  Universal Ctags could not be run ({e})")
            return False
        banner = (result.stdout or "").strip().splitlines()
        self.version = banner[0] if banner else ""
        if UNIVERSAL_BANNER not in (result.stdout or ""):
            self.progress(
                f"  the ctags on this machine is not Universal Ctags ({self.version or 'no version'}); "
                "it is not used"
            )
            return False
        if "json" not in (result.stdout or "").lower():
            self.progress(f"  {self.version} was built without JSON output; it is not used")
            return False
        self._usable = True
        self.progress(f"  reading unparsed languages with {self.version}")
        return True

    ### Reading One File ###

    def analyze(self, path, text, spec=None):
        """
        Reads one file with Ctags and reports the symbols it names.

        The file's content usually exists only in memory, so it is
        written to a temporary file first. **The repository's own path
        never names that file and never chooses its folder**: a path out
        of a repository is untrusted, and letting it pick a name is how a
        traversal or a shell character gets a foothold. The temporary
        name is generated here and carries only the extension, which is
        how Ctags knows the language.

        Args:
            path (str): the repository-relative path, for the record.
            text (str): the file's content.
            spec (languages.LanguageSpec | None): the language, taken
                from the path when not given.

        Returns:
            records.FileFacts | None: the symbols Ctags named, or None
            when Ctags is unavailable, does not read this language, or
            produced nothing usable. Imports and calls are always empty:
            Ctags does not produce them, and inventing them would put
            relationships in the index that nobody observed.
        """
        spec = spec or languages.language_for_path(path)
        if spec is None or not spec.ctags_language or not self.available:
            return None
        temporary = self._write_temporary(text, spec)
        if temporary is None:
            return None
        try:
            tags = self._run(temporary, spec)
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        if tags is None:
            return None
        return FileFacts(
            path=path, language=spec.name, display=spec.display,
            tier=languages.TIER_CTAGS,
            symbols=tags,
            line_count=text.count("\n") + (1 if text and not text.endswith("\n") else 0),
        )

    def _write_temporary(self, text, spec):
        """
        Writes one file's content where Ctags can read it, under a name
        this code chose.

        Returns:
            str | None: the temporary path, or None when it could not be
            written.
        """
        extension = spec.extensions[0] if spec.extensions else ".txt"
        name = os.path.join(tempfile.gettempdir(), f"extractium-{uuid.uuid4().hex}{extension}")
        try:
            with open(name, "w", encoding="utf-8", errors="replace") as f:
                f.write(text)
        except OSError as e:
            self.progress(f"  a file could not be handed to Universal Ctags ({e})")
            return None
        return name

    def _run(self, temporary, spec):
        """
        Runs Ctags over one temporary file and reads what it printed.

        The program is invoked with an argument array. There is no shell,
        so nothing in a file name is ever interpreted as a command. Ctags
        is also told to read no configuration file: a repository, or the
        machine running the build, may carry one that defines parsers
        this code knows nothing about.
        """
        command = self._command + [
            "--options=NONE",
            "--output-format=json",
            "--fields=+nKS",
            f"--languages={spec.ctags_language}",
            "-f", "-",
            temporary,
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                timeout=TIMEOUT_SECONDS, shell=False,
            )
        except (OSError, subprocess.SubprocessError) as e:
            self.progress(f"  Universal Ctags could not read a file ({e})")
            return None
        return _symbols_from(result.stdout, spec)


def _as_command(executable):
    """
    The program to run, as an argument array.

    A caller may name one program or the front of a command. Either way
    it becomes a list, because a list is what is handed to the operating
    system: there is no shell anywhere in this file, so nothing in a file
    name is ever read as a command.
    """
    if not executable:
        return []
    if isinstance(executable, str):
        return [executable]
    return [str(part) for part in executable]


def _symbols_from(output, spec):
    """
    The symbols in one Ctags run's output.

    Everything here arrived from another program reading a file nobody
    controls, so each line is checked before any of it is used: it must
    be one JSON object, of the type Ctags uses for a tag, carrying a name
    and a kind this code recognizes. A line failing any of that is
    dropped rather than guessed at.

    Args:
        output (str): what Ctags printed.
        spec (languages.LanguageSpec): the language it was reading.

    Returns:
        tuple[records.Symbol, ...]: the symbols, in the order they were
        printed, or an empty tuple when nothing usable came back.
    """
    symbols = []
    seen = set()
    for line in (output or "").splitlines():
        if len(symbols) >= MAX_TAGS:
            break
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            tag = json.loads(line)
        except ValueError:
            continue
        if not isinstance(tag, dict) or tag.get("_type") != "tag":
            continue
        name = tag.get("name")
        kind = KIND_MAP.get(tag.get("kind"))
        if not isinstance(name, str) or not name.strip() or kind is None:
            continue
        start = tag.get("line")
        start = start if isinstance(start, int) and start > 0 else 1
        scope = tag.get("scope")
        parent = scope.strip() if isinstance(scope, str) else ""
        key = (name, kind, start)
        if key in seen:
            continue
        seen.add(key)
        signature = tag.get("signature")
        symbols.append(Symbol(
            name=name.strip(),
            kind="method" if kind == "function" and parent else kind,
            signature=f"{name.strip()}{signature}" if isinstance(signature, str) else name.strip(),
            start_line=start,
            end_line=start,
            parent=parent,
            language=spec.name,
            tier=languages.TIER_CTAGS,
        ))
    return tuple(symbols)
