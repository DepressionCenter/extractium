"""
Summary: The web-crawl source, the one crawler in Extractium: a
queue-driven crawl from a seed URL, kept in scope by the same-origin or
prefix rules of extractium.core.fetch and by the operator's include,
leaf, and exclude patterns. Host-specific reading of pages is delegated to
site-handler plugins (generic, tdx, github), consulted per URL with
generic always last, so this module never branches on a host name. See
docs/extractium-spec.md sections 2.1, 5, and 6.

This file is part of Extractium™
extractium/sources/web.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
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
__date__ = "2026-09-15"

import hashlib
import re
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from extractium.core import fetch as fetching
from extractium.core.chunk import extract_links, markdown_text_to_soup
from extractium.core.models import Document
from extractium.core import prose
from extractium.readers import documents as readers
from extractium.sources.generic import GenericHandler

### Constants ###

# The handler every crawl ends with; it matches every URL.
FALLBACK_HANDLER_NAME = GenericHandler.name

# Safety ceiling on pages visited per crawl when the caller gives none;
# the same value the configuration file defaults to.
DEFAULT_MAX_PAGES = 10000

# Least time between two requests to one host when the caller gives none,
# in seconds. The pause itself is taken by the session, per host; the
# crawl only records the setting.
DEFAULT_DELAY_SECONDS = 0.5

# How many page fetches a crawl keeps in flight when the caller gives
# none: one, which is a fetch at a time.
DEFAULT_PARALLEL_PAGES = 1


### Crawl Settings ###

@dataclass(frozen=True)
class CrawlSettings:
    """
    The global settings a crawl needs, separate from the source's own
    options because they apply to every source in a build.

    Attributes:
        max_pages (int): the most pages one crawl may visit; 1 or more.
        delay_seconds (float): least time between two requests to the
            same host, in seconds; 0 for none. The session the build
            makes enforces it (see extractium.core.transport); a crawl
            handed a bare session is not paced.
        user_agent (str): how the crawler introduces itself.
        respect_robots_txt (bool): whether robots.txt rules are honored.
        github_owners (tuple[str, ...]): the GitHub accounts this build
            may read. Empty means the build reads only the accounts its
            own sources named. The GitHub site handler enforces this; no
            other handler looks at it.
        parallel_pages (int): how many page fetches a crawl keeps in
            flight; 1 or more. Pages are still visited, and documents
            still yielded, in the order a one-at-a-time crawl would.
    """

    max_pages: int = DEFAULT_MAX_PAGES
    delay_seconds: float = DEFAULT_DELAY_SECONDS
    user_agent: str = fetching.DEFAULT_USER_AGENT
    respect_robots_txt: bool = True
    github_owners: tuple = ()
    parallel_pages: int = DEFAULT_PARALLEL_PAGES

    @property
    def blocked_retry_user_agent(self):
        """
        The identity a refused page is retried with once, or None to never
        retry.

        Turning `respect_robots_txt` off is an operator's statement that
        they own the sites in scope, or have permission for them. That is
        the only condition under which a crawl will present itself as a
        browser, and then only for a page that refused the truthful
        identity outright. A crawl left at the default never does it, so
        no site is misled by a build nobody chose to configure that way.
        """
        return None if self.respect_robots_txt else fetching.BROWSER_USER_AGENT


### Seeds ###

def seed_urls_from(options):
    """
    The addresses a crawl starts from, as a tuple, however the entry
    wrote them.

    One crawl may start in several places. That is not the same as
    several sources: one crawl keeps one list of pages it has already
    visited, so a page reachable from two starting points is fetched once
    and indexed once. Two sources covering the same ground would index it
    twice.

    Args:
        options (Mapping): a web entry's options, holding `seed_urls`,
            `seed_url`, or both (the loader fills in both; a caller
            inside the program may set either).

    Returns:
        tuple[str, ...]: the seeds, in the order given, each once.

    Raises:
        KeyError: if the options name no seed at all.
    """
    seeds = options.get("seed_urls") or ()
    if not seeds:
        seeds = (options["seed_url"],)
    unique = []
    for seed in seeds:
        if fetching.normalise(seed) not in {fetching.normalise(s) for s in unique}:
            unique.append(seed)
    return tuple(unique)


### Site Handler Selection ###

def resolve_site_handlers(registry, names=None, settings=None):
    """
    Instantiates the site handlers a web source entry asks for.

    Args:
        registry (extractium.core.registry.Registry): where handler
            classes are looked up.
        names (Sequence[str] | None): the entry's `site_handlers` option.
            None means every registered handler; an empty sequence means
            the generic fallback only.
        settings (CrawlSettings | None): the build's global crawl
            settings, offered to each handler that defines the optional
            `configure` hook. A handler whose rules depend only on the URL
            does not define it and never sees these.

    Returns:
        tuple: handler instances in the order given (or, for None, in
        registry name order), with the generic handler last.

    Raises:
        extractium.core.registry.RegistryError: if a name is unknown.
    """
    if names is None:
        names = registry.site_handler_names()
    handlers = []
    for name in names:
        handler = registry.get_site_handler(name)()
        if settings is not None and hasattr(handler, "configure"):
            handler.configure(settings)
        handlers.append(handler)
    return order_site_handlers(handlers)


def scope_prefix_for(handlers, seed_url):
    """
    The default scope for one seed: a handler's narrower prefix when one
    claims the host, otherwise the seed's origin.

    Handlers are asked in their crawl order and the first answer wins, so
    a handler placed ahead of another decides for the hosts both know.

    Args:
        handlers (Iterable): the enabled handler instances.
        seed_url (str): one of the crawl's starting addresses.

    Returns:
        str: the prefix every discovered link must start with when the
        source has no include patterns.
    """
    for handler in handlers:
        if hasattr(handler, "scope_prefix"):
            prefix = handler.scope_prefix(seed_url)
            if prefix:
                return prefix
    return fetching.derive_auto_prefix(seed_url)


def observe_link(handlers, url):
    """
    Shows one discovered link to every handler that wants to see links,
    whatever the crawl then decides about it.

    Args:
        handlers (Iterable): the enabled handler instances.
        url (str): the discovered link.
    """
    for handler in handlers:
        if hasattr(handler, "observe_link"):
            handler.observe_link(url)


def handlers_allow(handlers, url):
    """
    Whether every handler that has an opinion lets a URL into the crawl.

    Every handler defining the optional `allows` hook is asked about every
    URL, whatever its `matches` says, because a scope rule has to cover
    the addresses a handler does not itself read: the GitHub rule applies
    to raw.githubusercontent.com as much as to github.com. One refusal is
    enough to keep the URL out.

    Args:
        handlers (Iterable): the enabled handler instances.
        url (str): the candidate URL.

    Returns:
        bool: True when no handler refuses it.
    """
    return all(handler.allows(url) for handler in handlers if hasattr(handler, "allows"))


def order_site_handlers(handlers):
    """
    Puts the generic fallback last and appends it when it is missing, so
    every URL has a handler and no host-specific handler is shadowed.

    Args:
        handlers (Iterable): handler instances.

    Returns:
        tuple: the handlers, generic last.
    """
    specific = [h for h in handlers if h.name != FALLBACK_HANDLER_NAME]
    fallback = [h for h in handlers if h.name == FALLBACK_HANDLER_NAME] or [GenericHandler()]
    return tuple(specific + fallback[:1])


def default_exclude_patterns(handlers, kind, readable=()):
    """
    The exclude list a crawl uses when the operator wrote none: the
    host-independent asset patterns plus what each enabled handler adds.

    Args:
        handlers (Iterable): the enabled handler instances.
        kind (str): "crawl" or "index".
        readable (Iterable[str]): file extensions a reader turns into
            text for this crawl, left off the asset patterns. When any
            are given, the addresses a handler names as documents are
            left off its exclusions too.

    Returns:
        tuple[str, ...]: regular expression strings, each once, asset
        patterns first.
    """
    attribute = f"default_{kind}_exclude_patterns"
    patterns = list(fetching.asset_exclude_patterns(readable))
    for handler in handlers:
        # An address a handler says serves a document file is kept off
        # the crawl only while no reader could turn the file into text.
        documents = getattr(handler, "document_url_patterns", ()) if readable else ()
        for pattern in getattr(handler, attribute):
            if pattern not in patterns and pattern not in documents:
                patterns.append(pattern)
    return tuple(patterns)


def document_url_re(handlers):
    """
    The addresses a crawl that reads documents fetches as files: any
    address that names a document extension, plus the addresses each
    enabled handler says serve a file without one.

    Args:
        handlers (Iterable): the enabled handler instances.

    Returns:
        re.Pattern: matches an address the crawl reads as a document.
    """
    patterns = [readers.DOCUMENT_URL_RE.pattern]
    for handler in handlers:
        patterns.extend(getattr(handler, "document_url_patterns", ()))
    return re.compile("|".join(f"(?:{pattern})" for pattern in patterns), re.I)


### Source ###

class WebSource:
    """
    Crawls one website from a seed URL and yields a Document per page
    that holds indexable content.

    The source takes everything it talks to from the caller: the HTTP
    session, the cache metadata, and the progress callback. It never
    constructs a session and never prints, so a library caller, a CI log,
    and a person at a terminal can each handle them differently.

    Args:
        options (Mapping): the validated options of a `web` entry in the
            configuration file: seed_url, include_patterns, leaf_patterns
            (single pages on other hosts, fetched when a page in the
            crawl's own scope links to them and never followed for links
            of their own), crawl_exclude_patterns, index_exclude_patterns (None for
            either exclude list means "asset patterns plus the enabled
            handlers' defaults"), extra_crawl_exclude_patterns and
            extra_index_exclude_patterns (added on top of whichever list
            applies), site_handlers (unused here; the caller resolves
            names to the handlers argument), and read_documents, which
            lets the crawl fetch a Word, OpenDocument, RTF, or PDF file it
            finds a link to and index the text a reader takes from it.

            Two further keys are set by a caller inside the program, never
            by a configuration file: `already_indexed`, a set of URLs
            another source has already turned into documents, which are
            followed for their links but never indexed twice; and
            `promote`, which a caller sets to False to stop a handler
            offering a different source for the seed. A source that
            falls back to a crawl sets both, so the crawl neither repeats
            its work nor hands the seed straight back to it.
        site_handlers (Iterable): handler instances, consulted per URL in
            this order. The generic handler is appended when missing and
            always consulted last.
        settings (CrawlSettings): the global crawl settings.
    """

    name = "web"

    def __init__(self, options, site_handlers=(), settings=CrawlSettings()):
        self.options = options
        self.seed_urls = seed_urls_from(options)
        # The first seed, for the things that need one address rather than
        # the set: the handler offer, and progress lines that name the crawl.
        self.seed_url = self.seed_urls[0]
        self.include_patterns = tuple(options.get("include_patterns") or ())
        self.leaf_patterns = tuple(options.get("leaf_patterns") or ())
        self.read_documents = bool(options.get("read_documents", False))
        self.already_indexed = set(options.get("already_indexed") or ())
        # Pages the server confirmed gone during this crawl, so an
        # incremental rebuild drops them rather than carrying them forward.
        self.gone = set()
        self.registry = None
        self._adopt(site_handlers, settings)

    def configure(self, registry, settings):
        """
        Adopts the enabled site handlers and the build's global crawl
        settings, which a caller such as the command line knows and the
        configuration file's own options do not carry.

        This is the optional hook of the source protocol: a source that
        takes no part in a crawl simply does not define it, and a caller
        that has nothing to supply never calls it.

        Args:
            registry (extractium.core.registry.Registry): where site
                handler classes are looked up.
            settings (CrawlSettings): the page ceiling, the delay, the
                User-Agent, and whether robots.txt is honored.

        Raises:
            extractium.core.registry.RegistryError: if the entry's
                `site_handlers` list names a handler that is not installed.
        """
        self.registry = registry
        self._adopt(
            resolve_site_handlers(registry, self.options.get("site_handlers"), settings),
            settings,
        )

    def _adopt(self, site_handlers, settings):
        """
        Sets the handlers and settings, then recomputes the exclude lists,
        which depend on which handlers are enabled: switching a handler
        off also drops the exclusions it contributed.
        """
        self.handlers = order_site_handlers(site_handlers)
        self.settings = settings
        self.crawl_exclude_patterns = self._patterns(self.options, "crawl")
        self.index_exclude_patterns = self._patterns(self.options, "index")

    def _patterns(self, options, kind):
        """
        One exclude list: the entry's own list, or the handler-derived
        default when the entry wrote none, followed by the entry's extra
        patterns. An extra pattern already on the list is not repeated.
        """
        base = options.get(f"{kind}_exclude_patterns")
        readable = readers.DOCUMENT_EXTENSIONS if self.read_documents else ()
        patterns = list(
            default_exclude_patterns(self.handlers, kind, readable) if base is None else base
        )
        for pattern in options.get(f"extra_{kind}_exclude_patterns") or ():
            if pattern not in patterns:
                patterns.append(pattern)
        return tuple(patterns)

    def handler_for(self, url):
        """The first enabled handler whose matches(url) is true; the generic fallback at worst."""
        for handler in self.handlers:
            if handler.matches(url):
                return handler
        return self.handlers[-1]

    def fetch(self, session, cache, progress):
        """
        Crawls from the seed URL and yields Document records.

        The seed is visited unconditionally, even when it matches an
        exclude pattern; the patterns govern which discovered links are
        followed. Each visited page's links are queued when in scope. A
        page whose URL matches an index exclude pattern is followed but
        not yielded. Every page counts toward max_pages whether or not it
        yields a document.

        A link that is out of scope but matches a leaf pattern is fetched
        and indexed as a leaf when the page linking to it sits inside the
        scope derived from a seed: the site itself, not a host reached
        through an include pattern. A leaf's own links are never read, so
        a leaf never starts a crawl of its host, and a leaf linked only
        from another leaf is never reached. The asset, exclude, robots,
        and page-ceiling rules apply to a leaf as to any page.

        A page whose request lands at another address the crawl may
        visit, such as a short link to an article, is recorded under the
        address it landed on: a later link to that address is not
        fetched again, a page already read there is not indexed twice,
        and its links resolve against the address the page really has.
        A request a handler rewrote, such as a file fetched from a raw
        host, keeps the page's own address.

        When the crawl reads documents and a page's handler knows where
        its host lists the files attached to the page, that listing is
        queued as a page of the crawl and its links are read like any
        page's; the listing itself yields no document.

        Up to `parallel_pages` fetches are kept in flight, but pages are
        taken from the queue, have their links read, and are yielded in
        the order a one-at-a-time crawl would use, and each page's own
        progress lines are printed together under its own line. The pause
        between requests is the session's job, kept per host, so a crawl
        that reads two hosts is not slowed by the pause on either.

        Every seed and every discovered link is folded to its handler's
        canonical form first, so a file linked under several addresses
        is visited once. With `read_documents` on, a link to a Word,
        OpenDocument, RTF, or PDF file in scope is fetched as bytes, read into
        text, and indexed as a document with no links of its own; the
        same file linked at two addresses is indexed once.

        Args:
            session: HTTP session to request through (requests.Session or
                a test double with the same get() signature).
            cache (dict): the fetch cache metadata (URL -> validators),
                read for conditional GETs and mutated with fresh entries.
                The caller loads it before the crawl and saves it after;
                this source only flushes it periodically.
            progress (Callable[[str], None]): receives one line per event.

        Before any of that, each enabled handler is asked whether it knows
        a better source for the seed. A repository host read through its
        own interface gives complete, structured content, where scraping
        its pages gives whatever its browser code happened to render. The
        offer is for the seed only, so a link found mid-crawl never
        redirects the build.

        Yields:
            extractium.core.models.Document: one per page with content.
        """
        offered = self._offered_source(progress)
        if offered is not None:
            yield from offered.fetch(session, cache, progress)
            return

        settings = self.settings
        auto_prefix = tuple(scope_prefix_for(self.handlers, seed) for seed in self.seed_urls)
        origin = tuple(fetching.get_origin(seed) for seed in self.seed_urls)
        include_res = fetching.compile_patterns(self.include_patterns)
        leaf_res = fetching.compile_patterns(self.leaf_patterns)
        crawl_exclude_res = fetching.compile_patterns(self.crawl_exclude_patterns)
        index_exclude_res = fetching.compile_patterns(self.index_exclude_patterns)
        robots = fetching.RobotsPolicy(
            session, settings.user_agent, enabled=settings.respect_robots_txt, progress=progress
        )
        # Addresses of files a reader turns into text, which pass the
        # asset filter; None when this crawl reads no documents.
        readable_re = document_url_re(self.handlers) if self.read_documents else None

        for seed in self.seed_urls:
            progress(f"Seed:         {seed}")
        progress(f"Auto prefix:  {', '.join(dict.fromkeys(auto_prefix))}")
        progress(f"Include pats: {list(self.include_patterns) or '(auto -- prefix only)'}")
        if self.leaf_patterns:
            progress(f"Leaf pats:    {list(self.leaf_patterns)}")
        progress(f"Site handlers: {[h.name for h in self.handlers]}")

        seed_norms = [self._canonical(fetching.normalise(seed)) for seed in self.seed_urls]
        visited = set()
        queued = set(seed_norms)   # dedup before download
        # Each entry is an address and whether its links are followed:
        # True for a page of the crawl, False for a leaf.
        queue = deque((seed, True) for seed in seed_norms)
        landed = {}
        # Addresses pages landed on after a redirect, so a later link to
        # one is not fetched again. Kept apart from `visited`, which is
        # what the page ceiling counts.
        landed_on = set()
        # The digest of every document file indexed so far, keyed to the
        # address it was indexed under, so one file linked at several
        # addresses is indexed once.
        seen_documents = {}

        def crawl_allows(link):
            """Whether a link is a page of this crawl: in scope, and allowed by every handler."""
            return fetching.in_scope(
                link, auto_prefix, origin, include_res, crawl_exclude_res, readable_re
            ) and handlers_allow(self.handlers, link)

        def leaf_allows(link):
            """
            Whether a link is a leaf: an address a leaf pattern names,
            fetched for its own content and never followed. The asset,
            exclude, and handler rules apply to it as to any page, so a
            leaf pattern for a file host reaches only what can be read.
            """
            if not any(r.search(link) for r in leaf_res):
                return False
            if fetching.is_asset(link, readable_re):
                return False
            if any(r.search(link) for r in crawl_exclude_res):
                return False
            return handlers_allow(self.handlers, link)

        def in_primary_scope(url):
            """Whether a page sits inside the scope derived from a seed, whatever the include patterns say."""
            return any(url.startswith(prefix) for prefix in auto_prefix)

        def listings_for(handler, soup, url):
            """
            The addresses where a page's host lists the files attached to
            the page, from a handler that knows them, read for their links
            only while this crawl reads documents; nothing otherwise.
            """
            if readable_re is None or not hasattr(handler, "attachment_listing_urls"):
                return ()
            return [fetching.normalise(listing) for listing in handler.attachment_listing_urls(soup, url)]

        def start_fetch(url, lines):
            """
            Begins one page's fetch, with its progress lines collected for
            later. The kind says what the fetch returns: "html" a parsed
            page, "text" a plain-text body, "document" a file's bytes.
            """
            handler = self.handler_for(url)
            request_url = handler.fetch_url(url)
            if readable_re is not None and readable_re.search(url):
                kind = "document"
            else:
                kind = "html" if handler.expects_html(url) else "text"
            if not robots.allows(request_url):
                lines.append(f"  SKIP {url} -- disallowed by robots.txt")
                return handler, request_url, kind, None
            common = dict(
                user_agent=settings.user_agent, progress=lines.append,
                fallback_user_agent=settings.blocked_retry_user_agent,
                note_final_url=lambda final, key=url: landed.__setitem__(key, final),
                note_gone=lambda key=url: self.gone.add(key),
            )
            if kind == "document":
                fetch = lambda: fetching.fetch_bytes(
                    session, request_url, cache, readers.MAX_DOCUMENT_BYTES, **common
                )
            else:
                fetch = lambda: fetching.fetch(
                    session, request_url, cache, expect_html=(kind == "html"), **common
                )
            if pool is None:
                result = Future()
                result.set_result(fetch())
            else:
                result = pool.submit(fetch)
            return handler, request_url, kind, result

        def next_page():
            """The next queued page with its fetch started, or None when none is left."""
            while queue and len(visited) < settings.max_pages:
                url, follow_links = queue.popleft()
                if url in visited or url in landed_on:
                    continue
                visited.add(url)
                lines = []
                handler, request_url, kind, result = start_fetch(url, lines)
                return len(visited), url, follow_links, handler, request_url, kind, lines, result
            return None

        depth = max(1, int(settings.parallel_pages))
        pool = ThreadPoolExecutor(max_workers=depth) if depth > 1 else None
        in_flight = deque()
        try:
            while True:
                # Keep the pipeline full, then take the oldest page in flight.
                while len(in_flight) < depth:
                    page = next_page()
                    if page is None:
                        break
                    in_flight.append(page)
                if not in_flight:
                    break
                ordinal, url, follow_links, handler, request_url, kind, lines, result = \
                    in_flight.popleft()
                progress(f"[{ordinal:4d}] {url}")
                fetched = None if result is None else result.result()
                for line in lines:
                    progress(line)
                if fetched is None:
                    continue
                if not follow_links:
                    progress("       (leaf; its links are not followed)")

                # Where a request actually lands is checked against the
                # scope like any discovered link: a page may redirect off
                # the site, and what arrives then is not this site's content.
                is_seed = url in seed_norms
                if is_seed and self._seed_redirected_out_of_scope(
                    url, landed.get(url), auto_prefix, origin, include_res, crawl_exclude_res, progress
                ):
                    continue
                if not is_seed and self._redirected_out_of_scope(
                    url, handler, request_url, landed.get(url),
                    crawl_allows if follow_links else leaf_allows, progress,
                ):
                    continue

                final = self._landed_address(
                    url, request_url, landed.get(url), crawl_allows if follow_links else leaf_allows
                )
                if final is not None:
                    if final in visited or final in landed_on or final in self.already_indexed:
                        progress(f"       (landed on {final}, which was already read; not indexed again)")
                        continue
                    landed_on.add(final)
                    progress(f"       (landed on {final})")
                    url = final

                if kind == "document":
                    # A file holds no links the crawl follows; it is read
                    # into text and indexed, or skipped with the reason.
                    document = self._document_for(
                        url, handler, fetched, index_exclude_res, seen_documents, progress,
                        served_as=cache.get(request_url, {}).get("name", ""),
                    )
                    if document is not None:
                        yield document
                    continue

                soup = fetched if kind == "html" else markdown_text_to_soup(fetched, url)

                # Enqueue new in-scope links, deduped before download. A
                # leaf's links are not read at all, so a leaf hands nothing
                # to the queue and nothing to another source.
                if follow_links:
                    from_primary = in_primary_scope(url)
                    for link in [*extract_links(soup, url), *listings_for(handler, soup, url)]:
                        link = self._canonical(link)
                        if link in visited or link in queued:
                            continue
                        observe_link(self.handlers, link)
                        if crawl_allows(link):
                            queued.add(link)
                            queue.append((link, True))
                        elif from_primary and leaf_allows(link):
                            queued.add(link)
                            queue.append((link, False))

                # Index exclusion only prevents indexing, not crawling.
                if any(r.search(url) for r in index_exclude_res):
                    continue

                # A page another source already turned into a document is
                # still followed for its links, and never indexed twice.
                if url in self.already_indexed:
                    progress("       (already read; not indexed again)")
                    continue

                extraction = handler.extract(soup, url)
                if extraction is None:
                    continue

                progress(f"       {handler.name}: {extraction.title[:70]}")
                yield Document(
                    url=url,
                    title=extraction.title,
                    content=self._content_to_index(extraction, progress),
                    source_type=handler.source_type,
                    content_type=handler.content_type(url),
                    categories=extraction.categories,
                    summary=extraction.summary,
                    tags=extraction.tags,
                )
        finally:
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)

        progress(f"Crawled {len(visited)} page(s).")

    def _canonical(self, url):
        """
        The one address a page is visited under: what its handler's
        `canonical_url` hook returns, normalised, or the address as
        written for a handler without the hook.
        """
        handler = self.handler_for(url)
        if hasattr(handler, "canonical_url"):
            return fetching.normalise(handler.canonical_url(url))
        return url

    def _document_for(self, url, handler, data, index_exclude_res, seen_documents, progress,
                      served_as=""):
        """
        The document for one fetched file, or None with the reason
        reported: the address is on the index exclude list or was read by
        another source, the same bytes were already indexed under another
        address, the reader refused the file, or it holds no text.

        Args:
            url (str): the file's address in the crawl.
            handler: the site handler that claims the address; its
                source_type is recorded on the document.
            data (bytes): the file as fetched.
            index_exclude_res (list[re.Pattern]): the index exclude list.
            seen_documents (dict): digest to the address a file was
                indexed under, updated here.
            progress (Callable[[str], None]): receives the reason line.
            served_as (str): the file name the server gave in its answer,
                recorded by the fetch; an empty string when it gave none.
        """
        if any(r.search(url) for r in index_exclude_res):
            return None
        if url in self.already_indexed:
            progress("       (already read; not indexed again)")
            return None
        digest = hashlib.sha256(data).hexdigest()
        earlier = seen_documents.get(digest)
        if earlier is not None:
            progress(f"       (the same file as {earlier}; not indexed again)")
            return None
        try:
            read = readers.read_document(data, url)
        except readers.DocumentError as e:
            progress(f"  SKIP {url} -- {e}")
            return None
        text = read.indexed_text
        if not text.strip():
            progress("       (the document holds no text)")
            return None
        seen_documents[digest] = url
        title = readers.document_title(read, readers.name_from_url(url, served_as))
        progress(f"       document: {title[:70]}")
        return Document(
            url=url,
            title=title,
            content=self._document_content(title, text, progress),
            source_type=handler.source_type,
            content_type="text",
        )

    def _document_content(self, title, text, progress):
        """
        The rendered text a reader produced, so the chunker cuts it at
        its headings, or its compact record when it runs past the ceiling
        the index takes whole.
        """
        if len(text) <= prose.MAX_PROSE_CHARS:
            return readers.content_node(text)
        progress(
            f"       indexed as an outline ({len(text)} characters is over the "
            f"{prose.MAX_PROSE_CHARS} the index takes whole)"
        )
        return prose.compact_record(title, text)

    def _content_to_index(self, extraction, progress):
        """
        The content node itself, or its compact record when the page's
        text runs past the ceiling the index takes whole. A site that
        publishes everything on one page, or a rendered report, would
        otherwise become thousands of sections for one address.
        """
        text = extraction.node.get_text("\n\n", strip=True)
        if len(text) <= prose.MAX_PROSE_CHARS:
            return extraction.node
        headings = [
            heading.get_text(" ", strip=True)
            for heading in extraction.node.find_all(["h1", "h2", "h3"])
        ]
        progress(
            f"       indexed as an outline ({len(text)} characters is over the "
            f"{prose.MAX_PROSE_CHARS} the index takes whole)"
        )
        return prose.compact_record(extraction.title, text, headings)

    def gone_pages(self):
        """
        The addresses the server confirmed gone during this crawl, in
        the normalised form the build files pages under.

        Returns:
            tuple[str, ...]: the addresses, or an empty tuple.
        """
        return tuple(sorted(self.gone))

    def _landed_address(self, url, request_url, final_url, allowed):
        """
        The address a page is recorded under when its request landed
        somewhere else inside the crawl, or None to keep its own.

        Only a request for the page's own address counts: a handler that
        rewrote the request, such as to a raw or export host, meant the
        page to be cited where it was linked. The landing address is
        folded by the handlers' canonical rule like any link, and must
        be one this page was allowed to be.

        Args:
            url (str): the page's address in the crawl.
            request_url (str): the address actually requested.
            final_url (str | None): where the request landed, or None.
            allowed (Callable[[str], bool]): the scope rule for this page.

        Returns:
            str | None: the landing address, normalised, or None.
        """
        if not final_url or fetching.normalise(request_url) != url:
            return None
        final = self._canonical(fetching.normalise(final_url))
        if final == url or not allowed(final):
            return None
        return final

    def _redirected_out_of_scope(self, url, handler, request_url, final_url, allowed, progress):
        """
        Whether a page landed somewhere the crawl may not go, and says so
        if it did.

        A redirect that stays in scope is ordinary and passes without
        comment. One that leaves it is skipped, because the body that
        arrived belongs to another site, or to an address the crawl was
        never allowed to ask for, and indexing it under this page's
        address would attribute it to this site. The address a request
        lands on is not one the site handlers were asked about either,
        so a handler's own scope rule is applied to it here, and a
        handler that expects its requests to land elsewhere, such as on
        an export host, says so through its `landing_allowed` hook.

        Args:
            url (str): the page's address in the crawl.
            handler: the site handler that claims the page.
            request_url (str): the address actually requested, which a
                handler may have rewritten, such as a blob page fetched
                from the raw host; landing there is no redirect.
            final_url (str | None): where the request landed, or None
                when the session does not report it.
            allowed (Callable[[str], bool]): whether an address is one
                this page was allowed to be: the crawl's scope rule for a
                page of the crawl, the leaf rule for a leaf.
            progress (Callable[[str], None]): receives the skip line.

        Returns:
            bool: True when the page is to be skipped.
        """
        if not final_url or fetching.normalise(final_url) in (url, fetching.normalise(request_url)):
            return False
        if hasattr(handler, "landing_allowed") and handler.landing_allowed(url, final_url):
            return False
        if allowed(final_url):
            return False
        progress(
            f"  SKIP {url} -- it redirects to {final_url}, which is outside what this "
            "source may crawl, so what arrived is not this site's content"
        )
        return True

    def _seed_redirected_out_of_scope(self, seed, final_url, auto_prefix, origin,
                                      include_res, crawl_exclude_res, progress):
        """
        Whether a seed landed somewhere the crawl is not allowed to go, and
        says so if it did.

        A short link is the usual cause. `https://example.edu/kb` may
        redirect to a portal on another host: the page arrives, but the
        scope was derived from the address that was configured, so every
        link on it is out of scope and the crawl stops after one page. Worse
        than that, links written relative to the page resolve against the
        configured address rather than the one it landed on, so they point
        at addresses that do not exist.

        Nothing about the result would show this. The index would simply be
        almost empty. So the seed is refused and the address to use instead
        is named, rather than crawling on and producing that quietly.

        A redirect that stays in scope is normal and passes without comment:
        http to https, a missing trailing slash, a canonical host.

        Args:
            seed (str): the seed as configured, normalised.
            final_url (str | None): where the request landed, or None when
                the session did not report it.
            auto_prefix (tuple[str, ...]): the derived scope prefixes.
            origin (tuple[str, ...]): the seeds' origins.
            include_res (list[re.Pattern]): the compiled include patterns.
            crawl_exclude_res (list[re.Pattern]): the compiled exclusions.
            progress (Callable[[str], None]): receives the explanation.

        Returns:
            bool: True when this seed must be abandoned.
        """
        if not final_url or fetching.normalise(final_url) == seed:
            return False
        if fetching.in_scope(final_url, auto_prefix, origin, include_res, crawl_exclude_res):
            return False
        progress(
            f"  SKIP {seed} -- it redirects to {final_url}, which is outside what this "
            f"source may crawl. Nothing there could be followed, so the crawl would "
            f"index one page and stop. Use {final_url} as the seed instead, or add an "
            f"include pattern that covers it."
        )
        return True

    def _offered_source(self, progress):
        """
        The source a handler offers for this crawl's seed, ready to run,
        or None when no handler offers one.

        Needs the registry, so it does nothing for a source constructed
        without `configure`. A caller that has already decided how to read
        the seed sets the `promote` option to False, which is how a source
        that falls back to a crawl avoids being handed straight back to
        itself.
        """
        if self.registry is None or not self.options.get("promote", True):
            return None
        for handler in self.handlers:
            offer = handler.offer_source(self.seed_url) if hasattr(handler, "offer_source") else None
            if offer is None:
                continue
            name, options = offer
            progress(f"Seed:         {self.seed_url}")
            progress(f"  the {handler.name} handler reads this address through the {name} source")
            source = self.registry.get_source(name)(options)
            if hasattr(source, "configure"):
                source.configure(self.registry, self.settings)
            return source
        return None
