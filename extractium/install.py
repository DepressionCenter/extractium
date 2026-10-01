"""
Summary: The part of the installer that runs once an interpreter exists.
The install scripts, install.bat and install.sh, obtain one, either the
managed Python that uv downloads into the Extractium folder or a
virtual environment on a Python already on the machine, and then hand
over here. This module installs the pinned packages and the tool into
that interpreter, writes the shim that starts the tool through it,
copies a ready folder under the profile, puts the shim on the person's
PATH, writes the menu entry that opens the page, and undoes all of it
on uninstall. Nothing here downloads anything and nothing runs with
admin rights. The module imports only the standard library, because it
is run as a file from a release checkout before the package is
installed, and as `python -m extractium.install` afterwards.

This file is part of Extractium™
extractium/install.py

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

import argparse
import os
import pathlib
import plistlib
import shutil
import stat
import subprocess
import sys

### Constants ###

# The names inside the Extractium folder. The interpreter uv installs
# lands under PYTHON_DIR in a folder named after its build; a virtual
# environment made on a machine Python lands under VENV_DIR. The shim
# in BIN_DIR finds whichever exists by a path relative to itself.
BIN_DIR = "bin"
CACHE_DIR = "cache"
PYTHON_DIR = "python"
VENV_DIR = "venv"
SHIM_NAME = "extractium"
PAGE_LAUNCHER_NAME = "extractium-page"
LOG_NAME = "extractium-ui.log"

# Marks the scripts read: which release is installed, and that this
# folder cannot be moved because its interpreter records where it was
# made.
VERSION_FILE = "installed-version.txt"
NOT_PORTABLE_FILE = "not-portable.txt"

# The menu entry's name on every system, and the identifier the macOS
# application bundle carries.
MENU_NAME = "Extractium"
BUNDLE_IDENTIFIER = "org.umich.depressioncenter.extractium"

# The variables the shim sets: where the folder is, for the tool's
# memory of the last compendium folder and for the page's log, and
# where the models live, so they travel with the folder.
HOME_VARIABLE = "EXTRACTIUM_HOME"
MODEL_CACHE_VARIABLE = "HF_HOME"

# The flags the shim starts the interpreter with. Isolated mode keeps
# the working folder off the import path, so a folder named after the
# package beside a settings file is never imported in its place, and
# ignores every PYTHON* variable; the utf8 switch does what PYTHONUTF8
# would have done if isolated mode did not ignore it.
INTERPRETER_FLAGS = ("-I", "-X", "utf8", "-m", "extractium.cli")

# The Windows shortcut opens the page with the server's window
# minimized: it exists, so Ctrl+C and the lines it prints are there,
# but it stays out of the way.
WINDOW_STYLE_MINIMIZED = 7

# The header every generated file carries, in the comment syntax of
# the file it goes in.
HEADER_LINES = (
    "This file is part of Extractium(TM)",
    "{name}",
    "Author(s): Gabriel Mongefranco.",
    "Summary: {summary}",
    "Notes: See README file for documentation and full license information.",
    "",
    "Copyright (c) 2026 The Regents of the University of Michigan",
    "",
    "This program is free software: you can redistribute it and/or modify",
    "it under the terms of the GNU General Public License as published by",
    "the Free Software Foundation, either version 3 of the License, or (at your option) any later version.",
    "This program is distributed in the hope that it will be useful,",
    "but WITHOUT ANY WARRANTY; without even the implied warranty of",
    "MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the",
    "GNU General Public License for more details.",
    "You should have received a copy of the GNU General Public License along",
    "with this program. If not, see <https://www.gnu.org/licenses/>.",
)

WINDOWS = "win32"
MACOS = "darwin"
LINUX = "linux"


class InstallError(Exception):
    """Something the installer cannot do, with the reason in words a person can act on."""


def platform_name(platform=None):
    """One of WINDOWS, MACOS, or LINUX, for the running system or the one given."""
    platform = platform or sys.platform
    if platform.startswith("win"):
        return WINDOWS
    if platform == MACOS:
        return MACOS
    return LINUX


def header(name, summary, comment):
    """The generated file's header, each line behind the comment mark."""
    return "".join(f"{comment} {line}".rstrip() + "\n" for line in HEADER_LINES).format(name=name, summary=summary)


### Installing The Packages ###

def run_command(arguments, env=None):
    """
    Runs one command, as an argument list, and stops on failure.

    Args:
        arguments (Sequence[str]): the command and its arguments.
        env (Mapping | None): the environment; the process's own when None.

    Raises:
        InstallError: if the command cannot start or ends with an error.
    """
    try:
        completed = subprocess.run([str(part) for part in arguments], env=env, check=False)
    except OSError as error:
        raise InstallError(f"{arguments[0]} could not be started ({error}).")
    if completed.returncode != 0:
        raise InstallError(f"{pathlib.Path(str(arguments[0])).name} ended with code {completed.returncode}.")


def install_packages(run, python, lock, source, uv=None, editable=False):
    """
    Installs the pinned packages, then the tool without dependencies.

    Every package comes from the lock file with its hash checked, so a
    package whose contents differ from what was locked is refused. The
    tool itself is installed last with no dependencies, because the
    lock already put the exact versions in place.

    Args:
        run (Callable): runs one command given as a list; `run_command`
            outside tests.
        python (pathlib.Path): the interpreter to install into.
        lock (pathlib.Path): the requirements lock file.
        source (pathlib.Path): the checkout or release folder to install.
        uv (pathlib.Path | None): the uv program; pip through the
            interpreter when None.
        editable (bool): whether the tool is installed editable, which
            ties the install to the source folder.
    """
    if uv is not None:
        # The managed Python is marked as uv's own, and uv refuses to
        # install into it unless told that this is what is wanted. It
        # is: the whole folder is private to the tool, and a virtual
        # environment would record where it was made and break when
        # the folder moves.
        installer = [uv, "pip", "install", "--python", python, "--break-system-packages"]
    else:
        installer = [python, "-m", "pip", "install"]
    run(installer + ["--require-hashes", "-r", lock])
    run(installer + ["--no-deps"] + (["-e"] if editable else []) + [source])


### The Folder ###

def find_interpreter(home):
    """
    The interpreter inside the folder, as a path relative to it.

    The managed Python uv installs is preferred; a virtual environment
    made on a machine Python is the fallback.

    Args:
        home (pathlib.Path): the Extractium folder.

    Returns:
        pathlib.Path: the relative path, such as
        `python/cpython-3.12.12-windows-x86_64-none/python.exe`.

    Raises:
        InstallError: if the folder holds no interpreter.
    """
    home = pathlib.Path(home)
    managed = home / PYTHON_DIR
    if managed.is_dir():
        for build in sorted(managed.iterdir()):
            for candidate in (build / "python.exe", build / "bin" / "python3", build / "bin" / "python"):
                if candidate.is_file():
                    return candidate.relative_to(home)
    for candidate in (home / VENV_DIR / "Scripts" / "python.exe", home / VENV_DIR / "bin" / "python3",
                      home / VENV_DIR / "bin" / "python"):
        if candidate.is_file():
            return candidate.relative_to(home)
    raise InstallError(f"no Python was found under {home}.")


def is_portable(home):
    """Whether the folder can be moved: its interpreter is the managed one, not a virtual environment."""
    return not (pathlib.Path(home) / NOT_PORTABLE_FILE).exists()


def shim_text(platform, python_relative):
    """
    The text of the shim that starts the tool through the folder's own
    interpreter, by a path relative to the shim.

    Args:
        platform (str): WINDOWS, MACOS, or LINUX.
        python_relative (pathlib.Path): the interpreter's path relative
            to the folder.

    Returns:
        str: the shim, with the line endings the platform expects.
    """
    parts = pathlib.PurePosixPath(pathlib.Path(python_relative).as_posix()).parts
    if platform == WINDOWS:
        python = "\\".join(parts)
        flags = " ".join(INTERPRETER_FLAGS)
        lines = [
            "@echo off",
            header(f"{BIN_DIR}\\{SHIM_NAME}.cmd",
                   "Starts Extractium through the Python in this folder, wherever the folder is.", "REM").rstrip("\n"),
            "setlocal",
            f'for %%I in ("%~dp0..") do set "{HOME_VARIABLE}=%%~fI"',
            f'set "{MODEL_CACHE_VARIABLE}=%{HOME_VARIABLE}%\\{CACHE_DIR}"',
            f'"%{HOME_VARIABLE}%\\{python}" {flags} %*',
            "exit /b %errorlevel%",
        ]
        return "\r\n".join(lines) + "\r\n"
    python = "/".join(parts)
    flags = " ".join(INTERPRETER_FLAGS)
    lines = [
        "#!/bin/sh",
        header(f"{BIN_DIR}/{SHIM_NAME}",
               "Starts Extractium through the Python in this folder, wherever the folder is.", "#").rstrip("\n"),
        'HERE="$(cd "$(dirname "$0")/.." && pwd)"',
        f'{HOME_VARIABLE}="$HERE"',
        f'{MODEL_CACHE_VARIABLE}="$HERE/{CACHE_DIR}"',
        f"export {HOME_VARIABLE} {MODEL_CACHE_VARIABLE}",
        f'exec "$HERE/{python}" {flags} "$@"',
    ]
    return "\n".join(lines) + "\n"


def page_launcher_text():
    """
    The script a menu entry runs on macOS and Linux: the page with no
    terminal, its lines appended to the log in the folder.
    """
    lines = [
        "#!/bin/sh",
        header(f"{BIN_DIR}/{PAGE_LAUNCHER_NAME}",
               "Opens the Extractium page from a menu entry, with its lines kept in the folder's log.",
               "#").rstrip("\n"),
        'HERE="$(cd "$(dirname "$0")/.." && pwd)"',
        f'exec "$HERE/{BIN_DIR}/{SHIM_NAME}" ui >> "$HERE/{LOG_NAME}" 2>&1',
    ]
    return "\n".join(lines) + "\n"


def write_executable(path, text):
    """Writes a script with the bytes as given and marks it executable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_shim(home, python_relative, platform):
    """
    Writes the shim, and on macOS and Linux the page launcher, into the
    folder's `bin`, and makes the model cache folder.

    Returns:
        pathlib.Path: the shim's path.
    """
    home = pathlib.Path(home)
    (home / CACHE_DIR).mkdir(parents=True, exist_ok=True)
    if platform == WINDOWS:
        shim = home / BIN_DIR / f"{SHIM_NAME}.cmd"
        write_executable(shim, shim_text(platform, python_relative))
        return shim
    shim = home / BIN_DIR / SHIM_NAME
    write_executable(shim, shim_text(platform, python_relative))
    write_executable(home / BIN_DIR / PAGE_LAUNCHER_NAME, page_launcher_text())
    return shim


def shim_path(home, platform):
    """Where the shim is, or would be, in a folder."""
    name = f"{SHIM_NAME}.cmd" if platform == WINDOWS else SHIM_NAME
    return pathlib.Path(home) / BIN_DIR / name


def write_marks(home, version=None, portable=True):
    """Records the installed release and, when the folder cannot move, says so."""
    home = pathlib.Path(home)
    if version:
        home.joinpath(VERSION_FILE).write_text(f"{version}\n", encoding="utf-8")
    mark = home / NOT_PORTABLE_FILE
    if portable:
        if mark.exists():
            mark.unlink()
    else:
        mark.write_text(
            "This folder's Python is a virtual environment made on a Python already on this\n"
            "computer, which records where it was made. Do not move or copy this folder;\n"
            "run the installer again where you want it instead.\n", encoding="utf-8")


def copy_installer(installer, home):
    """Keeps a copy of the install script in the folder, for updating and uninstalling later."""
    if installer is None:
        return None
    installer = pathlib.Path(installer)
    target = pathlib.Path(home) / installer.name
    try:
        if installer.resolve() != target.resolve():
            shutil.copyfile(installer, target)
    except OSError as error:
        raise InstallError(f"the installer could not be copied from {installer} into the folder ({error}).")
    return target


def copy_folder(source, home):
    """
    Copies a ready Extractium folder to another place, replacing what is
    there. Nothing is downloaded: the folder carries everything.

    Args:
        source (pathlib.Path): the folder to copy, as in the release zip.
        home (pathlib.Path): where it goes.

    Raises:
        InstallError: if the two are the same folder, or the copy fails.
    """
    source = pathlib.Path(source)
    home = pathlib.Path(home)
    if source.resolve() == home.resolve():
        raise InstallError(f"{source} is already the folder to install into.")
    if not is_portable(source):
        raise InstallError(f"{source} cannot be copied: its Python is a virtual environment made on this "
                           "computer's own Python. Run the installer on its own instead.")
    try:
        if home.exists():
            shutil.rmtree(home)
        shutil.copytree(source, home, symlinks=True)
    except OSError as error:
        raise InstallError(f"the folder could not be copied to {home} ({error}).")


### PATH ###

def path_with_entry(current, entry):
    """A PATH value with the entry added once, at the end, or unchanged when it is there."""
    entries = [part for part in (current or "").split(os.pathsep) if part]
    if any(_same_path(part, entry) for part in entries):
        return current
    return os.pathsep.join(entries + [entry])


def path_without_entry(current, entry):
    """A PATH value with every copy of the entry removed."""
    entries = [part for part in (current or "").split(os.pathsep) if part and not _same_path(part, entry)]
    return os.pathsep.join(entries)


def _same_path(left, right):
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def read_user_path():
    """
    The person's own PATH entry in the registry, and its kind.

    Returns:
        tuple[str, int]: the value and the registry type, or an empty
        expandable string when there is none.
    """
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            return winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return "", winreg.REG_EXPAND_SZ


def write_user_path(value, kind):
    """
    Writes the person's own PATH entry and tells open windows that the
    environment changed, so a new terminal sees it. Only the current
    user's key is written, which needs no admin rights; the machine's
    PATH is never touched.
    """
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, kind, value)
    try:
        broadcast = 0xFFFF
        setting_change = 0x1A
        abort_if_hung = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(broadcast, setting_change, 0, "Environment", abort_if_hung, 5000,
                                                 ctypes.byref(result))
    except (AttributeError, OSError):
        pass


def user_path_add(entry, read=read_user_path, write=write_user_path):
    """
    Adds a folder to the person's PATH once.

    Returns:
        bool: whether the value changed.
    """
    current, kind = read()
    changed = path_with_entry(current, entry)
    if changed == current:
        return False
    write(changed, kind)
    return True


def user_path_remove(entry, read=read_user_path, write=write_user_path):
    """Removes a folder from the person's PATH. Returns whether the value changed."""
    current, kind = read()
    changed = path_without_entry(current, entry)
    if changed == current:
        return False
    write(changed, kind)
    return True


def user_bin_script_text(shim):
    """The two-line script placed in `~/.local/bin` that runs the folder's shim by its full path."""
    return "#!/bin/sh\n" + f'exec "{shim}" "$@"\n'


def write_user_bin_script(user_bin, shim):
    """Puts the `extractium` command in the person's own bin folder, pointing at the shim."""
    path = pathlib.Path(user_bin) / SHIM_NAME
    write_executable(path, user_bin_script_text(shim))
    return path


def on_path(folder, path_value=None):
    """Whether a folder is on PATH, as the environment has it."""
    path_value = os.environ.get("PATH", "") if path_value is None else path_value
    return any(_same_path(part, str(folder)) for part in path_value.split(os.pathsep) if part)


### Menu Entries ###

SHORTCUT_SCRIPT = (
    "$shell = New-Object -ComObject WScript.Shell\n"
    "$shortcut = $shell.CreateShortcut($env:EXTRACTIUM_SHORTCUT)\n"
    "$shortcut.TargetPath = $env:EXTRACTIUM_TARGET\n"
    "$shortcut.Arguments = 'ui'\n"
    "$shortcut.WorkingDirectory = $env:EXTRACTIUM_WORKDIR\n"
    f"$shortcut.WindowStyle = {WINDOW_STYLE_MINIMIZED}\n"
    "$shortcut.Description = 'Open the Extractium page'\n"
    "$shortcut.Save()\n"
)


def shortcut_path(programs_dir):
    """Where the Start menu shortcut goes."""
    return pathlib.Path(programs_dir) / f"{MENU_NAME}.lnk"


def write_start_menu_shortcut(home, shim, programs_dir, run=run_command, env=None):
    """
    Writes the Start menu shortcut through PowerShell, which every
    supported Windows has. Every path travels in the child's
    environment rather than in the script's text, so a folder name
    can never become part of the script.

    Returns:
        pathlib.Path: the shortcut's path.
    """
    target = shortcut_path(programs_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    child_env = dict(os.environ if env is None else env)
    child_env.update({
        "EXTRACTIUM_SHORTCUT": str(target),
        "EXTRACTIUM_TARGET": str(shim),
        "EXTRACTIUM_WORKDIR": str(home),
    })
    run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", SHORTCUT_SCRIPT],
        env=child_env)
    return target


def remove_start_menu_shortcut(programs_dir):
    """Removes the Start menu shortcut, if there is one."""
    target = shortcut_path(programs_dir)
    if target.exists():
        target.unlink()
        return True
    return False


def desktop_entry_text(launcher):
    """The `.desktop` file that puts Extractium in a Linux application menu."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={MENU_NAME}\n"
        "Comment=Open the Extractium page\n"
        f'Exec="{launcher}"\n'
        "Terminal=false\n"
        "Categories=Utility;\n"
    )


def desktop_entry_path(applications_dir):
    """Where the Linux menu entry goes."""
    return pathlib.Path(applications_dir) / "extractium.desktop"


def write_desktop_entry(launcher, applications_dir):
    """Writes the Linux menu entry, pointing at the page launcher."""
    target = desktop_entry_path(applications_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(desktop_entry_text(launcher), encoding="utf-8")
    return target


def remove_desktop_entry(applications_dir):
    """Removes the Linux menu entry, if there is one."""
    target = desktop_entry_path(applications_dir)
    if target.exists():
        target.unlink()
        return True
    return False


def mac_app_path(applications_dir):
    """Where the macOS application bundle goes."""
    return pathlib.Path(applications_dir) / f"{MENU_NAME}.app"


def mac_app_plist(version=None):
    """The bundle's property list, as a mapping."""
    return {
        "CFBundleName": MENU_NAME,
        "CFBundleDisplayName": MENU_NAME,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleExecutable": MENU_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version or "0",
        "CFBundleVersion": version or "0",
    }


def write_mac_app(launcher, applications_dir, version=None):
    """
    Writes an application bundle that Launchpad and Spotlight list: a
    property list and one executable that runs the page launcher. Made
    on the machine rather than downloaded, so nothing quarantines it.
    """
    bundle = mac_app_path(applications_dir)
    contents = bundle / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    with open(contents / "Info.plist", "wb") as handle:
        plistlib.dump(mac_app_plist(version), handle)
    write_executable(contents / "MacOS" / MENU_NAME, "#!/bin/sh\n" + f'exec "{launcher}"\n')
    return bundle


def remove_mac_app(applications_dir):
    """Removes the application bundle, if there is one."""
    bundle = mac_app_path(applications_dir)
    if bundle.exists():
        shutil.rmtree(bundle)
        return True
    return False


### Where Things Go ###

def default_places(platform, environ=None):
    """
    Where the per-user pieces go on a platform: the profile folder the
    tool installs under, the person's own bin folder, and the menu
    folder.

    Args:
        platform (str): WINDOWS, MACOS, or LINUX.
        environ (Mapping | None): the environment; the process's own
            when None.

    Returns:
        dict: `home`, `user_bin`, `menu`.
    """
    environ = os.environ if environ is None else environ
    house = pathlib.Path(environ.get("HOME") or environ.get("USERPROFILE") or pathlib.Path.home())
    if platform == WINDOWS:
        local = pathlib.Path(environ.get("LOCALAPPDATA") or house / "AppData" / "Local")
        roaming = pathlib.Path(environ.get("APPDATA") or house / "AppData" / "Roaming")
        return {
            "home": local / MENU_NAME,
            "user_bin": None,
            "menu": roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        }
    data = pathlib.Path(environ.get("XDG_DATA_HOME") or house / ".local" / "share")
    return {
        "home": data / "extractium",
        "user_bin": house / ".local" / "bin",
        "menu": house / "Applications" if platform == MACOS else data / "applications",
    }


### The Steps ###

def per_user_steps(home, platform, places, run=run_command, read_path=read_user_path, write_path=write_user_path,
                   version=None, path_value=None):
    """
    Puts the command on PATH and the entry in the menu, for a folder
    under the profile.

    Returns:
        list[str]: what was done, and what the person still has to do.
    """
    home = pathlib.Path(home)
    shim = shim_path(home, platform)
    lines = []
    if platform == WINDOWS:
        bin_dir = str(home / BIN_DIR)
        if user_path_add(bin_dir, read_path, write_path):
            lines.append(f"Added {bin_dir} to your PATH. Open a new terminal to use the extractium command.")
        else:
            lines.append(f"{bin_dir} was already on your PATH.")
        write_start_menu_shortcut(home, shim, places["menu"], run=run)
        lines.append(f'Added "{MENU_NAME}" to the Start menu. It opens the page.')
        return lines
    script = write_user_bin_script(places["user_bin"], shim)
    lines.append(f"Wrote {script}, which runs the tool in {home}.")
    if on_path(places["user_bin"], path_value):
        lines.append("Open a new terminal to use the extractium command.")
    else:
        lines.append(f"{places['user_bin']} is not on your PATH. Add this line to your shell profile, such as "
                     f"~/.bashrc or ~/.zshrc, then open a new terminal:")
        lines.append(f'    export PATH="{places["user_bin"]}:$PATH"')
    launcher = home / BIN_DIR / PAGE_LAUNCHER_NAME
    if platform == MACOS:
        write_mac_app(launcher, places["menu"], version)
        lines.append(f'Added "{MENU_NAME}" to {places["menu"]}. It opens the page; its lines go to {home / LOG_NAME}.')
    else:
        write_desktop_entry(launcher, places["menu"])
        lines.append(f'Added "{MENU_NAME}" to the applications menu. It opens the page; its lines go to '
                     f"{home / LOG_NAME}.")
    return lines


def finish(home, python, source, lock, uv=None, editable=False, portable=False, installer=None, version=None,
           platform=None, places=None, run=run_command, read_path=read_user_path, write_path=write_user_path):
    """
    Completes an install into a folder that already holds an interpreter.

    Args:
        home (pathlib.Path): the Extractium folder.
        python (pathlib.Path): the interpreter inside it.
        source (pathlib.Path): the checkout or release to install.
        lock (pathlib.Path): the lock file to install from.
        uv (pathlib.Path | None): the uv program, when the folder has one.
        editable (bool): install the source editable, for developers.
        portable (bool): the folder stays where it is, with no PATH
            entry and no menu entry.
        installer (pathlib.Path | None): the install script, kept in
            the folder for updating and uninstalling.
        version (str | None): the release tag installed.
        platform, places, run, read_path, write_path: replaced in tests.

    Returns:
        list[str]: what was done.
    """
    platform = platform_name(platform)
    places = places or default_places(platform)
    home = pathlib.Path(home)
    python = pathlib.Path(python)
    install_packages(run, python, pathlib.Path(lock), pathlib.Path(source), uv, editable)
    relative = find_interpreter(home)
    shim = write_shim(home, relative, platform)
    write_marks(home, version, portable=relative.parts[0] != VENV_DIR)
    copy_installer(installer, home)
    lines = [f"Installed Extractium {version or ''} in {home}.".replace("  ", " ")]
    if editable:
        lines.append(f"The install is editable: it runs the code in {source}.")
    if not is_portable(home):
        lines.append("This folder cannot be moved, because its Python is a virtual environment made on the "
                     "Python already on this computer.")
    if portable:
        lines.append(f"Run {shim} to start; double-click run.bat beside this folder to open the page.")
        return lines
    lines += per_user_steps(home, platform, places, run, read_path, write_path, version)
    return lines


def copy(source, home, installer=None, platform=None, places=None, run=run_command, read_path=read_user_path,
         write_path=write_user_path):
    """
    Installs from a ready folder, as the release zip holds, by copying
    it under the profile and then doing the per-user steps. Nothing is
    downloaded.

    Returns:
        list[str]: what was done.
    """
    platform = platform_name(platform)
    places = places or default_places(platform)
    home = pathlib.Path(places["home"] if home is None else home)
    source = pathlib.Path(source)
    copy_folder(source, home)
    copy_installer(installer, home)
    version = read_version(home)
    lines = [f"Copied {source} to {home}."]
    lines += per_user_steps(home, platform, places, run, read_path, write_path, version)
    return lines


def read_version(home):
    """The release tag a folder records, or None."""
    try:
        return pathlib.Path(home).joinpath(VERSION_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def update(home, source, lock, version=None, run=run_command, platform=None):
    """
    Reinstalls the packages and the tool into the folder's own
    interpreter from a newer release, and rewrites the shim. Only what
    changed is downloaded, because the installer keeps what matches.

    Returns:
        list[str]: what was done.
    """
    platform = platform_name(platform)
    home = pathlib.Path(home)
    relative = find_interpreter(home)
    uv = home / ("uv.exe" if platform == WINDOWS else "uv")
    install_packages(run, home / relative, pathlib.Path(lock), pathlib.Path(source), uv if uv.is_file() else None)
    write_shim(home, relative, platform)
    write_marks(home, version, portable=relative.parts[0] != VENV_DIR)
    return [f"Updated Extractium in {home} to {version or 'the release given'}."]


def uninstall(home, platform=None, places=None, read_path=read_user_path, write_path=write_user_path):
    """
    Removes the PATH entry, the command in the person's bin folder, and
    the menu entry. The folder itself is left for the script that
    called this, because a running interpreter cannot delete the folder
    it runs from on Windows.

    Returns:
        list[str]: what was done.
    """
    platform = platform_name(platform)
    places = places or default_places(platform)
    home = pathlib.Path(home)
    lines = []
    if platform == WINDOWS:
        if user_path_remove(str(home / BIN_DIR), read_path, write_path):
            lines.append(f"Removed {home / BIN_DIR} from your PATH.")
        if remove_start_menu_shortcut(places["menu"]):
            lines.append(f'Removed "{MENU_NAME}" from the Start menu.')
    else:
        script = pathlib.Path(places["user_bin"]) / SHIM_NAME
        if script.exists():
            script.unlink()
            lines.append(f"Removed {script}.")
        if platform == MACOS and remove_mac_app(places["menu"]):
            lines.append(f'Removed "{MENU_NAME}" from {places["menu"]}.')
        if platform == LINUX and remove_desktop_entry(places["menu"]):
            lines.append(f'Removed "{MENU_NAME}" from the applications menu.')
    lines.append(f"The folder {home} is deleted by the install script once this step ends.")
    return lines


### Entry Point ###

def build_parser():
    """The argument parser the install scripts call."""
    parser = argparse.ArgumentParser(prog="extractium-install",
                                     description="The part of the Extractium installer that runs on Python.")
    commands = parser.add_subparsers(dest="command", required=True)

    finish_command = commands.add_parser("finish", help="Install the packages into the folder's Python and finish.")
    finish_command.add_argument("--home", required=True)
    finish_command.add_argument("--python", required=True)
    finish_command.add_argument("--source", required=True)
    finish_command.add_argument("--lock", required=True)
    finish_command.add_argument("--uv")
    finish_command.add_argument("--installer")
    finish_command.add_argument("--version")
    finish_command.add_argument("--editable", action="store_true")
    finish_command.add_argument("--portable", action="store_true")

    copy_command = commands.add_parser("copy", help="Copy a ready folder under the profile and finish.")
    copy_command.add_argument("--from", dest="source", required=True)
    copy_command.add_argument("--home")
    copy_command.add_argument("--installer")

    update_command = commands.add_parser("update", help="Reinstall from a newer release into the same folder.")
    update_command.add_argument("--home", required=True)
    update_command.add_argument("--source", required=True)
    update_command.add_argument("--lock", required=True)
    update_command.add_argument("--version")

    uninstall_command = commands.add_parser("uninstall", help="Remove the PATH entry and the menu entry.")
    uninstall_command.add_argument("--home", required=True)
    return parser


def main(argv=None, say=print):
    """
    Runs one step and prints what it did.

    Returns:
        int: 0 when the step finished, 1 with the reason on standard
        error otherwise.
    """
    args = build_parser().parse_args(argv)
    try:
        if args.command == "finish":
            lines = finish(args.home, args.python, args.source, args.lock, uv=args.uv, editable=args.editable,
                           portable=args.portable, installer=args.installer, version=args.version)
        elif args.command == "copy":
            lines = copy(args.source, args.home, installer=args.installer)
        elif args.command == "update":
            lines = update(args.home, args.source, args.lock, version=args.version)
        else:
            lines = uninstall(args.home)
    except InstallError as error:
        print(f"extractium install: {error}", file=sys.stderr, flush=True)
        return 1
    for line in lines:
        say(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
