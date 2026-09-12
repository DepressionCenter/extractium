"""
Summary: Tests for the hosted MCP examples under examples/mcp/. The D1
export is checked statement by statement: the committed golden SQL still
matches a fresh export of the contract compendium, every literal kind is
escaped the way SQLite reads it back, a statement never passes D1's size
limit, and loading the export into a fresh SQLite database reproduces
every table. The Val Town staging and push are driven against a fake of
the platform's API, call by call. The Node suites of the shared core, the
Val Town example, and the Cloudflare example are run from the last tests,
so one command checks every runtime.

This file is part of Extractium™
tests/test_mcp_remote_servers.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-12
Last Modified: 2026-09-12
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
__date__ = "2026-09-12"

import importlib.util
import io
import json
import pathlib
import re
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.parse

import pytest

from extractium.adapters.sqlite_out import SqliteAdapter
from tests.contract_fixture import build_contract_compendium

# The repository root, from which the Node suites are run.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Where the hosted examples and their shared core live.
EXAMPLES_DIR = REPO_ROOT / "examples" / "mcp"
EXPORT_SCRIPT = EXAMPLES_DIR / "cloudflare" / "export_d1.py"

# The committed D1 export of the contract compendium.
D1_GOLDEN_FILE = "contract-d1.sql"

# How long one Node run may take before it is treated as a failure.
NODE_TEST_TIMEOUT_SECONDS = 300


def _load_export_module():
    """Imports the export script by path; it lives outside the package."""
    spec = importlib.util.spec_from_file_location("export_d1", EXPORT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export_d1 = _load_export_module()


@pytest.fixture
def contract_sqlite(fixtures_dir, fake_embed_chunks_core, tmp_path):
    """The contract compendium written as the SQLite output."""
    compendium = build_contract_compendium(fixtures_dir, fake_embed_chunks_core)
    (path,) = SqliteAdapter().write(compendium, tmp_path, {"file": "contract.sqlite"})
    return path


def load_export(sql_path):
    """A fresh in-memory database filled from one export."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(pathlib.Path(sql_path).read_text(encoding="utf-8"))
    return connection


# ---------------------------------------------------------------------------
# The golden export
# ---------------------------------------------------------------------------

def test_the_committed_export_still_matches_a_fresh_one(contract_sqlite, golden_dir, tmp_path):
    fresh = tmp_path / D1_GOLDEN_FILE
    export_d1.write_sql(contract_sqlite, fresh)

    committed = (golden_dir / D1_GOLDEN_FILE).read_text(encoding="utf-8")
    assert fresh.read_text(encoding="utf-8") == committed, (
        "tests/golden/contract-d1.sql no longer matches the export; regenerate it with "
        "examples/mcp/cloudflare/export_d1.py if the change is intended."
    )


def test_loading_the_export_reproduces_every_table(contract_sqlite, golden_dir):
    source = sqlite3.connect(contract_sqlite)
    loaded = load_export(golden_dir / D1_GOLDEN_FILE)
    try:
        for table in export_d1.TABLES:
            expected = source.execute(f"SELECT * FROM {table} ORDER BY rowid;").fetchall()
            actual = loaded.execute(f"SELECT * FROM {table} ORDER BY rowid;").fetchall()
            assert actual == expected, table
    finally:
        source.close()
        loaded.close()


def test_the_export_replaces_an_older_build_rather_than_adding_to_it(contract_sqlite, tmp_path):
    sql_path = tmp_path / "twice.sql"
    export_d1.write_sql(contract_sqlite, sql_path)
    statements = sql_path.read_text(encoding="utf-8")

    connection = sqlite3.connect(":memory:")
    connection.executescript(statements)
    connection.executescript(statements)
    parents = connection.execute("SELECT COUNT(*) FROM parents;").fetchone()[0]
    once = sqlite3.connect(contract_sqlite).execute("SELECT COUNT(*) FROM parents;").fetchone()[0]

    assert parents == once


def test_no_statement_passes_the_size_limit(golden_dir):
    for statement in (golden_dir / D1_GOLDEN_FILE).read_text(encoding="utf-8").split(";\n\n"):
        assert len(statement) <= export_d1.MAX_STATEMENT_CHARS + 4096


# ---------------------------------------------------------------------------
# Literals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (None, "NULL"),
    (0, "0"),
    (-12, "-12"),
    (1.5, "1.5"),
    (True, "1"),
    ("plain", "'plain'"),
    ("it's", "'it''s'"),
    ("semi; colon", "'semi; colon'"),
    ("two\nlines", "'two\nlines'"),
    (b"\xff\x01", "X'FF01'"),
])
def test_every_literal_kind_reads_back_as_itself(value, expected):
    literal = export_d1.sql_literal(value)

    assert literal == expected
    read_back = sqlite3.connect(":memory:").execute(f"SELECT {literal};").fetchone()[0]
    assert read_back == (int(value) if isinstance(value, bool) else value)


def test_a_value_the_output_never_holds_is_refused():
    with pytest.raises(TypeError):
        export_d1.sql_literal(object())


def test_text_that_reads_like_sql_stays_text():
    hostile = "'); DROP TABLE parents; --"
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE t (x TEXT);")
    connection.executescript(
        f"INSERT INTO t (x) VALUES ({export_d1.sql_literal(hostile)});"
    )

    assert connection.execute("SELECT x FROM t;").fetchone()[0] == hostile


def test_rows_are_batched_by_size_and_none_is_lost():
    rows = [(index, "x" * 1000) for index in range(200)]

    statements = list(export_d1.insert_statements("t", ["a", "b"], rows))

    assert len(statements) > 1
    assert all(len(statement) <= export_d1.MAX_STATEMENT_CHARS + 1100 for statement in statements)
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE t (a INTEGER, b TEXT);")
    for statement in statements:
        connection.execute(statement)
    assert connection.execute("SELECT COUNT(*) FROM t;").fetchone()[0] == 200


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def test_the_command_writes_the_file_and_reports_the_count(contract_sqlite, tmp_path, capsys):
    out = tmp_path / "out.sql"

    code = export_d1.main([str(contract_sqlite), str(out)])

    assert code == export_d1.EXIT_OK
    assert out.exists()
    assert "statements" in capsys.readouterr().out


def test_a_missing_input_is_a_distinct_exit_code(tmp_path, capsys):
    code = export_d1.main([str(tmp_path / "absent.sqlite"), str(tmp_path / "out.sql")])

    assert code == export_d1.EXIT_INPUT_MISSING
    assert "is not a file" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The Val Town staging and push
# ---------------------------------------------------------------------------

PUSH_SCRIPT = EXAMPLES_DIR / "valtown" / "push.py"


def _load_push_module():
    """Imports the push script by path; it lives outside the package."""
    spec = importlib.util.spec_from_file_location("valtown_push", PUSH_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


valtown_push = _load_push_module()

# A synthetic token, a synthetic val id, and the account the fake serves.
FAKE_TOKEN = "EXAMPLE_VALTOWN_TOKEN"
FAKE_VAL_ID = "11111111-2222-3333-4444-555555555555"
FAKE_ORG_ID = "99999999-8888-7777-6666-555555555555"


class FakeResponse:
    """What urlopen hands back, or raises, for one call."""

    def __init__(self, status, body):
        self.status = status
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False


class FakeValTown:
    """
    Enough of the Val Town API to push against: an account, its
    organizations, an optional existing val, and a file store. Every call
    is recorded with its method, path, query, headers, and body.
    """

    def __init__(self, existing_val=False, existing_files=(), org=None):
        self.existing_val = existing_val
        self.files = set(existing_files)
        self.variables = {}
        self.org = org
        self.calls = []

    def __call__(self, request, timeout=None):
        parsed = urllib.parse.urlsplit(request.full_url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        self.calls.append({
            "method": request.get_method(), "path": parsed.path, "query": query,
            "headers": dict(request.header_items()), "body": body, "url": request.full_url,
        })
        status, answer = self.answer(request.get_method(), parsed.path, query, body, request)
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "refused", {}, io.BytesIO(json.dumps(answer).encode("utf-8")))
        return FakeResponse(status, answer)

    def answer(self, method, path, query, body, request):
        if request.get_header("Authorization") != f"Bearer {FAKE_TOKEN}":
            return 401, {"message": "bad token"}
        if path == "/v1/me":
            return 200, {"id": "u1", "username": "example"}
        if path == "/v2/orgs":
            return 200, {"data": [{"id": FAKE_ORG_ID, "username": self.org}] if self.org else []}
        if path.startswith("/v2/alias/vals/"):
            return (200, {"id": FAKE_VAL_ID}) if self.existing_val else (404, {"message": "not found"})
        if path == "/v2/vals" and method == "POST":
            self.created = body
            return 201, {"id": FAKE_VAL_ID}
        if path == f"/v2/vals/{FAKE_VAL_ID}/files":
            name = query["path"]
            if method == "GET":
                return 200, {"data": [{"path": name}] if name in self.files else []}
            if method == "POST" and name in self.files:
                return 409, {"message": "exists"}
            if method == "PUT" and name not in self.files:
                return 404, {"message": "missing"}
            self.files.add(name)
            record = {"path": name, "type": body["type"], "links": {}}
            if body["type"] == "http":
                record["links"]["endpoint"] = "https://example-kb.val.run"
            return (201 if method == "POST" else 200), record
        if path == f"/v2/vals/{FAKE_VAL_ID}/environment_variables/":
            if body["key"] in self.variables:
                return 409, {"message": "exists"}
            self.variables[body["key"]] = body["value"]
            return 201, {"key": body["key"]}
        if path.startswith(f"/v2/vals/{FAKE_VAL_ID}/environment_variables/"):
            key = path.rsplit("/", 1)[1]
            self.variables[key] = body["value"]
            return 201, {"key": key}
        return 404, {"message": f"no route {path}"}


@pytest.fixture
def fake_platform():
    return FakeValTown()


def client_for(platform):
    return valtown_push.ValTownClient(FAKE_TOKEN, opener=platform)


def staged_names():
    return [pathlib.PurePosixPath(relative).name for relative in valtown_push.SOURCE_FILES]


def test_imports_that_leave_the_folder_are_pointed_at_the_copies_beside_the_entry_point():
    source = (
        "import { a } from '../shared/mcp-http.js';\n"
        'import { b } from "../../../clients/js/extractium-client.js";\n'
        'import { c } from "./kb.js";\n'
        'import { d } from "https://esm.town/v/std/blob/main.ts";\n'
    )

    assert valtown_push.relocated_imports(source) == (
        "import { a } from './mcp-http.js';\n"
        'import { b } from "./extractium-client.js";\n'
        'import { c } from "./kb.js";\n'
        'import { d } from "https://esm.town/v/std/blob/main.ts";\n'
    )


def test_the_staged_folder_holds_every_file_the_val_needs_and_every_relative_import_resolves(tmp_path):
    written = valtown_push.stage(tmp_path)

    assert written == staged_names()
    for name in written:
        source = (tmp_path / name).read_text(encoding="utf-8")
        for match in re.finditer(r"""from\s+['"](\.[^'"]+)['"]""", source):
            assert (tmp_path / match.group(1)).exists(), f"{name} imports {match.group(1)}, which is not staged"


def test_a_first_push_creates_the_val_creates_every_file_and_reports_the_endpoint(fake_platform, tmp_path):
    result = valtown_push.push(client_for(fake_platform), target=tmp_path)

    assert result["val_id"] == FAKE_VAL_ID
    assert result["endpoint"] == "https://example-kb.val.run"
    assert result["files"] == staged_names()
    assert fake_platform.files == set(staged_names())
    assert fake_platform.created == {"name": "extractium-kb-mcp", "privacy": "public"}
    assert not [call for call in fake_platform.calls if call["method"] == "PUT"]


def test_a_later_push_finds_the_val_by_name_and_updates_the_files_it_already_holds(tmp_path):
    platform = FakeValTown(existing_val=True, existing_files=("main.http.ts", "kb.js"))

    valtown_push.push(client_for(platform), target=tmp_path)

    assert not [call for call in platform.calls if call["method"] == "POST" and call["path"] == "/v2/vals"]
    updated = sorted(call["query"]["path"] for call in platform.calls if call["method"] == "PUT")
    assert updated == ["kb.js", "main.http.ts"]


def test_a_push_under_an_organization_looks_the_handle_up_and_creates_the_val_there(tmp_path):
    platform = FakeValTown(org="efdc")

    valtown_push.push(client_for(platform), name="efdc-compendium", org="efdc", target=tmp_path)

    assert platform.created == {"name": "efdc-compendium", "privacy": "public", "orgId": FAKE_ORG_ID}
    lookups = [call for call in platform.calls if call["path"].startswith("/v2/alias/vals/")]
    assert lookups[0]["path"] == "/v2/alias/vals/efdc/efdc-compendium"


def test_an_organization_the_account_does_not_belong_to_is_refused(tmp_path):
    with pytest.raises(valtown_push.PushError, match="not a member"):
        valtown_push.push(client_for(FakeValTown(org="other")), org="efdc", target=tmp_path)


def test_the_entry_point_is_an_http_val_and_every_other_file_is_a_plain_file(fake_platform, tmp_path):
    valtown_push.push(client_for(fake_platform), target=tmp_path)

    for call in fake_platform.calls:
        if call["method"] == "POST" and call["path"].endswith("/files"):
            expected = "http" if call["query"]["path"] == "main.http.ts" else "file"
            assert call["body"]["type"] == expected, call["query"]["path"]


def test_environment_variables_are_created_and_then_updated(tmp_path):
    platform = FakeValTown()
    variables = [("EXTRACTIUM_INDEX_URL", "https://example.org/kb/kb-index.json")]

    valtown_push.push(client_for(platform), variables=variables, target=tmp_path)
    valtown_push.push(client_for(platform), variables=[("EXTRACTIUM_INDEX_URL", "https://example.org/other.json")],
                      val_id=FAKE_VAL_ID, target=tmp_path)

    assert platform.variables == {"EXTRACTIUM_INDEX_URL": "https://example.org/other.json"}
    methods = [call["method"] for call in platform.calls if "environment_variables" in call["path"]]
    assert methods == ["POST", "POST", "PUT"]


def test_the_token_travels_in_the_authorization_header_and_in_no_address_or_body(fake_platform, tmp_path):
    valtown_push.push(client_for(fake_platform), target=tmp_path)

    for call in fake_platform.calls:
        assert call["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"
        assert FAKE_TOKEN not in call["url"]
        assert FAKE_TOKEN not in json.dumps(call["body"])


def test_a_refused_token_is_a_push_error_that_says_what_the_token_needs(fake_platform, tmp_path):
    client = valtown_push.ValTownClient("WRONG", opener=fake_platform)

    with pytest.raises(valtown_push.PushError, match="read and write on vals") as caught:
        valtown_push.push(client, target=tmp_path)
    assert "WRONG" not in str(caught.value)


def test_a_file_past_the_platform_limit_is_refused_before_it_is_sent(fake_platform):
    with pytest.raises(valtown_push.PushError, match="80000 per file"):
        client_for(fake_platform).put_file(FAKE_VAL_ID, "big.js", "x" * 80_001)
    assert fake_platform.calls == []


def test_a_platform_that_cannot_be_reached_is_a_push_error(tmp_path):
    def down(request, timeout=None):
        raise urllib.error.URLError("name or service not known")

    with pytest.raises(valtown_push.PushError, match="could not reach"):
        valtown_push.push(valtown_push.ValTownClient(FAKE_TOKEN, opener=down), target=tmp_path)


def test_without_push_the_command_only_stages(tmp_path, capsys):
    code = valtown_push.main(["--target", str(tmp_path)], environ={})

    assert code == valtown_push.EXIT_OK
    assert (tmp_path / "main.http.ts").exists()
    assert "web editor" in capsys.readouterr().out


def test_a_push_without_a_token_stops_with_a_distinct_exit_code(tmp_path, capsys):
    code = valtown_push.main(["--push", "--target", str(tmp_path)], environ={})

    assert code == valtown_push.EXIT_NO_TOKEN
    assert "VALTOWN_API_TOKEN" in capsys.readouterr().err


def test_a_set_argument_must_be_key_equals_value():
    with pytest.raises(SystemExit):
        valtown_push.main(["--push", "--set", "novalue"], environ={valtown_push.TOKEN_SETTING: FAKE_TOKEN})

# ---------------------------------------------------------------------------
# The Node suites
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed on this machine")
@pytest.mark.parametrize("folder", ["shared", "valtown", "cloudflare"])
def test_the_node_suite_passes(folder):
    completed = subprocess.run(
        ["node", "--test", f"examples/mcp/{folder}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=NODE_TEST_TIMEOUT_SECONDS,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
