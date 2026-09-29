"""
Summary: The Extractium home folder: the folder an installer built, which
holds the interpreter, the packages, the model cache, the log a page
started from the menu writes to, and the compendium folder the page used
last. The shim that starts the tool names it in EXTRACTIUM_HOME; a tool
started any other way has no home, remembers nothing, and works as
before.

This file is part of Extractium™
extractium/home.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-29
Last Modified: 2026-09-29
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
__date__ = "2026-09-29"

import os
import pathlib

### Constants ###

# The variable the shim sets to the folder it lives under.
HOME_VARIABLE = "EXTRACTIUM_HOME"

# The file under the home that names the compendium folder the page used
# last, so the menu entry reopens it, and the log a page started with no
# terminal writes its lines to.
LAST_FOLDER_FILE = "last-folder.txt"
LOG_NAME = "extractium-ui.log"

# Where a first compendium goes when nobody chose a folder: under the
# home folder, not under Documents, which corporate images often sync to
# a cloud drive and which would then upload every build.
DEFAULT_COMPENDIUM_FOLDER_NAME = "Extractium"


### The Home Folder ###

def home_dir(environ=None):
    """
    The home folder the shim named, or None when the tool was started
    another way.

    Args:
        environ (Mapping | None): the environment to read; the process's
            own when None.

    Returns:
        pathlib.Path | None
    """
    environ = os.environ if environ is None else environ
    value = environ.get(HOME_VARIABLE, "").strip()
    return pathlib.Path(value) if value else None


def default_compendium_folder():
    """The folder the welcome screen suggests: `Extractium` under the person's home folder."""
    return pathlib.Path.home() / DEFAULT_COMPENDIUM_FOLDER_NAME


### The Last Folder ###

def remembered_folder(home=None):
    """
    The compendium folder the page used last, when a home is set and the
    folder still exists.

    Args:
        home (pathlib.Path | None): the home folder; read from the
            environment when None.

    Returns:
        pathlib.Path | None
    """
    home = home or home_dir()
    if home is None:
        return None
    try:
        text = (home / LAST_FOLDER_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    folder = pathlib.Path(text)
    return folder if folder.is_dir() else None


def remember_folder(folder, home=None):
    """
    Records the compendium folder the page is working in, under the home.

    Nothing is written when there is no home. A folder that cannot be
    written is not an error the page needs to stop for, so the failure
    is returned rather than raised.

    Args:
        folder (str | pathlib.Path): the compendium folder.
        home (pathlib.Path | None): the home folder; read from the
            environment when None.

    Returns:
        bool: whether the memory was written.
    """
    home = home or home_dir()
    if home is None:
        return False
    try:
        home.mkdir(parents=True, exist_ok=True)
        (home / LAST_FOLDER_FILE).write_text(str(pathlib.Path(folder)) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def log_path(home=None):
    """The log a page started with no terminal writes to, or None without a home."""
    home = home or home_dir()
    return None if home is None else home / LOG_NAME
