"""
Summary: Tests for the okf source, which reads an Open Knowledge Format
bundle back into documents: a bundle the okf adapter wrote round-trips
its pages, a concept read from a local folder stays local, the reserved
files and unreadable concepts are skipped with a reason, a resource that
is not a web address is refused, and a file outside the bundle folder is
never read.

This file is part of Extractium™
tests/test_source_okf.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-12
Last Modified: 2026-09-12
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
__date__ = "2026-09-12"

import pytest

from extractium import config
from extractium.adapters.okf import OkfAdapter
from extractium.core.models import Source
from extractium.core.registry import build_registry
from extractium.sources import okf
from extractium.sources.okf import OkfSource
from tests.test_adapter_container import mixed_compendium, sample_compendium


def quiet(line):
    """A progress sink for tests that do not inspect progress."""


def bundle_from(compendium, tmp_path, include_local=False):
    """Writes a bundle with the adapter and returns its folder."""
    OkfAdapter().write(compendium, tmp_path, {"include_local": include_local})
    return tmp_path / "okf"


def read(folder, progress=quiet):
    source = OkfSource({"path": str(folder)})
    return source, list(source.fetch(None, {}, progress))


### Round Trip ###

def test_the_source_satisfies_the_protocol_and_is_a_built_in():
    assert isinstance(OkfSource({"path": "."}), Source)
    assert build_registry().get_source("okf") is OkfSource


def test_a_bundle_the_adapter_wrote_reads_back_as_the_same_pages(tmp_path, fixtures_dir, fake_embed_chunks_core):
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)
    folder = bundle_from(compendium, tmp_path)

    source, documents = read(folder)

    pages = {parent.u for parent in compendium.parents}
    assert {d.url for d in documents} == pages
    assert source.read == len(pages) and source.skipped == 0
    for document in documents:
        assert document.local is False
        assert document.source_type == "web"
        assert document.content_type == "page"
        # The concept's text is what was indexed, rendered from Markdown.
        text = document.content.get_text(" ", strip=True)
        originals = [p.x for p in compendium.parents if p.u == document.url]
        assert all(original[:40] in text for original in originals)


def test_the_concept_type_becomes_the_content_type_again(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\ntype: Knowledge Base Article\ntitle: Reset\nresource: https://example.edu/kb/1\n---\n\n"
        "# Reset\n\nSource: [https://example.edu/kb/1](https://example.edu/kb/1)\n\n"
        "Open the account page and choose reset. The link arrives within a minute.\n",
        encoding="utf-8",
    )
    (tmp_path / "b.md").write_text(
        "---\ntype: Something New\ntitle: Other\nresource: https://example.edu/other\n---\n\nText here.\n",
        encoding="utf-8",
    )

    _, documents = read(tmp_path)

    by_url = {d.url: d for d in documents}
    assert by_url["https://example.edu/kb/1"].content_type == "article"
    assert by_url["https://example.edu/other"].content_type == "page"
    # The title heading and the source line repeat the front matter and are not indexed.
    assert "Source:" not in by_url["https://example.edu/kb/1"].content.get_text()
    assert "Reset" not in by_url["https://example.edu/kb/1"].content.get_text()


### The Local Guardrail ###

def test_a_concept_from_a_local_folder_stays_local(tmp_path, fixtures_dir, fake_embed_chunks_core):
    folder = bundle_from(mixed_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path, include_local=True)

    _, documents = read(folder)

    local = [d for d in documents if d.local]
    assert len(local) == 1
    assert local[0].url == "local:notes/internal.txt"
    assert local[0].source_type == "local"


def test_a_bundle_written_without_local_content_holds_none_to_read(tmp_path, fixtures_dir, fake_embed_chunks_core):
    folder = bundle_from(mixed_compendium(fixtures_dir, fake_embed_chunks_core), tmp_path)

    _, documents = read(folder)

    assert all(not d.local for d in documents)


### Refusals ###

@pytest.mark.parametrize("resource", ["file:///etc/passwd", "javascript:alert(1)", "ftp://host/x", "", "local:", 12])
def test_a_resource_that_is_not_a_web_address_is_refused(resource):
    assert okf.checked_resource(resource) is None


def test_the_reserved_files_and_unreadable_concepts_are_skipped_with_a_reason(tmp_path):
    (tmp_path / "index.md").write_text("---\nokf_version: '0.2'\n---\n\n# Index\n", encoding="utf-8")
    (tmp_path / "log.md").write_text("# Log\n\n- built\n", encoding="utf-8")
    (tmp_path / "plain.md").write_text("# No front matter\n\nJust text.\n", encoding="utf-8")
    (tmp_path / "bad.md").write_text("---\nresource: file:///secret\ntitle: X\n---\n\nText.\n", encoding="utf-8")
    (tmp_path / "untitled.md").write_text("---\nresource: https://example.edu/\n---\n\nText.\n", encoding="utf-8")
    (tmp_path / "empty.md").write_text("---\nresource: https://example.edu/e\ntitle: E\n---\n\n# E\n", encoding="utf-8")
    (tmp_path / "good.md").write_text("---\nresource: https://example.edu/g\ntitle: G\n---\n\nGood text.\n", encoding="utf-8")
    lines = []

    source, documents = read(tmp_path, lines.append)

    assert [d.url for d in documents] == ["https://example.edu/g"]
    assert source.skipped == 4
    reasons = "\n".join(lines)
    for expected in ("no front matter", "no readable resource address", "no title", "no text"):
        assert expected in reasons
    assert "index.md" not in reasons and "log.md" not in reasons
    assert source.summary_lines() == ["1 concept(s) read from the bundle, 4 skipped"]


def test_a_missing_folder_reads_nothing_and_says_so(tmp_path):
    lines = []
    source, documents = read(tmp_path / "absent", lines.append)

    assert documents == [] and source.summary_lines() == []
    assert any("not a folder" in line for line in lines)


def test_a_file_outside_the_bundle_folder_is_never_read(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("---\nresource: https://example.edu/o\ntitle: O\n---\n\nOutside.\n", encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    try:
        (bundle / "link.md").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")
    lines = []

    _, documents = read(bundle, lines.append)

    assert documents == []
    assert any("outside the source folder" in line for line in lines)


### Settings ###

def test_an_okf_source_needs_a_path_and_nothing_else():
    cfg = config.config_from_mapping({"sources": [{"type": "okf", "label": "Bundle", "path": "./okf"}]})
    assert cfg.sources[0].options == {"path": "./okf"}

    with pytest.raises(config.ConfigError, match="path is required"):
        config.config_from_mapping({"sources": [{"type": "okf", "label": "Bundle"}]})
    with pytest.raises(config.ConfigError, match="unrecognized setting"):
        config.config_from_mapping({"sources": [{"type": "okf", "label": "Bundle", "path": "x", "globs": []}]})
