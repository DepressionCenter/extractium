"""
Summary: Assembles the Val Town val and, when asked, pushes it through the
platform's REST API with nothing beyond Python's standard library. A val
holds only its own files, so the JavaScript client and the shared protocol
modules this example imports from elsewhere in the repository are copied
beside the entry point with their import lines rewritten. With a token, the
script finds or creates the val by name, under your account or an
organization, writes the six files with the entry point marked as an HTTP
val, sets any environment variables given, and prints the endpoint the
platform assigns. Without a token it only assembles the folder, for pasting
into the web editor.

This file is part of Extractium™
examples/mcp/valtown/push.py

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

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

### Constants ###

HERE = pathlib.Path(__file__).resolve().parent

# Where the assembled val lands. Not committed: it is a build product.
DEFAULT_TARGET = HERE / "val"

# Every file the val needs, relative to this folder. The entry point and
# the search live here; the rest are copied from where they are kept.
SOURCE_FILES = (
    "main.http.ts",
    "kb.js",
    "../shared/mcp-protocol.js",
    "../shared/mcp-http.js",
    "../shared/search-tool.js",
    "../../../clients/js/extractium-client.js",
)

# A relative import that leaves the folder, such as '../shared/mcp-http.js'
# or '../../../clients/js/extractium-client.js'. Only the file name
# survives, because every file lands in one folder.
OUTSIDE_IMPORT = re.compile(r"""(from\s+|import\s+)(['"])(?:\.\./)+(?:[^'"]*/)?([^'"/]+)\2""")

# The platform's API. Every call below is documented at
# https://docs.val.town/reference/api/ and in its OpenAPI description.
API_BASE = "https://api.val.town"

# The setting the token is read from. Create one at
# https://www.val.town/settings/api with read and write on vals.
TOKEN_SETTING = "VALTOWN_API_TOKEN"

# What the val is called unless the command line says otherwise, and how
# visible its source is. The source is public here because it is this
# repository's own code, and because the free plan caps the number of
# unlisted and private vals; the HTTP endpoint is reachable either way.
DEFAULT_VAL_NAME = "extractium-kb-mcp"
DEFAULT_PRIVACY = "public"

# The file the platform runs on each request. Its `http` type is what
# gives the val an endpoint; every other file is a plain module.
ENTRY_FILE = "main.http.ts"

# The platform's per-file size limit, and how long one call may take.
MAX_FILE_CHARS = 80_000
TIMEOUT_SECONDS = 60

# Exit codes.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_TOKEN = 2


class PushError(Exception):
    """The platform refused a step, or could not be reached."""


### Staging ###

def relocated_imports(source):
    """
    The same source with every import that left the folder pointed at the
    copy beside it.

    Args:
        source (str): a JavaScript or TypeScript module.

    Returns:
        str: the rewritten module.
    """
    return OUTSIDE_IMPORT.sub(lambda match: f"{match.group(1)}{match.group(2)}./{match.group(3)}{match.group(2)}", source)


def stage(target=DEFAULT_TARGET):
    """
    Writes the val folder.

    Args:
        target (str | pathlib.Path): where to write; created if missing.

    Returns:
        list[str]: the files written, by name, in the order they were written.
    """
    target = pathlib.Path(target)
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for relative in SOURCE_FILES:
        name = pathlib.PurePosixPath(relative).name
        source = (HERE / relative).read_text(encoding="utf-8")
        (target / name).write_text(relocated_imports(source), encoding="utf-8", newline="\n")
        written.append(name)
    return written


### The API ###

class ValTownClient:
    """
    The handful of calls the push makes, over one token.

    The token travels in one header. It reaches no address, no body, no
    log line, and no exception message.
    """

    def __init__(self, token, opener=urllib.request.urlopen, base=API_BASE):
        self.token = token
        self.opener = opener
        self.base = base

    def call(self, method, route, body=None):
        """
        One call.

        Args:
            method (str): the HTTP method.
            route (str): the path and query under the API base.
            body (dict | None): JSON to send.

        Returns:
            tuple[int, dict | list | None]: the status and the parsed answer.

        Raises:
            PushError: on a network failure or a 5xx answer.
        """
        data = None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + route, data=data, method=method, headers=headers)
        try:
            with self.opener(request, timeout=TIMEOUT_SECONDS) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as error:
            status = error.code
            raw = error.read()
        except (urllib.error.URLError, OSError) as error:
            raise PushError(f"could not reach {self.base}: {getattr(error, 'reason', error)}") from None
        if status >= 500:
            raise PushError(f"the platform answered {status} for {method} {route}.")
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            parsed = None
        return status, parsed

    def accepted(self, result, what):
        """The answer's body, or a PushError naming the step that was refused."""
        status, parsed = result
        if 200 <= status < 300:
            return parsed
        detail = ""
        if isinstance(parsed, dict) and (parsed.get("message") or parsed.get("error")):
            detail = f": {parsed.get('message') or parsed.get('error')}"
        raise PushError(f"{what} was refused with {status}{detail}. A token needs read and write on vals.")

    def username(self):
        """The handle of the account the token belongs to."""
        me = self.accepted(self.call("GET", "/v1/me"), "reading the account")
        if not isinstance(me, dict) or not me.get("username"):
            raise PushError("the account answer carried no username.")
        return me["username"]

    def organization_id(self, handle):
        """
        The id of one organization the account belongs to.

        Args:
            handle (str): the organization's handle, as shown on Val Town.

        Returns:
            str: its id.

        Raises:
            PushError: if the account is not a member of it.
        """
        page = self.accepted(self.call("GET", "/v2/orgs?offset=0&limit=100"), "listing organizations")
        entries = page.get("data", []) if isinstance(page, dict) else page or []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("username", "").lower() == handle.lower():
                return entry["id"]
        raise PushError(f"this account is not a member of an organization called {handle!r}.")

    def find_val(self, owner, name):
        """The id of the named val under one owner, or None."""
        status, parsed = self.call("GET", f"/v2/alias/vals/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}")
        if status == 200 and isinstance(parsed, dict) and parsed.get("id"):
            return parsed["id"]
        if status == 404:
            return None
        self.accepted((status, parsed), "looking the val up")
        return None

    def create_val(self, name, privacy, org_id=None):
        """Creates the val and returns its id."""
        body = {"name": name, "privacy": privacy}
        if org_id:
            body["orgId"] = org_id
        created = self.accepted(self.call("POST", "/v2/vals", body), "creating the val")
        return created["id"]

    def put_file(self, val_id, name, content):
        """
        Creates or updates one file in the val.

        Args:
            val_id (str): the val.
            name (str): the file name inside the val.
            content (str): the file's text.

        Returns:
            dict: the platform's record of the file.

        Raises:
            PushError: if the file is over the platform's limit or refused.
        """
        if len(content) > MAX_FILE_CHARS:
            raise PushError(f"{name} is {len(content)} characters; the platform accepts {MAX_FILE_CHARS} per file.")
        file_type = "http" if name == ENTRY_FILE else "file"
        route = f"/v2/vals/{urllib.parse.quote(val_id)}/files?path={urllib.parse.quote(name)}"
        status, listed = self.call("GET", route + "&limit=1")
        present = (
            status == 200 and isinstance(listed, dict)
            and any(entry.get("path") == name for entry in listed.get("data", []) if isinstance(entry, dict))
        )
        method = "PUT" if present else "POST"
        return self.accepted(self.call(method, route, {"content": content, "type": file_type}), f"writing {name}")

    def set_environment_variable(self, val_id, key, value):
        """Creates the variable, or updates it when it already exists."""
        base = f"/v2/vals/{urllib.parse.quote(val_id)}/environment_variables/"
        status, parsed = self.call("POST", base, {"key": key, "value": value})
        if status == 409:
            status, parsed = self.call("PUT", base + urllib.parse.quote(key), {"value": value})
        self.accepted((status, parsed), f"setting {key}")


### Pushing ###

def push(client, name=DEFAULT_VAL_NAME, privacy=DEFAULT_PRIVACY, org=None, val_id=None,
         variables=(), target=DEFAULT_TARGET, log=lambda message: None):
    """
    Stages the val and pushes every file.

    Args:
        client (ValTownClient): the API, with its token.
        name (str): the val's name.
        privacy (str): `public`, `unlisted`, or `private` for the source.
        org (str | None): an organization handle to create the val under.
        val_id (str | None): a known val id, which skips the lookup.
        variables (Iterable[tuple[str, str]]): environment variables to set.
        target (str | pathlib.Path): where to stage.
        log (Callable[[str], None]): where to report progress.

    Returns:
        dict: `val_id`, `endpoint` (or None), and the `files` written.

    Raises:
        PushError: if the platform refuses any step.
    """
    files = stage(target)
    if val_id is None:
        owner = org or client.username()
        val_id = client.find_val(owner, name)
        if val_id is None:
            org_id = client.organization_id(org) if org else None
            val_id = client.create_val(name, privacy, org_id)
            log(f"created the val {owner}/{name}")
        else:
            log(f"updating the val {owner}/{name}")

    endpoint = None
    for file_name in files:
        content = (pathlib.Path(target) / file_name).read_text(encoding="utf-8")
        record = client.put_file(val_id, file_name, content)
        log(f"wrote {file_name}")
        if file_name == ENTRY_FILE and isinstance(record, dict):
            endpoint = (record.get("links") or {}).get("endpoint")
    for key, value in variables:
        client.set_environment_variable(val_id, key, value)
        log(f"set {key}")
    return {"val_id": val_id, "endpoint": endpoint, "files": files}


### Command Line ###

def parse_variable(text):
    """One `KEY=VALUE` argument, split once."""
    key, separator, value = text.partition("=")
    if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise argparse.ArgumentTypeError(f"{text!r} is not KEY=VALUE")
    return key, value


def main(argv=None, environ=None):
    """
    Parses the command line, stages the val, and pushes it when asked.

    Returns:
        int: the exit code.
    """
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(
        description="Assemble the Val Town val, and push it when --push is given.",
    )
    parser.add_argument("--push", action="store_true",
                        help=f"push through the API, with {TOKEN_SETTING} in the environment")
    parser.add_argument("--name", default=DEFAULT_VAL_NAME, help="the val's name")
    parser.add_argument("--org", default=None, help="organization handle to create the val under")
    parser.add_argument("--val-id", default=None, help="id of an existing val, which skips the lookup")
    parser.add_argument("--privacy", default=DEFAULT_PRIVACY, choices=("public", "unlisted", "private"),
                        help="visibility of the val's source")
    parser.add_argument("--set", action="append", default=[], type=parse_variable, metavar="KEY=VALUE",
                        help="an environment variable to set on the val; repeatable")
    parser.add_argument("--target", default=str(DEFAULT_TARGET), help="folder to assemble the val in")
    args = parser.parse_args(argv)

    def log(message):
        print(f"push: {message}", file=sys.stderr)

    if not args.push:
        files = stage(args.target)
        print(f"staged {len(files)} files under {args.target}:")
        for name in files:
            print(f"  {name}")
        print("paste them into a new val in the web editor, or run again with --push and a token.")
        return EXIT_OK

    token = environ.get(TOKEN_SETTING)
    if not token:
        log(f"set {TOKEN_SETTING} to a Val Town API token with read and write on vals.")
        return EXIT_NO_TOKEN

    try:
        result = push(ValTownClient(token), name=args.name, privacy=args.privacy, org=args.org,
                      val_id=args.val_id, variables=args.set, target=args.target, log=log)
    except PushError as error:
        log(str(error))
        return EXIT_FAILED

    print(f"pushed {len(result['files'])} files to val {result['val_id']}")
    if result["endpoint"]:
        endpoint = result["endpoint"].rstrip("/")
        print(f"endpoint: {endpoint}")
        print(f"the MCP endpoint is {endpoint}/mcp")
    if not any(key == "EXTRACTIUM_INDEX_URL" for key, _value in args.set):
        print("set EXTRACTIUM_INDEX_URL in the val's environment variables before the first request.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
