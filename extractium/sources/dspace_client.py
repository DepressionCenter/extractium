"""
Summary: Reads a DSpace 7 repository through its REST interface: turns a
handle into the collection it names, confirms a collection exists before
anything is searched, lists a collection's deposits together with the
files attached to each, and downloads the plain text the repository
extracted from those files. Every address and identifier that arrives in
a response is checked before it is used, because a response is untrusted
input. See docs/dspace-repository-indexing.md.

This file is part of Extractium™
extractium/sources/dspace_client.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-10
Last Modified: 2026-09-10
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
__date__ = "2026-09-10"

import re
import time
from urllib.parse import urlparse

import requests

from extractium.core.fetch import DEFAULT_USER_AGENT, REQUEST_TIMEOUT_SECONDS

### Constants ###

# Largest page of search results DSpace serves. Asking for it turns a
# forty-deposit collection into one request instead of two.
PAGE_SIZE = 100

# A hard stop on paging, and on how many deposits one collection may
# contribute. A collection larger than this is far outside what one
# knowledge base should hold, and the ceilings mean a listing that never
# ends cannot run a build out of time or memory.
MAX_PAGES = 100
MAX_DEPOSITS = 5_000

# Asked for alongside each search result, so one request brings back a
# deposit's metadata, its bundles, and the files in them. Without it every
# deposit costs a second request just to learn what it holds.
DEPOSIT_EMBED = "bundles/bitstreams"

# Everything DSpace names -- a deposit, a collection, a file -- carries a
# UUID. Checked before it goes into a request path or a cache file name,
# because these arrive in responses rather than from the operator.
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# A handle is the permanent name of a deposit or collection: a numeric
# prefix, then a suffix the repository assigns, as in "2027.42/195355".
HANDLE_RE = re.compile(r"^\d+(?:\.\d+)*/[A-Za-z0-9._~-]{1,100}$")

# The one shape of file address this client will download from. The
# address comes out of a response, so it is matched against the configured
# interface rather than trusted: a response that pointed somewhere else
# would otherwise send a build's requests wherever it liked.
CONTENT_PATH_RE = re.compile(
    r"^/core/bitstreams/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/content$"
)

### Errors ###

class DSpaceError(Exception):
    """Base class for every failure this client reports."""


class DSpaceUnavailable(DSpaceError):
    """
    The repository could not be read: the host is unreachable, the service
    failed, or it answered something other than the data asked for. The
    source stops rather than falling back to a crawl, because the pages a
    crawler could reach hold no deposits.
    """


class DSpaceNotFound(DSpaceError):
    """
    The repository has nothing at the address asked for. For a collection
    the operator named, this is a wrong identifier rather than a broken
    repository, so the message says so.
    """


class DSpaceNotAnInterface(DSpaceError):
    """
    The configured address answered a web page instead of data. That is
    what a repository's reader site does with an address it does not
    recognize, and it is the failure to expect when `api_url` points at
    the reader site rather than at the interface behind it.
    """


### Client ###

class DSpaceClient:
    """
    Reads one DSpace 7 repository through its REST interface.

    The session and the progress callback come from the caller, so a
    library user, a test, and a person at a terminal each control them.
    The client never constructs a session, never prints, and sends no
    credential: only what a repository publishes is read.

    Args:
        session: the HTTP session to request through (requests.Session or
            a test double with the same get() signature).
        api_url (str): where the repository's interface lives, such as
            "https://repository.example.edu/server/api". Not guessable
            from the reader site's address; see
            docs/dspace-repository-indexing.md.
        user_agent (str): how the build introduces itself. Truthful on
            every request.
        progress (Callable[[str], None] | None): receives one line per
            event worth reporting.
        delay_seconds (float): pause before each request after the first,
            so a build is no heavier on a repository than a reader is.

    Attributes:
        request_count (int): how many requests this client has made,
            which is what a report of an incremental build is measured in.
    """

    def __init__(self, session, api_url, user_agent=DEFAULT_USER_AGENT,
                 progress=None, delay_seconds=0.0):
        self.session = session
        self.api_url = str(api_url).rstrip("/")
        self.user_agent = user_agent
        self.progress = progress
        self.delay_seconds = float(delay_seconds or 0.0)
        self.request_count = 0

    ### Requests ###

    def _report(self, line):
        """Sends one line to the progress callback, when there is one."""
        if self.progress is not None:
            self.progress(line)

    def _headers(self, accept):
        """The headers one request sends. No credential travels here or anywhere else."""
        return {"Accept": accept, "User-Agent": self.user_agent}

    def _pace(self):
        """Waits the configured delay before every request but the first."""
        if self.request_count and self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

    def _get(self, path, accept="application/json", params=None, allow_redirects=True):
        """
        Makes one request against the interface and classifies the answer.

        Args:
            path (str): a path under the interface root, starting with a
                slash.
            accept (str): the content type asked for.
            params (Mapping | None): query parameters.
            allow_redirects (bool): False to read a redirect rather than
                follow it, which is how a handle is resolved.

        Returns:
            requests.Response: the answer, which may be a redirect when
            allow_redirects is False.

        Raises:
            DSpaceNotFound: the repository has nothing at this address.
            DSpaceNotAnInterface: the address answered a web page.
            DSpaceUnavailable: the host could not be reached, or answered
                an error.
        """
        url = self.api_url + path
        self._pace()
        try:
            response = self.session.get(
                url,
                headers=self._headers(accept),
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=allow_redirects,
            )
        except requests.RequestException as e:
            raise DSpaceUnavailable(f"the repository could not be reached at {url} ({e}).") from e

        self.request_count += 1
        status = response.status_code
        if status == 404:
            raise DSpaceNotFound(f"the repository has nothing at {url}.")
        if status >= 400:
            raise DSpaceUnavailable(f"the repository answered {status} for {url}.")
        content_type = (response.headers.get("content-type") or "").lower()
        if "text/html" in content_type:
            raise DSpaceNotAnInterface(
                f"{url} answered a web page rather than data. A repository's reader "
                "site and its interface are different addresses; check api_url "
                "against the reader site's dspaceServer setting."
            )
        return response

    def get_json(self, path, params=None):
        """
        Reads one document from the interface.

        Args:
            path (str): a path under the interface root.
            params (Mapping | None): query parameters.

        Returns:
            dict: the decoded document.

        Raises:
            DSpaceUnavailable: if the answer is not a usable JSON object.
            DSpaceNotFound, DSpaceNotAnInterface: as _get raises them.
        """
        response = self._get(path, params=params)
        try:
            document = response.json()
        except ValueError as e:
            raise DSpaceUnavailable(
                f"the repository sent something that is not JSON for {path} ({e})."
            ) from e
        if not isinstance(document, dict):
            raise DSpaceUnavailable(
                f"the repository answered {path} with "
                f"{type(document).__name__} rather than a record."
            )
        return document

    ### Collections ###

    def collection(self, collection_id):
        """
        Reads one collection, which both confirms it exists and gives the
        name a reader sees for it.

        Every collection is confirmed this way before it is searched. A
        search scope the interface does not recognize is not refused: it
        is answered with every deposit in the repository, so an identifier
        with a typo in it would quietly index a whole university's
        holdings. Confirming first turns that into a plain "no such
        collection".

        Args:
            collection_id (str): the collection's UUID.

        Returns:
            dict: the collection record, including its name and handle.

        Raises:
            ValueError: if collection_id is not a UUID.
            DSpaceNotFound: if the repository has no such collection.
        """
        return self.get_json(f"/core/collections/{_checked_uuid(collection_id, 'a collection')}")

    def resolve_handle(self, handle):
        """
        Reads the collection a handle names.

        The interface answers a handle lookup with a redirect to the
        record it belongs to, and the address it redirects to says what
        kind of thing that is. A handle naming a deposit or a community is
        therefore refused here rather than searched as though it were a
        collection.

        Args:
            handle (str): a handle such as "2027.42/195355", without a
                scheme or host.

        Returns:
            str: the collection's UUID.

        Raises:
            ValueError: if handle is not shaped like a handle.
            DSpaceNotFound: if the repository does not know the handle.
            DSpaceUnavailable: if the answer is not a redirect to a
                collection on this interface.
        """
        if not isinstance(handle, str) or not HANDLE_RE.match(handle):
            raise ValueError(
                f"a handle must look like 2027.42/195355; got {handle!r}."
            )
        response = self._get(
            "/pid/find", params={"id": f"hdl:{handle}"}, allow_redirects=False
        )
        location = response.headers.get("Location") or ""
        if response.status_code not in (301, 302, 303, 307, 308) or not location:
            raise DSpaceUnavailable(
                f"the repository did not say what handle {handle} names "
                f"(it answered {response.status_code})."
            )
        return self._collection_uuid_from(location, handle)

    def _collection_uuid_from(self, location, handle):
        """
        Reads the collection UUID out of the address a handle lookup
        pointed at, and refuses anything else.

        The address arrives in a response header, so it is matched against
        the configured interface. A redirect to another host is refused
        rather than followed: a build reads the repository its operator
        named and nothing a response points it at.
        """
        prefix = f"{self.api_url}/core/collections/"
        if location.startswith(prefix):
            candidate = location[len(prefix):].split("?")[0].split("#")[0].strip("/")
            if UUID_RE.match(candidate):
                return candidate
        kind = _named_kind(location, self.api_url)
        if kind:
            raise DSpaceUnavailable(
                f"handle {handle} names {kind}, not a collection. List collections "
                "under `collections:`; a build reads the collections it was given."
            )
        raise DSpaceUnavailable(
            f"the repository pointed handle {handle} at {location}, which is not a "
            f"collection on {self.api_url}."
        )

    ### Deposits ###

    def deposits(self, collection_id):
        """
        Yields every deposit in one collection, with the files attached to
        each.

        One request covers a page of a hundred deposits: their metadata,
        the change stamp that says whether each has moved since the last
        build, and the files in every bundle. Nothing is downloaded here.

        Args:
            collection_id (str): the collection's UUID, already confirmed
                to exist. See collection().

        Yields:
            dict: one deposit record, as the interface returned it.

        Raises:
            ValueError: if collection_id is not a UUID.
            DSpaceUnavailable: if a page is not a search result.
        """
        scope = _checked_uuid(collection_id, "a collection")
        seen = 0
        for page in range(MAX_PAGES):
            document = self.get_json("/discover/search/objects", params={
                "dsoType": "item",
                "scope": scope,
                "size": PAGE_SIZE,
                "page": page,
                "embed": DEPOSIT_EMBED,
            })
            result = _search_result(document, scope)
            records = _indexable_objects(result, scope)
            if not records:
                return
            for record in records:
                if seen >= MAX_DEPOSITS:
                    self._report(
                        f"  stopped after {MAX_DEPOSITS} deposits in one collection; "
                        "split the collection across sources to read the rest"
                    )
                    return
                seen += 1
                yield record
            total_pages = (result.get("page") or {}).get("totalPages")
            if isinstance(total_pages, int) and page + 1 >= total_pages:
                return
        self._report(f"  stopped listing collection {scope} after {MAX_PAGES} pages")

    def deposit_text(self, content_url, max_bytes):
        """
        Downloads the plain text a repository extracted from one deposited
        file.

        Nothing is parsed and nothing is unpacked. The repository
        extracted this text when the file was deposited, so a build needs
        no reader for PDF, Word, or archive formats, and there is no
        malformed-document risk to manage.

        Args:
            content_url (str): the file's address, as the deposit's record
                gave it. Must be a file on the configured interface.
            max_bytes (int): largest body to accept. A larger one is
                refused by name rather than read.

        Returns:
            str: the text, or "" when the repository answered something
            that is not plain text.

        Raises:
            ValueError: if the address is not a file on this interface, or
                the body is over the ceiling.
            DSpaceUnavailable: if the file could not be read.
        """
        path = self._content_path(content_url)
        response = self._get(path, accept="text/plain")
        content_type = (response.headers.get("content-type") or "").lower()
        if "text/plain" not in content_type:
            return ""
        text = response.text or ""
        size = len(text.encode("utf-8"))
        if size > max_bytes:
            raise ValueError(f"{size} bytes is over the {max_bytes} byte ceiling")
        return text

    def _content_path(self, content_url):
        """
        The interface path for one file address, refusing any address that
        is not a file on this interface.

        Raises:
            ValueError: if the address is not on the configured interface,
                or does not name a file's contents.
        """
        if not isinstance(content_url, str) or not content_url.startswith(self.api_url + "/"):
            raise ValueError(
                f"{content_url!r} is not a file on {self.api_url} and was not requested"
            )
        path = content_url[len(self.api_url):].split("?")[0].split("#")[0]
        if not CONTENT_PATH_RE.match(path):
            raise ValueError(f"{content_url!r} does not name a deposited file's contents")
        return path


### Response Shapes ###

def _search_result(document, scope):
    """
    The search result inside a listing answer.

    Raises:
        DSpaceUnavailable: if the answer is not a search result. An
            interface that answers a search with something else is not
            one this source can read, and guessing at the shape would
            index whatever happened to parse.
    """
    result = ((document.get("_embedded") or {}).get("searchResult"))
    if not isinstance(result, dict):
        raise DSpaceUnavailable(
            f"the repository answered a search of collection {scope} with something "
            "other than a list of deposits."
        )
    return result


def _indexable_objects(result, scope):
    """
    The deposit records on one page of a search result.

    Raises:
        DSpaceUnavailable: if the page is not a list of records.
    """
    objects = (result.get("_embedded") or {}).get("objects")
    if objects is None:
        return []
    if not isinstance(objects, list):
        raise DSpaceUnavailable(
            f"the repository answered a search of collection {scope} with "
            f"{type(objects).__name__} rather than a list."
        )
    records = []
    for entry in objects:
        record = ((entry or {}).get("_embedded") or {}).get("indexableObject")
        if isinstance(record, dict):
            records.append(record)
    return records


def _named_kind(location, api_url):
    """
    What kind of record an interface address names, in words, or "" when
    the address is not a record on this interface. Used to explain a
    handle that names something other than a collection.
    """
    kinds = {"items": "a deposit", "communities": "a community", "collections": "a collection"}
    if not location.startswith(api_url + "/core/"):
        return ""
    segments = [s for s in location[len(api_url):].split("?")[0].split("/") if s]
    if len(segments) < 3:
        return ""
    return kinds.get(segments[1], "")


def _checked_uuid(value, description):
    """
    Returns value when it is a UUID, and refuses it otherwise.

    Raises:
        ValueError: if value is not a lowercase UUID. Identifiers reach a
            request path from configuration and from responses, both of
            which are untrusted; an unchecked one could send a request
            somewhere else entirely.
    """
    if not isinstance(value, str) or not UUID_RE.match(value):
        raise ValueError(
            f"{description} is named by a UUID such as "
            f"3acf951c-e107-4b8d-8f7d-ced171665b11; got {value!r}."
        )
    return value


### Collection Selectors ###

# How a handle is written once a configured collection has been read: the
# prefix DSpace itself uses for a handle lookup, so one setting can hold
# either a UUID or a handle without a second key to say which.
HANDLE_SELECTOR_PREFIX = "hdl:"

# The addresses an operator is likely to have in hand for a collection. A
# handle link is what a repository prints as the collection's permanent
# address; a /collections/ link is what the browser shows after that link
# redirects. Both name the same collection, so both are accepted.
_COLLECTION_URL_RE = re.compile(
    r"/collections/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/?$"
)
_ITEM_URL_RE = re.compile(
    r"/items/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/?$"
)
_HANDLE_URL_RE = re.compile(r"^/(?:handle/)?(\d+(?:\.\d+)*/[A-Za-z0-9._~-]{1,100})/?$")

# What an unrecognized collection setting is answered with, so the fix is
# a line to copy rather than a guess.
ACCEPTED_COLLECTION_FORMS = (
    "a collection UUID (3acf951c-e107-4b8d-8f7d-ced171665b11), "
    "a handle link (https://hdl.handle.net/2027.42/195355), "
    "a handle on its own (2027.42/195355), "
    "or a collection address (https://repository.example.edu/collections/<uuid>)"
)


def parse_collection_selector(value):
    """
    Reads one configured collection into the form this client looks it up
    by.

    An operator has one of two things in hand: the permanent handle link a
    repository prints beside a collection, or the address the browser
    showed after following it. Both are accepted, as is a bare UUID or a
    bare handle, so nobody has to convert one into the other by hand.

    Args:
        value (str): the collection as written in the configuration.

    Returns:
        str: the collection's UUID, or "hdl:" followed by its handle.

    Raises:
        ValueError: if the value names no collection, or names a deposit
            rather than a collection. The message lists what is accepted.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"a collection must be text; got {value!r}.")
    text = value.strip()

    if UUID_RE.match(text.lower()):
        return text.lower()
    if text.lower().startswith(HANDLE_SELECTOR_PREFIX):
        return HANDLE_SELECTOR_PREFIX + _checked_handle(text[len(HANDLE_SELECTOR_PREFIX):], text)
    if HANDLE_RE.match(text):
        return HANDLE_SELECTOR_PREFIX + text
    if text.lower().startswith(("http://", "https://")):
        return _selector_from_url(text)
    raise ValueError(f"{value!r} names no collection. Give {ACCEPTED_COLLECTION_FORMS}.")


def _selector_from_url(url):
    """
    The collection a repository address names.

    Raises:
        ValueError: if the address names a deposit, or names nothing this
            client can look up.
    """
    parsed = urlparse(url)
    path = parsed.path or "/"

    collection = _COLLECTION_URL_RE.search(path)
    if collection:
        return collection.group(1).lower()

    handle = _HANDLE_URL_RE.match(path)
    if handle:
        return HANDLE_SELECTOR_PREFIX + handle.group(1)

    if _ITEM_URL_RE.search(path):
        raise ValueError(
            f"{url!r} is one deposit, not a collection. A source reads whole "
            "collections; give the collection the deposit sits in."
        )
    raise ValueError(f"{url!r} names no collection. Give {ACCEPTED_COLLECTION_FORMS}.")


def _checked_handle(handle, original):
    """
    Returns handle when it is shaped like one.

    Raises:
        ValueError: if it is not, naming the value as the operator wrote it.
    """
    handle = handle.strip()
    if not HANDLE_RE.match(handle):
        raise ValueError(f"{original!r} is not a handle. A handle looks like 2027.42/195355.")
    return handle


def collection_selectors(entries):
    """
    Reads a configured list of collections into the forms the interface
    looks them up by.

    Args:
        entries (Iterable[str]): the collections as written: UUIDs,
            handles, handle links, or collection addresses.

    Returns:
        tuple[str, ...]: one selector per entry, in the order written,
        each appearing once.

    Raises:
        ValueError: if an entry names no collection.
    """
    return tuple(dict.fromkeys(parse_collection_selector(entry) for entry in entries))
