<!--
This file is part of Extractium™
docs/architecture.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-12
Summary: How the Extractium codebase is put together today, which parts
are finished, and the design decisions that have been settled, each with
the reason and a pointer to where it is specified.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Architecture and Current State

[← Back to README](../README.md)


## Summary

This page describes the code as it stands, not the finished design. It says what each module does and which design decisions are settled, so that nobody builds on a question that has already been answered a different way. Read it before you add to the engine.

The target design is in [the specification](extractium-spec.md) and the order of work is in the [implementation plan](implementation-plan.md). Where this page and the specification disagree, the specification says what is intended and this page says what exists.


## How the pieces fit

Extractium is one Python package with three layers. Source plugins gather documents, one core engine turns them into searchable chunks, and adapter plugins write each output format. The web source, which is the core crawler, asks small site-handler plugins how to read each kind of page it visits. Everything runs offline against flat files: no server, no database, no cloud calls.

The rule that shapes the whole design: **one crawl and one embedding pass per build**. Fetching, chunking, and embedding happen once. Every output format is then a cheap serialization of the same result. An adapter that re-fetched or re-embedded would break the design's main promise.


## What exists today

The engine was extracted from a single-file script, which is kept frozen at [tests/reference/build_kb_index_reference.py](../tests/reference/build_kb_index_reference.py) as the yardstick the port is measured against. Each ported module has tests that pin its behavior to that original.

| Part | File | State |
|---|---|---|
| Settings | `extractium/config.py` | Working. Loads and checks `config.yaml`: global settings, a `sources` list, and an `outputs` list, with per-type checks for the built-in types. See the [configuration reference](configuration.md). |
| Fetch and cache | `extractium/core/fetch.py`, `core/cache.py` | Working. Conditional GET, on-disk page cache, URL scope rules, a truthful User-Agent, a per-origin `robots.txt` policy, and progress through a callback. Core knows no host: the TeamDynamix portal-folder scope lives in the `tdx` handler through the protocol's `scope_prefix` hook. With `respect_robots_txt: false`, a page that answers 401, 403, or 429 to the configured User-Agent is requested once more with a browser's, and both attempts are reported; the setting is the operator's statement that they own the site. |
| Transport | `extractium/core/transport.py` | Working. One function returns the session a build fetches through, for the `transport` setting: an ordinary session, a browser-shaped one, or the default that starts plain and switches a host to the browser handshake the first time it answers a bot-protection challenge. The crawler's own `User-Agent` goes over either. The choice is reported once per host and listed in the build summary. See [reading a site behind bot protection](bot-protection-transport.md). |
| Chunking | `extractium/core/chunk.py` | Working. Parent sections, child windows with their offsets into the parent, stable parent identifiers, `chunk_document` for a `Document` record. No host branches; reading a page is the site handlers' job. |
| Scoring | `extractium/core/embed.py`, `dedup.py`, `bm25.py`, `calibration.py` | Working. `core/build.py` runs them in order. The embedding library is imported only when embedding runs, so nothing that merely reads an index loads it. |
| Crawl loop | `extractium/sources/web.py` | Working. The `web` source: takes the session, the cache metadata, and a progress callback; consults the site handlers per URL; yields `Document` records. Pinned against the reference crawl on the fixtures. |
| Build step | `extractium/core/build.py` | Working. `build_compendium` chunks the documents, embeds the children once, collapses near-duplicates, compacts orphaned parents, builds the BM25 and calibration statistics, and returns one `Compendium`. |
| Carry-forward | `extractium/core/retain.py` | Working. Writes a manifest of every published page's sections beside the cache after each build, never holding local content, and on `rebuild: incremental` rebuilds the pages the last build had and this one did not see, with the identifiers they had, unless the server confirmed them gone or their source left the settings file. Only a web crawl's pages qualify; every other source is authoritative about its own content. |
| Plugin registry | `extractium/core/registry.py` | Working. Resolves sources, site handlers, and adapters from the `plugins/` folder, installed entry points, and built-ins, in that order. The built-in `web`, `local`, `github_api`, `dspace`, and `youtube` sources, the `generic`, `tdx`, `github`, and `youtube` handlers, and the `container`, `llmstxt`, `sqlite`, and `okf` adapters are declared as entry points in `pyproject.toml`. See [plugin architecture](plugin-architecture.md). |
| Data models | `extractium/core/models.py` | Working. `Document`, `Extraction`, `Parent`, `Children`, `Compendium`, and the three plugin protocols, including the three optional site-handler hooks. |
| PHI check | `extractium/core/phi_lint.py` | Working. A table of 26 rules over the HIPAA Safe Harbor identifiers, in two tiers: shapes settled by a check digit fire anywhere, and the rest fire only next to a label word. Writes a JSON report and a plain-text report to the working directory, neither holding the text it matched. The command line runs it between the sources and the build step. |
| Site handlers | `extractium/sources/generic.py`, `tdx.py`, `github.py`, `youtube_site.py` | Working. Each owns its host's selectors, title rule, categories, content types, and default exclude patterns. The TeamDynamix handler also recovers an article title the portal cut short. The GitHub handler additionally keeps a crawl to the accounts the operator named, and offers the API source for a GitHub seed, through the three optional handler hooks. The YouTube handler uses the same hooks for the opposite purpose: it refuses every YouTube address for crawling, because a video's words are in its caption track and not on its page, and offers the video source for a channel, playlist, or watch address given as a seed. Through the `observe_link` hook it also collects the videos linked from crawled pages, which the command line offers to the `youtube` source once every source has run. The TeamDynamix handler supplies the portal-folder scope through `scope_prefix`. |
| GitHub source | `extractium/sources/github_api.py`, `github_client.py`, `github_files.py` | Working, and registered as an entry point. Reads an organization, a user, or one repository through the REST API: complete tree inventory with subtree walking, documentation, project manifests, and source files, file bodies cached by blob SHA, rate-limit headers obeyed. Three ways of reading GitHub are tried in order, and every repository's tier is reported, alongside one map per repository and one per account. See [GitHub repository indexing](github-repository-indexing.md). |
| Code analysis | `extractium/code/` | Working. Reads a repository's source files with Tree-sitter, driven by one query file per language, and falls back to Universal Ctags and then to a file-level record. Produces a record per file and a record per definition -- signature, documentation, imports, calls labelled by confidence, reverse edges, and a link to the exact lines -- and never a source body. The parser set is the optional `extractium[code]` install. Nothing a repository holds is executed, and a notebook's saved outputs are never read. See [GitHub repository indexing](github-repository-indexing.md). |
| Repository source | `extractium/sources/dspace.py`, `dspace_client.py` | Working, and registered as an entry point. Reads named collections of a DSpace 7 repository through its own interface: one document per deposit, carrying the abstract, the authors, the subjects, the three kinds of address a deposit holds, and the text the repository extracted from the deposited files. A collection is confirmed before it is searched, and rebuilds read only what the repository says changed. See [Indexing a DSpace repository](dspace-repository-indexing.md). |
| Video source | `extractium/sources/youtube.py`, `youtube_client.py`, `youtube_pages.py` | Working, and registered as an entry point. Indexes what is said in a video: each stretch of a caption track becomes one section addressed at the moment it begins, so a citation opens the video at the quoted words. A channel may be named by handle, by address, or by id, and anything but an id is resolved once against the channel's own page and stored. Listings come from the Data API when a key is set and from YouTube's own pages when none is; the page path stops where `robots.txt` does, which is the newest hundred of a listing, and says so. A channel's uploads and its playlists are both read, and a video in a playlist that another channel published is left out. Everything read is stored under `cache_dir` and meant to be committed, because YouTube refuses caption requests from cloud-provider addresses and a scheduled build can only reuse what a person fetched. The caption library is the optional `extractium[youtube]` install. |
| Adapters | `extractium/adapters/container.py`, `llmstxt.py`, `sqlite_out.py`, `okf.py` | Working, and registered as entry points. The container writer produces the version 4 file, compressed through gzip when the output asks; the Open Knowledge Format writer keeps its folder in step with the compendium, removing only files this tool wrote; the llms.txt writer produces `llms.txt` and `llms-full.txt`; the SQLite writer produces `compendium.sqlite`, the same content in tables a SQL consumer can query; the Open Knowledge Format writer produces the `okf/` folder, one Markdown file per page with the front matter that format defines. `extractium/adapters/base.py` holds the output folder helper, the shared text helpers the Markdown writers share, and the local-content guardrail every adapter goes through. |
| Local source | `extractium/sources/local.py` | Working, and registered as an entry point. Reads Markdown, plain text, and HTML from a folder; marks every document `local`; records a path relative to that folder as the URL; refuses a file whose real location is outside it. |
| Bundle source | `extractium/sources/okf.py` | Working, and registered as an entry point. Reads an Open Knowledge Format bundle, from this tool or any other, as one document per concept file addressed at the resource its front matter names, with the concept's type read back as the content type. A `local:` resource stays local, a resource that is not a web address is refused, and the folder guard is the one the local source uses. |
| Clients | `extractium/search.py`, `clients/js/extractium-client.js` | Working. Each reads the version 4 container, refuses a file that fails any reader check, and runs the same hybrid search: cosine similarity, BM25, reciprocal rank fusion, a corpus-relative relevance cutoff, diversity selection with a per-section cap, and resolution of a matched window to its whole section. The caller supplies the query embedder. A committed golden container and query vector hold both to the same ranking. |
| Local MCP servers | `examples/mcp/local-python/server.py`, `examples/mcp/local-node/server.js` | Working. One file per runtime, over the client library beside it. Each speaks JSON-RPC on standard input and output, answers both eras of the Model Context Protocol, and exposes one tool, `search_kb`, that returns whole sections with their addresses. The index address comes from the environment, must be HTTPS away from the loopback address, and is cached under a digest of itself. Examples, not part of the installed package. See [how to connect an MCP client](how-to/connect-an-mcp-client.md). |
| Shared MCP core | `examples/mcp/shared/` | Working. The tool definition and answer shape, the protocol core that answers both eras, and the Streamable HTTP binding, written once and used by the Node local server and both hosted servers. The HTTP binding accepts one POST per message, answers one JSON object, keeps no session, caps the body, checks the mirrored headers against the body, and applies an optional bearer token and an optional origin allowlist. |
| Hosted MCP servers | `examples/mcp/valtown/`, `examples/mcp/cloudflare/` | Working. The Val Town example holds the container in memory, keeps a copy in the val's blob store, and answers with BM25 alone or, with an HTTP embedding service configured, with the clients' hybrid search. The Cloudflare example reads a build's SQLite output from D1, loaded through `export_d1.py`, ranks by BM25 inside the database with every term bound, and re-ranks those candidates through Workers AI when that binding is on. Each was run against the golden compendium: the val on the live platform, pushed by `push.py` over the REST API and answering from a published copy of the compendium, and the Worker under `wrangler dev` against a local D1. See [how to deploy a remote MCP server](how-to/deploy-a-remote-mcp-server.md). |
| Hosted assistant prompts | `examples/wrappers/` | Working. Two plain-text system prompts: one for a platform that can browse but not call tools, pointing at `llms.txt`, and one for a platform connected to a hosted search server. |
| Operations | `run.sh`, `run.bat`, `requirements-lock.txt`, `.github/workflows/build-compendium.yml`, `examples/data-repo/` | Working. One command builds locally on either platform from a hash-checked lock file; the workflow runs weekly and on a button press, reuses the crawl cache between runs, and publishes through the official GitHub Pages actions only. The data-repository template is what an organization copies for its own content. |
| Command line | `extractium/cli.py` | Working. `extractium build --config config.yaml`, with `--out-dir`, `--max-pages`, and `--float32-vecs`; progress on standard error, the summary on standard output, and a distinct exit code for a bad configuration, an empty crawl, and an unwritable output. |

Every component above is built.

The test suite passes: 1,786 Python tests as of 2026-09-12, with one skipped, plus 39 Node tests for the JavaScript client (`node --test clients/js`), 24 for the local Node MCP server, 19 for the shared MCP core, 13 for the Val Town example, and 14 for the Cloudflare example (`node --test examples/mcp/<folder>`).


## Settled design decisions

Each decision below was open at some point and is now fixed. Each one is cheap to follow now and expensive to reverse once code depends on it. The specification section given is the authority; this list is the short version.


### 1. Building an index and writing one are separate steps

The original script's `build_index()` embeds and scores the chunks, then writes the container in the same function.

**Decision:** core gains one build step that embeds the children, drops near-duplicates, remaps parents, builds the BM25 postings, computes the calibration statistics, and returns one `Compendium` record. Adapters only turn that record into files.

**Why:** several output formats need the same scored data. If scoring lived inside the container writer, every other adapter would duplicate it or re-run the model, and the one-embedding-pass rule would be lost. The split also makes scoring testable without writing a file.

Specification: section 2, key invariants.


### 2. The crawl loop takes its session and reports through a callback

The original `crawl()` builds its own `requests.Session()` and reports progress with `print()`.

**Decision:** the loop takes the session as a parameter and reports progress through a callback the caller supplies. The global crawl settings (page ceiling, delay, User-Agent, `robots.txt`) travel in a small `CrawlSettings` record, separate from the source's own options, because they apply to every source in a build.

**Why:** a function that builds its own session can only be tested by monkeypatching the `requests` module, which reaches past the code under test. Progress has three audiences with different needs: a person watching a double-click run, a CI log, and a library caller who wants silence. A callback serves all three.

Specification: section 2.1, the source protocol.


### 3. Chunk identifiers are stable, and they include an ordinal

The current code has no identifiers. It links a child to its parent by position in a list, which shifts whenever a section disappears on re-crawl.

**Decision:** a parent's id is a hash of its URL, its heading, and its ordinal among parents on the same page with the same heading. A child's id is derived from its parent's id and its own ordinal. Ids are added with the crawl port, not after it.

**Why:** the ordinal is needed because a long section is cut into several parents that share a heading; without it they would share an id. Stable ids are what saved answers, cached enrichment, and future delta builds use to match old work to new content.

This decision deliberately breaks equality with the frozen reference script for the id fields only. The characterization tests for chunk building compare every field the reference has and treat `id` and the per-parent metadata (`source_type`, `content_type`, `categories`, `local`) as additions. The reference's coarse `kind` facet (`code`, `kb`, `page`) is replaced by `source_type` and `content_type`.

Specification: section 3.3.


### 4. One web crawler, pluggable site handlers, three plugin kinds

The v0.1 specification listed `web`, `tdx`, and `github` as three source plugins. The code is one crawler with host-specific branches, and the crawl is one graph: a knowledge-base article links to a repository README and the same queue must follow it.

**Decision:** the generic crawler is core. TeamDynamix and GitHub handling become site handlers: plugins the crawler consults per URL, shipped enabled, switchable off in configuration. Sources, site handlers, and adapters are the three plugin kinds, all resolved by one registry in the order local `plugins/` folder, installed entry points, built-ins.

**Why:** the split keeps one loop and one link graph while moving every host-specific line out of core, which is what makes the tool usable by an organization that has no TeamDynamix portal and no GitHub.

Specification: sections 2.1 to 2.3.


### 5. The configuration file lists sources and outputs

The first loader accepted one `seed_url` and a handful of crawl settings.

**Decision:** the file is a `sources:` list and an `outputs:` list plus global settings, changed before any code beyond the loader depended on the old shape.

**Why:** a second source type or a second output cannot be expressed in the flat form. Changing it now costs one module and its tests; changing it later costs every caller.

Specification: section 12.


### 6. The container never carried version 2's waste

Field Station AI's version 2 file duplicates every child's text, heading, URL, and facets. Measured on the real index, that is a third of a 10 MB file, and no search step reads it.

**Decision:** Extractium started at version 3 and writes version 4 today: children are column arrays of parent index and character offsets, and everything else is read from the parent. Field Station AI keeps its own version 2 file and is unaffected; moving it to the Extractium client is a later task in that repository.

**Why:** there is no compatibility obligation to carry the waste, and doing it now avoids a migration later.

Version 4 added `source_label` to every parent, which is what lets a client name the collection an answer came from. See the [container format](container-format.md) page for the versioning rule and why adding that field justified a new version.

Specification: section 4 and the [container format](container-format.md) page.


### 7. Local content stays out of every output unless the output opts in

The v0.1 rule excluded local content from web-facing formats but let the container and SQLite include it. The container is exactly the file that gets published.

**Decision:** every adapter drops local parents by default. An output opts in with `include_local: true`, and the command line names each output that contains local content.

**Why:** publishing is the normal use of every output. The safe default is the one that cannot leak by omission.

Specification: section 7.


### 8. The crawler identifies itself and honors `robots.txt`

The reference script sends a browser User-Agent and never reads `robots.txt`.

**Decision:** the default User-Agent names the tool and its repository; `robots.txt` is honored unless switched off; both are settings. Whether the TeamDynamix portal serves article HTML to the truthful agent is checked before the crawler ships.

**Why:** a tool distributed to other organizations should not spoof a browser by default. The check exists because some portals do serve different pages to non-browser agents, and the answer belongs in the documentation, not in a surprise.

The check was made on 2026-09-04: the portal serves full article HTML to the truthful User-Agent, so no override is needed. Its `robots.txt` answers 406 to a request that accepts only HTML, so the robots request sends a plain-text Accept header. When a site's `robots.txt` cannot be read (a 5xx answer or a network failure), every URL on that site is skipped and the reason is reported; a 404 means no rules. Failing closed is deliberate.

A second finding, made on 2026-09-10, separates the identity from the connection. Three of the Depression Center's own sites challenge any client whose TLS handshake does not look like a browser's, whatever name it gives. The crawler therefore opens its connection the way a browser does when, and only when, a site has answered a challenge, and keeps naming itself Extractium over that connection. The name is the honesty; the handshake is plumbing. `robots.txt` is unchanged by this: it is read first and obeyed, and a site that refuses the crawler there stays refused.

Specification: section 6.


### 9. The parsers and the caption library are optional installs

**Decision:** the Tree-sitter grammars are the `extractium[code]` extra and the caption library is the `extractium[youtube]` extra. Neither is a runtime dependency. A build without the parsers still records every source file by name, language, and length; a build without the caption library still reads transcripts a person already stored.

**Why:** most builds index documentation and no code or video at all, and the parser set is fourteen packages with native wheels. Making them optional keeps the default install small and keeps a machine that cannot install them able to build everything else.

Specification: section 5, the `youtube` and code-structure rows.


### 10. The YouTube store is committed content, not a cache

**Decision:** captions and playlist listings are written under `cache_dir/youtube/`, nothing in that folder is revalidated, and a data repository commits it. A build that reads YouTube names a visible folder as its `cache_dir`.

**Why:** YouTube refuses caption requests from cloud-provider addresses, so a scheduled build cannot fetch a transcript. It can only reuse what a person fetched on their own machine. Treating the store as a convenience that may be deleted would make every scheduled build lose its videos.

Specification: sections 5, 8, and 11.


### 11. One page is indexed once, whichever source reached it first

**Decision:** pages are compared by their normalized address across every source in a build. The first source to produce a page keeps it, later sources are told they were too late, and the build reports how many pages that happened to.

**Why:** two sources often overlap without meaning to: a website and a section of it, or a portal and a short link into one of its articles. Indexing the page twice would double its weight in every search and list it twice in `llms.txt`. A section of a site that is already crawled belongs to that crawl as a second `seed_urls` entry, not to a source of its own.

Specification: section 3.1.


### 12. A video is one document per stretch of its captions

**Decision:** consecutive caption lines are joined into stretches of roughly a thousand characters, and each stretch is one document addressed at the moment it begins. The outputs that list pages group the stretches back into one video.

**Why:** a caption track arrives one phrase per line, far too small to answer a question with, and a whole talk is too large to cite. A stretch is the size of a section elsewhere in the index, and addressing it at its start time is what lets a citation open the video at the words it quoted.

Specification: section 5, the `youtube` row.


### 13. Bot protection is answered in the handshake, not in the name

**Decision:** the `transport` setting defaults to `auto`: an ordinary request first, and one retry over a browser-shaped TLS handshake when a host answers a bot-protection challenge, keeping that choice for the host. The crawler's own User-Agent is sent over either connection, `robots.txt` is read first and obeyed as before, and the choice is reported once per host and in the build summary.

**Why:** the three Depression Center sites that challenged the crawler were measured to read the TLS handshake and not the User-Agent, and the center cannot change the rule. Changing the name would have been dishonest and would not have worked. Changing the handshake is plumbing, and the name stays truthful.

Specification: section 6, and [reading a site behind bot protection](bot-protection-transport.md).


### 14. A linked video is read only when a named channel published it

**Decision:** a video linked from a page another source crawled reaches the `youtube` source through the crawl's `observe_link` hook and the source's `read_found_links` method, and is read only when its publisher is known and is a channel the source names. A source naming no channel reads no linked video, an unknown publisher keeps a video out, and `only_channel_videos` does not relax the rule.

**Why:** one link on one page is not the operator's decision to index another organization's words. The playlist rule already guards what the operator chose to read; a link found by chance gets the stricter rule, so a build cannot grow past what its settings file names.

Specification: section 5, the `youtube` row.


### 15. A full rebuild is the default, and incremental keeps nothing confirmed gone

**Decision:** the `rebuild` setting defaults to `full`, which publishes exactly what the build read. `incremental` carries forward a web page the last build published and this one did not see, unless the server answered 404 or 410 for it or its source left the settings file. No other source's pages are carried forward, and there is no append-only mode.

**Why:** two failures pull in opposite directions. A site down for the hour the weekly build runs should not empty a quarter of the published index, which argues for keeping unseen pages. A page taken down on purpose, which for a health research center can mean a page that should never have been up, must leave the published index on the next build, which argues for publishing what was read. Incremental by default would get the second case wrong in a way nobody notices, so full is the default and incremental keeps a page only while nothing has confirmed it gone. An append-only mode would leave a changed page wrong on purpose, which git history on a data repository already does better.

Specification: section 11.


## Conclusion

A build runs end to end, and what it writes can be read back. The settings layer, the registry, and the data models are in place. The web source crawls through the site handlers to produce documents, one build step turns them into a scored compendium, and the adapters write it in four formats from the command line.

Five source types feed that build. Websites are crawled, with a browser-shaped connection used only where a site challenges the crawler and the crawler still naming itself. GitHub repositories are read through the API, with their code analyzed into records a search can find a definition in. A DSpace repository's deposits are read through its own interface. A channel's videos are indexed from their captions, each stretch citable at the moment it was said, and a video linked from a crawled page is read when a named channel published it. A folder on the operator's own machine can be indexed, and every output drops that content unless it opted in. A bundle another build wrote can be read back and merged.

Every build checks what it read for likely protected health information and writes two reports for a person to review. One command, locally or on a weekly schedule, does the whole thing and publishes it.

The result is searched the same way from Python and JavaScript. An assistant on the operator's own machine can search it through either of two local MCP servers, an assistant anywhere can search it through a server hosted on Val Town or Cloudflare, and a platform that only browses can be pointed at the static files by a system prompt.

Every phase of the [implementation plan](implementation-plan.md) is built. The GitHub and code-analysis work is designed in detail in [GitHub repository indexing](github-repository-indexing.md), and the plugin kinds a contributor can add are described in [plugin architecture](plugin-architecture.md).


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Extractium™ specification](extractium-spec.md) — the intended design, data model, and plugin protocols.
* [Implementation plan](implementation-plan.md) — the phased order of work.
* [Container format](container-format.md) — the flagship output, byte by byte.
* [GitHub repository indexing](github-repository-indexing.md) — the design for the GitHub API source and the code analysis on top of it.
* [Data flow](data-flow.md) — what happens to content between the site and the output folder.
* [Running a build](usage.md) — the command line, its options, and its exit codes.
* [Configuration reference](configuration.md) — every setting in `config.yaml` as it exists now.
* [Plugin architecture](plugin-architecture.md) — the three plugin kinds, the registry, and a working example of each.
* [tests/reference/build_kb_index_reference.py](../tests/reference/build_kb_index_reference.py) — the frozen original the port is measured against.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
