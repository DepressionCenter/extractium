#!/usr/bin/env bash
# This file is part of Extractium™
# run.sh
# Author(s): Gabriel Mongefranco.
# Created: 2026-09-08
# Last Modified: 2026-09-15
# Summary: One-command build for macOS and Linux. Downloads Extractium when
# this script is on its own, creates a virtual environment beside the
# checkout, installs the pinned dependencies, installs Extractium into it,
# writes a first settings file by asking three questions when there is
# none, runs the build, and prints what to commit afterwards.
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

# The settings file to build from, relative to the folder you run the
# script in. Override it by setting CONFIG in the environment, or by
# passing --config yourself as an argument.
CONFIG="${CONFIG:-config.yaml}"

# Where the virtual environment goes. Override with VENV_DIR to keep
# several environments side by side.
VENV_DIR="${VENV_DIR:-$HERE/.venv}"

# The interpreter used to create the environment. Extractium needs 3.10
# or newer. A standard build is preferred: the free-threaded build
# (python3.13t, python3.14t) cannot use the compiled wheels the code
# parsers ship. PYTHON is checked when it is set; otherwise each name
# below is tried and the first standard build is kept. When only a free-threaded build exists, it is used and the
# parsers are left out of the install.
PYTHON="${PYTHON:-}"

# Where Extractium is downloaded from, and which release, when this script
# was saved on its own rather than run from inside a checkout. "latest"
# means the newest published release, looked up when the script runs. A
# tag or a branch name pins one. The download lands in EXTRACTIUM_DIR.
#
# That folder name is deliberately not a valid Python module name. A
# folder named "extractium" beside the settings file is taken for the
# package itself by anything that puts the working directory on the
# import path, and the checkout's outer folder is not the package.
EXTRACTIUM_REPO="${EXTRACTIUM_REPO:-https://github.com/DepressionCenter/extractium}"
EXTRACTIUM_REF="${EXTRACTIUM_REF:-latest}"
EXTRACTIUM_DIR="${EXTRACTIUM_DIR:-$HERE/extractium-src}"

### Check the interpreter ###

# True when a command runs a Python 3.10 or newer that is not free-threaded.
is_standard_python() {
    command -v "$1" >/dev/null 2>&1 && "$1" -c 'import sys, sysconfig
sys.exit(0 if sys.version_info >= (3, 10) and not sysconfig.get_config_var("Py_GIL_DISABLED") else 1)' >/dev/null 2>&1
}

# True when a command runs any Python 3.10 or newer.
is_any_python() {
    command -v "$1" >/dev/null 2>&1 && "$1" -c 'import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

CANDIDATES="python3 python3.14 python3.13 python3.12 python3.11 python3.10 python"
CHOSEN=""
FREE_THREADED_ONLY=""
if [ -n "$PYTHON" ] && is_standard_python "$PYTHON"; then
    CHOSEN="$PYTHON"
fi
if [ -z "$CHOSEN" ]; then
    for candidate in $CANDIDATES; do
        if is_standard_python "$candidate"; then
            CHOSEN="$candidate"
            break
        fi
    done
fi
if [ -z "$CHOSEN" ]; then
    for candidate in $PYTHON $CANDIDATES; do
        if is_any_python "$candidate"; then
            CHOSEN="$candidate"
            FREE_THREADED_ONLY=1
            break
        fi
    done
fi
if [ -z "$CHOSEN" ]; then
    echo "No Python 3.10 or newer was found. Install one, or set PYTHON to the path of one." >&2
    exit 1
fi
if [ -n "$PYTHON" ] && [ "$PYTHON" != "$CHOSEN" ] && [ -z "$FREE_THREADED_ONLY" ]; then
    echo "PYTHON names a free-threaded or older build; using $CHOSEN instead."
fi
PYTHON="$CHOSEN"

### Get Extractium if this script is on its own ###

# Turns "latest" into the newest release's tag. GitHub answers the
# releases/latest address with a redirect to that release's page, and the
# tag is the last part of where it lands.
resolve_latest_release() {
    local address="$EXTRACTIUM_REPO/releases/latest"
    local landed=""
    if command -v curl >/dev/null 2>&1; then
        landed="$(curl -fsSL -o /dev/null -w '%{url_effective}' "$address")"
    elif command -v wget >/dev/null 2>&1; then
        landed="$(wget -q -O /dev/null -S --max-redirect=0 "$address" 2>&1 | sed -n 's/^ *Location: *//p' | head -n 1)"
    else
        landed="$("$PYTHON" -c 'import sys, urllib.request; print(urllib.request.urlopen(sys.argv[1]).geturl())' "$address")"
    fi
    case "$landed" in
        */releases/tag/*) EXTRACTIUM_REF="${landed##*/releases/tag/}" ;;
        *)
            echo "No published release was found at $address. Set EXTRACTIUM_REF to a tag or branch name." >&2
            exit 1
            ;;
    esac
}

# Downloads one release into EXTRACTIUM_DIR. Tries git first, then the
# release archive through curl, wget, or Python's own library, so a
# machine with nothing but Python installed can still get the tool.
download_extractium() {
    if [ "$EXTRACTIUM_REF" = "latest" ]; then
        resolve_latest_release
    fi
    echo "Downloading Extractium $EXTRACTIUM_REF into $EXTRACTIUM_DIR ..."
    if command -v git >/dev/null 2>&1; then
        if git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$EXTRACTIUM_REF" "$EXTRACTIUM_REPO" "$EXTRACTIUM_DIR"; then
            return 0
        fi
        echo "git could not clone the repository; downloading the release archive instead." >&2
    fi

    local archive="$EXTRACTIUM_REPO/archive/$EXTRACTIUM_REF.tar.gz"
    local staging
    staging="$(mktemp -d)"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$archive" -o "$staging/extractium.tar.gz"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$staging/extractium.tar.gz" "$archive"
    else
        "$PYTHON" -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' \
            "$archive" "$staging/extractium.tar.gz"
    fi

    if command -v tar >/dev/null 2>&1; then
        tar -xzf "$staging/extractium.tar.gz" -C "$staging"
    else
        # The data filter refuses archive entries that would land outside
        # the folder; older interpreters extract without it.
        "$PYTHON" -c 'import sys, tarfile
with tarfile.open(sys.argv[1]) as archive:
    if hasattr(tarfile, "data_filter"):
        archive.extractall(sys.argv[2], filter="data")
    else:
        archive.extractall(sys.argv[2])' "$staging/extractium.tar.gz" "$staging"
    fi

    # The archive holds one top-level folder named after the release.
    local unpacked
    unpacked="$(find "$staging" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    if [ -z "$unpacked" ] || [ ! -f "$unpacked/pyproject.toml" ]; then
        echo "The downloaded archive did not hold Extractium. Check EXTRACTIUM_REF ($EXTRACTIUM_REF)." >&2
        rm -rf "$staging"
        exit 1
    fi
    mv "$unpacked" "$EXTRACTIUM_DIR"
    rm -rf "$staging"
}

if [ ! -f "$HERE/pyproject.toml" ]; then
    if [ ! -f "$EXTRACTIUM_DIR/pyproject.toml" ]; then
        download_extractium
    fi
    # Hand over to the copy of this script inside the checkout, which finds
    # the lock file and the package beside itself. The settings file stays
    # relative to the folder you ran this from.
    exec bash "$EXTRACTIUM_DIR/run.sh" "$@"
fi

### Create the environment ###

# A virtual environment keeps its interpreter under bin/ on macOS and
# Linux and under Scripts/ on Windows, which this script also reaches
# through Git Bash and the Windows Subsystem for Linux.
venv_python() {
    if [ -x "$VENV_DIR/bin/python" ]; then
        echo "$VENV_DIR/bin/python"
    else
        echo "$VENV_DIR/Scripts/python.exe"
    fi
}
VENV_PYTHON="$(venv_python)"

# An environment made earlier with a free-threaded Python cannot install
# the parsers. It is made again with the standard build found above.
if [ -x "$VENV_PYTHON" ] && [ -z "$FREE_THREADED_ONLY" ] && ! is_standard_python "$VENV_PYTHON"; then
    echo "The environment in $VENV_DIR was made with a free-threaded Python. Making it again with $PYTHON ..."
    rm -rf "$VENV_DIR"
fi
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Creating a virtual environment in $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
    VENV_PYTHON="$(venv_python)"
fi

### Install pinned dependencies ###

# The lock file carries a hash for every package, so pip refuses anything
# whose contents do not match what was locked. A free-threaded Python
# installs from a copy of it without the code parsers, which have no
# wheels for that build; everything else keeps its hash.
LOCK="$HERE/requirements-lock.txt"
if ! is_standard_python "$VENV_PYTHON"; then
    echo "This Python is the free-threaded build, which cannot use the code parsers' wheels."
    echo "Installing without them: code files are still recorded by name, language, and length,"
    echo "but what they define is not read. Install a standard Python for that."
    LOCK="$VENV_DIR/requirements-lock-without-parsers.txt"
    "$VENV_PYTHON" "$HERE/tools/lock_without_parsers.py" "$HERE/requirements-lock.txt" "$LOCK"
fi

echo "Installing pinned dependencies ..."
# The lock file carries a hash for every package, so pip refuses anything
# whose contents do not match what was locked.
"$VENV_PYTHON" -m pip install --quiet --upgrade pip
"$VENV_PYTHON" -m pip install --quiet --require-hashes -r "$LOCK"

# Installed without dependencies, because the line above already put the
# exact locked versions in place.
"$VENV_PYTHON" -m pip install --quiet --no-deps -e "$HERE"

# The build runs through the command the install just placed in the
# environment, and not through the interpreter's -m flag on the
# extractium.cli module. The module form puts the folder you ran this
# script from at the front of the import path, so a folder named
# "extractium" sitting there is imported in place of the installed
# package and the build stops before it starts.
if [ -x "$VENV_DIR/bin/extractium" ]; then
    VENV_EXTRACTIUM="$VENV_DIR/bin/extractium"
else
    VENV_EXTRACTIUM="$VENV_DIR/Scripts/extractium.exe"
fi

### Write a first settings file ###

# With no settings file and no arguments, this is a first run: ask for
# the name, the short name, and the website, then build with a page
# limit so a pattern broader than intended costs seconds.
FIRST_RUN=0
if [ "$#" -eq 0 ] && [ ! -f "$CONFIG" ]; then
    echo
    echo "There is no $CONFIG yet, so a few questions first."
    "$VENV_EXTRACTIUM" init --output "$CONFIG"
    FIRST_RUN=1
fi

### Run the build ###

echo
if [ "$#" -gt 0 ]; then
    "$VENV_EXTRACTIUM" build "$@"
elif [ "$FIRST_RUN" -eq 1 ]; then
    echo "Building from $CONFIG, limited to 25 pages for this first run ..."
    "$VENV_EXTRACTIUM" build --config "$CONFIG" --max-pages 25
else
    echo "Building from $CONFIG ..."
    "$VENV_EXTRACTIUM" build --config "$CONFIG"
fi

### Say what to do next ###

echo
echo "Build finished. The summary above lists every file that was written."
echo
if [ "$FIRST_RUN" -eq 1 ]; then
    echo "This first run stopped at 25 pages. Open dist/llms.txt to see which pages"
    echo "were indexed. When the list looks right, run this script again to build"
    echo "the whole site. To change what is crawled, edit $CONFIG."
    echo
fi
echo "To publish the result:"
echo "  1. Add those files to git:   git add <output folder>"
echo "  2. Commit them:              git commit -m \"Rebuild the knowledge index\""
echo "  3. Push:                     git push"
echo
echo "Do not commit the .venv folder or the .kb_cache folder. The cache only"
echo "saves time on the next run; deleting it is always safe."
