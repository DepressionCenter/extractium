"""
Summary: Tests for the local-filesystem source. Checks which files it
selects, the titles and content types it records, and the two properties the
confidentiality rule rests on: every document is marked local, and its URL is
a path relative to the source folder rather than a path on someone's disk.
Also checks that a file whose real location is outside the folder is refused.

This file is part of Extractium™
tests/test_source_local.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-09
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
__date__ = "2026-09-09"

import pytest

from extractium.config import DEFAULT_LOCAL_INCLUDE_GLOBS
from extractium.core.models import LOCAL_URL_PREFIX, Document, Source
from extractium.sources.local import LocalSource

# Long enough that the chunker keeps each file as a section of its own.
BODY = (
    "This paragraph is comfortably longer than the smallest chunk the "
    "chunker will keep, so the file survives as a section of its own."
)


def make_source(path, globs=DEFAULT_LOCAL_INCLUDE_GLOBS):
    """A source over one folder, built the way the command line builds it."""
    return LocalSource({"path": str(path), "include_globs": globs})


def read(path, globs=DEFAULT_LOCAL_INCLUDE_GLOBS, progress=None):
    """Every document the source yields for one folder."""
    return list(make_source(path, globs).fetch(None, None, progress or (lambda line: None)))


@pytest.fixture
def folder(tmp_path):
    """A small folder holding one file of each kind the source reads."""
    root = tmp_path / "notes"
    (root / "sub").mkdir(parents=True)
    (root / "intake.md").write_text(f"# Intake Notes\n\n{BODY}\n", encoding="utf-8")
    (root / "protocol.txt").write_text(BODY, encoding="utf-8")
    (root / "sub" / "export.html").write_text(
        f"<html><head><title>Exported Page | Site</title></head>"
        f"<body><nav>Skip this menu</nav><p>{BODY}</p></body></html>",
        encoding="utf-8",
    )
    (root / "notes.docx").write_text("not read", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def test_the_source_satisfies_the_source_protocol(tmp_path):
    assert isinstance(make_source(tmp_path), Source)
    assert LocalSource.name == "local"


def test_the_default_globs_read_markdown_text_and_html(folder):
    urls = [document.url for document in read(folder)]

    assert urls == [
        "local:intake.md",
        "local:protocol.txt",
        "local:sub/export.html",
    ]


def test_a_format_the_defaults_leave_out_is_not_read(folder):
    """Word and PDF files would need dependencies the project does not carry."""
    assert "local:notes.docx" not in [document.url for document in read(folder)]


def test_narrower_globs_read_only_what_they_name(folder):
    urls = [document.url for document in read(folder, globs=("**/*.md",))]

    assert urls == ["local:intake.md"]


def test_the_order_is_the_same_on_every_run(folder):
    assert [d.url for d in read(folder)] == [d.url for d in read(folder)]


def test_an_empty_file_is_skipped_with_a_reason(folder):
    (folder / "blank.md").write_text("   \n", encoding="utf-8")
    lines = []

    urls = [document.url for document in read(folder, progress=lines.append)]

    assert "local:blank.md" not in urls
    assert any("skipped (empty): local:blank.md" in line for line in lines)


def test_a_missing_folder_stops_the_build_rather_than_indexing_nothing(tmp_path):
    """A mistyped path would otherwise look exactly like an empty folder."""
    with pytest.raises(FileNotFoundError, match="does not exist"):
        read(tmp_path / "not-here")


# ---------------------------------------------------------------------------
# What never leaves the machine
# ---------------------------------------------------------------------------

def test_every_document_is_marked_local(folder):
    assert all(document.local for document in read(folder))
    assert all(document.source_type == "local" for document in read(folder))


def test_a_url_is_relative_to_the_source_folder(folder):
    """
    The folder someone points the build at can identify a person or a study
    by its name alone, so no part of the absolute path travels with a
    document.
    """
    documents = read(folder)

    assert all(document.url.startswith(LOCAL_URL_PREFIX) for document in documents)
    for document in documents:
        assert str(folder) not in document.url
        assert "\\" not in document.url


def test_a_file_reached_from_outside_the_folder_is_refused(folder, tmp_path):
    """
    A symbolic link, or a pattern that climbs out, would otherwise pull in
    content from a part of the disk nobody asked to index.
    """
    outside = tmp_path / "elsewhere.md"
    outside.write_text(f"# Elsewhere\n\n{BODY}\n", encoding="utf-8")
    try:
        (folder / "linked.md").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not allow creating symbolic links here")
    lines = []

    urls = [document.url for document in read(folder, progress=lines.append)]

    assert "local:linked.md" not in urls
    assert any("outside the source folder" in line for line in lines)


# ---------------------------------------------------------------------------
# Titles, types, and content
# ---------------------------------------------------------------------------

def test_a_markdown_file_is_titled_by_its_first_heading(folder):
    document = next(d for d in read(folder) if d.url == "local:intake.md")

    assert document.title == "Intake Notes"
    assert document.content_type == "text"


def test_a_text_file_is_titled_by_its_file_name(folder):
    document = next(d for d in read(folder) if d.url == "local:protocol.txt")

    assert document.title == "protocol"
    assert document.content_type == "text"


def test_an_html_file_is_titled_by_its_page_title_and_read_as_a_page(folder):
    document = next(d for d in read(folder) if d.url == "local:sub/export.html")

    assert document.title == "Exported Page"
    assert document.content_type == "page"


def test_an_html_file_loses_its_navigation_the_way_a_crawled_page_does(folder):
    document = next(d for d in read(folder) if d.url == "local:sub/export.html")

    text = document.content.get_text(" ", strip=True)
    assert "Skip this menu" not in text
    assert BODY in text


def test_a_markdown_file_keeps_its_text_for_the_chunker_to_render(folder):
    document = next(d for d in read(folder) if d.url == "local:intake.md")

    assert isinstance(document.content, str)
    assert document.content.startswith("# Intake Notes")


def test_an_html_file_with_no_readable_content_is_skipped(folder):
    (folder / "shell.html").write_text("<html><body></body></html>", encoding="utf-8")
    lines = []

    urls = [document.url for document in read(folder, progress=lines.append)]

    assert "local:shell.html" not in urls
    assert any("no content found" in line for line in lines)


def test_a_file_saved_in_another_encoding_still_yields_a_document(folder):
    """One unreadable byte should not cost a whole build."""
    (folder / "legacy.txt").write_bytes(BODY.encode("utf-8") + b" caf\xe9")

    document = next(d for d in read(folder) if d.url == "local:legacy.txt")

    assert isinstance(document, Document)
    assert BODY in document.content
