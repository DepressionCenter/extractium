"""
Summary: The web-crawl source, the one crawler in Extractium: a
queue-driven crawl from a seed URL, kept in scope by the same-origin or
prefix rules of extractium.core.fetch and by the operator's include and
exclude patterns. Host-specific reading of pages is delegated to
site-handler plugins (generic, tdx, github), consulted per URL with
generic always last, so this module never branches on a host name. See
docs/extractium-spec.md sections 2.1, 5, and 6.

This file is part of Extractium™
extractium/sources/web.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-09
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
__date__ = "2026-09-09"

import time
from collections import deque
from dataclasses import dataclass

from extractium.core import fetch as fetching
from extractium.core.chunk import extract_links, markdown_text_to_soup
from extractium.core.models import Document
from extractium.sources.generic import GenericHandler

### Constants ###

# The handler every crawl ends with; it matches every URL.
FALLBACK_HANDLER_NAME = GenericHandler.name

# Safety ceiling on pages visited per crawl when the caller gives none;
# the same value the configuration file defaults to.
DEFAULT_MAX_PAGES = 10000

# Pause between requests when the caller gives none, in seconds.
DEFAULT_DELAY_SECONDS = 0.5


### Crawl Settings ###

@dataclass(frozen=True)
class CrawlSettings:
    """
    The global settings a crawl needs, separate from the source's own
    options because they apply to every source in a build.

    Attributes:
        max_pages (int): the most pages one crawl may visit; 1 or more.
        delay_seconds (float): pause after each page, in seconds; 0 for none.
        user_agent (str): how the crawler introduces itself.
        respect_robots_txt (bool): whether robots.txt rules are honored.
        github_owners (tuple[str, ...]): the GitHub accounts this build
            may read. Empty means the build reads only the accounts its
            own sources named. The GitHub site handler enforces this; no
            other handler looks at it.
    """

    max_pages: int = DEFAULT_MAX_PAGES
    delay_seconds: float = DEFAULT_DELAY_SECONDS
    user_agent: str = fetching.DEFAULT_USER_AGENT
    respect_robots_txt: bool = True
    github_owners: tuple = ()

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


def default_exclude_patterns(handlers, kind):
    """
    The exclude list a crawl uses when the operator wrote none: the
    host-independent asset patterns plus what each enabled handler adds.

    Args:
        handlers (Iterable): the enabled handler instances.
        kind (str): "crawl" or "index".

    Returns:
        tuple[str, ...]: regular expression strings, each once, asset
        patterns first.
    """
    attribute = f"default_{kind}_exclude_patterns"
    patterns = list(fetching.ASSET_EXCLUDE_PATTERNS)
    for handler in handlers:
        for pattern in getattr(handler, attribute):
            if pattern not in patterns:
                patterns.append(pattern)
    return tuple(patterns)


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
            configuration file: seed_url, include_patterns,
            crawl_exclude_patterns, index_exclude_patterns (None for
            either exclude list means "asset patterns plus the enabled
            handlers' defaults"), and site_handlers (unused here; the
            caller resolves names to the handlers argument).

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
        self.already_indexed = set(options.get("already_indexed") or ())
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
        self.crawl_exclude_patterns = self._patterns(self.options, "crawl_exclude_patterns", "crawl")
        self.index_exclude_patterns = self._patterns(self.options, "index_exclude_patterns", "index")

    def _patterns(self, options, key, kind):
        """The option's own list, or the handler-derived default when the option is None."""
        value = options.get(key)
        if value is None:
            return default_exclude_patterns(self.handlers, kind)
        return tuple(value)

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
        auto_prefix = tuple(fetching.derive_auto_prefix(seed) for seed in self.seed_urls)
        origin = tuple(fetching.get_origin(seed) for seed in self.seed_urls)
        include_res = fetching.compile_patterns(self.include_patterns)
        crawl_exclude_res = fetching.compile_patterns(self.crawl_exclude_patterns)
        index_exclude_res = fetching.compile_patterns(self.index_exclude_patterns)
        robots = fetching.RobotsPolicy(
            session, settings.user_agent, enabled=settings.respect_robots_txt, progress=progress
        )

        for seed in self.seed_urls:
            progress(f"Seed:         {seed}")
        progress(f"Auto prefix:  {', '.join(dict.fromkeys(auto_prefix))}")
        progress(f"Include pats: {list(self.include_patterns) or '(auto -- prefix only)'}")
        progress(f"Site handlers: {[h.name for h in self.handlers]}")

        seed_norms = [fetching.normalise(seed) for seed in self.seed_urls]
        visited = set()
        queued = set(seed_norms)   # dedup before download
        queue = deque(seed_norms)
        landed = {}

        while queue and len(visited) < settings.max_pages:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            progress(f"[{len(visited):4d}] {url}")

            handler = self.handler_for(url)
            request_url = handler.fetch_url(url)
            if not robots.allows(request_url):
                progress(f"  SKIP {url} -- disallowed by robots.txt")
                continue

            # Where a seed actually lands decides whether the crawl can go
            # anywhere at all, so it is worth one callback to find out.
            is_seed = url in seed_norms
            expect_html = handler.expects_html(url)
            fetched = fetching.fetch(
                session, request_url, cache,
                expect_html=expect_html, user_agent=settings.user_agent, progress=progress,
                fallback_user_agent=settings.blocked_retry_user_agent,
                note_final_url=(lambda final, key=url: landed.__setitem__(key, final)) if is_seed else None,
            )
            if fetched is None:
                continue

            if is_seed and self._seed_redirected_out_of_scope(
                url, landed.get(url), auto_prefix, origin, include_res, crawl_exclude_res, progress
            ):
                continue

            soup = fetched if expect_html else markdown_text_to_soup(fetched, url)

            # Enqueue new in-scope links, deduped before download.
            for link in extract_links(soup, url):
                if link not in visited and link not in queued:
                    in_scope = fetching.in_scope(
                        link, auto_prefix, origin, include_res, crawl_exclude_res
                    )
                    if in_scope and handlers_allow(self.handlers, link):
                        queued.add(link)
                        queue.append(link)

            # Index exclusion only prevents indexing, not crawling.
            if any(r.search(url) for r in index_exclude_res):
                self._pause()
                continue

            # A page another source already turned into a document is
            # still followed for its links, and never indexed twice.
            if url in self.already_indexed:
                progress("       (already read; not indexed again)")
                self._pause()
                continue

            extraction = handler.extract(soup, url)
            if extraction is None:
                continue

            progress(f"       {handler.name}: {extraction.title[:70]}")
            yield Document(
                url=url,
                title=extraction.title,
                content=extraction.node,
                source_type=handler.source_type,
                content_type=handler.content_type(url),
                categories=extraction.categories,
            )
            self._pause()

        progress(f"Crawled {len(visited)} page(s).")

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

    def _pause(self):
        """Waits delay_seconds between requests, so the crawl stays polite to the site."""
        if self.settings.delay_seconds > 0:
            time.sleep(self.settings.delay_seconds)
