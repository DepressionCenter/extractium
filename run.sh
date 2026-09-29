#!/usr/bin/env bash
# This file is part of Extractium™
# run.sh
# Author(s): Gabriel Mongefranco.
# Created: 2026-09-08
# Last Modified: 2026-09-30
# Summary: The one-command entry point for macOS and Linux. Runs
# Extractium from the Extractium folder beside this script, as a
# portable archive holds, or from the per-user install, and installs
# first when there is neither. With no argument it builds, or sets up on
# a first run; "./run.sh ui" opens the local page; any other argument
# goes to the build command.
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

set -euo pipefail

### Settings ###

# Where this script lives.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Where the installer is fetched from when nothing is installed yet.
EXTRACTIUM_REPO="${EXTRACTIUM_REPO:-https://github.com/DepressionCenter/extractium}"
EXTRACTIUM_RAW="${EXTRACTIUM_RAW:-https://raw.githubusercontent.com/DepressionCenter/extractium/main}"

# The per-user install, used by its full path so this works before a
# new terminal has picked PATH up, and when PATH could not be changed.
USER_SHIM="${XDG_DATA_HOME:-$HOME/.local/share}/extractium/bin/extractium"

### Find Extractium ###

SHIM=""
if [ -x "$HERE/Extractium/bin/extractium" ]; then
    SHIM="$HERE/Extractium/bin/extractium"
elif [ -x "$USER_SHIM" ]; then
    SHIM="$USER_SHIM"
else
    # Nothing is installed yet. The installer beside this script, as in
    # a checkout, is run; otherwise the newest release's installer is
    # fetched and run. Either way the install lands under the profile.
    if [ -f "$HERE/install.sh" ]; then
        bash "$HERE/install.sh"
    else
        staging="$(mktemp -d)"
        echo "Downloading the Extractium installer ..."
        # The newest release's own copy first; the repository's current
        # copy when no release carries one yet.
        fetched=""
        for address in "$EXTRACTIUM_REPO/releases/latest/download/install.sh" "$EXTRACTIUM_RAW/install.sh"; do
            if command -v curl >/dev/null 2>&1; then
                curl -fsSL "$address" -o "$staging/install.sh" && fetched=1 && break
            else
                wget -q -O "$staging/install.sh" "$address" && fetched=1 && break
            fi
        done
        if [ -z "$fetched" ]; then
            echo "The installer could not be downloaded. Check the network, or save install.sh from the" >&2
            echo "releases page beside this script and run this script again." >&2
            rm -rf "$staging"
            exit 1
        fi
        bash "$staging/install.sh"
        rm -rf "$staging"
    fi
    if [ ! -x "$USER_SHIM" ]; then
        echo "The install did not finish, so there is nothing to run yet." >&2
        exit 1
    fi
    SHIM="$USER_SHIM"
fi

### Run ###

# CONFIG names another settings file for the page and for a build with
# no other argument.
CONFIG_ARGS=()
if [ -n "${CONFIG:-}" ]; then
    CONFIG_ARGS=(--config "$CONFIG")
fi

if [ "${1:-}" = "ui" ]; then
    shift
    exec "$SHIM" ui "${CONFIG_ARGS[@]}" "$@"
elif [ "$#" -eq 0 ]; then
    exec "$SHIM" start "${CONFIG_ARGS[@]}"
else
    exec "$SHIM" build "$@"
fi
