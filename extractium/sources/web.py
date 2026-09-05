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
    """

    max_pages: int = DEFAULT_MAX_PAGES
    delay_seconds: float = DEFAULT_DELAY_SECONDS
    user_agent: str = fetching.DEFAULT_USER_AGENT
    respect_robots_txt: bool = True


### Site Handler Selection ###

def resolve_site_handlers(registry, names=None):
    """
    Instantiates the site handlers a web source entry asks for.

    Args:
        registry (extractium.core.registry.Registry): where handler
            classes are looked up.
        names (Sequence[str] | None): the entry's `site_handlers` option.
            None means every registered handler; an empty sequence means
            the generic fallback only.

    Returns:
        tuple: handler instances in the order given (or, for None, in
        registry name order), with the generic handler last.

    Raises:
        extractium.core.registry.RegistryError: if a name is unknown.
    """
    if names is None:
        names = registry.site_handler_names()
    handlers = [registry.get_site_handler(name)() for name in names]
    return order_site_handlers(handlers)


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
        site_handlers (Iterable): handler instances, consulted per URL in
            this order. The generic handler is appended when missing and
            always consulted last.
        settings (CrawlSettings): the global crawl settings.
    """

    name = "web"

    def __init__(self, options, site_handlers=(), settings=CrawlSettings()):
        self.seed_url = options["seed_url"]
        self.handlers = order_site_handlers(site_handlers)
        self.settings = settings
        self.include_patterns = tuple(options.get("include_patterns") or ())
        self.crawl_exclude_patterns = self._patterns(options, "crawl_exclude_patterns", "crawl")
        self.index_exclude_patterns = self._patterns(options, "index_exclude_patterns", "index")

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

        Yields:
            extractium.core.models.Document: one per page with content.
        """
        settings = self.settings
        auto_prefix = fetching.derive_auto_prefix(self.seed_url)
        origin = fetching.get_origin(self.seed_url)
        include_res = fetching.compile_patterns(self.include_patterns)
        crawl_exclude_res = fetching.compile_patterns(self.crawl_exclude_patterns)
        index_exclude_res = fetching.compile_patterns(self.index_exclude_patterns)
        robots = fetching.RobotsPolicy(
            session, settings.user_agent, enabled=settings.respect_robots_txt, progress=progress
        )

        progress(f"Seed:         {self.seed_url}")
        progress(f"Auto prefix:  {auto_prefix}")
        progress(f"Include pats: {list(self.include_patterns) or '(auto -- prefix only)'}")
        progress(f"Site handlers: {[h.name for h in self.handlers]}")

        seed_norm = fetching.normalise(self.seed_url)
        visited = set()
        queued = {seed_norm}   # dedup before download
        queue = deque([seed_norm])

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

            expect_html = handler.expects_html(url)
            fetched = fetching.fetch(
                session, request_url, cache,
                expect_html=expect_html, user_agent=settings.user_agent, progress=progress,
            )
            if fetched is None:
                continue
            soup = fetched if expect_html else markdown_text_to_soup(fetched, url)

            # Enqueue new in-scope links, deduped before download.
            for link in extract_links(soup, url):
                if link not in visited and link not in queued:
                    if fetching.in_scope(link, auto_prefix, origin, include_res, crawl_exclude_res):
                        queued.add(link)
                        queue.append(link)

            # Index exclusion only prevents indexing, not crawling.
            if any(r.search(url) for r in index_exclude_res):
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

    def _pause(self):
        """Waits delay_seconds between requests, so the crawl stays polite to the site."""
        if self.settings.delay_seconds > 0:
            time.sleep(self.settings.delay_seconds)
