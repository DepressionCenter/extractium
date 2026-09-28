"""
Summary: The record every build leaves behind: one JSON file per run,
written on success and on failure alike, holding what the summary
prints. When the build started and ended in UTC, how long it took, the
tool version, a digest of the settings file, the exit status, the
counts of pages, sections, and windows per source, what each output
wrote and how large it is, and the notes and errors. A history of
builds is read from these files. A record never holds a page's text,
an address list, or a credential.

This file is part of Extractium™
extractium/core/runs.py

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

import hashlib
import json
import os
import pathlib
from datetime import datetime, timezone

from extractium import __version__
from extractium.adapters.base import page_address
from extractium.adapters.container import LICENSE_NOTICE
from extractium.core.build import utc_now

### Constants ###

# The layout of a record. A reader that meets another number knows the
# fields may differ.
RECORD_VERSION = 1

# The two outcomes a record reports, beside the exit code.
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

# The most files one output has named one by one. Past this the output is
# recorded as a folder with a count and a total size, the same rule the
# printed summary follows, because an output that writes one file per
# page writes thousands and the history shows the figures, not the names.
FILES_NAMED = 8


### File Names ###

def record_file_name(started_at, existing=()):
    """
    The file a record is written to, named after the moment the build
    started.

    Colons are replaced with hyphens because Windows refuses them in a
    file name, and the name still sorts by time. A second build started
    in the same second takes a numbered suffix rather than replacing the
    first.

    Args:
        started_at (str): the start time, UTC, ISO 8601 with a Z suffix.
        existing (Iterable[str]): file names already in the folder.

    Returns:
        str: the file name, ending in `.json`.
    """
    stem = started_at.replace(":", "-")
    taken = set(existing)
    name = f"{stem}.json"
    counter = 2
    while name in taken:
        name = f"{stem}-{counter}.json"
        counter += 1
    return name


def digest_of_file(path):
    """
    The SHA-256 digest of a file's bytes, as hexadecimal.

    Args:
        path (str | pathlib.Path): the file.

    Returns:
        str | None: the digest, or None when the file cannot be read,
        which is what a record says about a settings file that was
        missing.
    """
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


### The Record ###

class RunRecorder:
    """
    Collects the figures of one build as it runs and writes the record at
    the end.

    Made before the settings file is read, with the default folder, and
    pointed at the configured folder once the settings load, so a build
    that fails on its settings file still leaves a record. Every method
    is cheap and none can fail the build: the write itself is the one
    step that touches the disk, and its caller decides what a failure
    there means.
    """

    def __init__(self, runs_dir, started_at=None):
        """
        Args:
            runs_dir (str | pathlib.Path): the folder to write into.
            started_at (str | None): the start time, UTC, ISO 8601 with a
                Z suffix. None takes the current time.
        """
        self.runs_dir = pathlib.Path(runs_dir)
        self.started_at = started_at or utc_now()
        self.config_path = None
        self.config_sha256 = None
        self.max_pages = None
        self.name = None
        self.built_at = None
        self.totals = None
        self.sources = []
        self.outputs = []
        self.notices = []
        self.notes = []
        self.errors = []

    def point_at(self, runs_dir):
        """Changes the folder the record will be written to, once the settings name one."""
        self.runs_dir = pathlib.Path(runs_dir)

    def note_config(self, path, max_pages=None):
        """
        Records which settings file the build read and its digest, so a
        later reader can tell whether two builds ran from the same file.

        Args:
            path (str | pathlib.Path): the settings file as given.
            max_pages (int | None): the page ceiling in force, when known.
        """
        self.config_path = str(path)
        self.config_sha256 = digest_of_file(path)
        if max_pages is not None:
            self.max_pages = max_pages

    def note_compendium(self, compendium, name=None):
        """
        Records what the build produced: its build time, the name the
        settings file gave it, and the pages, sections, and windows in
        all and per source label.

        Grain of `sources`: one entry per source label, in the order the
        labels first appear in the compendium. Two sources that share a
        label are one entry, as they are one heading in every output.

        Args:
            compendium (extractium.core.models.Compendium): the build result.
            name (str | None): the display name from the settings file.
                A compendium not named there takes the title of its first
                page, which may have been read from a local folder, so
                that name is left out of the record.
        """
        self.name = name
        self.built_at = compendium.built_at
        per_label = {}
        for parent in compendium.parents:
            entry = per_label.setdefault(
                parent.source_label, {"label": parent.source_label, "pages": set(), "sections": 0, "windows": 0}
            )
            entry["pages"].add(page_address(parent))
            entry["sections"] += 1
        for pid in compendium.children.pid:
            per_label[compendium.parents[pid].source_label]["windows"] += 1
        self.sources = [
            {"label": entry["label"], "pages": len(entry["pages"]),
             "sections": entry["sections"], "windows": entry["windows"]}
            for entry in per_label.values()
        ]
        self.totals = {
            "pages": sum(entry["pages"] for entry in self.sources),
            "sections": len(compendium.parents),
            "windows": len(compendium.children),
        }

    def note_outputs(self, written, local_content=False):
        """
        Records what each output wrote, the way the summary prints it.

        Args:
            written (Sequence[tuple]): one (output entry, paths) pair per
                output, as the command line collects them.
            local_content (bool): whether the compendium held content
                read from a local folder, so an output that opted in is
                marked as carrying it.
        """
        self.outputs = []
        for entry, paths in written:
            paths = [pathlib.Path(path) for path in paths]
            sizes = [_size_of(path) for path in paths]
            record = {"type": entry.type, "include_local": bool(entry.include_local)}
            if len(paths) <= FILES_NAMED:
                record["files"] = [{"path": str(path), "bytes": size} for path, size in zip(paths, sizes)]
            else:
                record["folder"] = os.path.commonpath([str(path) for path in paths])
                record["file_count"] = len(paths)
                record["bytes"] = sum(sizes)
            self.outputs.append(record)
            if entry.include_local and local_content:
                self.notices.append(
                    f"output {entry.type!r} includes local content; check before publishing."
                )

    def note_lines(self, notes):
        """Records the coverage and transport notes the summary prints."""
        self.notes = list(notes)

    def note_error(self, message):
        """Records why the build stopped, in the words the terminal showed."""
        self.errors.append(str(message))

    def to_dict(self, exit_code, ended_at=None):
        """
        The record as it is written.

        Args:
            exit_code (int): the process exit code.
            ended_at (str | None): the end time; None takes the current time.

        Returns:
            dict: the record, with every time in UTC.
        """
        ended_at = ended_at or utc_now()
        return {
            "_license": LICENSE_NOTICE,
            "version": RECORD_VERSION,
            "tool_version": __version__,
            "started_at": self.started_at,
            "ended_at": ended_at,
            "duration_seconds": _seconds_between(self.started_at, ended_at),
            "config_path": self.config_path,
            "config_sha256": self.config_sha256,
            "max_pages": self.max_pages,
            "exit_code": int(exit_code),
            "status": STATUS_SUCCEEDED if exit_code == 0 else STATUS_FAILED,
            "name": self.name,
            "built_at": self.built_at,
            "totals": self.totals,
            "sources": self.sources,
            "outputs": self.outputs,
            "notices": self.notices,
            "notes": self.notes,
            "errors": self.errors,
        }

    def finish(self, exit_code):
        """
        Writes the record and returns its path.

        The file is written whole under a temporary name and then moved
        into place, so a reader never meets a half-written record.

        Args:
            exit_code (int): the process exit code.

        Returns:
            pathlib.Path: the record written.

        Raises:
            OSError: if the folder cannot be made or the file written.
        """
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        existing = {entry.name for entry in self.runs_dir.iterdir()}
        path = self.runs_dir / record_file_name(self.started_at, existing)
        tmp_path = path.with_name(path.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(exit_code), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)
        return path


### Helpers ###

def _size_of(path):
    """A written file's size in bytes, or 0 when it can no longer be read."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _seconds_between(started_at, ended_at):
    """Whole seconds from one UTC timestamp to another, never negative."""
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    end = datetime.fromisoformat(ended_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    return max(0, int((end - start).total_seconds()))
