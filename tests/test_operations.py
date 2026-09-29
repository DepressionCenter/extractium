"""
Summary: Tests for the pieces a scheduled or one-command build relies on:
the pinned dependency list, the two thin run scripts, the two install
scripts, and the GitHub Actions workflows. They check what can be checked
without a runner: that every dependency is pinned and hashed; that the
run scripts find the folder beside them, then the per-user install, then
the installer, and route "ui", no argument, and a build argument; that
the installers pin uv by version and hash, keep it inside the folder,
tell the three situations apart, route every flag, pipe nothing into a
shell, run no admin step on their own, and stop saying what to ask for;
and that each workflow runs weekly, runs on a button press, caches the
crawl, keeps least privilege, and publishes only through the official
Pages actions.

This file is part of Extractium™
tests/test_operations.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
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
import re
import shutil
import subprocess
import sys

import pytest
import yaml

# The repository root, from which every path below is resolved.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# The two workflows: the template in this repository, and the copy that
# ships inside the data-repository template.
WORKFLOW_PATHS = (
    REPO_ROOT / ".github" / "workflows" / "build-compendium.yml",
    REPO_ROOT / "examples" / "data-repo" / ".github" / "workflows" / "build-compendium.yml",
)

# Every runtime dependency named in pyproject.toml. A lock file missing
# one of these would install a different set of packages than a developer
# install does.
RUNTIME_PACKAGES = ("requests", "beautifulsoup4", "sentence-transformers", "numpy", "markdown", "pyyaml")

# Publishing must go through GitHub's own Pages actions, never a
# third-party publisher with a token.
OFFICIAL_PAGES_ACTIONS = (
    "actions/configure-pages",
    "actions/upload-pages-artifact",
    "actions/deploy-pages",
)


@pytest.fixture(scope="module")
def lock_text():
    """The committed dependency lock file."""
    return (REPO_ROOT / "requirements-lock.txt").read_text(encoding="utf-8")


@pytest.fixture(params=WORKFLOW_PATHS, ids=lambda path: path.parts[-4])
def workflow(request):
    """Each workflow in turn, parsed."""
    return yaml.safe_load(request.param.read_text(encoding="utf-8"))


@pytest.fixture(params=WORKFLOW_PATHS, ids=lambda path: path.parts[-4])
def workflow_text(request):
    """Each workflow in turn, as written."""
    return request.param.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The lock file
# ---------------------------------------------------------------------------

def test_the_lock_file_pins_every_runtime_dependency(lock_text):
    pinned = {line.split("==")[0].lower() for line in lock_text.splitlines() if "==" in line}

    missing = [package for package in RUNTIME_PACKAGES if package not in pinned]
    assert not missing, f"not pinned: {missing}"


def test_every_pinned_package_carries_a_hash(lock_text):
    packages = re.findall(r"^([A-Za-z0-9._-]+)==([^\s\\]+)", lock_text, flags=re.MULTILINE)
    hashes = lock_text.count("--hash=sha256:")

    assert packages
    assert hashes >= len(packages)


def test_the_lock_file_keeps_its_license_header(lock_text):
    assert lock_text.startswith("# This file is part of Extractium")
    assert "GNU General Public License" in lock_text


def test_the_lock_file_records_how_it_was_generated(lock_text):
    assert "uv pip compile" in lock_text


def test_the_lock_file_pins_every_code_parser(lock_text):
    """
    The build scripts and the scheduled workflow install from the lock
    file alone, so a grammar missing from it is a language no scripted
    build can parse. The lock is generated with the code extra for that
    reason, and this keeps it from drifting back.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^code = \[(.*?)^\]", pyproject, flags=re.MULTILINE | re.DOTALL).group(1)
    wanted = {re.split(r"[<>=!~]", item, maxsplit=1)[0].lower() for item in re.findall(r'"([^"]+)"', block)}
    pinned = {line.split("==")[0].lower() for line in lock_text.splitlines() if "==" in line}

    assert wanted
    assert wanted <= pinned, f"not pinned: {sorted(wanted - pinned)}"


def test_the_lock_file_pins_the_pdf_reader(lock_text):
    """
    A scripted build reads PDF files only if the lock carries the pdf
    extra, for the same reason the parsers have to be in it.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^pdf = \[(.*?)\]", pyproject, flags=re.MULTILINE | re.DOTALL).group(1)
    wanted = {re.split(r"[<>=!~]", item, maxsplit=1)[0].lower() for item in re.findall(r'"([^"]+)"', block)}
    pinned = {line.split("==")[0].lower() for line in lock_text.splitlines() if "==" in line}

    assert wanted == {"pypdf"}
    assert wanted <= pinned
    assert "--extra pdf" in lock_text


# ---------------------------------------------------------------------------
# The scripts
# ---------------------------------------------------------------------------

def test_the_lock_file_pins_the_caption_library(lock_text):
    """
    The build scripts are how a build is made on a person's own
    computer, which is the only kind of machine YouTube answers caption
    requests from, so the lock they install from has to carry the
    caption library or no scripted build can fetch a transcript.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^youtube = \[(.*?)\]", pyproject, flags=re.MULTILINE | re.DOTALL).group(1)
    wanted = {re.split(r"[<>=!~]", item, maxsplit=1)[0].lower() for item in re.findall(r'"([^"]+)"', block)}
    pinned = {line.split("==")[0].lower() for line in lock_text.splitlines() if "==" in line}
    assert wanted == {"youtube-transcript-api"}
    assert wanted <= pinned
    assert "--extra youtube" in lock_text


def test_the_lock_file_pins_the_audio_packages(lock_text):
    """
    A scripted build transcribes a refused video from its audio only
    if the lock carries the whisper extra. YouTube refuses captions to
    most machines that build on a schedule, so a lock without these
    packages is a build that indexes no video from such a machine.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^whisper = \[(.*?)\]", pyproject, flags=re.MULTILINE | re.DOTALL).group(1)
    wanted = {re.split(r"[<>=!~]", item, maxsplit=1)[0].lower() for item in re.findall(r'"([^"]+)"', block)}
    pinned = {line.split("==")[0].lower() for line in lock_text.splitlines() if "==" in line}
    assert wanted == {"yt-dlp", "faster-whisper"}
    assert wanted <= pinned
    assert "--extra whisper" in lock_text


def test_the_lock_file_pins_the_keyword_extractor(lock_text):
    """
    A scripted build names sections with keywords only if the lock
    carries the keywords extra, for the same reason the parsers have
    to be in it.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^keywords = \[(.*?)\]", pyproject, flags=re.MULTILINE | re.DOTALL).group(1)
    wanted = {re.split(r"[<>=!~]", item, maxsplit=1)[0].lower() for item in re.findall(r'"([^"]+)"', block)}
    pinned = {line.split("==")[0].lower() for line in lock_text.splitlines() if "==" in line}

    assert wanted == {"yake"}
    assert wanted <= pinned
    assert "--extra keywords" in lock_text


def _working_bash():
    """
    A bash that can run on this machine, or None.

    On Windows, `bash` on the path is often the Windows Subsystem for
    Linux launcher in System32, which fails before running anything when
    no distribution is set up or the session cannot log on to it. The
    bash that Git for Windows ships beside git.exe always works, so it
    is tried first, then whatever the path names. Each candidate has to
    run a trivial command before it is trusted with the script.
    """
    candidates = []
    git = shutil.which("git")
    if git and sys.platform == "win32":
        install_root = pathlib.Path(git).resolve().parent.parent
        candidates += [install_root / "usr" / "bin" / "bash.exe", install_root / "bin" / "bash.exe"]
    on_path = shutil.which("bash")
    if on_path:
        candidates.append(pathlib.Path(on_path))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            probe = subprocess.run([str(candidate), "-c", "exit 0"], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            return str(candidate)
    return None


POSIX_SCRIPTS = ("run.sh", "install.sh")
WINDOWS_SCRIPTS = ("run.bat", "install.bat")
INSTALLERS = ("install.sh", "install.bat")
RUN_SCRIPTS = ("run.sh", "run.bat")


def script_text(name):
    return (REPO_ROOT / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("script", POSIX_SCRIPTS)
def test_each_posix_script_is_valid_shell(script):
    bash = _working_bash()
    if bash is None:
        pytest.skip("no working bash on this machine")

    # Read from standard input, because a Windows path means nothing to
    # the bash on the path, which may be either Git for Windows or the
    # Windows Subsystem for Linux.
    # Sent as bytes so the line endings reach bash exactly as committed:
    # text mode would rewrite them for Windows, and a shell block ending
    # in a carriage return does not parse.
    result = subprocess.run([bash, "-n"], input=(REPO_ROOT / script).read_bytes(), capture_output=True)

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


@pytest.mark.parametrize("script", POSIX_SCRIPTS)
def test_each_posix_script_has_unix_line_endings_and_stops_at_the_first_failure(script):
    # A carriage return at the end of a line is part of the command on
    # macOS and Linux, so a script saved the Windows way does not run
    # there at all.
    assert b"\r\n" not in (REPO_ROOT / script).read_bytes()
    assert "set -euo pipefail" in script_text(script)


@pytest.mark.parametrize("script", POSIX_SCRIPTS + WINDOWS_SCRIPTS)
def test_each_script_hard_codes_no_developer_path(script):
    text = script_text(script)

    assert "C:\\Users" not in text
    assert "/home/" not in text
    assert "/Users/" not in text


# The thin entry points ------------------------------------------------------

@pytest.mark.parametrize("script", RUN_SCRIPTS)
def test_each_run_script_prefers_the_folder_beside_it_then_the_per_user_install_then_installs(script):
    text = script_text(script)

    if script == "run.bat":
        assert 'if exist "%HERE%\\Extractium\\bin\\extractium.cmd" set "SHIM=' in text
        assert 'set "USER_SHIM=%LOCALAPPDATA%\\Extractium\\bin\\extractium.cmd"' in text
        assert 'if exist "%HERE%\\install.bat"' in text
        assert "/releases/latest/download/install.bat" in text
    else:
        assert 'if [ -x "$HERE/Extractium/bin/extractium" ]; then' in text
        assert 'USER_SHIM="${XDG_DATA_HOME:-$HOME/.local/share}/extractium/bin/extractium"' in text
        assert 'if [ -f "$HERE/install.sh" ]; then' in text
        assert "/releases/latest/download/install.sh" in text
    # The order is beside, then the profile, then the installer.
    if script == "run.bat":
        beside, profile = 'if exist "%HERE%\\Extractium\\bin', 'if exist "%USER_SHIM%"'
    else:
        beside, profile = 'if [ -x "$HERE/Extractium/bin/extractium" ]', 'elif [ -x "$USER_SHIM" ]'
    assert text.index(beside) < text.index(profile) < text.index("/releases/latest/download/")


@pytest.mark.parametrize("script", RUN_SCRIPTS)
def test_each_run_script_routes_ui_no_argument_and_a_build_argument(script):
    text = script_text(script)

    if script == "run.bat":
        assert 'if /i "%~1"=="ui" (' in text
        assert '"%SHIM%" ui %CONFIG_ARGS%' in text
        assert '"%SHIM%" start %CONFIG_ARGS%' in text
        assert '"%SHIM%" build %*' in text
    else:
        assert 'if [ "${1:-}" = "ui" ]; then' in text
        assert 'exec "$SHIM" ui "${CONFIG_ARGS[@]}" "$@"' in text
        assert 'exec "$SHIM" start "${CONFIG_ARGS[@]}"' in text
        assert 'exec "$SHIM" build "$@"' in text
    # CONFIG still names another settings file.
    assert "CONFIG" in text


@pytest.mark.parametrize("script", RUN_SCRIPTS)
def test_each_run_script_installs_nothing_itself(script):
    text = script_text(script)

    # The install, the environment, and the interpreter search all live
    # in the installer now; the entry point only finds and runs the shim.
    assert "pip install" not in text
    assert "venv" not in text
    assert "-m extractium.cli" not in text
    assert "requirements-lock" not in text


# The installers ---------------------------------------------------------------

UV_HASH_LINE = re.compile(r'UV_SHA256_[A-Z0-9_]+="?([0-9a-f]{64})"?', re.M)


@pytest.mark.parametrize("script", INSTALLERS)
def test_each_installer_pins_uv_by_version_and_hash(script):
    text = script_text(script)

    assert re.search(r'UV_VERSION="?\d+\.\d+\.\d+"?', text)
    hashes = UV_HASH_LINE.findall(text)
    # Two Windows archives; two macOS and two Linux ones.
    assert len(hashes) == (2 if script == "install.bat" else 4)
    assert len(set(hashes)) == len(hashes)
    assert "releases/download/" in text and "astral-sh/uv" in text
    # The download is checked before it is unpacked or run.
    assert "does not match the SHA-256" in text
    if script == "install.bat":
        assert "Get-FileHash -Algorithm SHA256" in text
    else:
        assert "sha256sum" in text and "shasum -a 256" in text


@pytest.mark.parametrize("script", INSTALLERS)
def test_each_installer_keeps_uv_inside_the_folder_and_trusts_the_machines_certificates(script):
    text = script_text(script)

    assert "UV_NATIVE_TLS=1" in text
    assert "UV_LINK_MODE=copy" in text
    assert "UV_PYTHON_INSTALL_DIR=" in text
    assert "UV_CACHE_DIR=" in text
    assert re.search(r'PYTHON_VERSION="?3\.\d+\.\d+"?', text)
    assert "python install" in text and "--install-dir" in text


@pytest.mark.parametrize("script", INSTALLERS)
def test_each_installer_tells_the_three_situations_apart(script):
    text = script_text(script)

    if script == "install.bat":
        assert 'if exist "%HERE%\\Extractium\\bin\\extractium.cmd"' in text
        assert 'if exist "%HERE%\\pyproject.toml"' in text
        assert "extractium.install copy --from" in text
    else:
        assert 'if [ -x "$HERE/Extractium/bin/extractium" ]' in text
        assert 'if [ -f "$HERE/pyproject.toml" ]; then' in text
        assert "extractium.install copy --from" in text
    # On its own: the newest release through the redirect, then the archive.
    assert "/releases/latest" in text
    assert "/releases/tag/" in text
    assert "/archive/" in text
    # git is not used to fetch the tool any more.
    assert "git clone" not in text


@pytest.mark.parametrize("script", INSTALLERS)
def test_each_installer_routes_every_flag(script):
    text = script_text(script)

    for flag in ("--portable", "--update", "--uninstall", "--version", "--editable", "--help"):
        assert flag in text, flag
    assert "install.py" in text and "finish" in text
    assert '" update ' in text
    assert "uninstall --home" in text


@pytest.mark.parametrize("script", INSTALLERS)
def test_each_installer_hands_over_with_the_lock_and_never_a_shell_string(script):
    text = script_text(script)

    # The packages are installed by install.py from the lock, which the
    # script names; the script itself never calls pip on the lock.
    assert "requirements-lock.txt" in text
    assert "--require-hashes" not in text
    # Nothing downloaded is piped into a shell.
    for forbidden in ("| sh", "| bash", "|sh", "|bash", "iex", "Invoke-Expression"):
        assert forbidden not in text, forbidden


@pytest.mark.parametrize("script", INSTALLERS)
def test_each_installer_runs_no_admin_step_and_never_truncates_path(script):
    text = script_text(script)

    assert "setx" not in text
    assert "runas" not in text.lower()
    if script == "install.bat":
        assert "sudo" not in text
        assert "winget install" in text
    else:
        # A packager command that needs sudo is printed and run only
        # after a yes, inside the one helper that asks.
        offering = text[text.index("offer_command() {"):]
        helper = offering[:offering.index("\n}\n")]
        assert 'read -r -p "Run it now? [y/N]: "' in helper
        for line in text.splitlines():
            if "sudo" in line:
                assert "offer_command" in line, line
        assert "dnf install" in text and "apt-get install python3-venv" in text and "brew install" in text


@pytest.mark.parametrize("script", INSTALLERS)
def test_each_installer_stops_and_says_what_to_ask_for(script):
    text = script_text(script)

    assert "Ask IT for" in text
    assert "cannot be moved" in text                    # the machine-Python fallback is not portable
    assert "Py_GIL_DISABLED" in text                    # a standard build is preferred
    assert "sys.version_info >= (3, 10)" in text


def test_the_windows_installer_pauses_when_double_clicked_and_asks_before_removing():
    text = script_text("install.bat")

    assert "%cmdcmdline%" in text and "pause" in text
    assert "[y/N]" in text and "rmdir /s /q \"%HOME_DIR%\"" in text


def test_the_windows_installer_downloads_through_powershell():
    text = script_text("install.bat")

    assert "Invoke-WebRequest" in text
    assert "Expand-Archive" in text
    assert "SecurityProtocolType]::Tls12" in text


def test_the_posix_installer_downloads_through_curl_or_wget():
    text = script_text("install.sh")

    assert "curl -fsSL" in text
    assert "wget -q" in text


FAKE_CURL = """#!/bin/sh
# Serves the same small archive for every address, so the hash never
# matches what the installer expects.
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o) out="$2"; shift ;;
    esac
    shift
done
cp "$FAKE_ARCHIVE" "$out"
"""


def test_the_posix_installer_refuses_a_uv_download_whose_hash_differs(tmp_path):
    """
    A real run of install.sh with a fake curl on the path: the archive it
    serves holds a fake uv, and its hash is not the one pinned in the
    script, so the install must stop at step 1 without running it.
    """
    bash = _working_bash()
    if bash is None:
        pytest.skip("no working bash on this machine")
    if sys.platform == "win32":
        pytest.skip("the fake path and uname of a Windows bash do not stand in for macOS or Linux")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    archive_root = tmp_path / "archive" / "uv-fake"
    archive_root.mkdir(parents=True)
    (archive_root / "uv").write_text("#!/bin/sh\necho 'uv ran' > \"$FAKE_RAN\"\n", encoding="utf-8")
    (archive_root / "uv").chmod(0o755)
    archive = tmp_path / "uv.tar.gz"
    subprocess.run(["tar", "-czf", str(archive), "-C", str(tmp_path / "archive"), "uv-fake"], check=True)
    (fake_bin / "curl").write_text(FAKE_CURL, encoding="utf-8")
    (fake_bin / "curl").chmod(0o755)
    home = tmp_path / "profile"
    ran = tmp_path / "ran.txt"
    # A checkout beside the script, so nothing but uv is downloaded.
    checkout = tmp_path / "checkout"
    shutil.copytree(REPO_ROOT / "extractium", checkout / "extractium")
    for name in ("pyproject.toml", "requirements-lock.txt", "install.sh"):
        shutil.copy(REPO_ROOT / name, checkout / name)

    result = subprocess.run(
        [bash, str(checkout / "install.sh"), "--portable"],
        env={"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": str(home), "FAKE_ARCHIVE": str(archive),
             "FAKE_RAN": str(ran), "PYTHON_EXE": "/no/such/python"},
        capture_output=True, text=True, cwd=tmp_path, timeout=120,
    )

    assert result.returncode != 0
    assert "does not match the SHA-256" in result.stderr
    assert not ran.exists(), "the unverified uv must never run"
    assert not (checkout / "Extractium" / "uv").exists()


def test_the_lock_without_parsers_keeps_every_other_package_and_hash(lock_text):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "lock_without_parsers", REPO_ROOT / "tools" / "lock_without_parsers.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    filtered = module.without_parsers(lock_text)

    packages = lambda text: [line.split("==")[0] for line in text.splitlines() if "==" in line]
    assert [name for name in packages(lock_text) if not name.startswith("tree-sitter")] == packages(filtered)
    assert not any(name.startswith("tree-sitter") for name in packages(filtered))
    # Every hash of every kept package is still there, and no parser hash is.
    kept_hashes = filtered.count("--hash=")
    parser_hashes = sum(
        block.count("--hash=") for block in re.split(r"(?m)^(?=\S)", lock_text) if block.startswith("tree-sitter")
    )
    assert kept_hashes == lock_text.count("--hash=") - parser_hashes
    assert filtered.startswith(lock_text[:200])          # the license header survives


# ---------------------------------------------------------------------------
# The workflows
# ---------------------------------------------------------------------------

def test_each_workflow_runs_weekly_and_on_a_button_press(workflow):
    # PyYAML reads the unquoted key "on" as the boolean True, which is
    # what the YAML 1.1 rules say; GitHub reads it as the word.
    triggers = workflow[True]

    assert "workflow_dispatch" in triggers
    (cron,) = triggers["schedule"]
    assert re.fullmatch(r"\d+ \d+ \* \* [0-6]", cron["cron"]), cron


def test_each_workflow_asks_for_no_more_than_read_access_by_default(workflow):
    assert workflow["permissions"] == {"contents": "read"}


def test_only_the_publishing_job_may_write_to_pages(workflow):
    publish = workflow["jobs"]["publish"]

    assert publish["permissions"] == {"pages": "write", "id-token": "write"}
    assert "contents" not in publish["permissions"]


def test_each_workflow_publishes_only_through_the_official_pages_actions(workflow_text):
    used = re.findall(r"uses:\s*([^\s@]+)@", workflow_text)

    publishers = [action for action in used if "pages" in action]
    assert publishers
    for action in publishers:
        assert action in OFFICIAL_PAGES_ACTIONS, action


# An action reference pinned to a full commit digest, with the release it
# is in a comment, so a moved tag can never change what a workflow runs.
PINNED_ACTION_RE = re.compile(r"^\s*uses:\s*[\w.-]+/[\w.-]+@[0-9a-f]{40}\s+# v\d+\.\d+\.\d+\s*$", re.M)


def test_every_action_is_pinned_to_a_commit_digest(workflow_text):
    references = re.findall(r"^\s*uses:.*$", workflow_text, re.M)

    assert references
    for reference in references:
        assert PINNED_ACTION_RE.match(reference), reference


def test_each_workflow_caches_the_crawl_keyed_on_the_settings_file(workflow):
    steps = [step for job in workflow["jobs"].values() for step in job.get("steps", [])]

    cache = next(step for step in steps if str(step.get("uses", "")).startswith("actions/cache@"))
    assert cache["with"]["path"] == ".kb_cache"
    assert "hashFiles" in cache["with"]["key"]
    assert "restore-keys" in cache["with"]


def test_each_workflow_publishes_one_run_at_a_time_without_cancelling(workflow):
    assert workflow["concurrency"]["group"] == "pages"
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_the_data_repository_workflow_builds_with_a_named_version_of_the_tool():
    workflow = yaml.safe_load(WORKFLOW_PATHS[1].read_text(encoding="utf-8"))

    # A release tag, so a change merged here never reaches an adopter's
    # scheduled build unannounced.
    assert re.fullmatch(r"v\d+\.\d+(\.\d+)?", workflow["env"]["EXTRACTIUM_REF"])
    steps = workflow["jobs"]["build"]["steps"]
    checkout = next(step for step in steps if step.get("with", {}).get("repository"))
    assert checkout["with"]["ref"] == "${{ env.EXTRACTIUM_REF }}"


# ---------------------------------------------------------------------------
# The data-repository template
# ---------------------------------------------------------------------------

def test_the_data_repository_template_holds_what_an_operator_needs():
    template = REPO_ROOT / "examples" / "data-repo"

    for name in ("config.yaml", "README.md", ".gitignore",
                 ".github/workflows/build-compendium.yml", ".gitlab-ci.yml"):
        assert (template / name).exists(), name


def test_the_gitlab_pipeline_pins_the_tool_checks_hashes_and_keeps_the_cache():
    pipeline = yaml.safe_load(
        (REPO_ROOT / "examples" / "data-repo" / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    script = " ".join(pipeline["build"]["script"])

    assert pipeline["variables"]["EXTRACTIUM_REF"].startswith("v")
    assert '--branch "$EXTRACTIUM_REF"' in script
    assert "--require-hashes" in script
    assert "--no-deps" in script
    assert ".kb_cache/" in pipeline["cache"]["paths"]
    assert pipeline["cache"]["key"]["files"] == ["config.yaml"]
    assert pipeline["build"]["artifacts"]["paths"] == ["$OUT_DIR/"]
    assert "public/" in pipeline["pages"]["artifacts"]["paths"]


def test_the_gitlab_pipeline_runs_only_on_a_schedule_or_by_hand():
    pipeline = yaml.safe_load(
        (REPO_ROOT / "examples" / "data-repo" / ".gitlab-ci.yml").read_text(encoding="utf-8"))

    for job in ("build", "pages"):
        sources = {rule["if"] for rule in pipeline[job]["rules"] if rule.get("when") != "never"}
        assert sources == {'$CI_PIPELINE_SOURCE == "schedule"', '$CI_PIPELINE_SOURCE == "web"'}, job


def test_the_template_settings_file_loads_and_names_synthetic_sources():
    from extractium.config import load_config

    config = load_config(REPO_ROOT / "examples" / "data-repo" / "config.yaml")

    assert config.sources
    assert config.sources[0].type == "web"
    assert "example.edu" in config.sources[0].options["seed_url"]
    assert config.out_dir


def test_the_template_keeps_the_crawl_cache_and_the_environment_out_of_git():
    ignored = (REPO_ROOT / "examples" / "data-repo" / ".gitignore").read_text(encoding="utf-8")

    assert ".kb_cache/" in ignored
    assert ".venv/" in ignored


# ---------------------------------------------------------------------------
# The test workflow
# ---------------------------------------------------------------------------

TESTS_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "tests.yml"


@pytest.fixture(scope="module")
def tests_workflow():
    return yaml.safe_load(TESTS_WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_the_test_workflow_runs_on_pull_requests_and_on_pushes_to_main(tests_workflow):
    triggers = tests_workflow[True]

    assert "pull_request" in triggers
    assert triggers["push"]["branches"] == ["main"]


def test_the_test_workflow_asks_for_read_access_only_and_no_secret(tests_workflow):
    assert tests_workflow["permissions"] == {"contents": "read"}
    text = TESTS_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "secrets." not in text


def test_the_test_workflow_covers_both_python_extremes_and_both_operating_systems(tests_workflow):
    matrix = tests_workflow["jobs"]["python"]["strategy"]["matrix"]

    assert "3.10" in matrix["python"]
    assert any(os.startswith("ubuntu") for os in matrix["os"])
    assert any(os.startswith("windows") for os in matrix["os"])


def test_the_test_workflow_runs_every_suite_with_every_extra(tests_workflow):
    python_steps = "\n".join(str(step.get("run", "")) for step in tests_workflow["jobs"]["python"]["steps"])
    node_steps = "\n".join(str(step.get("run", "")) for step in tests_workflow["jobs"]["node"]["steps"])

    assert '.[dev,code,youtube,pdf,keywords]' in python_steps
    assert "pytest" in python_steps
    for suite in ("clients/js", "examples/mcp/local-node", "examples/mcp/shared",
                  "examples/mcp/valtown", "examples/mcp/cloudflare"):
        assert f"node --test {suite}" in node_steps


def test_the_test_workflow_pins_every_action_to_a_commit_digest():
    references = re.findall(r"^\s*uses:.*$", TESTS_WORKFLOW_PATH.read_text(encoding="utf-8"), re.M)

    assert references
    for reference in references:
        assert PINNED_ACTION_RE.match(reference), reference
