"""
Summary: The records that pass between an Extractium build's layers and
the protocols its plugins implement. A source yields Document records;
a site handler returns an Extraction for a page the crawler fetched;
the build step returns one Compendium (parents, children, vectors,
keyword statistics, calibration) that every adapter serializes. The
Source, SiteHandler, and Adapter protocols are the three plugin kinds
the registry resolves. See docs/extractium-spec.md sections 2 and 3 and
docs/container-format.md for the field meanings.

This file is part of Extractium™
extractium/core/models.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-04
Last Modified: 2026-09-04
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
__date__ = "2026-09-04"

import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Protocol, runtime_checkable

import numpy as np

# Model constants only; embed_chunks, which loads the model, is never
# called from here.
from extractium.core.embed import (
    DIMS,
    EMBED_MODEL,
    EMBED_MODEL_BROWSER_ID,
    INT8_SCALE,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
)

### Controlled Vocabularies ###

# Every value a parent's source_type may hold. "kb" is a TeamDynamix
# portal, because that is what the original index called it and the
# search clients key display rules on it.
SOURCE_TYPES = frozenset({"kb", "github", "web", "youtube", "local"})

# Every value a parent's content_type may hold.
CONTENT_TYPES = frozenset({
    "article", "readme", "wiki", "release_notes", "page", "text", "video_transcript",
})

# A local document's URL is "local:" plus a path relative to the source
# folder, so an absolute path from the operator's disk never reaches an
# output file.
LOCAL_URL_PREFIX = "local:"

# A parent id is the first 16 hexadecimal characters of a SHA-1 digest.
PARENT_ID_RE = re.compile(r"^[0-9a-f]{16}$")

# Storage types the container format allows for vector components.
VECTOR_DTYPES = ("int8", "float32")

# Build times are exchanged in UTC only, ISO 8601 with a Z suffix.
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

# A progress callback receives one short human-readable line per event.
# The caller decides where it goes: standard error, a CI log, or nowhere.
Progress = Callable[[str], None]


def _require_text(value, name):
    """Raises ValueError unless value is non-blank text."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-blank text.")


def _require_vocabulary(value, name, allowed):
    """Raises ValueError unless value is one of the allowed strings."""
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(sorted(allowed))}; got {value!r}.")


def _check_local_marker(url, local):
    """
    The local flag and the local: URL prefix must agree, so a local file
    can neither be published under a web-looking URL nor slip past the
    adapters' local-content guardrail.
    """
    is_local_url = url.startswith(LOCAL_URL_PREFIX)
    if local and not is_local_url:
        raise ValueError(f"a local record must use a {LOCAL_URL_PREFIX} URL; got {url!r}.")
    if is_local_url and not local:
        raise ValueError(f"a {LOCAL_URL_PREFIX} URL must be marked local; got {url!r}.")


### Source Output ###

@dataclass(frozen=True)
class Document:
    """
    One unit of content a source hands to the core engine. The engine
    never sees how the source fetched it.

    Attributes:
        url (str): where the content came from. For local files,
            "local:" plus the path relative to the source folder.
        title (str): page or file title.
        content (bs4.Tag | str): a parsed HTML content node, or plain
            text the chunker wraps itself.
        source_type (str): one of SOURCE_TYPES.
        content_type (str): one of CONTENT_TYPES.
        categories (tuple[str, ...]): hierarchy from the source,
            outermost first; empty when the source has none.
        local (bool): True for local-filesystem content, which every
            output drops unless it opts in.
        weight (float): per-document multiplier applied after rank
            fusion; greater than zero, 1.0 by default.

    Raises:
        ValueError: if a field is blank, outside its vocabulary, or the
            local flag disagrees with the URL prefix.
    """

    url: str
    title: str
    content: object
    source_type: str
    content_type: str
    categories: tuple = ()
    local: bool = False
    weight: float = 1.0

    def __post_init__(self):
        _require_text(self.url, "url")
        _require_vocabulary(self.source_type, "source_type", SOURCE_TYPES)
        _require_vocabulary(self.content_type, "content_type", CONTENT_TYPES)
        if not (isinstance(self.weight, (int, float)) and self.weight > 0):
            raise ValueError(f"weight must be a number greater than zero; got {self.weight!r}.")
        _check_local_marker(self.url, self.local)
        object.__setattr__(self, "categories", tuple(self.categories))


### Site Handler Output ###

@dataclass(frozen=True)
class Extraction:
    """
    What a site handler read from one fetched page. A handler returns
    None instead when the page is only a link-discovery hop.

    Attributes:
        title (str): the page title after any host-specific cleanup.
        node (bs4.Tag | str): the content node to chunk, or plain text.
        categories (tuple[str, ...]): hierarchy from the page, outermost
            first; empty when the page shows none.
    """

    title: str
    node: object
    categories: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "categories", tuple(self.categories))


### Build Output ###

@dataclass(frozen=True)
class Parent:
    """
    One section of text: the unit shown to a language model and cited
    in an answer. Field names match the container header so adapters
    can write records without renaming.

    Attributes:
        id (str): stable identifier, 16 lowercase hexadecimal characters.
        t (str): heading, "Page title -- Section heading".
        x (str): the section text.
        u (str): source URL, or "local:" plus a relative path.
        host (str): lowercase host of u; empty for local files.
        source_type (str): one of SOURCE_TYPES.
        content_type (str): one of CONTENT_TYPES.
        categories (tuple[str, ...]): hierarchy, outermost first.
        local (bool): True when the parent came from a local source.
        weight (float): per-document multiplier; greater than zero.
    """

    id: str
    t: str
    x: str
    u: str
    host: str
    source_type: str
    content_type: str
    categories: tuple = ()
    local: bool = False
    weight: float = 1.0

    def __post_init__(self):
        if not isinstance(self.id, str) or not PARENT_ID_RE.match(self.id):
            raise ValueError(f"id must be 16 lowercase hexadecimal characters; got {self.id!r}.")
        _require_text(self.u, "u")
        _require_vocabulary(self.source_type, "source_type", SOURCE_TYPES)
        _require_vocabulary(self.content_type, "content_type", CONTENT_TYPES)
        if not (isinstance(self.weight, (int, float)) and self.weight > 0):
            raise ValueError(f"weight must be a number greater than zero; got {self.weight!r}.")
        _check_local_marker(self.u, self.local)
        object.__setattr__(self, "categories", tuple(self.categories))


@dataclass(frozen=True)
class Children:
    """
    The search windows, as column arrays. Grain: one entry per child, in
    the order the vectors and the BM25 postings use.

    Attributes:
        pid (tuple[int, ...]): index into the parent list for each child.
        start (tuple[int, ...]): start of each window inside its parent's
            text, in UTF-16 code units; empty when offsets are not kept.
        end (tuple[int, ...]): exclusive end of each window; same length
            as start.

    Raises:
        ValueError: if the offset columns are present but do not match
            pid in length, or an end precedes its start.
    """

    pid: tuple
    start: tuple = ()
    end: tuple = ()

    def __post_init__(self):
        pid = tuple(int(i) for i in self.pid)
        start = tuple(int(i) for i in self.start)
        end = tuple(int(i) for i in self.end)
        if (start or end) and not (len(start) == len(end) == len(pid)):
            raise ValueError(
                f"start and end must each have one entry per child ({len(pid)}); "
                f"got {len(start)} and {len(end)}."
            )
        for position, (begin, stop) in enumerate(zip(start, end)):
            if begin < 0 or stop < begin:
                raise ValueError(f"child {position}: end ({stop}) precedes start ({begin}).")
        object.__setattr__(self, "pid", pid)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def __len__(self):
        return len(self.pid)


@dataclass(frozen=True)
class EmbeddingInfo:
    """
    How the vectors were produced, recorded in every output so a client
    can refuse a file its query embedder cannot match.

    Attributes:
        model (str): Hugging Face model id used at build time.
        browser_model (str): the same model packaged for transformers.js.
        dims (int): vector length.
        normalized (bool): True when every vector has unit length.
        query_prefix (str): text placed before a query at search time.
        passage_prefix (str): text placed before each passage at build time.
        dtype (str): "int8" or "float32".
        scale (int | None): divisor that recovers a float from an int8
            component; None for float32.
    """

    model: str = EMBED_MODEL
    browser_model: str = EMBED_MODEL_BROWSER_ID
    dims: int = DIMS
    normalized: bool = True
    query_prefix: str = QUERY_PREFIX
    passage_prefix: str = PASSAGE_PREFIX
    dtype: str = "int8"
    scale: object = field(default=None)

    def __post_init__(self):
        if self.dtype not in VECTOR_DTYPES:
            raise ValueError(f"dtype must be one of {', '.join(VECTOR_DTYPES)}; got {self.dtype!r}.")
        if self.dtype == "int8" and self.scale is None:
            object.__setattr__(self, "scale", INT8_SCALE)
        if self.dtype == "float32":
            object.__setattr__(self, "scale", None)


@dataclass(frozen=True)
class Compendium:
    """
    The complete, scored result of one build. Every adapter serializes
    this record and nothing else, so one crawl and one embedding pass
    feed every output format.

    Attributes:
        name (str): display name of the knowledge base.
        built_at (str): build time, UTC, ISO 8601 with a Z suffix.
        parents (tuple[Parent, ...]): sections, in build order.
        children (Children): search windows; one entry per vector row.
        vectors (numpy.ndarray): shape (child count, dims); dtype matches
            embedding.dtype.
        embedding (EmbeddingInfo): how the vectors were made.
        bm25 (Mapping): keyword statistics as build_bm25_index returns
            them (k, b, d, avgDocLen, docLen, df, postings).
        calibration (Mapping): mean, std, sampleSize as
            compute_calibration_stats returns them.

    Raises:
        ValueError: if the vectors, children, and parents disagree in
            count, width, or offsets, if parent ids repeat, or if
            built_at is not a UTC timestamp.
    """

    name: str
    built_at: str
    parents: tuple
    children: Children
    vectors: np.ndarray
    embedding: EmbeddingInfo
    bm25: Mapping
    calibration: Mapping

    def __post_init__(self):
        _require_text(self.name, "name")
        if not isinstance(self.built_at, str) or not UTC_TIMESTAMP_RE.match(self.built_at):
            raise ValueError(f"built_at must be a UTC ISO 8601 timestamp ending in Z; got {self.built_at!r}.")
        parents = tuple(self.parents)
        object.__setattr__(self, "parents", parents)

        seen = set()
        for parent in parents:
            if parent.id in seen:
                raise ValueError(f"parent id {parent.id!r} appears more than once.")
            seen.add(parent.id)

        child_count = len(self.children)
        if self.vectors.ndim != 2 or self.vectors.shape[0] != child_count:
            raise ValueError(
                f"vectors must have one row per child ({child_count}); got shape {self.vectors.shape}."
            )
        if self.vectors.shape[1] != self.embedding.dims:
            raise ValueError(
                f"vectors must be {self.embedding.dims} wide to match embedding.dims; "
                f"got {self.vectors.shape[1]}."
            )
        for position, pid in enumerate(self.children.pid):
            if pid < 0 or pid >= len(parents):
                raise ValueError(f"child {position}: pid {pid} is outside the {len(parents)} parents.")
        for position, (pid, stop) in enumerate(zip(self.children.pid, self.children.end)):
            # Offsets are UTF-16 code units, the unit JavaScript strings use.
            length = len(parents[pid].x.encode("utf-16-le")) // 2
            if stop > length:
                raise ValueError(
                    f"child {position}: end ({stop}) is past the end of parent {pid}'s text ({length})."
                )

    @property
    def source_count(self):
        """Number of distinct URLs that contributed at least one parent."""
        return len({parent.u for parent in self.parents})

    def local_parents(self):
        """Parents from local sources: the ones every adapter drops unless its output opts in."""
        return tuple(parent for parent in self.parents if parent.local)


### Plugin Protocols ###

@runtime_checkable
class Source(Protocol):
    """
    A plugin that produces documents. `name` is the registry key and the
    `type:` value in the configuration file's sources list. The class is
    constructed with the validated options of its entry.

    A source never constructs an HTTP session and never prints; both
    come from the caller so a library user, a CI log, and a person at a
    terminal can each handle them differently.
    """

    name: ClassVar[str]

    def fetch(self, session, cache, progress: Progress) -> Iterator[Document]:
        """
        Yields Document records.

        Args:
            session: HTTP session to request through (requests.Session or
                a test double with the same get() signature).
            cache: the fetch cache the session's conditional GETs use.
            progress: callback receiving one line per event.
        """
        ...


@runtime_checkable
class SiteHandler(Protocol):
    """
    A plugin the web source consults for each URL it visits. Handlers
    are consulted in registration order and `generic` is always last.
    A handler reads a page; it never discovers links, so the crawl stays
    one graph however many handlers are enabled.

    Class attributes:
        name: registry key and the value used in `site_handlers:`.
        source_type: recorded on every parent this handler reads.
        default_crawl_exclude_patterns: regular expressions added to the
            crawl's exclude list while this handler is enabled.
        default_index_exclude_patterns: the same for the index list.
    """

    name: ClassVar[str]
    source_type: ClassVar[str]
    default_crawl_exclude_patterns: ClassVar[Sequence]
    default_index_exclude_patterns: ClassVar[Sequence]

    def matches(self, url: str) -> bool:
        """True when this handler reads the page at url."""
        ...

    def fetch_url(self, url: str) -> str:
        """The URL to request for url (a blob page rewritten to its raw file, for example)."""
        ...

    def expects_html(self, url: str) -> bool:
        """
        True when the response for url is HTML to parse; False when it is
        plain text to wrap. Decided per URL because one host can serve
        both kinds of page.
        """
        ...

    def extract(self, soup, url: str):
        """Returns an Extraction, or None when the page is only a link-discovery hop."""
        ...

    def content_type(self, url: str) -> str:
        """The CONTENT_TYPES value recorded on parents read from url."""
        ...


@runtime_checkable
class Adapter(Protocol):
    """
    A plugin that writes one output format. `name` is the registry key
    and the `type:` value in the configuration file's outputs list. An
    adapter never fetches a URL or runs a model. The shared adapter base
    drops local parents unless the output's options set include_local.
    """

    name: ClassVar[str]

    def write(self, compendium: Compendium, out_dir, options: Mapping) -> Iterable:
        """
        Writes files under out_dir and returns the paths written, so the
        command line can list them.
        """
        ...
