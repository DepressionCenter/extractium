"""
Summary: The DSpace source: indexes the scholarly deposits held in named
collections of a DSpace 7 repository, such as the University of Michigan
Library's Deep Blue. One document per deposit, carrying its abstract,
authors, date, subjects, rights, permanent identifiers, and the plain
text the repository already extracted from the deposited files. A deposit
whose file holds no readable text is still indexed and says so, and a
collection nobody has changed re-reads nothing.
See docs/dspace-repository-indexing.md.

This file is part of Extractium™
extractium/sources/dspace.py

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
from urllib.parse import urlparse

from extractium.core import cache as caching
from extractium.core.fetch import DEFAULT_USER_AGENT
from extractium.core.models import Document
from extractium.sources.dspace_client import (
    HANDLE_SELECTOR_PREFIX,
    DSpaceClient,
    DSpaceError,
    DSpaceNotFound,
)

### Constants ###

# Largest extracted text file read from a deposit, in bytes, when the
# configuration names no ceiling. Extracted text is prose, and a file far
# above this is machine output rather than something worth indexing whole.
DEFAULT_MAX_FILE_BYTES = 2_000_000

# The bundle a repository puts extracted text in, and the one holding the
# files as they were deposited. The others -- previews and deposit
# agreements -- carry nothing a reader would search for.
TEXT_BUNDLE = "TEXT"
ORIGINAL_BUNDLE = "ORIGINAL"

# The metadata fields read from a deposit. Every one of these is written
# by the depositor to describe the work, and every one is public.
TITLE_FIELD = "dc.title"
ABSTRACT_FIELD = "dc.description.abstract"
NOTE_FIELD = "dc.description"
AUTHOR_FIELD = "dc.contributor.author"
ISSUED_FIELD = "dc.date.issued"
SUBJECT_FIELDS = ("dc.subject", "dc.subject.other")
RIGHTS_FIELD = "dc.rights"
PUBLISHER_FIELD = "dc.publisher"
URI_FIELD = "dc.identifier.uri"
DOI_FIELD = "dc.identifier.doi"

# Two fields are deliberately not read: "dc.description.depositor" and
# "dc.description.provenance" record who submitted a deposit and when,
# often with a staff member's name and email address. They describe the
# paperwork rather than the work, so they are of no use to a reader and
# are personal information this build has no reason to publish.

# The hosts that tell the three kinds of address in dc.identifier.uri
# apart. A handle leads back to the deposit; a DOI is how the work is
# cited in the literature and may lead to a version of record elsewhere;
# anything else is wherever the depositor pointed, which is often the
# project's own documentation.
HANDLE_HOSTS = ("hdl.handle.net", "handle.net")
DOI_HOSTS = ("doi.org", "dx.doi.org")

# Runs of blank space in text a repository extracted from a page layout.
# Collapsed before the text is chunked: extracted text arrives with ragged
# padding that would otherwise reach the reader, and with lines long
# enough that the section splitter sees one enormous paragraph.
_SPACES_RE = re.compile(r"[^\S\n]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


### Errors ###

class DSpaceSourceError(Exception):
    """
    Raised when the operator named a collection the repository does not
    have, or the repository cannot be read at all. Either stops the
    source: a repository's own pages hold no deposits, so a quiet fall
    back to crawling would produce a collection's title and nothing else.
    """


### Source ###

class DSpaceSource:
    """
    Reads named collections of a DSpace repository.

    Collections are named in the configuration and never discovered. A
    repository holds the deposits of everybody at a university, and a
    build indexes what its operator asked for rather than everything it
    can reach.

    Args:
        options (Mapping): the validated options of a `dspace` entry:
            api_url, site_url, collections, include_full_text, and
            max_file_bytes.

    Attributes:
        coverage (tuple): one record per collection read, in the order
            read: its name, how many deposits it holds, and how many of
            them have text that could be read out of their files.
    """

    name = "dspace"

    def __init__(self, options):
        self.api_url = str(options["api_url"]).rstrip("/")
        self.site_url = str(options["site_url"]).rstrip("/")
        self.collections = tuple(options.get("collections") or ())
        self.include_full_text = bool(options.get("include_full_text", True))
        self.max_file_bytes = int(options.get("max_file_bytes") or DEFAULT_MAX_FILE_BYTES)
        self.settings = None
        self.coverage = ()
        self.downloads = 0

    def configure(self, registry, settings):
        """
        Adopts the build's global crawl settings.

        Only two of them apply here: how the build introduces itself, and
        how long it waits between requests. A repository interface is read
        rather than crawled, so nothing else in those settings is used.

        Args:
            registry (extractium.core.registry.Registry): unused; a
                repository interface needs no site handlers.
            settings (extractium.sources.web.CrawlSettings): the build's
                User-Agent and politeness delay.
        """
        self.settings = settings

    ### Reading ###

    def fetch(self, session, cache, progress):
        """
        Reads every configured collection and yields one Document per
        deposit.

        Each collection is confirmed to exist before it is searched, which
        is both how its name is learned and how a mistyped identifier is
        caught. There is no fall back to crawling: the pages a crawler
        could reach in a repository hold no deposits, so a collection that
        cannot be read is reported and the source stops.

        Args:
            session: HTTP session to request through.
            cache (dict): the fetch cache metadata. Unused: deposit text
                is stored under its own key, the identifier and change
                stamp the repository reports, rather than by URL.
            progress (Callable[[str], None]): receives one line per event.

        Yields:
            extractium.core.models.Document: one per deposit.

        Raises:
            DSpaceSourceError: if a configured collection does not exist,
                or the repository cannot be read.
        """
        client = DSpaceClient(
            session,
            self.api_url,
            user_agent=self._user_agent(),
            progress=progress,
            delay_seconds=self._delay_seconds(),
        )
        progress(f"DSpace:       {self.api_url}")
        for selector in self.collections:
            collection = self._collection(client, selector, progress)
            deposits = with_text = 0
            for deposit in self._deposits(client, collection):
                document, has_text = self._document_for(client, deposit, collection, progress)
                if document is None:
                    continue
                deposits += 1
                with_text += 1 if has_text else 0
                yield document
            progress(
                f"  {collection['name']}: {deposits} deposit(s), "
                f"{with_text} with text read from their files"
            )
            self.coverage += ((collection["name"], deposits, with_text),)

    def _collection(self, client, selector, progress):
        """
        Confirms one configured collection exists, and reads its name.

        Args:
            client (DSpaceClient): the interface client.
            selector (str): the collection's UUID, or "hdl:" and its
                handle, as the configuration was normalized to.
            progress (Callable[[str], None]): receives one line naming
                what the collection turned out to be.

        Returns:
            dict: the collection's uuid, name, and handle.

        Raises:
            DSpaceSourceError: if the repository has no such collection,
                or cannot be read.
        """
        try:
            uuid = self._collection_uuid(client, selector)
            record = client.collection(uuid)
        except DSpaceNotFound as e:
            raise DSpaceSourceError(
                f"the repository has no collection {_as_written(selector)}. Check the "
                f"identifier against the collection's own address. ({e})"
            ) from e
        except (DSpaceError, ValueError) as e:
            raise DSpaceSourceError(
                f"collection {_as_written(selector)} could not be read ({e})"
            ) from e
        name = (record.get("name") or "").strip() or _as_written(selector)
        handle = (record.get("handle") or "").strip()
        progress(f"  collection {_as_written(selector)} is {name!r}")
        return {"uuid": uuid, "name": name, "handle": handle}

    def _collection_uuid(self, client, selector):
        """The UUID of one configured collection, resolving a handle when that is what was given."""
        if selector.startswith(HANDLE_SELECTOR_PREFIX):
            return client.resolve_handle(selector[len(HANDLE_SELECTOR_PREFIX):])
        return selector

    def _deposits(self, client, collection):
        """
        The deposits of one collection that are worth a document.

        A withdrawn deposit stops appearing in the listing, so nothing has
        to be removed by hand between builds. One that is still in a
        submission workflow is not published yet and is left out here, so
        an index never shows a reader something the repository does not.
        """
        try:
            for deposit in client.deposits(collection["uuid"]):
                if deposit.get("withdrawn"):
                    continue
                if deposit.get("inArchive") is False:
                    continue
                yield deposit
        except (DSpaceError, ValueError) as e:
            raise DSpaceSourceError(
                f"the deposits of collection {collection['name']!r} could not be read ({e})"
            ) from e

    def _document_for(self, client, deposit, collection, progress):
        """
        One deposit as an indexed document.

        Returns:
            tuple[Document | None, bool]: the document, and whether text
            was read out of the deposit's files. The document is None only
            for a record with no identifier or no title, which is not a
            deposit this source can cite.
        """
        uuid = (deposit.get("uuid") or "").strip().lower()
        title = first_value(deposit, TITLE_FIELD) or (deposit.get("name") or "").strip()
        if not uuid or not title:
            progress("  skipped a record with no identifier or title")
            return None, False

        files = original_files(deposit)
        text = self._text_for(client, deposit, uuid, progress)
        body = deposit_body(deposit, collection, files, text)
        return Document(
            url=f"{self.site_url}/items/{uuid}",
            title=title,
            content=body,
            source_type="repository",
            content_type="article",
            categories=(collection["name"],),
        ), bool(text)

    def _text_for(self, client, deposit, uuid, progress):
        """
        The text a repository extracted from one deposit's files.

        A deposit is read again only when the repository says it changed.
        The change stamp is stored beside the text, so a collection nobody
        has touched costs one listing request and no downloads at all.

        Returns:
            str: the extracted text, blank when there is none to read.
        """
        if not self.include_full_text:
            return ""
        stamp = (deposit.get("lastModified") or "").strip()
        stored = caching.load_deposit_text(uuid, stamp) if stamp else None
        if stored is not None:
            return stored

        parts = []
        complete = True
        for entry in text_files(deposit):
            part, read_whole = self._download(client, entry, deposit, progress)
            complete = complete and read_whole
            if part:
                parts.append(part)
        text = collapse_whitespace("\n\n".join(parts))
        # Only a complete reading is stored. A file left out for its size
        # or for a failed request is read again next time, so raising the
        # ceiling or fixing a network problem takes effect on the next
        # build rather than waiting for the deposit itself to change.
        if stamp and complete:
            try:
                caching.save_deposit_text(uuid, stamp, text)
            except (OSError, ValueError):
                # A cache that cannot be written costs a slower next
                # build. It must never cost this one its content.
                pass
        return text

    def _download(self, client, entry, deposit, progress):
        """
        One extracted-text file.

        A file left out is always named. An index quietly missing a
        deposit's contents is worse than one that says what it skipped.

        Returns:
            tuple[str, bool]: the text, blank when none was read, and
            whether the file was read to the end. False means something
            stopped this build from reading it, not that the file holds
            nothing.
        """
        name = (entry.get("name") or "a file").strip()
        title = first_value(deposit, TITLE_FIELD) or name
        size = entry.get("sizeBytes")
        if isinstance(size, int) and size > self.max_file_bytes:
            progress(
                f"  {title}: skipped its extracted text "
                f"({size} bytes is over the {self.max_file_bytes} byte ceiling)"
            )
            return "", False
        href = ((entry.get("_links") or {}).get("content") or {}).get("href")
        try:
            text = client.deposit_text(href, self.max_file_bytes)
        except ValueError as e:
            progress(f"  {title}: skipped its extracted text ({e})")
            return "", False
        except DSpaceError as e:
            progress(f"  {title}: its extracted text could not be read ({e})")
            return "", False
        self.downloads += 1
        return text, True

    ### Reporting ###

    def _user_agent(self):
        """How this source introduces itself: the build's identity, or the default."""
        return self.settings.user_agent if self.settings else DEFAULT_USER_AGENT

    def _delay_seconds(self):
        """The pause between requests, taken from the build's crawl settings."""
        return getattr(self.settings, "delay_seconds", 0.0) or 0.0

    def summary_lines(self):
        """
        One line per collection, naming how many deposits it contributed
        and how many of those had text that could be read out of their
        files.

        A deposit with no readable text is still indexed, from its
        abstract and metadata, so these lines say how much of the index is
        description alone.

        Returns:
            list[str]: the coverage report, empty when nothing was read.
        """
        if not self.coverage:
            return []
        width = max(len(name) for name, _, _ in self.coverage)
        lines = []
        for name, deposits, with_text in self.coverage:
            without = deposits - with_text
            lines.append(
                f"{name:<{width}}  {deposits} deposit(s)  "
                f"{with_text} with file text  {without} description only"
            )
        return lines


### Deposit Records ###

def metadata_values(deposit, field):
    """
    Every value one metadata field holds on a deposit, in the order the
    repository returned them.

    Args:
        deposit (Mapping): the deposit record from the interface.
        field (str): the field name, such as "dc.title".

    Returns:
        list[str]: the values, blanks removed. Empty when the deposit does
        not carry the field, which is normal: repositories configure their
        own metadata, so a source reads what it recognizes and ignores the
        rest rather than insisting on a shape.
    """
    entries = (deposit.get("metadata") or {}).get(field)
    if not isinstance(entries, list):
        return []
    values = []
    for entry in entries:
        value = (entry or {}).get("value") if isinstance(entry, dict) else None
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def first_value(deposit, field):
    """The first value of one metadata field, or "" when the deposit has none."""
    values = metadata_values(deposit, field)
    return values[0] if values else ""


def bundle_files(deposit, bundle_name):
    """
    The files in one of a deposit's bundles.

    Args:
        deposit (Mapping): the deposit record, listed with its bundles
            and their files embedded.
        bundle_name (str): the bundle to read, such as "TEXT".

    Returns:
        list[dict]: the file records, in the order the repository returned
        them. Empty when the deposit has no such bundle.
    """
    bundles = _embedded_list(deposit, "bundles")
    for bundle in bundles:
        if (bundle.get("name") or "") == bundle_name:
            return _embedded_list(bundle, "bitstreams")
    return []


def text_files(deposit):
    """The files holding text the repository extracted from this deposit's deposited files."""
    return bundle_files(deposit, TEXT_BUNDLE)


def original_files(deposit):
    """
    The files as they were deposited, with the name and size of each.

    Recorded on the document rather than downloaded: a reader who finds a
    deposit should be able to see what is attached to it.
    """
    files = []
    for entry in bundle_files(deposit, ORIGINAL_BUNDLE):
        name = (entry.get("name") or "").strip()
        if name:
            files.append((name, entry.get("sizeBytes")))
    return files


def _embedded_list(record, key):
    """
    One embedded list out of an interface record.

    The interface nests a list twice, once under `_embedded` and again
    under its own name, and either level may be missing on a record that
    has none of that kind.
    """
    outer = (record.get("_embedded") or {}).get(key)
    if not isinstance(outer, dict):
        return []
    inner = (outer.get("_embedded") or {}).get(key)
    return [entry for entry in inner if isinstance(entry, dict)] if isinstance(inner, list) else []


def sorted_identifiers(deposit):
    """
    A deposit's addresses, told apart by the host each one points at.

    All three kinds are kept, for three different reasons. The handle is
    the permanent citation. The DOI is how the work is cited in the
    literature, and may be the only route to the version of record. Any
    other address is wherever the depositor pointed, which is often the
    project's own documentation, and a reader who finds the deposit should
    be able to reach it.

    Args:
        deposit (Mapping): the deposit record.

    Returns:
        tuple[list[str], list[str], list[str]]: the handles, the DOIs, and
        every other address, each in the order the repository gave them
        and each address appearing once.
    """
    handles, dois, others = [], [], []
    for value in metadata_values(deposit, URI_FIELD) + metadata_values(deposit, DOI_FIELD):
        host = (urlparse(value).netloc or "").lower()
        bucket = others
        if host in HANDLE_HOSTS:
            bucket = handles
        elif host in DOI_HOSTS:
            bucket = dois
        if value not in bucket:
            bucket.append(value)
    return handles, dois, others


def collapse_whitespace(text):
    """
    Tidies text a repository extracted from a page layout.

    Extracted text arrives padded: trailing spaces on most lines, and runs
    of empty lines where a column or a figure sat. Runs of spaces become
    one, trailing spaces go, and a run of empty lines becomes a single
    blank line, which is what the section splitter cuts long text on.

    Args:
        text (str): the text as the repository served it.

    Returns:
        str: the tidied text, with paragraph breaks preserved.
    """
    if not text:
        return ""
    lines = [_SPACES_RE.sub(" ", line).strip() for line in text.replace("\r\n", "\n").split("\n")]
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()


def deposit_body(deposit, collection, files, text):
    """
    One deposit as the text that gets indexed.

    The abstract comes first, because it is the part a person wrote
    deliberately to describe the work. The facts a reader needs to cite or
    follow the deposit come next. The text extracted from the files comes
    last, because it is machine output whose reading order can be wrong on
    a poster laid out in columns.

    A deposit whose files hold no readable text says so in place of that
    text. A search that misses such a deposit is then explainable, rather
    than looking like an index that lost it.

    Args:
        deposit (Mapping): the deposit record from the interface.
        collection (Mapping): the collection it sits in, with its name.
        files (Sequence): the deposited files, as (name, size in bytes).
        text (str): the extracted text, blank when there is none.

    Returns:
        str: the document body, as plain text.
    """
    lines = []
    abstract = first_value(deposit, ABSTRACT_FIELD)
    if abstract:
        lines += [abstract, ""]
    note = first_value(deposit, NOTE_FIELD)
    if note and note != abstract:
        lines += [note, ""]

    handles, dois, others = sorted_identifiers(deposit)
    subjects = [value for field in SUBJECT_FIELDS for value in metadata_values(deposit, field)]
    facts = [
        ("Authors", "; ".join(metadata_values(deposit, AUTHOR_FIELD))),
        ("Published", first_value(deposit, ISSUED_FIELD)),
        ("Collection", collection.get("name") or ""),
        ("Publisher", first_value(deposit, PUBLISHER_FIELD)),
        ("Subjects", ", ".join(dict.fromkeys(subjects))),
        ("Rights", first_value(deposit, RIGHTS_FIELD)),
        ("Permanent address", " ".join(handles)),
        ("DOI", " ".join(dois)),
        ("Also published at", " ".join(others)),
        ("Files", ", ".join(_file_description(name, size) for name, size in files)),
    ]
    lines += [f"{label}: {value}" for label, value in facts if value]

    if text:
        lines += ["", text]
    elif files:
        lines += ["", "No text could be read out of the file(s) deposited here, so this "
                      "record is its description only."]
    return "\n".join(lines)


def _file_description(name, size):
    """One deposited file, named with its size when the repository reported one."""
    if not isinstance(size, int) or size < 0:
        return name
    return f"{name} ({_human_bytes(size)})"


def _human_bytes(size):
    """A file size in the units a person reads, one decimal place from kilobytes up."""
    if size < 1024:
        return f"{size} bytes"
    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} GB"


def _as_written(selector):
    """One configured collection in the words an operator would recognize."""
    if selector.startswith(HANDLE_SELECTOR_PREFIX):
        return selector[len(HANDLE_SELECTOR_PREFIX):]
    return selector
