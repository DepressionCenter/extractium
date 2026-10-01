"""
Summary: Tests for the Extractium home folder: it is named by the
variable the shim sets and is otherwise absent; the compendium folder
the page used last is remembered under it and read back only while
that folder still exists; nothing is written when there is no home;
and a home that cannot be written is reported, not raised.

This file is part of Extractium™
tests/test_home.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-30
Last Modified: 2026-09-30
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
__date__ = "2026-09-30"

import pathlib

from extractium import home


def test_the_home_comes_from_the_variable_the_shim_sets(tmp_path, monkeypatch):
    monkeypatch.delenv(home.HOME_VARIABLE, raising=False)
    assert home.home_dir() is None
    assert home.log_path() is None

    monkeypatch.setenv(home.HOME_VARIABLE, str(tmp_path))
    assert home.home_dir() == tmp_path
    assert home.log_path() == tmp_path / home.LOG_NAME

    assert home.home_dir({home.HOME_VARIABLE: "   "}) is None


def test_the_default_compendium_folder_is_under_the_home_folder_not_documents():
    folder = home.default_compendium_folder()

    assert folder.parent == pathlib.Path.home()
    assert folder.name == "Extractium"
    assert "Documents" not in folder.parts


def test_the_last_folder_is_remembered_under_the_home_and_read_back(tmp_path, monkeypatch):
    house = tmp_path / "home"
    compendium = tmp_path / "my-compendium"
    compendium.mkdir()
    monkeypatch.setenv(home.HOME_VARIABLE, str(house))

    assert home.remember_folder(compendium) is True
    assert (house / home.LAST_FOLDER_FILE).read_text(encoding="utf-8") == f"{compendium}\n"
    assert home.remembered_folder() == compendium


def test_a_remembered_folder_that_no_longer_exists_is_forgotten(tmp_path, monkeypatch):
    house = tmp_path / "home"
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.setenv(home.HOME_VARIABLE, str(house))
    home.remember_folder(gone)
    gone.rmdir()

    assert home.remembered_folder() is None


def test_nothing_is_remembered_without_a_home(tmp_path, monkeypatch):
    monkeypatch.delenv(home.HOME_VARIABLE, raising=False)

    assert home.remember_folder(tmp_path) is False
    assert home.remembered_folder() is None
    assert not list(tmp_path.iterdir())


def test_a_home_that_cannot_be_written_is_reported_rather_than_raised(tmp_path, monkeypatch):
    # A file where the home folder should be: the folder cannot be made.
    blocker = tmp_path / "home"
    blocker.write_text("not a folder", encoding="utf-8")
    monkeypatch.setenv(home.HOME_VARIABLE, str(blocker))

    assert home.remember_folder(tmp_path) is False
    assert home.remembered_folder() is None


def test_an_empty_or_missing_memory_file_means_no_folder(tmp_path, monkeypatch):
    house = tmp_path / "home"
    house.mkdir()
    monkeypatch.setenv(home.HOME_VARIABLE, str(house))

    assert home.remembered_folder() is None
    (house / home.LAST_FOLDER_FILE).write_text("  \n", encoding="utf-8")
    assert home.remembered_folder() is None
