"""
Summary: Tests for the pieces a scheduled or one-command build relies on:
the pinned dependency list, the two run scripts, and the two GitHub
Actions workflows. They check what can be checked without a runner --
that every dependency is pinned and hashed, that the scripts install from
the lock file and fail on the first error, and that each workflow runs
weekly, runs on a button press, caches the crawl, keeps least privilege,
and publishes only through the official Pages actions.

This file is part of Extractium™
tests/test_operations.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
Last Modified: 2026-09-08
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
__date__ = "2026-09-08"

import pathlib
import re
import shutil
import subprocess

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


# ---------------------------------------------------------------------------
# The run scripts
# ---------------------------------------------------------------------------

def test_the_posix_script_is_valid_shell():
    if shutil.which("bash") is None:
        pytest.skip("bash is not installed on this machine")

    # Read from standard input, because a Windows path means nothing to
    # the bash on the path, which may be either Git for Windows or the
    # Windows Subsystem for Linux.
    # Sent as bytes so the line endings reach bash exactly as committed:
    # text mode would rewrite them for Windows, and a shell block ending
    # in a carriage return does not parse.
    result = subprocess.run(
        ["bash", "-n"],
        input=(REPO_ROOT / "run.sh").read_bytes(),
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


def test_the_posix_script_has_unix_line_endings():
    # A carriage return at the end of a line is part of the command on
    # macOS and Linux, so a script saved the Windows way does not run
    # there at all.
    assert b"\r\n" not in (REPO_ROOT / "run.sh").read_bytes()


def test_the_posix_script_stops_at_the_first_failure():
    text = (REPO_ROOT / "run.sh").read_text(encoding="utf-8")

    assert "set -euo pipefail" in text


@pytest.mark.parametrize("script", ["run.sh", "run.bat"])
def test_each_run_script_installs_the_locked_versions_only(script):
    text = (REPO_ROOT / script).read_text(encoding="utf-8")

    assert "requirements-lock.txt" in text
    assert "--require-hashes" in text
    # The project itself goes in without dependencies, so pip cannot
    # quietly resolve something the lock file did not name.
    assert "--no-deps" in text


@pytest.mark.parametrize("script", ["run.sh", "run.bat"])
def test_each_run_script_builds_and_says_what_to_commit(script):
    text = (REPO_ROOT / script).read_text(encoding="utf-8")

    assert "extractium.cli build" in text
    assert "git add" in text
    assert ".kb_cache" in text


@pytest.mark.parametrize("script", ["run.sh", "run.bat"])
def test_each_run_script_hard_codes_no_developer_path(script):
    text = (REPO_ROOT / script).read_text(encoding="utf-8")

    assert "C:\\Users" not in text
    assert "/home/" not in text
    assert "/Users/" not in text


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


def test_every_action_is_pinned_to_a_major_version(workflow_text):
    references = re.findall(r"uses:\s*(\S+)", workflow_text)

    assert references
    for reference in references:
        assert re.search(r"@v\d+$", reference), reference


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

    assert workflow["env"]["EXTRACTIUM_REF"]
    steps = workflow["jobs"]["build"]["steps"]
    checkout = next(step for step in steps if step.get("with", {}).get("repository"))
    assert checkout["with"]["ref"] == "${{ env.EXTRACTIUM_REF }}"


# ---------------------------------------------------------------------------
# The data-repository template
# ---------------------------------------------------------------------------

def test_the_data_repository_template_holds_what_an_operator_needs():
    template = REPO_ROOT / "examples" / "data-repo"

    for name in ("config.yaml", "README.md", ".gitignore",
                 ".github/workflows/build-compendium.yml"):
        assert (template / name).exists(), name


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

    assert '.[dev,code,youtube]' in python_steps
    assert "pytest" in python_steps
    for suite in ("clients/js", "examples/mcp/local-node", "examples/mcp/shared",
                  "examples/mcp/valtown", "examples/mcp/cloudflare"):
        assert f"node --test {suite}" in node_steps


def test_the_test_workflow_pins_every_action_to_a_major_version():
    references = re.findall(r"uses:\s*(\S+)", TESTS_WORKFLOW_PATH.read_text(encoding="utf-8"))

    assert references
    for reference in references:
        assert re.search(r"@v\d+$", reference), reference
