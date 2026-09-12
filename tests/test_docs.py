"""
Summary: Tests that the written documentation agrees with the repository.
Every relative link under docs/, in the README, in SKILLS.md, under
skills/, and in the example READMEs resolves to a file; every page
carries the license comment; every page under docs/ and every example
README has one H1, an H2 subtitle, two links back to the README, the
Summary, Conclusion, and Additional Resources sections, and no skipped
heading level. Every YAML block in the documentation and every shipped
settings file loads through the configuration loader, so a documented
setting that does not exist fails here rather than misleading a reader.
The three plugin examples on the plugin architecture page load through
the registry and run.

This file is part of Extractium™
tests/test_docs.py

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

import json
import pathlib
import re
import urllib.parse

import pytest
import yaml
from bs4 import BeautifulSoup

from extractium import config
from extractium.core import registry as registry_module
from tests.test_adapter_container import sample_compendium

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# The license notice every page carries inside its opening HTML comment.
LICENSE_SENTENCE = "This file is part of Extractium"

# Fenced code blocks are removed before headings and links are read, because
# a YAML comment or a shell prompt inside one looks like a heading or a link.
FENCE = re.compile(r"^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$", re.M | re.S)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
HEADING = re.compile(r"^(#{1,6})[ \t]+\S[^\n]*$", re.M)
# Inline links and images: the text in brackets, then the target in parentheses.
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
BACK_LINK = re.compile(r"\[[^\]]*Back to[^\]]*\]\((?:\.\./)+README\.md\)")
YAML_BLOCK = re.compile(r"^```yaml[ \t]*\n(.*?)^```", re.M | re.S)
PYTHON_BLOCK = re.compile(r"^```python[ \t]*\n(.*?)^```", re.M | re.S)
PLUGIN_FILE_LINE = re.compile(r"^# plugins/(\w+)\.py$", re.M)

# A YAML block that holds no sources list is a fragment showing one setting,
# and is loaded on top of this minimal file so its keys are still checked.
MINIMAL_SOURCES = {"sources": [{"type": "web", "label": "Example", "seed_url": "https://example.edu/"}]}


### Page Inventory ###

def _markdown_under(folder):
    return sorted(
        path for path in (REPO_ROOT / folder).rglob("*.md") if "node_modules" not in path.parts
    )


DOC_PAGES = _markdown_under("docs")
EXAMPLE_READMES = sorted(
    path for path in (REPO_ROOT / "examples").rglob("README.md") if "node_modules" not in path.parts
)
ALL_PAGES = (
    DOC_PAGES
    + EXAMPLE_READMES
    + [REPO_ROOT / "README.md", REPO_ROOT / "SKILLS.md"]
    + _markdown_under("skills")
)
STRUCTURED_PAGES = DOC_PAGES + EXAMPLE_READMES
SETTINGS_FILES = sorted((REPO_ROOT / "examples").glob("*.yaml")) + [
    REPO_ROOT / "examples" / "data-repo" / "config.yaml"
]


def _relative(path):
    return path.relative_to(REPO_ROOT).as_posix()


def _prose(path):
    """The page with its HTML comments and fenced code blocks removed."""
    text = path.read_text(encoding="utf-8")
    return FENCE.sub("", HTML_COMMENT.sub("", text))


### Links ###

@pytest.mark.parametrize("page", ALL_PAGES, ids=_relative)
def test_every_relative_link_resolves(page):
    broken = []
    for target in LINK.findall(_prose(page)):
        if urllib.parse.urlsplit(target).scheme or target.startswith("#"):
            continue
        relative = urllib.parse.unquote(target.split("#", 1)[0])
        if not relative:
            continue
        if not (page.parent / relative).exists():
            broken.append(target)
    assert not broken, f"{_relative(page)} links to files that do not exist: {broken}"


### License Comment ###

@pytest.mark.parametrize("page", ALL_PAGES, ids=_relative)
def test_every_page_opens_with_the_license_comment(page):
    text = page.read_text(encoding="utf-8")
    first_heading = HEADING.search(FENCE.sub("", text))
    head = text[: first_heading.start()] if first_heading else text
    assert LICENSE_SENTENCE in head, f"{_relative(page)} has no license comment before its first heading"
    assert "GNU" in head, f"{_relative(page)} names no license in its opening comment"


### Page Structure ###

def _headings(page):
    return [(len(level), line) for level, line in
            ((m.group(1), m.group(0)) for m in HEADING.finditer(_prose(page)))]


@pytest.mark.parametrize("page", STRUCTURED_PAGES, ids=_relative)
def test_page_has_one_h1_and_an_h2_subtitle(page):
    headings = _headings(page)
    levels = [level for level, _ in headings]
    assert levels.count(1) == 1, f"{_relative(page)} has {levels.count(1)} H1 headings"
    assert levels[0] == 1, f"{_relative(page)} does not open with its H1"
    assert len(levels) > 1 and levels[1] == 2, f"{_relative(page)} has no H2 subtitle under the H1"


@pytest.mark.parametrize("page", STRUCTURED_PAGES, ids=_relative)
def test_page_links_back_to_the_readme_twice(page):
    prose = _prose(page)
    assert len(BACK_LINK.findall(prose)) == 2, f"{_relative(page)} needs exactly two links back to the README"


@pytest.mark.parametrize("page", STRUCTURED_PAGES, ids=_relative)
def test_page_has_the_standard_sections(page):
    titles = {line.lstrip("#").strip().lower() for _, line in _headings(page)}
    for required in ("summary", "conclusion", "additional resources"):
        assert required in titles, f"{_relative(page)} has no '{required.title()}' heading"


@pytest.mark.parametrize("page", STRUCTURED_PAGES, ids=_relative)
def test_page_skips_no_heading_level(page):
    previous = 0
    for level, line in _headings(page):
        assert level <= previous + 1, f"{_relative(page)} jumps to {line!r} from level {previous}"
        previous = level


### Settings Examples ###

def _yaml_blocks():
    for page in DOC_PAGES:
        text = page.read_text(encoding="utf-8")
        for match in YAML_BLOCK.finditer(text):
            line = text[: match.start()].count("\n") + 1
            yield pytest.param(page, match.group(1), id=f"{_relative(page)}:{line}")


@pytest.mark.parametrize("page, block", list(_yaml_blocks()))
def test_every_yaml_block_in_the_docs_loads(page, block, tmp_path):
    data = yaml.safe_load(block)
    if not isinstance(data, dict):
        pytest.skip("not a settings file: a list or a scalar, such as a workflow line")
    if "sources" not in data:
        data = {**MINIMAL_SOURCES, **data}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    loaded = config.load_config(path)
    assert loaded.sources, f"the block in {_relative(page)} loaded with no sources"


@pytest.mark.parametrize("path", SETTINGS_FILES, ids=_relative)
def test_every_shipped_settings_file_loads(path):
    loaded = config.load_config(path)
    assert loaded.sources


### Plugin Examples ###

def _plugin_examples():
    """The example plugin files on the plugin architecture page, by their stated file names."""
    text = (REPO_ROOT / "docs" / "plugin-architecture.md").read_text(encoding="utf-8")
    files = {}
    for match in PYTHON_BLOCK.finditer(text):
        block = match.group(1)
        named = PLUGIN_FILE_LINE.match(block)
        if named:
            files[named.group(1) + ".py"] = block
    return files


@pytest.fixture
def example_plugin_dir(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    for name, code in _plugin_examples().items():
        (plugin_dir / name).write_text(code, encoding="utf-8")
    return plugin_dir


def test_the_page_documents_one_example_of_each_kind():
    assert set(_plugin_examples()) == {"faq_source.py", "example_docs_handler.py", "titles_adapter.py"}


def test_example_plugins_load_through_the_registry(example_plugin_dir):
    loaded = registry_module.build_registry(plugin_dir=example_plugin_dir, entry_points=())
    assert loaded.get_source("faq").name == "faq"
    assert loaded.get_site_handler("example_docs").name == "example_docs"
    assert loaded.get_adapter("titles").name == "titles"


def test_example_source_yields_documents(example_plugin_dir, tmp_path):
    loaded = registry_module.build_registry(plugin_dir=example_plugin_dir, entry_points=())
    faq = tmp_path / "faq.json"
    faq.write_text(json.dumps([
        {"question": "How do I reset my password?", "answer": "Use the account page.",
         "url": "https://example.edu/faq#password"},
    ]), encoding="utf-8")
    lines = []
    source = loaded.get_source("faq")({"path": str(faq)})
    documents = list(source.fetch(session=None, cache=None, progress=lines.append))
    assert [d.title for d in documents] == ["How do I reset my password?"]
    assert documents[0].source_type == "web" and documents[0].content_type == "page"
    assert lines == ["  read: https://example.edu/faq#password"]


def test_example_handler_reads_a_page(example_plugin_dir):
    loaded = registry_module.build_registry(plugin_dir=example_plugin_dir, entry_points=())
    handler = loaded.get_site_handler("example_docs")()
    assert handler.matches("https://docs.example.edu/guide/")
    assert not handler.matches("https://example.org/guide/")
    soup = BeautifulSoup(
        "<html><body><nav class='breadcrumb'><a href='/'>Home</a><a href='/guide/'>Guide</a></nav>"
        "<main><h1>Getting started</h1><p>First steps.</p></main></body></html>",
        "html.parser",
    )
    extraction = handler.extract(soup, "https://docs.example.edu/guide/start")
    assert extraction.title == "Getting started"
    assert extraction.categories == ("Home", "Guide")
    assert extraction.node.name == "main"
    assert handler.extract(BeautifulSoup("<p>no main</p>", "html.parser"), "https://docs.example.edu/") is None
    assert handler.content_type("https://docs.example.edu/guide/start") == "page"


def test_example_adapter_writes_one_line_per_page(example_plugin_dir, tmp_path, fixtures_dir,
                                                  fake_embed_chunks_core):
    loaded = registry_module.build_registry(plugin_dir=example_plugin_dir, entry_points=())
    compendium = sample_compendium(fixtures_dir, fake_embed_chunks_core)
    out_dir = tmp_path / "dist"
    (written,) = loaded.get_adapter("titles")().write(compendium, out_dir, {})
    lines = written.read_text(encoding="utf-8").splitlines()
    addresses = [line.split("\t")[1] for line in lines]
    assert addresses == sorted(set(addresses), key=addresses.index)
    assert set(addresses) == {parent.u for parent in compendium.parents}
