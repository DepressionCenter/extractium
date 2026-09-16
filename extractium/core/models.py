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
Last Modified: 2026-09-16
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
__date__ = "2026-09-16"

import re
import urllib.parse
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
# search clients key display rules on it. "repository" is a scholarly
# repository such as a DSpace instance: its records are deposits with
# abstracts, authors, and permanent identifiers, which is neither a
# website nor a code host nor a help-desk article.
SOURCE_TYPES = frozenset({"kb", "github", "web", "youtube", "local", "repository"})

# The display name used when a record is built without one. A build reads
# its labels from the configuration, where every source must name itself;
# these cover records made outside a build, such as by a plugin under test
# or by a program that uses this package as a library. They are deliberately
# generic, because the useful name ("Peer-to-Peer Program", "Video Library")
# is knowledge the configuration holds and this file cannot guess.
#
# Keyed on source_type rather than on the configured source type, because a
# web source pointed at a TeamDynamix portal yields "kb" records: the site
# handler decides, not the configuration entry.
DEFAULT_SOURCE_LABELS = {
    "kb": "Knowledge Base",
    "github": "GitHub",
    "web": "Website",
    "youtube": "YouTube Channel",
    "local": "Local Files",
    "repository": "Repository",
}

# Longest a source label may be. Long enough for a program or center name,
# short enough to head a section in llms.txt and to sit in a search result
# without wrapping.
MAX_SOURCE_LABEL_CHARS = 60

# Every value a parent's content_type may hold.
# "manifest" is a project or build file indexed as text (a pyproject.toml,
# a DESCRIPTION, a Dockerfile): short, and often a faster explanation of a
# project than its prose. "repo_map" is the synthetic per-repository
# summary a code source writes, which also records how completely that
# repository could be read. "code_file" is what one source file holds --
# its definitions, what it brings in, and what reaches into it -- and
# "code_symbol" is one definition, with its signature, its documentation,
# and a link to its lines. Neither ever carries a source body.
CONTENT_TYPES = frozenset({
    "article", "readme", "wiki", "release_notes", "page", "text", "video_transcript",
    "manifest", "repo_map", "code_file", "code_symbol",
})

# A local document's URL is "local:" plus a path relative to the source
# folder, so an absolute path from the operator's disk never reaches an
# output file.
LOCAL_URL_PREFIX = "local:"

# The query parameter a video's address carries the moment in, and the
# source type whose addresses carry it. A video's sections are each
# addressed at the moment they begin, which is what makes a citation
# open the video at the quoted words; anything that works per page
# wants the video itself, so it drops this one parameter and keeps the
# rest. Scoped to that source type because "t" means something else
# elsewhere, and dropping it from another site's address would break
# the link.
MOMENT_PARAM = "t"
MOMENT_SOURCE_TYPE = "youtube"

# The fields an enrichment pass fills on a section: a summary, tags,
# keywords, when the pass ran (UTC, ISO 8601), and which version of it.
# Every section carries them, None until something has written them, so
# an adapter writes a value when there is one and nothing when there
# is not, and the container's layout is the same either way. A source
# that knows a page's own description and tags (a video's description,
# a repository's topics, a portal article's tag list) sets the summary
# and the tags itself; the keyword step (extractium.core.keywords)
# fills the keywords, and adds to every page's tags the keywords its
# sections share, after whatever the source gave.
ENRICHMENT_FIELDS = ("summary", "tags", "keywords", "enriched_at", "enrich_ver")

# Longest summary a source may hand over, in characters. A video's
# description can run to pages of links and boilerplate; what an index
# entry and a concept file need is the opening, cut at a word.
MAX_SUMMARY_CHARS = 600

# The most tags a source may hand over for one page, and the longest one
# may be. Tags arrive from pages and API responses, which are untrusted,
# so a page that declares hundreds of keywords contributes the first few.
MAX_TAGS = 20
MAX_TAG_CHARS = 80

# Collapses any run of whitespace, including newlines, into one space.
_WHITESPACE_RUN = re.compile(r"\s+")

# A parent id is the first 16 hexadecimal characters of a SHA-1 digest.
PARENT_ID_RE = re.compile(r"^[0-9a-f]{16}$")

# Storage types the container format allows for vector components.
VECTOR_DTYPES = ("int8", "float32")

# Build times are exchanged in UTC only, ISO 8601 with a Z suffix.
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

# A progress callback receives one short human-readable line per event.
# The caller decides where it goes: standard error, a CI log, or nowhere.
Progress = Callable[[str], None]


def page_address_of(url, source_type):
    """
    The address of the page a section belongs to.

    For almost every source this is the section's own address, because
    a page and its sections share one. A video is the exception: each
    stretch of a transcript is addressed at the moment it begins, so
    one video has as many addresses as it has sections, and this folds
    them back into the video.

    Args:
        url (str): the section's address.
        source_type (str): the section's source type.

    Returns:
        str: the page's address. Unchanged for every source but a video.
    """
    if source_type != MOMENT_SOURCE_TYPE:
        return url
    split = urllib.parse.urlsplit(url)
    kept = [
        (name, value)
        for name, value in urllib.parse.parse_qsl(split.query, keep_blank_values=True)
        if name != MOMENT_PARAM
    ]
    return urllib.parse.urlunsplit(
        (split.scheme, split.netloc, split.path, urllib.parse.urlencode(kept), split.fragment)
    )


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


def clean_summary(text, limit=MAX_SUMMARY_CHARS):
    """
    A source's description of a page as one paragraph of bounded length.

    Args:
        text (str | None): the description as the source reported it.
        limit (int): the most characters to keep.

    Returns:
        str: whitespace collapsed, cut at a word boundary with an
        ellipsis when anything was cut; empty when there was nothing.

    Raises:
        ValueError: if text is neither text nor None.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        raise ValueError(f"summary must be text; got {type(text).__name__}.")
    flat = _WHITESPACE_RUN.sub(" ", text).strip()
    if len(flat) <= limit:
        return flat
    cut = flat.rfind(" ", 0, limit)
    return flat[:cut if cut > 0 else limit].rstrip() + "..."


def clean_tags(values, limit=MAX_TAGS, max_chars=MAX_TAG_CHARS):
    """
    A source's tags for a page, each once, in the order given.

    Args:
        values (Iterable[str] | None): the tags as the source reported
            them.
        limit (int): the most tags to keep.
        max_chars (int): a tag longer than this is dropped rather than
            cut, because half a tag names nothing.

    Returns:
        tuple[str, ...]: stripped, non-empty, compared without regard to
        case with the first spelling kept.

    Raises:
        ValueError: if values is not a sequence of text.
    """
    if values is None:
        return ()
    if isinstance(values, str) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"tags must be a list of text values; got {values!r}.")
    kept = {}
    for value in values:
        tag = _WHITESPACE_RUN.sub(" ", value).strip()
        if not tag or len(tag) > max_chars:
            continue
        kept.setdefault(tag.casefold(), tag)
        if len(kept) >= limit:
            break
    return tuple(kept.values())


def _resolve_source_label(value, source_type):
    """
    The display name to store on a record, filling in a generic one when
    the caller gave none.

    Every record carries a label, so a client never has to decide what to
    show when the field is missing. A build overrides these defaults with
    the label its configuration requires of each source.

    Args:
        value (str | None): the label the caller supplied, if any.
        source_type (str): the record's source_type, already validated.

    Returns:
        str: the supplied label with surrounding blanks removed, or the
        default for this source_type.

    Raises:
        ValueError: if the label is not text, or is longer than
            MAX_SOURCE_LABEL_CHARS.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT_SOURCE_LABELS[source_type]
    if not isinstance(value, str):
        raise ValueError(f"source_label must be text; got {type(value).__name__}.")
    label = value.strip()
    if len(label) > MAX_SOURCE_LABEL_CHARS:
        raise ValueError(
            f"source_label must be {MAX_SOURCE_LABEL_CHARS} characters or fewer; "
            f"got {len(label)}."
        )
    return label


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
        source_label (str): the name a reader sees for the collection
            this came from, such as "Peer-to-Peer Program". Blank or
            absent takes the DEFAULT_SOURCE_LABELS entry for
            source_type, so the field is never empty. A build replaces
            it with the label its configuration gives the source.
        categories (tuple[str, ...]): hierarchy from the source,
            outermost first; empty when the source has none.
        local (bool): True for local-filesystem content, which every
            output drops unless it opts in.
        weight (float): per-document multiplier applied after rank
            fusion; greater than zero, 1.0 by default.
        summary (str): the page's own description, as its source states
            it: a video's description, a repository's description, a
            portal article's summary, a page's meta description. Empty
            when the source has none, in which case an output that
            needs one uses an excerpt of the text. Cleaned through
            clean_summary.
        tags (tuple[str, ...]): the page's own tags, as its source
            states them: a video's tags, a repository's topics, an
            article's tag list, a page's meta keywords. They come first
            in the page's tags; the keyword step adds what the text
            yields after them. Cleaned through clean_tags.

    Raises:
        ValueError: if a field is blank, outside its vocabulary, longer
            than its limit, or the local flag disagrees with the URL
            prefix.
    """

    url: str
    title: str
    content: object
    source_type: str
    content_type: str
    source_label: str = ""
    categories: tuple = ()
    local: bool = False
    weight: float = 1.0
    summary: str = ""
    tags: tuple = ()

    def __post_init__(self):
        _require_text(self.url, "url")
        _require_vocabulary(self.source_type, "source_type", SOURCE_TYPES)
        _require_vocabulary(self.content_type, "content_type", CONTENT_TYPES)
        object.__setattr__(
            self, "source_label", _resolve_source_label(self.source_label, self.source_type)
        )
        if not (isinstance(self.weight, (int, float)) and self.weight > 0):
            raise ValueError(f"weight must be a number greater than zero; got {self.weight!r}.")
        _check_local_marker(self.url, self.local)
        object.__setattr__(self, "categories", tuple(self.categories))
        object.__setattr__(self, "summary", clean_summary(self.summary))
        object.__setattr__(self, "tags", clean_tags(self.tags))


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
        summary (str): the page's own description where the page states
            one, such as its meta description; empty otherwise.
        tags (tuple[str, ...]): the page's own tags where the page shows
            them; empty otherwise. Both are cleaned as Document cleans
            them.
    """

    title: str
    node: object
    categories: tuple = ()
    summary: str = ""
    tags: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "categories", tuple(self.categories))
        object.__setattr__(self, "summary", clean_summary(self.summary))
        object.__setattr__(self, "tags", clean_tags(self.tags))


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
        source_label (str): the name a reader sees for the collection
            this section came from. Never empty; see Document.
        categories (tuple[str, ...]): hierarchy, outermost first.
        local (bool): True when the parent came from a local source.
        weight (float): per-document multiplier; greater than zero.
        summary (str | None): the page's own description as its source
            gave it, or one an enrichment pass wrote; None when neither.
        tags (tuple[str, ...] | None): the page's tags: the ones its
            source gave, then the ones the keyword step found; None when
            neither.
        keywords (tuple[str, ...] | None): the phrases an enrichment
            pass found this section to be about, most telling first.
        enriched_at (str | None): when the pass ran, UTC, ISO 8601.
        enrich_ver (str | None): which version of the pass wrote them.
    """

    id: str
    t: str
    x: str
    u: str
    host: str
    source_type: str
    content_type: str
    source_label: str = ""
    categories: tuple = ()
    local: bool = False
    weight: float = 1.0
    summary: object = None
    tags: object = None
    keywords: object = None
    enriched_at: object = None
    enrich_ver: object = None

    def __post_init__(self):
        if not isinstance(self.id, str) or not PARENT_ID_RE.match(self.id):
            raise ValueError(f"id must be 16 lowercase hexadecimal characters; got {self.id!r}.")
        _require_text(self.u, "u")
        _require_vocabulary(self.source_type, "source_type", SOURCE_TYPES)
        _require_vocabulary(self.content_type, "content_type", CONTENT_TYPES)
        object.__setattr__(
            self, "source_label", _resolve_source_label(self.source_label, self.source_type)
        )
        if not (isinstance(self.weight, (int, float)) and self.weight > 0):
            raise ValueError(f"weight must be a number greater than zero; got {self.weight!r}.")
        _check_local_marker(self.u, self.local)
        object.__setattr__(self, "categories", tuple(self.categories))
        for name in ("summary", "enriched_at", "enrich_ver"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be text or None; got {value!r}.")
        for name in ("tags", "keywords"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, str) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{name} must be a list of text values or None; got {value!r}.")
            object.__setattr__(self, name, tuple(value))


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
        name (str): display name of the compendium.
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

    A source that takes part in a web crawl may also define an optional
    `configure(registry, settings)`, which the caller invokes after
    construction to hand over the plugin registry and the global crawl
    settings. Those belong to the whole build rather than to one entry in
    the sources list, so they do not travel in the entry's options. A
    source that needs neither omits the method.

    A source may also define `read_found_links(session, cache, progress,
    links)`, which the caller invokes once every source has run, with the
    addresses the site handlers collected during the crawls and held back
    from them. It yields documents like `fetch`, and it applies the
    source's own rule for what a link found on somebody's page may add to
    the index.
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

    Eight methods are optional, and a handler that defines none behaves
    exactly as the required five describe:

    - `scope_prefix(seed_url)` may narrow the default crawl scope for a
      seed on a host it knows, returning the prefix the crawl stays
      inside, or None to leave the seed's origin as the scope. It is
      consulted only when the source has no include patterns, because
      an explicit list replaces the default scope altogether.
    - `observe_link(url)` sees every link the crawl discovers, in scope
      or not, before the scope check. It returns nothing. A handler
      uses it to collect addresses another source should read, such as
      videos linked from a page.
    - `configure(settings)` receives the build's global crawl settings
      after construction. A handler needs it when its rules depend on
      what the operator configured rather than on the URL alone.
    - `allows(url)` may veto a URL the crawl would otherwise follow.
      Every handler that defines it is asked about every URL, whatever
      `matches` says, and one refusal keeps the URL out of scope. This
      is how a host-specific scope rule stays in its own handler.
    - `offer_source(seed_url)` may name a better source for a crawl's
      seed, as `(source name, options)`. It is consulted for the seed
      only, so a link found mid-crawl never redirects the build.
    - `canonical_url(url)` may fold the several addresses one page is
      linked under into one, which the crawl then visits once and
      records on the document. It is consulted for every seed and every
      discovered link the handler matches, before anything else is
      decided about the address. A handler that does not define it
      leaves every address as written.
    - `landing_allowed(url, final_url)` may say that a request for a
      page it reads is expected to land at another address, such as an
      export served from a delivery host, so the crawl does not treat
      that landing as a redirect off the site. Consulted only when a
      request was redirected somewhere the scope would refuse.
    - `attachment_listing_urls(soup, url)` may name the addresses where
      the page's host lists the files attached to the page, when that
      list is not in the page itself. While the source reads documents,
      each is queued as a page of the crawl and its links are read like
      any page's. Consulted for pages whose links are followed.

    Class attributes:
        name: registry key and the value used in `site_handlers:`.
        source_type: recorded on every parent this handler reads.
        default_crawl_exclude_patterns: regular expressions added to the
            crawl's exclude list while this handler is enabled.
        default_index_exclude_patterns: the same for the index list.
        document_url_patterns: optional. Regular expressions for
            addresses on the handler's host that serve a document file
            without naming its extension. While a source reads
            documents, such an address is fetched as a file and read,
            and the same pattern in the exclude lists is set aside.
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
