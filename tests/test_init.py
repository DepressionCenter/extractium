"""
Summary: Tests for the `extractium init` command: the values it accepts
and refuses, the questions it asks when a flag is missing, the file it
writes from the commented example and from the fallback template, the
refusal to replace an existing file, and that a hostile name cannot turn
into a setting.

This file is part of Extractium™
tests/test_init.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-14
Last Modified: 2026-09-14
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
__date__ = "2026-09-14"

import argparse
import pathlib

import pytest

from extractium import cli
from extractium import init
from extractium.config import load_config


def args(**values):
    """The parsed `init` arguments, with every flag absent unless given."""
    given = {"name": None, "slug": None, "seed_url": None, "output": "config.yaml", "force": False}
    given.update(values)
    return argparse.Namespace(**given)


def answers(*lines):
    """A stand-in for input() that hands out the given lines in order, then hits end of input."""
    queue = list(lines)

    def ask_line(prompt):
        if not queue:
            raise EOFError
        return queue.pop(0)

    return ask_line


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, slug", [
    ("EFDC Knowledge Base", "efdc-knowledge-base"),
    ("  Peer-to-Peer   Program  ", "peer-to-peer-program"),
    ("Résumé & Notes 2026", "r-sum-notes-2026"),
    ("---", "compendium"),
    ("", "compendium"),
    ("a" * 80, "a" * 64),
])
def test_the_slug_is_derived_from_the_name(name, slug):
    assert init.slug_from_name(name) == slug


def test_an_empty_name_takes_the_default_and_extra_space_is_removed():
    assert init.checked_name("   ") == init.DEFAULT_NAME
    assert init.checked_name("  My   Knowledge  Base ") == "My Knowledge Base"


@pytest.mark.parametrize("bad", ["My KB", "UPPER", "-leading", "a" * 65, "with.dot"])
def test_a_slug_that_the_settings_loader_would_refuse_is_refused_here(bad):
    with pytest.raises(init.InitError, match="lowercase letters, digits, and hyphens"):
        init.checked_slug(bad, "name")


def test_an_empty_slug_is_derived_from_the_name():
    assert init.checked_slug("", "My KB") == "my-kb"


@pytest.mark.parametrize("bad", ["", "   ", "example.edu/docs/", "ftp://example.edu/", "file:///etc/passwd",
                                 "https://example.edu/a b", "javascript:alert(1)"])
def test_an_address_that_is_not_a_web_address_is_refused(bad):
    with pytest.raises(init.InitError):
        init.checked_seed_url(bad)


def test_a_web_address_is_kept_as_typed_without_surrounding_space():
    assert init.checked_seed_url("  https://example.edu/docs/  ") == "https://example.edu/docs/"


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

def test_every_missing_flag_becomes_a_question_and_empty_answers_take_the_defaults():
    said = []
    values = init.gather(args(), answers("", "", "https://example.edu/"), said.append)

    assert values == {"name": init.DEFAULT_NAME, "slug": "knowledge-base", "seed_url": "https://example.edu/"}


def test_a_refused_answer_is_explained_and_asked_again():
    said = []
    values = init.gather(args(name="My KB", seed_url=None), answers("not an address", "https://example.edu/"), said.append)

    assert values["seed_url"] == "https://example.edu/"
    assert any("must start with http:// or https://" in line for line in said)


def test_too_many_refused_answers_end_the_setup():
    with pytest.raises(init.InitError, match="too many refused answers"):
        init.gather(args(name="x"), answers("bad", "bad", "bad"), lambda line: None)


def test_end_of_input_names_the_way_out():
    with pytest.raises(init.InitError, match="pass the value as a flag"):
        init.gather(args(name="x"), answers(), lambda line: None)


def test_flags_for_the_name_and_the_website_ask_nothing_and_derive_the_slug():
    values = init.gather(args(name="EFDC Knowledge Base", seed_url="https://example.edu/"), answers(), lambda line: None)

    assert values == {"name": "EFDC Knowledge Base", "slug": "efdc-knowledge-base", "seed_url": "https://example.edu/"}


def test_a_slug_flag_is_checked_like_an_answer():
    with pytest.raises(init.InitError, match="lowercase letters"):
        init.gather(args(name="x", slug="Bad Slug", seed_url="https://example.edu/"), answers(), lambda line: None)


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------

VALUES = {"name": "EFDC Knowledge Base", "slug": "efdc-kb", "seed_url": "https://example.edu/docs/"}


def test_the_file_is_the_commented_example_with_the_three_values_filled_in(tmp_path):
    path = init.write_settings(VALUES, tmp_path / "config.yaml")
    text = path.read_text(encoding="utf-8")

    assert "Writing patterns safely" in text, "the example's comments travel with the file"
    assert "label: Website" in text
    assert "#name:" not in text and "#slug:" not in text
    config = load_config(path)
    assert config.name == "EFDC Knowledge Base"
    assert config.slug == "efdc-kb"
    assert config.sources[0].label == "Website"
    assert config.sources[0].options["seed_url"] == "https://example.edu/docs/"


def test_the_fallback_template_is_used_when_the_example_is_missing(tmp_path):
    path = init.write_settings(VALUES, tmp_path / "config.yaml", example_path=tmp_path / "absent.yaml")
    text = path.read_text(encoding="utf-8")

    assert "Writing patterns safely" not in text
    config = load_config(path)
    assert (config.name, config.slug) == ("EFDC Knowledge Base", "efdc-kb")
    assert config.sources[0].options["seed_url"] == "https://example.edu/docs/"


def test_the_fallback_is_also_used_when_the_example_no_longer_holds_the_placeholder_lines(tmp_path):
    changed = tmp_path / "example.yaml"
    changed.write_text("sources:\n  - type: web\n    label: Other\n    seed_url: https://other.example/\n", encoding="utf-8")

    path = init.write_settings(VALUES, tmp_path / "config.yaml", example_path=changed)

    assert load_config(path).sources[0].options["seed_url"] == "https://example.edu/docs/"


def test_an_existing_file_is_kept_unless_force_is_given(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("keep me\n", encoding="utf-8")

    with pytest.raises(init.InitError, match="already exists"):
        init.write_settings(VALUES, path)
    assert path.read_text(encoding="utf-8") == "keep me\n"

    init.write_settings(VALUES, path, force=True)
    assert load_config(path).slug == "efdc-kb"


@pytest.mark.parametrize("name", [
    'Evil: "name',
    "name\nsources: []\nmax_pages: 1",
    "#not a comment",
    "a: b",
    "- list",
])
def test_a_hostile_name_stays_a_name_and_cannot_become_a_setting(tmp_path, name):
    values = dict(VALUES, name=name)

    path = init.write_settings(values, tmp_path / "config.yaml")

    config = load_config(path)
    assert config.name == name
    assert config.max_pages != 1
    assert len(config.sources) == 1


def test_a_hostile_address_stays_one_address(tmp_path):
    values = dict(VALUES, seed_url='https://example.edu/"\nmax_pages: 1')

    with pytest.raises(init.InitError):
        init.checked_seed_url(values["seed_url"])
    # And even a checked value with a quotation mark is written safely.
    values = dict(VALUES, seed_url='https://example.edu/?q="x"')
    path = init.write_settings(values, tmp_path / "config.yaml")
    assert load_config(path).sources[0].options["seed_url"] == 'https://example.edu/?q="x"'


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def test_the_command_writes_the_file_and_says_what_to_do_next(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    code = cli.main(["init", "--name", "My KB", "--seed-url", "https://example.edu/"])

    assert code == 0
    out = capsys.readouterr().out
    assert "Wrote config.yaml" in out
    assert "--max-pages 25" in out
    assert load_config(tmp_path / "config.yaml").slug == "my-kb"


def test_the_command_asks_when_a_flag_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", answers("Asked KB", "", "https://example.edu/"))

    code = cli.main(["init"])

    assert code == 0
    assert load_config(tmp_path / "config.yaml").name == "Asked KB"


def test_a_refused_flag_exits_two_with_the_reason(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    code = cli.main(["init", "--name", "x", "--seed-url", "ftp://example.edu/"])

    assert code == 2
    assert "must start with http:// or https://" in capsys.readouterr().err
    assert not (tmp_path / "config.yaml").exists()


def test_an_existing_file_exits_two(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("keep me\n", encoding="utf-8")

    code = cli.main(["init", "--name", "x", "--seed-url", "https://example.edu/"])

    assert code == 2
    assert "already exists" in capsys.readouterr().err


def test_an_unwritable_file_exits_four(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    code = cli.main(["init", "--name", "x", "--seed-url", "https://example.edu/",
                     "--output", str(tmp_path / "missing-folder" / "config.yaml")])

    assert code == 4
    assert "could not be written" in capsys.readouterr().err


def test_the_output_flag_names_the_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert cli.main(["init", "--name", "x", "--seed-url", "https://example.edu/", "--output", "other.yaml"]) == 0
    assert (tmp_path / "other.yaml").exists()
    assert not (tmp_path / "config.yaml").exists()


def test_the_example_file_still_holds_the_lines_the_command_fills_in():
    text = pathlib.Path(init.EXAMPLE_CONFIG).read_text(encoding="utf-8")

    for pattern in (init.EXAMPLE_LABEL_LINE, init.EXAMPLE_SEED_LINE, init.EXAMPLE_NAME_LINE, init.EXAMPLE_SLUG_LINE):
        assert len(pattern.findall(text)) == 1, pattern.pattern
