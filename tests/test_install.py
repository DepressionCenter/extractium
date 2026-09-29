"""
Summary: Tests for the Python half of the installer: the packages are
installed from the lock with hashes and the tool without dependencies,
as argument lists and never a shell string; the shim starts the tool
through the folder's own interpreter by a relative path in isolated
mode; a ready folder is copied under the profile with nothing
downloaded; the PATH entry is added once and removed on uninstall; the
menu entries are written with every path passed outside the script
text and removed again; and nothing the installer writes holds the
path of the machine it was made on. The module imports only the
standard library, because it runs before the package is installed.

This file is part of Extractium™
tests/test_install.py

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

import ast
import os
import pathlib
import plistlib
import sys

import pytest

from extractium import install

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MANAGED_BUILD = "cpython-3.12.12-windows-x86_64-none"


### Fixtures ###

class Recorder:
    """Stands in for the command runner: keeps every command and runs nothing."""

    def __init__(self):
        self.commands = []
        self.environments = []

    def __call__(self, arguments, env=None):
        self.commands.append([str(part) for part in arguments])
        self.environments.append(env)


class FakeRegistry:
    """The person's PATH value in the registry, kept in memory."""

    def __init__(self, value=""):
        self.value = value
        self.kind = 2
        self.writes = 0

    def read(self):
        return self.value, self.kind

    def write(self, value, kind):
        self.value = value
        self.kind = kind
        self.writes += 1


def make_home(tmp_path, platform=install.WINDOWS, venv=False):
    """A folder holding an interpreter where uv or venv would have put it."""
    home = tmp_path / "Extractium"
    if venv:
        python = home / install.VENV_DIR / ("Scripts/python.exe" if platform == install.WINDOWS else "bin/python3")
    else:
        build = MANAGED_BUILD if platform == install.WINDOWS else MANAGED_BUILD.replace("windows", "macos")
        python = home / install.PYTHON_DIR / build / ("python.exe" if platform == install.WINDOWS else "bin/python3")
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    return home, python


def places_under(tmp_path):
    return {
        "home": tmp_path / "profile" / "Extractium",
        "user_bin": tmp_path / "profile" / ".local" / "bin",
        "menu": tmp_path / "profile" / "menu",
    }


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "release"
    folder.mkdir()
    (folder / "pyproject.toml").write_text("[project]\nname = 'extractium'\n", encoding="utf-8")
    (folder / "requirements-lock.txt").write_text("# lock\n", encoding="utf-8")
    (folder / "install.bat").write_text("@echo off\r\n", encoding="utf-8")
    return folder


# ---------------------------------------------------------------------------
# The module itself
# ---------------------------------------------------------------------------

def test_the_module_imports_only_the_standard_library():
    tree = ast.parse((REPO_ROOT / "extractium" / "install.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
            assert node.level == 0, "no relative import: the file runs on its own before the package exists"

    assert "extractium" not in names
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


def test_the_module_runs_as_a_file_and_as_a_module(tmp_path):
    import subprocess

    as_file = subprocess.run([sys.executable, "-I", str(REPO_ROOT / "extractium" / "install.py"), "--help"],
                             capture_output=True, text=True, cwd=tmp_path)
    as_module = subprocess.run([sys.executable, "-m", "extractium.install", "--help"],
                               capture_output=True, text=True, cwd=REPO_ROOT)

    assert as_file.returncode == 0 and "finish" in as_file.stdout
    assert as_module.returncode == 0 and "uninstall" in as_module.stdout


# ---------------------------------------------------------------------------
# Installing the packages
# ---------------------------------------------------------------------------

def test_the_packages_come_from_the_lock_with_hashes_and_the_tool_without_dependencies(tmp_path):
    run = Recorder()
    python = tmp_path / "python.exe"
    lock = tmp_path / "requirements-lock.txt"

    install.install_packages(run, python, lock, tmp_path / "src", uv=tmp_path / "uv.exe")

    first, second = run.commands
    assert first[:5] == [str(tmp_path / "uv.exe"), "pip", "install", "--python", str(python)]
    assert first[5:] == ["--require-hashes", "-r", str(lock)]
    assert second[5:] == ["--no-deps", str(tmp_path / "src")]
    # Every command is a list; nothing was joined into a string.
    assert all(isinstance(command, list) for command in run.commands)


def test_without_uv_pip_runs_through_the_interpreter_and_editable_is_opt_in(tmp_path):
    run = Recorder()
    python = tmp_path / "python.exe"

    install.install_packages(run, python, tmp_path / "lock.txt", tmp_path / "src", editable=True)

    first, second = run.commands
    assert first[:4] == [str(python), "-m", "pip", "install"]
    assert "--require-hashes" in first
    assert second[-3:] == ["--no-deps", "-e", str(tmp_path / "src")]

    run = Recorder()
    install.install_packages(run, python, tmp_path / "lock.txt", tmp_path / "src")
    assert "-e" not in run.commands[1]


def test_a_command_that_fails_stops_the_install_with_its_code(tmp_path):
    with pytest.raises(install.InstallError, match="ended with code"):
        install.run_command([sys.executable, "-c", "import sys; sys.exit(3)"])
    with pytest.raises(install.InstallError, match="could not be started"):
        install.run_command([str(tmp_path / "no-such-program")])


# ---------------------------------------------------------------------------
# The shim
# ---------------------------------------------------------------------------

def test_the_windows_shim_starts_the_tool_through_the_folders_python_in_isolated_mode(tmp_path):
    home, python = make_home(tmp_path)

    relative = install.find_interpreter(home)
    text = install.shim_text(install.WINDOWS, relative)

    assert relative == pathlib.Path(install.PYTHON_DIR) / MANAGED_BUILD / "python.exe"
    assert text.startswith("@echo off\r\n")
    assert "\r\n" in text and "\n\n" not in text.replace("\r\n", "")
    assert f'"%EXTRACTIUM_HOME%\\python\\{MANAGED_BUILD}\\python.exe" -I -X utf8 -m extractium.cli %*' in text
    assert 'set "HF_HOME=%EXTRACTIUM_HOME%\\cache"' in text
    assert 'for %%I in ("%~dp0..") do set "EXTRACTIUM_HOME=%%~fI"' in text
    assert "This file is part of Extractium" in text
    assert str(tmp_path) not in text


def test_the_posix_shim_does_the_same_with_a_relative_path_and_exec(tmp_path):
    home, python = make_home(tmp_path, platform=install.MACOS)

    relative = install.find_interpreter(home)
    text = install.shim_text(install.LINUX, relative)

    assert text.startswith("#!/bin/sh\n")
    assert "\r" not in text
    assert 'HERE="$(cd "$(dirname "$0")/.." && pwd)"' in text
    assert f'exec "$HERE/python/{MANAGED_BUILD.replace("windows", "macos")}/bin/python3" -I -X utf8 -m extractium.cli "$@"' in text
    assert 'HF_HOME="$HERE/cache"' in text and "export EXTRACTIUM_HOME HF_HOME" in text
    assert str(tmp_path) not in text


def test_the_shim_finds_a_virtual_environment_when_there_is_no_managed_python(tmp_path):
    home, python = make_home(tmp_path, venv=True)

    assert install.find_interpreter(home) == pathlib.Path(install.VENV_DIR) / "Scripts" / "python.exe"

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(install.InstallError, match="no Python was found"):
        install.find_interpreter(empty)


def test_writing_the_shim_makes_the_cache_folder_and_on_posix_the_page_launcher(tmp_path):
    home, python = make_home(tmp_path, platform=install.LINUX)

    shim = install.write_shim(home, install.find_interpreter(home), install.LINUX)

    assert shim == home / "bin" / "extractium"
    assert os.access(shim, os.X_OK)
    assert (home / "cache").is_dir()
    launcher = (home / "bin" / "extractium-page").read_text(encoding="utf-8")
    assert 'exec "$HERE/bin/extractium" ui >> "$HERE/extractium-ui.log" 2>&1' in launcher

    home, python = make_home(tmp_path / "w")
    shim = install.write_shim(home, install.find_interpreter(home), install.WINDOWS)
    assert shim == home / "bin" / "extractium.cmd"
    assert not (home / "bin" / "extractium-page").exists()


# ---------------------------------------------------------------------------
# Copying a ready folder
# ---------------------------------------------------------------------------

def test_a_ready_folder_is_copied_under_the_profile_with_nothing_downloaded(tmp_path, source):
    home, python = make_home(tmp_path)
    install.write_shim(home, install.find_interpreter(home), install.WINDOWS)
    (home / "cache" / "model.bin").write_bytes(b"weights")
    install.write_marks(home, "v9.9")
    places = places_under(tmp_path)
    registry = FakeRegistry("C:\\Windows")
    run = Recorder()

    lines = install.copy(home, None, installer=source / "install.bat", platform=install.WINDOWS, places=places,
                         run=run, read_path=registry.read, write_path=registry.write)

    target = places["home"]
    assert (target / "bin" / "extractium.cmd").read_bytes() == (home / "bin" / "extractium.cmd").read_bytes()
    assert (target / "cache" / "model.bin").read_bytes() == b"weights"
    assert (target / "install.bat").exists()
    assert registry.value == f"C:\\Windows{os.pathsep}{target / 'bin'}"
    # The only command run is the one that writes the shortcut.
    assert len(run.commands) == 1 and run.commands[0][0] == "powershell"
    assert any("Copied" in line for line in lines) and any("Start menu" in line for line in lines)


def test_copying_replaces_an_older_folder_and_refuses_the_same_folder(tmp_path):
    home, python = make_home(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "stale.txt").write_text("old", encoding="utf-8")

    install.copy_folder(home, target)

    assert not (target / "stale.txt").exists()
    assert (target / install.PYTHON_DIR).is_dir()
    with pytest.raises(install.InstallError, match="already the folder"):
        install.copy_folder(home, home)


# ---------------------------------------------------------------------------
# PATH
# ---------------------------------------------------------------------------

def test_the_path_entry_is_added_once_and_removed_on_uninstall():
    registry = FakeRegistry("C:\\Windows;C:\\Tools")
    entry = "C:\\Users\\someone\\AppData\\Local\\Extractium\\bin"

    assert install.user_path_add(entry, registry.read, registry.write) is True
    assert install.user_path_add(entry, registry.read, registry.write) is False
    assert install.user_path_add(entry.lower() + "\\", registry.read, registry.write) is False
    assert registry.value == f"C:\\Windows;C:\\Tools;{entry}" and registry.writes == 1

    assert install.user_path_remove(entry, registry.read, registry.write) is True
    assert registry.value == "C:\\Windows;C:\\Tools"
    assert install.user_path_remove(entry, registry.read, registry.write) is False


def test_the_path_value_keeps_its_kind_and_an_empty_value_gets_only_the_entry():
    registry = FakeRegistry("")
    registry.kind = 2

    install.user_path_add("D:\\bin", registry.read, registry.write)

    assert registry.value == "D:\\bin" and registry.kind == 2


def test_the_posix_command_is_a_script_in_the_persons_bin_that_runs_the_shim(tmp_path):
    shim = tmp_path / "Extractium" / "bin" / "extractium"

    script = install.write_user_bin_script(tmp_path / ".local" / "bin", shim)

    text = script.read_text(encoding="utf-8")
    assert text == f'#!/bin/sh\nexec "{shim}" "$@"\n'
    assert os.access(script, os.X_OK)
    assert install.on_path(tmp_path / ".local" / "bin", f"/usr/bin{os.pathsep}{tmp_path / '.local' / 'bin'}")
    assert not install.on_path(tmp_path / ".local" / "bin", "/usr/bin")


# ---------------------------------------------------------------------------
# Menu entries
# ---------------------------------------------------------------------------

def test_the_start_menu_shortcut_is_written_through_powershell_with_paths_in_the_environment(tmp_path):
    home = tmp_path / "Extractium"
    shim = home / "bin" / "extractium.cmd"
    run = Recorder()
    menu = tmp_path / "Programs"

    written = install.write_start_menu_shortcut(home, shim, menu, run=run, env={"PATH": "x"})

    assert written == menu / "Extractium.lnk"
    (command,) = run.commands
    assert command[:2] == ["powershell", "-NoProfile"] and "-NonInteractive" in command
    script = command[-1]
    assert "WScript.Shell" in script and "$shortcut.Arguments = 'ui'" in script
    assert f"$shortcut.WindowStyle = {install.WINDOW_STYLE_MINIMIZED}" in script
    # No path is in the script text; each travels as a variable.
    assert str(tmp_path) not in script
    env = run.environments[0]
    assert env["EXTRACTIUM_SHORTCUT"] == str(written)
    assert env["EXTRACTIUM_TARGET"] == str(shim)
    assert env["EXTRACTIUM_WORKDIR"] == str(home)
    assert env["PATH"] == "x"

    written.write_bytes(b"lnk")
    assert install.remove_start_menu_shortcut(menu) is True
    assert not written.exists()
    assert install.remove_start_menu_shortcut(menu) is False


def test_the_linux_menu_entry_runs_the_page_launcher_with_no_terminal(tmp_path):
    launcher = tmp_path / "Extractium" / "bin" / "extractium-page"

    entry = install.write_desktop_entry(launcher, tmp_path / "applications")

    text = entry.read_text(encoding="utf-8")
    assert text.startswith("[Desktop Entry]\n")
    assert f'Exec="{launcher}"\n' in text
    assert "Terminal=false\n" in text and "Name=Extractium\n" in text
    assert install.remove_desktop_entry(tmp_path / "applications") is True
    assert not entry.exists()


def test_the_macos_application_is_a_bundle_with_a_property_list_and_one_executable(tmp_path):
    launcher = tmp_path / "Extractium" / "bin" / "extractium-page"

    bundle = install.write_mac_app(launcher, tmp_path / "Applications", version="v9.9")

    assert bundle == tmp_path / "Applications" / "Extractium.app"
    with open(bundle / "Contents" / "Info.plist", "rb") as handle:
        plist = plistlib.load(handle)
    assert plist["CFBundleExecutable"] == "Extractium" and plist["CFBundleIdentifier"] == install.BUNDLE_IDENTIFIER
    assert plist["CFBundleShortVersionString"] == "v9.9"
    executable = bundle / "Contents" / "MacOS" / "Extractium"
    assert executable.read_text(encoding="utf-8") == f'#!/bin/sh\nexec "{launcher}"\n'
    assert os.access(executable, os.X_OK)
    assert install.remove_mac_app(tmp_path / "Applications") is True
    assert not bundle.exists()


# ---------------------------------------------------------------------------
# Finishing an install
# ---------------------------------------------------------------------------

def test_finish_installs_writes_the_shim_and_the_marks_and_holds_no_machine_path(tmp_path, source):
    home, python = make_home(tmp_path)
    run = Recorder()
    registry = FakeRegistry("C:\\Windows")
    places = places_under(tmp_path)

    lines = install.finish(home, python, source, source / "requirements-lock.txt", uv=home / "uv.exe",
                           installer=source / "install.bat", version="v9.9", platform=install.WINDOWS,
                           places=places, run=run, read_path=registry.read, write_path=registry.write)

    assert run.commands[0][0] == str(home / "uv.exe") and "--require-hashes" in run.commands[0]
    assert run.commands[1][-2:] == ["--no-deps", str(source)]
    assert run.commands[2][0] == "powershell"
    shim = home / "bin" / "extractium.cmd"
    assert shim.exists() and (home / "cache").is_dir()
    assert (home / install.VERSION_FILE).read_text(encoding="utf-8") == "v9.9\n"
    assert not (home / install.NOT_PORTABLE_FILE).exists()
    assert (home / "install.bat").exists()
    assert registry.value.endswith(str(home / "bin"))
    assert any("Installed Extractium v9.9" in line for line in lines)
    # Nothing the installer wrote names where the folder was made.
    for written in (shim, home / install.VERSION_FILE, home / "install.bat"):
        assert str(tmp_path) not in written.read_text(encoding="utf-8")


def test_a_portable_finish_touches_neither_path_nor_the_menu(tmp_path, source):
    home, python = make_home(tmp_path)
    run = Recorder()
    registry = FakeRegistry("C:\\Windows")

    lines = install.finish(home, python, source, source / "requirements-lock.txt", portable=True,
                           platform=install.WINDOWS, places=places_under(tmp_path), run=run,
                           read_path=registry.read, write_path=registry.write)

    assert len(run.commands) == 2
    assert registry.writes == 0
    assert not (places_under(tmp_path)["menu"]).exists()
    assert any("double-click run.bat" in line for line in lines)


def test_a_finish_on_a_virtual_environment_marks_the_folder_as_not_portable(tmp_path, source):
    home, python = make_home(tmp_path, venv=True)
    run = Recorder()
    registry = FakeRegistry("")

    lines = install.finish(home, python, source, source / "requirements-lock.txt", platform=install.WINDOWS,
                           places=places_under(tmp_path), run=run, read_path=registry.read,
                           write_path=registry.write)

    assert (home / install.NOT_PORTABLE_FILE).exists()
    assert not install.is_portable(home)
    assert any("cannot be moved" in line for line in lines)
    assert run.commands[0][:4] == [str(python), "-m", "pip", "install"]


def test_a_posix_finish_writes_the_bin_script_the_menu_entry_and_says_about_path(tmp_path, source, monkeypatch):
    home, python = make_home(tmp_path, platform=install.LINUX)
    run = Recorder()
    places = places_under(tmp_path)
    monkeypatch.setenv("PATH", "/usr/bin")

    lines = install.finish(home, python, source, source / "requirements-lock.txt", platform=install.LINUX,
                           places=places, run=run, version="v9.9")

    assert (places["user_bin"] / "extractium").exists()
    assert (places["menu"] / "extractium.desktop").exists()
    assert any("is not on your PATH" in line for line in lines)
    assert any(line.strip().startswith('export PATH="') for line in lines)
    assert len(run.commands) == 2

    monkeypatch.setenv("PATH", f"/usr/bin{os.pathsep}{places['user_bin']}")
    lines = install.finish(home, python, source, source / "requirements-lock.txt", platform=install.MACOS,
                           places=places, run=Recorder(), version="v9.9")
    assert (places["menu"] / "Extractium.app").is_dir()
    assert any("Open a new terminal" in line for line in lines)


def test_an_editable_finish_says_so(tmp_path, source):
    home, python = make_home(tmp_path)
    run = Recorder()

    lines = install.finish(home, python, source, source / "requirements-lock.txt", editable=True, portable=True,
                           platform=install.WINDOWS, places=places_under(tmp_path), run=run)

    assert "-e" in run.commands[1]
    assert any("editable" in line for line in lines)


# ---------------------------------------------------------------------------
# Update and uninstall
# ---------------------------------------------------------------------------

def test_update_reinstalls_into_the_folders_own_interpreter_with_its_uv(tmp_path, source):
    home, python = make_home(tmp_path)
    (home / "uv.exe").write_bytes(b"")
    install.write_shim(home, install.find_interpreter(home), install.WINDOWS)
    run = Recorder()

    lines = install.update(home, source, source / "requirements-lock.txt", version="v9.10", run=run,
                           platform=install.WINDOWS)

    assert run.commands[0][:5] == [str(home / "uv.exe"), "pip", "install", "--python", str(python)]
    assert (home / install.VERSION_FILE).read_text(encoding="utf-8") == "v9.10\n"
    assert any("v9.10" in line for line in lines)


def test_uninstall_removes_the_path_entry_and_the_menu_entry_and_leaves_the_folder(tmp_path):
    home, python = make_home(tmp_path)
    places = places_under(tmp_path)
    registry = FakeRegistry(f"C:\\Windows{os.pathsep}{home / 'bin'}")
    places["menu"].mkdir(parents=True)
    (places["menu"] / "Extractium.lnk").write_bytes(b"lnk")

    lines = install.uninstall(home, platform=install.WINDOWS, places=places, read_path=registry.read,
                              write_path=registry.write)

    assert registry.value == "C:\\Windows"
    assert not (places["menu"] / "Extractium.lnk").exists()
    assert home.exists()
    assert any("deleted by the install script" in line for line in lines)


def test_uninstall_on_posix_removes_the_bin_script_and_the_entry(tmp_path):
    home, python = make_home(tmp_path, platform=install.LINUX)
    places = places_under(tmp_path)
    install.write_user_bin_script(places["user_bin"], home / "bin" / "extractium")
    install.write_desktop_entry(home / "bin" / "extractium-page", places["menu"])
    install.write_mac_app(home / "bin" / "extractium-page", places["menu"])

    install.uninstall(home, platform=install.LINUX, places=places)
    assert not (places["user_bin"] / "extractium").exists()
    assert not (places["menu"] / "extractium.desktop").exists()

    install.uninstall(home, platform=install.MACOS, places=places)
    assert not (places["menu"] / "Extractium.app").exists()


# ---------------------------------------------------------------------------
# Where things go
# ---------------------------------------------------------------------------

def test_the_default_places_follow_the_profile_on_each_platform():
    windows = install.default_places(install.WINDOWS, {"LOCALAPPDATA": "C:\\L", "APPDATA": "C:\\R",
                                                        "USERPROFILE": "C:\\U"})
    assert windows["home"] == pathlib.Path("C:\\L") / "Extractium"
    assert windows["menu"] == pathlib.Path("C:\\R") / "Microsoft" / "Windows" / "Start Menu" / "Programs"

    linux = install.default_places(install.LINUX, {"HOME": "/home/x"})
    assert linux["home"] == pathlib.Path("/home/x/.local/share/extractium")
    assert linux["user_bin"] == pathlib.Path("/home/x/.local/bin")
    assert linux["menu"] == pathlib.Path("/home/x/.local/share/applications")

    mac = install.default_places(install.MACOS, {"HOME": "/Users/x"})
    assert mac["menu"] == pathlib.Path("/Users/x/Applications")


def test_the_command_line_routes_each_step_and_reports_a_failure(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(install, "uninstall", lambda home, **kw: calls.append(("uninstall", home)) or ["done"])
    assert install.main(["uninstall", "--home", str(tmp_path)]) == 0
    assert calls == [("uninstall", str(tmp_path))]
    assert "done" in capsys.readouterr().out

    def failing(*args, **kw):
        raise install.InstallError("no Python was found")
    monkeypatch.setattr(install, "update", failing)
    assert install.main(["update", "--home", str(tmp_path), "--source", "s", "--lock", "l"]) == 1
    assert "no Python was found" in capsys.readouterr().err
