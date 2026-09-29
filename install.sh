#!/usr/bin/env bash
# This file is part of Extractium™
# install.sh
# Author(s): Gabriel Mongefranco.
# Created: 2026-09-30
# Last Modified: 2026-09-30
# Summary: Installs Extractium on macOS and Linux for the person running
# it, with no admin rights, into one folder that holds its own Python,
# the packages, the command, and the model cache. Beside a ready
# Extractium folder it copies that folder under the profile with no
# download. Inside a checkout it installs the checkout. On its own it
# downloads the release and builds the folder: uv first, with its hash
# checked, then a Python already on this computer. It then puts the
# command in ~/.local/bin and Extractium in the applications menu.
# "--portable" builds the folder beside this script and changes nothing
# else; "--update" moves an install to a newer release; "--uninstall"
# removes it.
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

# Stop on the first failure, on an unset variable, and on a failure
# anywhere in a pipeline, so a half-finished install never looks whole.
set -euo pipefail

### Settings ###

# The uv release this script downloads, and the SHA-256 of each archive
# as published beside it. Move the version and the hashes together,
# after reading the release notes. A download whose hash differs is
# refused.
UV_VERSION="0.12.20"
UV_SHA256_X86_64_MACOS="ac54283d211fd77cdc152b67606dbaf6406ff4ab03f3af4ae99468fa8e887141"
UV_SHA256_AARCH64_MACOS="848fdeb602ff1a1baacd4f6c8b7bdc6cf1ad026a6d9cf59475fda17c179743ca"
UV_SHA256_X86_64_LINUX="6590717592ace991ff83a63fef799e3ad9d33ecc8f96c5d6bdd732496e79337f"
UV_SHA256_AARCH64_LINUX="8a7aad7bc76a2fae5151566ff3e43eacce0b2a113d5e4de3e4afe3e58fa2441e"

# The Python uv installs into the folder. A standard build: the
# free-threaded one cannot use the code parsers' wheels.
PYTHON_VERSION="3.12.12"

# Where Extractium is downloaded from, and which release. "latest" is
# looked up as the newest published release; --version TAG pins one.
EXTRACTIUM_REPO="${EXTRACTIUM_REPO:-https://github.com/DepressionCenter/extractium}"
EXTRACTIUM_REF="latest"

# Where this script lives.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="$HERE/$(basename "${BASH_SOURCE[0]}")"

# Where the folder goes for a per-user install. A portable install puts
# it beside this script instead.
HOME_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/extractium"

MODE="install"
PORTABLE=""
EDITABLE=""
HOME_GIVEN=""
SOURCE=""
RELEASE_STAGING=""
UV=""
PYTHON=""

### Flags ###

while [ "$#" -gt 0 ]; do
    case "$1" in
        --portable) PORTABLE=1 ;;
        --editable) EDITABLE=1 ;;
        --update) MODE="update" ;;
        --uninstall) MODE="uninstall" ;;
        --version) EXTRACTIUM_REF="${2:-}"; shift ;;
        --home) HOME_GIVEN="${2:-}"; shift ;;
        --help|-h)
            cat <<'USAGE'
Installs Extractium for your account, with no admin rights.

  ./install.sh                 Install, or copy the Extractium folder beside this script under your profile.
  ./install.sh --portable      Build the Extractium folder beside this script and change nothing else.
  ./install.sh --home DIR      Put the Extractium folder there instead. A portable build inside a checkout needs it.
  ./install.sh --update        Move an existing install to the newest release.
  ./install.sh --version TAG   Install, or update to, that release instead of the newest.
  ./install.sh --editable      In a checkout, run the code in the checkout (for developers).
  ./install.sh --uninstall     Remove the install, its command, and its menu entry.
USAGE
            exit 0
            ;;
        *) echo "Unknown option: $1. Run ./install.sh --help." >&2; exit 2 ;;
    esac
    shift
done

if [ -n "$PORTABLE" ]; then
    HOME_DIR="$HERE/Extractium"
fi
if [ -n "$HOME_GIVEN" ]; then
    HOME_DIR="$HOME_GIVEN"
fi

# Inside a checkout, a folder named Extractium beside this script is the
# package folder itself on a disk that ignores case, as macOS does by
# default, so a portable build there needs --home to say where it goes.
if [ -n "$PORTABLE" ] && [ -z "$HOME_GIVEN" ] && [ -f "$HERE/pyproject.toml" ]; then
    echo "Inside a checkout, a portable build needs --home DIR to say where the Extractium folder goes," >&2
    echo "because a folder of that name beside this script would be the package folder on some disks." >&2
    exit 2
fi

# Every uv call trusts the certificates this computer trusts, so a
# corporate proxy that inspects traffic does not stop the download,
# keeps its cache outside the folder, and copies files into the folder
# rather than linking them, so the folder can move.
export UV_NATIVE_TLS=1
export UV_LINK_MODE=copy
export UV_CACHE_DIR="${TMPDIR:-/tmp}/extractium-uv-cache"
export UV_PYTHON_INSTALL_DIR="$HOME_DIR/python"

### Helpers ###

# Downloads one address to one file, through curl or wget.
download() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$2" "$1"
    else
        echo "Neither curl nor wget is installed, so nothing can be downloaded." >&2
        return 1
    fi
}

# The SHA-256 of one file, lowercase, through whichever tool the system has.
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print tolower($1)}'
    else
        shasum -a 256 "$1" | awk '{print tolower($1)}'
    fi
}

# True when a command runs a Python 3.10 or newer that is not free-threaded.
is_standard_python() {
    command -v "$1" >/dev/null 2>&1 && "$1" -c 'import sys, sysconfig
sys.exit(0 if sys.version_info >= (3, 10) and not sysconfig.get_config_var("Py_GIL_DISABLED") else 1)' >/dev/null 2>&1
}

# The interpreter inside a folder: the managed one, else the virtual environment's.
python_in() {
    local found
    found="$(find "$1/python" -type f \( -name python3 -o -name python \) -path '*/bin/*' 2>/dev/null | head -n 1 || true)"
    if [ -z "$found" ] && [ -x "$1/venv/bin/python3" ]; then
        found="$1/venv/bin/python3"
    fi
    echo "$found"
}

# Prints a packager command that would supply what is missing, and runs
# it only on a yes. It is the one place this script ever asks for
# elevated rights, and it never runs it on its own.
offer_command() {
    echo "This computer needs: $1"
    echo "It can be installed with:"
    echo "    $2"
    local answer="n"
    if [ -t 0 ]; then
        read -r -p "Run it now? [y/N]: " answer || answer="n"
    fi
    case "$answer" in
        [Yy]*) eval "$2" ;;
        *) return 1 ;;
    esac
}

cleanup_download() {
    if [ -n "$RELEASE_STAGING" ] && [ -d "$RELEASE_STAGING" ]; then
        rm -rf "$RELEASE_STAGING"
    fi
}

### The Release ###

# Resolves "latest" to the newest release's tag through the redirect
# GitHub serves, downloads that release's archive, and unpacks it into a
# temporary folder that is removed once the install ends.
download_release() {
    if [ "$EXTRACTIUM_REF" = "latest" ]; then
        local address="$EXTRACTIUM_REPO/releases/latest"
        local landed=""
        if command -v curl >/dev/null 2>&1; then
            landed="$(curl -fsSL -o /dev/null -w '%{url_effective}' "$address")"
        elif command -v wget >/dev/null 2>&1; then
            landed="$(wget -q -O /dev/null -S --max-redirect=0 "$address" 2>&1 | sed -n 's/^ *Location: *//p' | head -n 1)"
        fi
        case "$landed" in
            */releases/tag/*) EXTRACTIUM_REF="${landed##*/releases/tag/}" ;;
            *)
                echo "No published release was found at $address. Pass --version with a tag." >&2
                return 1
                ;;
        esac
    fi
    local archive="$EXTRACTIUM_REPO/archive/$EXTRACTIUM_REF.tar.gz"
    RELEASE_STAGING="$(mktemp -d)"
    echo "Downloading Extractium $EXTRACTIUM_REF ..."
    if ! download "$archive" "$RELEASE_STAGING/extractium.tar.gz"; then
        echo "Extractium could not be downloaded from $archive. Check the network and --version." >&2
        return 1
    fi
    tar -xzf "$RELEASE_STAGING/extractium.tar.gz" -C "$RELEASE_STAGING"
    SOURCE="$(find "$RELEASE_STAGING" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    if [ -z "$SOURCE" ] || [ ! -f "$SOURCE/pyproject.toml" ]; then
        echo "The downloaded archive did not hold Extractium. Check --version ($EXTRACTIUM_REF)." >&2
        return 1
    fi
}

### Step 1: uv ###

# Downloads uv at the pinned version, checks its hash, unpacks it into
# the folder, and asks it for its version. A uv already in the folder
# that starts is kept.
get_uv() {
    UV="$HOME_DIR/uv"
    if [ -x "$UV" ] && "$UV" --version >/dev/null 2>&1; then
        return 0
    fi
    local system machine asset expected
    system="$(uname -s)"
    machine="$(uname -m)"
    case "$system:$machine" in
        Darwin:arm64) asset="uv-aarch64-apple-darwin.tar.gz"; expected="$UV_SHA256_AARCH64_MACOS" ;;
        Darwin:x86_64) asset="uv-x86_64-apple-darwin.tar.gz"; expected="$UV_SHA256_X86_64_MACOS" ;;
        Linux:x86_64) asset="uv-x86_64-unknown-linux-gnu.tar.gz"; expected="$UV_SHA256_X86_64_LINUX" ;;
        Linux:aarch64|Linux:arm64) asset="uv-aarch64-unknown-linux-gnu.tar.gz"; expected="$UV_SHA256_AARCH64_LINUX" ;;
        *)
            echo "No uv build is pinned for $system on $machine." >&2
            return 1
            ;;
    esac
    local url="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$asset"
    local staging
    staging="$(mktemp -d)"
    echo "Step 1: downloading uv $UV_VERSION ..."
    if ! download "$url" "$staging/uv.tar.gz"; then
        echo "uv could not be downloaded from $url. Check the network." >&2
        rm -rf "$staging"
        return 1
    fi
    local got
    got="$(sha256_of "$staging/uv.tar.gz")"
    if [ "$got" != "$expected" ]; then
        echo "The uv download does not match the SHA-256 this script expects, so it was not used." >&2
        echo "  expected $expected" >&2
        echo "  got      $got" >&2
        rm -rf "$staging"
        return 1
    fi
    tar -xzf "$staging/uv.tar.gz" -C "$staging"
    local unpacked
    unpacked="$(find "$staging" -type f -name uv | head -n 1)"
    if [ -z "$unpacked" ]; then
        echo "The uv archive held no uv program." >&2
        rm -rf "$staging"
        return 1
    fi
    mkdir -p "$HOME_DIR"
    cp "$unpacked" "$UV"
    chmod 755 "$UV"
    rm -rf "$staging"
    if ! "$UV" --version; then
        echo "uv is in $HOME_DIR but could not start. A policy on this computer may refuse programs run" >&2
        echo "from a user folder; ask IT whether that is so." >&2
        return 1
    fi
}

### Step 2: a Python that uv manages ###

managed_python() {
    echo "Installing Python $PYTHON_VERSION into $HOME_DIR/python ..."
    if "$UV" python install "$PYTHON_VERSION" --install-dir "$HOME_DIR/python"; then
        PYTHON="$(python_in "$HOME_DIR")"
        [ -n "$PYTHON" ] && return 0
        echo "uv installed Python but no interpreter was found under $HOME_DIR/python." >&2
    fi
    echo "The managed Python could not be downloaded. Looking for a Python already on this computer for uv to use."
    # An environment on a machine Python records where it was made, so
    # an install made this way cannot be moved.
    local found
    found="$("$UV" python find ">=3.10" 2>/dev/null || true)"
    if [ -z "$found" ]; then
        return 1
    fi
    rm -rf "$HOME_DIR/venv"
    "$UV" venv --python "$found" "$HOME_DIR/venv" || return 1
    PYTHON="$HOME_DIR/venv/bin/python3"
}

### Step 3: a Python already on this computer, with pip ###

machine_python() {
    echo
    echo "Step 3: using a Python already on this computer. An install made this way cannot be moved."
    UV=""
    local chosen=""
    for candidate in ${PYTHON_EXE:-} python3 python3.14 python3.13 python3.12 python3.11 python3.10 python; do
        if is_standard_python "$candidate"; then
            chosen="$candidate"
            break
        fi
    done
    if [ -z "$chosen" ]; then
        echo "No Python 3.10 or newer was found on this computer."
        if command -v dnf >/dev/null 2>&1; then
            offer_command "Python 3" "sudo dnf install python3" || return 1
        elif command -v apt-get >/dev/null 2>&1; then
            offer_command "Python 3 with venv" "sudo apt-get install python3 python3-venv" || return 1
        elif command -v brew >/dev/null 2>&1; then
            offer_command "Python 3" "brew install python" || return 1
        else
            return 1
        fi
        for candidate in python3 python; do
            if is_standard_python "$candidate"; then
                chosen="$candidate"
                break
            fi
        done
        [ -n "$chosen" ] || return 1
    fi
    echo "Making a virtual environment in $HOME_DIR/venv with $chosen ..."
    rm -rf "$HOME_DIR/venv"
    mkdir -p "$HOME_DIR"
    if ! "$chosen" -m venv "$HOME_DIR/venv"; then
        # Debian and Ubuntu ship Python without the venv module.
        if command -v apt-get >/dev/null 2>&1; then
            offer_command "the venv module" "sudo apt-get install python3-venv" || return 1
            "$chosen" -m venv "$HOME_DIR/venv" || return 1
        else
            return 1
        fi
    fi
    PYTHON="$HOME_DIR/venv/bin/python3"
    "$PYTHON" -m pip install --quiet --upgrade pip
}

### Step 4: stop, and say what to ask for ###

stop_and_explain() {
    echo >&2
    echo "Extractium could not be installed on this computer without help." >&2
    echo "  Step 1, uv, could not be downloaded or could not start." >&2
    echo "  Step 3, a Python already on this computer, was not found or could not make an environment." >&2
    echo "Ask IT for one of these:" >&2
    echo "  - permission to run programs from $HOME_DIR, which is what uv and its Python need; or" >&2
    echo "  - a standard Python 3.10 or newer, with its venv module, installed for you." >&2
    echo "Then run this script again." >&2
    exit 1
}

### The Situations ###

copy_ready() {
    local python
    python="$(python_in "$HERE/Extractium")"
    if [ -z "$python" ]; then
        echo "The Extractium folder beside this script holds no Python. Download the release archive again." >&2
        exit 1
    fi
    echo "Copying $HERE/Extractium to $HOME_DIR ..."
    exec "$python" -I -m extractium.install copy --from "$HERE/Extractium" --home "$HOME_DIR" --installer "$SELF"
}

find_home() {
    if [ -x "$HERE/bin/extractium" ]; then
        HOME_DIR="$HERE"
    elif [ -x "$HERE/Extractium/bin/extractium" ]; then
        HOME_DIR="$HERE/Extractium"
    elif [ ! -x "$HOME_DIR/bin/extractium" ]; then
        echo "No Extractium install was found beside this script or in $HOME_DIR." >&2
        exit 1
    fi
}

update_install() {
    find_home
    if [ -f "$HERE/pyproject.toml" ]; then
        SOURCE="$HERE"
    else
        download_release || exit 1
    fi
    local python
    python="$(python_in "$HOME_DIR")"
    local -a arguments=(--home "$HOME_DIR" --source "$SOURCE" --lock "$SOURCE/requirements-lock.txt")
    if [ "$EXTRACTIUM_REF" != "latest" ]; then
        arguments+=(--version "$EXTRACTIUM_REF")
    fi
    echo "Updating $HOME_DIR ..."
    "$python" -I "$SOURCE/extractium/install.py" update "${arguments[@]}"
    cp "$SOURCE/install.sh" "$HOME_DIR/install.sh"
    cleanup_download
}

uninstall_install() {
    find_home
    local answer="n"
    read -r -p "Remove Extractium from $HOME_DIR, its command, and its menu entry? [y/N]: " answer || answer="n"
    case "$answer" in
        [Yy]*) ;;
        *) echo "Nothing was removed."; exit 0 ;;
    esac
    local python
    python="$(python_in "$HOME_DIR")"
    if [ -n "$python" ]; then
        "$python" -I -m extractium.install uninstall --home "$HOME_DIR"
    fi
    rm -rf "$HOME_DIR"
    echo "Removed $HOME_DIR."
}

### Main ###

case "$MODE" in
    uninstall) uninstall_install; exit 0 ;;
    update) update_install; exit 0 ;;
esac

# A ready folder beside this script, as the release archive holds:
# copied under the profile, with nothing downloaded.
if [ -x "$HERE/Extractium/bin/extractium" ] && [ -z "$PORTABLE" ]; then
    copy_ready
fi

# Inside a checkout, the checkout is what gets installed. On its own,
# the release is downloaded first.
if [ -f "$HERE/pyproject.toml" ]; then
    SOURCE="$HERE"
else
    download_release || exit 1
fi
LOCK="$SOURCE/requirements-lock.txt"
INSTALL_PY="$SOURCE/extractium/install.py"
if [ ! -f "$INSTALL_PY" ]; then
    echo "The folder $SOURCE does not hold this release's installer. Check --version." >&2
    exit 1
fi
mkdir -p "$HOME_DIR"

if get_uv && managed_python; then
    :
elif machine_python; then
    :
else
    stop_and_explain
fi

### Install the packages and finish ###

FINISH=(--home "$HOME_DIR" --python "$PYTHON" --source "$SOURCE" --lock "$LOCK" --installer "$SELF")
if [ -n "$UV" ]; then
    FINISH+=(--uv "$UV")
fi
if [ -n "$PORTABLE" ]; then
    FINISH+=(--portable)
fi
if [ -n "$EDITABLE" ]; then
    FINISH+=(--editable)
fi
if [ "$EXTRACTIUM_REF" != "latest" ]; then
    FINISH+=(--version "$EXTRACTIUM_REF")
fi
echo "Installing the packages from the lock file, with every hash checked ..."
"$PYTHON" -I "$INSTALL_PY" finish "${FINISH[@]}"
cleanup_download
