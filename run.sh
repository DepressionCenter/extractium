#!/usr/bin/env bash
# This file is part of Extractium™
# run.sh
# Author(s): Gabriel Mongefranco.
# Created: 2026-09-08
# Last Modified: 2026-09-08
# Summary: One-command build for macOS and Linux. Creates a virtual
# environment beside this script, installs the pinned dependencies, installs
# Extractium into it, runs the build, and prints what to commit afterwards.
# Notes: See README file for documentation and full license information.
#
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

# Stop on the first failure, on an unset variable, and on a failure anywhere
# in a pipeline, so a half-finished install can never look like a good build.
set -euo pipefail

### Settings ###

# Where this script lives. The virtual environment and the pinned
# dependency list are found relative to it, so the script works from any
# working directory.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The settings file to build from. Override it by setting CONFIG in the
# environment, or by passing --config yourself as an argument.
CONFIG="${CONFIG:-config.yaml}"

# Where the virtual environment goes. Override with VENV_DIR to keep
# several environments side by side.
VENV_DIR="${VENV_DIR:-$HERE/.venv}"

# The interpreter used to create the environment. Extractium needs 3.10
# or newer.
PYTHON="${PYTHON:-python3}"

### Check the interpreter ###

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Cannot find $PYTHON. Install Python 3.10 or newer, or set PYTHON to its path." >&2
    exit 1
fi

### Create the environment ###

if [ ! -x "$VENV_DIR/bin/python" ] && [ ! -x "$VENV_DIR/Scripts/python.exe" ]; then
    echo "Creating a virtual environment in $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# A virtual environment keeps its interpreter under bin/ on macOS and
# Linux and under Scripts/ on Windows, which this script also reaches
# through Git Bash and the Windows Subsystem for Linux.
if [ -x "$VENV_DIR/bin/python" ]; then
    VENV_PYTHON="$VENV_DIR/bin/python"
else
    VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
fi

### Install pinned dependencies ###

echo "Installing pinned dependencies ..."
# The lock file carries a hash for every package, so pip refuses anything
# whose contents do not match what was locked.
"$VENV_PYTHON" -m pip install --quiet --upgrade pip
"$VENV_PYTHON" -m pip install --quiet --require-hashes -r "$HERE/requirements-lock.txt"

# Installed without dependencies, because the line above already put the
# exact locked versions in place.
"$VENV_PYTHON" -m pip install --quiet --no-deps -e "$HERE"

### Run the build ###

echo "Building from $CONFIG ..."
if [ "$#" -gt 0 ]; then
    "$VENV_PYTHON" -m extractium.cli build "$@"
else
    "$VENV_PYTHON" -m extractium.cli build --config "$CONFIG"
fi

### Say what to do next ###

echo
echo "Build finished. The summary above lists every file that was written."
echo
echo "To publish the result:"
echo "  1. Add those files to git:   git add <output folder>"
echo "  2. Commit them:              git commit -m \"Rebuild the knowledge index\""
echo "  3. Push:                     git push"
echo
echo "Do not commit the .venv folder or the .kb_cache folder. The cache only"
echo "saves time on the next run; deleting it is always safe."
