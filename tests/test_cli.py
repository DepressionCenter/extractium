"""
Summary: Tests for the command line. Drives a complete build through a
throwaway source dropped into a plugins/ folder, so the registry, the
build step, and both adapters are exercised without a network or the
embedding model. Pins the exit code for each way a build can fail, the
command-line overrides, and the split between progress on standard error
and the summary on standard output.

This file is part of Extractium™
tests/test_cli.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
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

import json
import struct
import textwrap

import pytest

from extractium import cli
from extractium.core import phi_lint

# A source plugin the tests drop into a plugins/ folder. It yields fixed
# documents rather than fetching anything, which is what lets the whole
# command line run offline. The page bodies are long enough to clear the
# chunker's minimum section size.
PLUGIN_SOURCE = '''
from extractium.core.models import Document

PAGES = [
    ("https://example.org/alpha", "Alpha Page",
     "Alpha body text that is comfortably longer than the minimum section size, so "
     "the chunker keeps it as one section of its own for this test."),
    ("https://example.org/beta", "Beta Page",
     "Beta body text that is also comfortably longer than the minimum section size, "
     "with different wording so it is not collapsed as a near duplicate."),
]


class FixedSource:
    name = "fixed"

    def __init__(self, options):
        self.options = options

    def fetch(self, session, cache, progress):
        for url, title, body in PAGES:
            progress("visiting " + url)
            yield Document(url=url, title=title, content=body,
                           source_type="web", content_type="page")


class EmptySource:
    name = "empty"

    def __init__(self, options):
        self.options = options

    def fetch(self, session, cache, progress):
        return iter(())


def register(registry):
    registry.register_source(FixedSource)
    registry.register_source(EmptySource)
'''

# The tests never load the real embedding model. This replacement gives
# every chunk a distinct unit vector derived from its own text.
FAKE_EMBEDDER = '''
import hashlib
import numpy as np
from extractium.core.embed import DIMS


def embed_chunks(chunks, progress=None):
    vecs = np.zeros((len(chunks), DIMS), dtype=np.float32)
    for i, c in enumerate(chunks):
        seed = int(hashlib.sha256(c["x"].encode("utf-8")).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).normal(size=DIMS).astype(np.float32)
        vecs[i] = v / np.linalg.norm(v)
    return vecs
'''


@pytest.fixture
def build_workspace(tmp_path, monkeypatch, fake_embed_chunks_core):
    """
    A folder the command line can run a whole build in: a plugins/ folder
    holding the throwaway sources, an isolated cache, and the embedding
    step replaced by the deterministic fake.
    """
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "fixed_source.py").write_text(PLUGIN_SOURCE, encoding="utf-8")

    from extractium.core import embed

    monkeypatch.setattr(embed, "embed_chunks", lambda chunks, progress=None: fake_embed_chunks_core(chunks))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write_config(folder, body, name="config.yaml"):
    path = folder / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(path)


def read_container(path):
    data = path.read_bytes()
    (length,) = struct.unpack("<I", data[:4])
    return json.loads(data[4:4 + length].decode("utf-8"))


# ---------------------------------------------------------------------------
# A complete build
# ---------------------------------------------------------------------------

def test_build_writes_every_configured_output(build_workspace, capsys):
    config = write_config(build_workspace, """
        name: Example Org
        cache_dir: .cache
        sources:
          - type: fixed
        outputs:
          - type: container
          - type: llmstxt
    """)

    code = cli.main(["build", "--config", config])

    assert code == cli.EXIT_OK
    out_dir = build_workspace / "dist"
    assert (out_dir / "kb-index.json").exists()
    assert (out_dir / "llms.txt").exists()
    assert (out_dir / "llms-full.txt").exists()
    header = read_container(out_dir / "kb-index.json")
    assert header["site"] == "Example Org"
    assert header["v"] == 3
    assert len(header["parents"]) == 2
    assert capsys.readouterr().out.count("wrote    :") == 3


def test_build_defaults_to_the_container_and_llmstxt_outputs(build_workspace):
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: fixed
    """)

    assert cli.main(["build", "--config", config]) == cli.EXIT_OK
    assert (build_workspace / "dist" / "kb-index.json").exists()
    assert (build_workspace / "dist" / "llms.txt").exists()


def test_build_names_the_index_after_the_first_page_when_the_file_does_not(build_workspace):
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: fixed
    """)

    cli.main(["build", "--config", config])

    assert read_container(build_workspace / "dist" / "kb-index.json")["site"] == "Alpha Page"


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

def test_out_dir_flag_overrides_the_configuration_file(build_workspace):
    config = write_config(build_workspace, """
        out_dir: dist
        cache_dir: .cache
        sources:
          - type: fixed
    """)

    cli.main(["build", "--config", config, "--out-dir", "published"])

    assert (build_workspace / "published" / "kb-index.json").exists()
    assert not (build_workspace / "dist").exists()


def test_float32_vecs_flag_changes_the_stored_vector_type(build_workspace):
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: fixed
    """)

    cli.main(["build", "--config", config, "--float32-vecs"])

    embedding = read_container(build_workspace / "dist" / "kb-index.json")["embedding"]
    assert embedding["dtype"] == "float32"
    assert "scale" not in embedding


def test_max_pages_flag_is_validated_like_the_setting_it_overrides(build_workspace, capsys):
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: fixed
    """)

    code = cli.main(["build", "--config", config, "--max-pages", "0"])

    assert code == cli.EXIT_CONFIG
    assert "max_pages must be 1 or greater" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------

def test_a_missing_configuration_file_exits_two(build_workspace, capsys):
    code = cli.main(["build", "--config", "no-such-file.yaml"])

    assert code == cli.EXIT_CONFIG
    assert "cannot be read" in capsys.readouterr().err


def test_an_invalid_configuration_file_exits_two(build_workspace, capsys):
    config = write_config(build_workspace, """
        max_page: 10
        sources:
          - type: fixed
    """)

    code = cli.main(["build", "--config", config])

    assert code == cli.EXIT_CONFIG
    assert "unrecognized setting(s): max_page" in capsys.readouterr().err


def test_an_unknown_source_type_exits_two(build_workspace, capsys):
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: not_installed
    """)

    code = cli.main(["build", "--config", config])

    assert code == cli.EXIT_CONFIG
    assert "not_installed" in capsys.readouterr().err


def test_an_unknown_output_type_exits_two(build_workspace, capsys):
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: fixed
        outputs:
          - type: not_installed
    """)

    code = cli.main(["build", "--config", config])

    assert code == cli.EXIT_CONFIG
    assert "not_installed" in capsys.readouterr().err


def test_a_build_with_no_indexable_content_exits_three_and_writes_nothing(
    build_workspace, capsys
):
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: empty
    """)

    code = cli.main(["build", "--config", config])

    assert code == cli.EXIT_NO_CONTENT
    assert "no indexable content" in capsys.readouterr().err
    assert not (build_workspace / "dist").exists()


def test_an_unwritable_output_exits_four(build_workspace, monkeypatch, capsys):
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: fixed
        outputs:
          - type: container
    """)
    from extractium.adapters import container

    def refuse(self, compendium, out_dir, options):
        raise OSError("disk is full")

    monkeypatch.setattr(container.ContainerAdapter, "write", refuse)

    code = cli.main(["build", "--config", config])

    assert code == cli.EXIT_OUTPUT
    assert "disk is full" in capsys.readouterr().err


def test_an_unexpected_failure_exits_one_without_a_traceback(build_workspace, monkeypatch, capsys):
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: fixed
    """)
    monkeypatch.setattr(cli, "build_compendium", lambda *a, **k: 1 / 0)

    code = cli.main(["build", "--config", config])

    err = capsys.readouterr().err
    assert code == cli.EXIT_FAILED
    assert "ZeroDivisionError" in err
    assert "Traceback" not in err


# ---------------------------------------------------------------------------
# Local content and the review reports
# ---------------------------------------------------------------------------

LOCAL_NOTE = (
    "# Intake Notes\n\n"
    "MRN: AB123456. The rest of this note is ordinary prose, long enough that "
    "the chunker keeps it as one section of its own for this test.\n"
)


def workspace_with_a_local_folder(folder):
    """The build workspace with a folder of local notes beside it."""
    notes = folder / "notes"
    notes.mkdir()
    (notes / "intake.md").write_text(LOCAL_NOTE, encoding="utf-8")
    return notes


def test_a_local_source_reaches_no_output_that_did_not_opt_in(build_workspace, capsys):
    workspace_with_a_local_folder(build_workspace)
    config = write_config(build_workspace, """
        name: Example Org
        out_dir: dist
        cache_dir: .cache
        sources:
          - type: local
            path: notes
        outputs:
          - type: container
          - type: sqlite
    """)

    assert cli.main(["build", "--config", config]) == cli.EXIT_OK

    published = (build_workspace / "dist" / "kb-index.json").read_bytes()
    assert b"AB123456" not in published
    assert "NOTICE" not in capsys.readouterr().out


def test_an_output_that_opts_in_gets_the_local_content_and_is_named_in_the_summary(
    build_workspace, capsys
):
    workspace_with_a_local_folder(build_workspace)
    config = write_config(build_workspace, """
        name: Example Org
        out_dir: dist
        cache_dir: .cache
        sources:
          - type: local
            path: notes
        outputs:
          - type: container
          - type: sqlite
            include_local: true
    """)

    assert cli.main(["build", "--config", config]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "output 'sqlite' includes local content" in out
    assert "output 'container' includes local content" not in out
    assert b"AB123456" not in (build_workspace / "dist" / "kb-index.json").read_bytes()
    assert b"AB123456" in (build_workspace / "dist" / "compendium.sqlite").read_bytes()


def test_a_build_writes_both_review_reports_to_the_working_folder(build_workspace, capsys):
    """
    The reports say where someone should look before publishing, so they
    stay out of the folder that gets published.
    """
    workspace_with_a_local_folder(build_workspace)
    config = write_config(build_workspace, """
        out_dir: dist
        cache_dir: .cache
        sources:
          - type: local
            path: notes
    """)

    cli.main(["build", "--config", config])

    assert (build_workspace / phi_lint.JSON_REPORT_NAME).exists()
    assert (build_workspace / phi_lint.TEXT_REPORT_NAME).exists()
    assert not (build_workspace / "dist" / phi_lint.JSON_REPORT_NAME).exists()
    assert not (build_workspace / "dist" / phi_lint.TEXT_REPORT_NAME).exists()


def test_the_review_summary_reports_what_was_found_without_claiming_what_was_not(
    build_workspace, capsys
):
    workspace_with_a_local_folder(build_workspace)
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: local
            path: notes
    """)

    cli.main(["build", "--config", config])

    captured = capsys.readouterr()
    assert "PHI lint" in captured.err
    assert "pattern match(es) to review" in captured.err
    assert "no phi" not in (captured.err + captured.out).lower()


def test_turning_the_check_off_writes_no_report(build_workspace, capsys):
    """
    The mode is quoted because YAML reads a bare off as the boolean false.
    The configuration loader refuses that with a message naming the setting.
    """
    workspace_with_a_local_folder(build_workspace)
    config = write_config(build_workspace, """
        cache_dir: .cache
        phi_lint: 'off'
        sources:
          - type: local
            path: notes
    """)

    cli.main(["build", "--config", config])

    assert not (build_workspace / phi_lint.JSON_REPORT_NAME).exists()
    assert "PHI lint: off" in capsys.readouterr().err


def test_a_report_that_cannot_be_written_exits_four(build_workspace, monkeypatch, capsys):
    workspace_with_a_local_folder(build_workspace)
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: local
            path: notes
    """)

    def refuse(report, directory=None):
        raise OSError("disk full")

    monkeypatch.setattr(phi_lint, "write_reports", refuse)

    assert cli.main(["build", "--config", config]) == cli.EXIT_OUTPUT
    assert "report could not be written" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Output streams
# ---------------------------------------------------------------------------

def test_progress_goes_to_standard_error_and_the_summary_to_standard_output(
    build_workspace, capsys
):
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: fixed
    """)

    cli.main(["build", "--config", config])

    captured = capsys.readouterr()
    assert "visiting https://example.org/alpha" in captured.err
    assert "visiting" not in captured.out
    assert captured.out.startswith("Built ")
    assert "sections :" in captured.out


def test_the_summary_calls_out_an_output_that_includes_local_content(build_workspace, capsys):
    plugins = build_workspace / "plugins"
    (plugins / "local_source.py").write_text(
        "from extractium.core.models import Document\n"
        "\n"
        "\n"
        "class LocalSource:\n"
        "    name = 'localfixture'\n"
        "\n"
        "    def __init__(self, options):\n"
        "        self.options = options\n"
        "\n"
        "    def fetch(self, session, cache, progress):\n"
        "        yield Document(url='local:notes.txt', title='Notes',\n"
        "                       content='Internal note long enough to clear the minimum "
        "section size used by the chunker for this test.',\n"
        "                       source_type='local', content_type='text', local=True)\n"
        "\n"
        "\n"
        "def register(registry):\n"
        "    registry.register_source(LocalSource)\n",
        encoding="utf-8",
    )
    config = write_config(build_workspace, """
        cache_dir: .cache
        sources:
          - type: fixed
          - type: localfixture
        outputs:
          - type: container
            include_local: true
    """)

    cli.main(["build", "--config", config])

    assert "includes local content" in capsys.readouterr().out


def test_output_survives_a_console_that_cannot_encode_a_page_title(tmp_path):
    """
    Page titles come from sites nobody here controls. A console whose
    encoding has no room for one of their characters must not cost a
    finished build its summary.
    """
    path = tmp_path / "summary.txt"
    with open(path, "w", encoding="cp1252", newline="\n") as narrow:
        cli.write_line("Built 'Mobile Tech ⌚ FAQs \U0001F4C5'", narrow)

    written = path.read_text(encoding="cp1252")
    assert written.startswith("Built 'Mobile Tech ")
    assert "FAQs" in written


def test_output_leaves_text_the_stream_can_encode_alone(tmp_path):
    path = tmp_path / "summary.txt"
    with open(path, "w", encoding="utf-8", newline="\n") as wide:
        cli.write_line("Built 'Mobile Tech ⌚ FAQs'", wide)

    assert path.read_text(encoding="utf-8") == "Built 'Mobile Tech ⌚ FAQs'\n"


def test_version_flag_reports_the_package_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("extractium ")
