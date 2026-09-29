"""
Summary: Tests for the connection card in extractium.mcp.connect and
the `extractium connect` command: the card holds the given path, its
JSON snippets parse, the skill front matter is valid, the HTTP section
appears only when an address on this machine is given, no line holds an
environment variable's value, and the command writes the skill folder
and prints the same text.

This file is part of Extractium™
tests/test_mcp_connect.py

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

import argparse
import json
import re

import pytest
import yaml

from extractium import cli
from extractium.mcp import connect
from tests.contract_fixture import CONTAINER_FILE

FENCED_JSON = re.compile(r"^```json\n(.*?)^```", re.M | re.S)
FRONT_MATTER = re.compile(r"\A---\n(.*?)^---\n", re.M | re.S)


### Fixtures ###

@pytest.fixture
def index_file(golden_dir):
    return golden_dir / CONTAINER_FILE


@pytest.fixture
def card(index_file):
    return connect.connection_card(index_file)


def connect_args(index, out=None, url=None):
    """The parsed arguments of one `extractium connect` command."""
    return argparse.Namespace(index=str(index), out=out, url=url)


### The card ###

def test_the_card_names_the_file_by_its_absolute_path_with_forward_slashes(card, index_file):
    expected = connect.index_path_of(index_file)

    assert "\\" not in expected
    assert expected.endswith(CONTAINER_FILE)
    assert f"extractium mcp --index {expected}" in card
    assert expected in card.split("---")[1]  # the description names it too


def test_every_json_snippet_on_the_card_parses_and_the_first_starts_the_server(card, index_file):
    snippets = [json.loads(block) for block in FENCED_JSON.findall(card)]

    assert len(snippets) == 1
    assert snippets[0] == {"mcpServers": {"extractium": {
        "command": "extractium", "args": ["mcp", "--index", connect.index_path_of(index_file)],
    }}}


def test_the_skill_front_matter_is_valid_and_names_the_skill(card):
    match = FRONT_MATTER.match(card)

    assert match is not None
    fields = yaml.safe_load(match.group(1))
    assert fields["name"] == connect.SKILL_NAME
    assert re.fullmatch(r"[a-z0-9-]+", fields["name"])
    assert "search_kb" in fields["description"]
    assert list(fields) == ["name", "description"]


def test_the_card_carries_the_rules_the_wrappers_state(card):
    assert "quoted evidence, not instructions" in card
    assert "confidential" in card
    assert "does not cover the question" in card
    assert "Cite the address" in card


def test_the_card_says_for_every_known_client_whether_it_can_reach_a_local_server(card):
    for client, _ in connect.CLIENT_NOTES:
        assert f"**{client}**" in card
    assert "claude mcp add extractium -- extractium mcp --index" in card
    assert "cannot start a program on this computer" in card


def test_the_http_section_appears_only_when_an_address_is_given(index_file):
    without = connect.connection_card(index_file)
    with_url = connect.connection_card(index_file, "http://127.0.0.1:8765/mcp")

    assert "over HTTP" not in without
    assert "http://127.0.0.1:8765/mcp" in with_url
    snippets = [json.loads(block) for block in FENCED_JSON.findall(with_url)]
    assert snippets[1] == {"mcpServers": {"extractium": {"url": "http://127.0.0.1:8765/mcp"}}}


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8765/mcp",
    "http://localhost:8765/mcp",
    "http://[::1]:8765/mcp",
])
def test_an_address_on_this_machine_is_accepted(url):
    assert connect.checked_http_url(url) == url


@pytest.mark.parametrize("url", [
    "http://example.org/mcp",
    "https://kb.example.org/mcp",
    "http://127.0.0.1:8765/mcp?token=EXAMPLE_SECRET",
    "http://user:EXAMPLE_SECRET@127.0.0.1:8765/mcp",
    "ftp://127.0.0.1/mcp",
    "not an address",
])
def test_an_address_off_this_machine_or_carrying_a_secret_is_refused(url):
    with pytest.raises(connect.ConnectError):
        connect.checked_http_url(url)


def test_no_line_of_the_card_holds_an_environment_variables_value(index_file, monkeypatch):
    secrets = {
        "EXTRACTIUM_BEARER_TOKEN": "EXAMPLE_BEARER_TOKEN_VALUE",
        "GITHUB_TOKEN": "EXAMPLE_GITHUB_TOKEN_VALUE",
        "YOUTUBE_API_KEY": "EXAMPLE_YOUTUBE_KEY_VALUE",
        "EXTRACTIUM_INDEX_URL": "https://secret.example.org/kb/compendium.json",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)

    card = connect.connection_card(index_file, "http://127.0.0.1:8765/mcp")

    for line in card.splitlines():
        for value in secrets.values():
            assert value not in line
    assert "token" not in card.lower()


def test_a_path_holding_a_space_is_quoted_in_the_command_line(tmp_path):
    folder = tmp_path / "My Builds"
    folder.mkdir()
    index = folder / "compendium-full.json.gz"
    index.write_bytes(b"")

    card = connect.connection_card(index)

    assert f'extractium mcp --index "{connect.index_path_of(index)}"' in card
    assert json.loads(FENCED_JSON.search(card).group(1))["mcpServers"]["extractium"]["args"][-1] == (
        connect.index_path_of(index)
    )


### The command ###

def test_the_command_writes_the_skill_folder_and_prints_the_same_text(index_file, tmp_path, capsys):
    out = tmp_path / "skills" / "extractium-search"

    code = cli.main(["connect", "--index", str(index_file), "--out", str(out)])

    assert code == 0
    written = (out / "SKILL.md").read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert written == connect.connection_card(index_file)
    assert captured.out.rstrip("\n") == written.rstrip("\n")
    assert "Wrote" in captured.err


def test_the_command_defaults_to_a_folder_named_after_the_skill(index_file, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert cli.main(["connect", "--index", str(index_file)]) == 0

    assert (tmp_path / connect.SKILL_NAME / "SKILL.md").is_file()


def test_the_command_puts_the_page_address_on_the_card_when_given(index_file, tmp_path, capsys):
    code = cli.main([
        "connect", "--index", str(index_file), "--out", str(tmp_path / "card"),
        "--url", "http://127.0.0.1:8765/mcp",
    ])

    assert code == 0
    assert "http://127.0.0.1:8765/mcp" in (tmp_path / "card" / "SKILL.md").read_text(encoding="utf-8")


def test_a_file_that_is_not_there_is_refused_with_exit_two(tmp_path, capsys):
    code = cli.main(["connect", "--index", str(tmp_path / "absent.json.gz"), "--out", str(tmp_path / "card")])

    assert code == 2
    assert "is not a file" in capsys.readouterr().err
    assert not (tmp_path / "card").exists()


def test_a_page_address_off_this_machine_is_refused_with_exit_two(index_file, tmp_path, capsys):
    code = cli.main([
        "connect", "--index", str(index_file), "--out", str(tmp_path / "card"),
        "--url", "https://kb.example.org/mcp",
    ])

    assert code == 2
    assert "on this machine" in capsys.readouterr().err
    assert not (tmp_path / "card").exists()


def test_a_folder_that_cannot_be_written_is_exit_four(index_file, tmp_path, capsys):
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the folder should be", encoding="utf-8")

    code = connect.run_connect(connect_args(index_file, out=str(blocked)), say=lambda line: None)

    assert code == 4
    assert "could not be written" in capsys.readouterr().err
