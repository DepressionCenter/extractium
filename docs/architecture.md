<!--
This file is part of Extractium™
docs/architecture.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-11
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

This page describes the code as it stands, not the finished design. It says which modules work, which are empty placeholders, and which design decisions are settled so that nobody builds on a question that has already been answered a different way. Read it before you add to the engine.

The target design is in [the specification](extractium-spec.md) and the order of work is in the [implementation plan](implementation-plan.md). Where this page and the specification disagree, the specification says what is intended and this page says what exists.


## How the pieces fit

Extractium is one Python package with three layers. Source plugins gather documents, one core engine turns them into searchable chunks, and adapter plugins write each output format. The web source, which is the core crawler, asks small site-handler plugins how to read each kind of page it visits. Everything runs offline against flat files: no server, no database, no cloud calls.

The rule that shapes the whole design: **one crawl and one embedding pass per build**. Fetching, chunking, and embedding happen once. Every output format is then a cheap serialization of the same result. An adapter that re-fetched or re-embedded would break the design's main promise.


## What exists today

The engine was extracted from a single-file script, which is kept frozen at [tests/reference/build_kb_index_reference.py](../tests/reference/build_kb_index_reference.py) as the yardstick the port is measured against. Each ported module has tests that pin its behavior to that original.

| Part | File | State |
|---|---|---|
| Settings | `extractium/config.py` | Working. Loads and checks `config.yaml`: global settings, a `sources` list, and an `outputs` list, with per-type checks for the built-in types. See the [configuration reference](configuration.md). |
| Fetch and cache | `extractium/core/fetch.py`, `core/cache.py` | Working. Conditional GET, on-disk page cache, URL scope rules, a truthful User-Agent, a per-origin `robots.txt` policy, and progress through a callback. One host-specific rule remains: the TeamDynamix portal-folder scope prefix in `derive_auto_prefix`. The handler protocol now has an optional scope hook, which the GitHub account rule uses; moving the TeamDynamix rule onto it is possible and has not been done. |
| Chunking | `extractium/core/chunk.py` | Working. Parent sections, child windows with their offsets into the parent, stable parent identifiers, `chunk_document` for a `Document` record. No host branches; reading a page is the site handlers' job. |
| Scoring | `extractium/core/embed.py`, `dedup.py`, `bm25.py`, `calibration.py` | Working. `core/build.py` runs them in order. The embedding library is imported only when embedding runs, so nothing that merely reads an index loads it. |
| Crawl loop | `extractium/sources/web.py` | Working. The `web` source: takes the session, the cache metadata, and a progress callback; consults the site handlers per URL; yields `Document` records. Pinned against the reference crawl on the fixtures. |
| Build step | `extractium/core/build.py` | Working. `build_compendium` chunks the documents, embeds the children once, collapses near-duplicates, compacts orphaned parents, builds the BM25 and calibration statistics, and returns one `Compendium`. |
| Plugin registry | `extractium/core/registry.py` | Working. Resolves sources, site handlers, and adapters from the `plugins/` folder, installed entry points, and built-ins, in that order. The built-in `web`, `local`, `github_api`, and `dspace` sources, the `generic`, `tdx`, and `github` handlers, and the `container`, `llmstxt`, and `sqlite` adapters are declared as entry points in `pyproject.toml`. |
| Data models | `extractium/core/models.py` | Working. `Document`, `Extraction`, `Parent`, `Children`, `Compendium`, and the three plugin protocols, including the three optional site-handler hooks. |
| PHI check | `extractium/core/phi_lint.py` | Working. A table of 26 rules over the HIPAA Safe Harbor identifiers, in two tiers: shapes settled by a check digit fire anywhere, and the rest fire only next to a label word. Writes a JSON report and a plain-text report to the working directory, neither holding the text it matched. The command line runs it between the sources and the build step. |
| Site handlers | `extractium/sources/generic.py`, `tdx.py`, `github.py` | Working. Each owns its host's selectors, title rule, categories, content types, and default exclude patterns. The TeamDynamix handler also recovers an article title the portal cut short. The GitHub handler additionally keeps a crawl to the accounts the operator named, and offers the API source for a GitHub seed, through the three optional handler hooks. |
| GitHub source | `extractium/sources/github_api.py`, `github_client.py`, `github_files.py` | Working, and registered as an entry point. Reads an organization, a user, or one repository through the REST API: complete tree inventory with subtree walking, documentation, project manifests, and source files, file bodies cached by blob SHA, rate-limit headers obeyed. Three ways of reading GitHub are tried in order, and every repository's tier is reported, alongside one map per repository and one per account. See [GitHub repository indexing](github-repository-indexing.md). |
| Code analysis | `extractium/code/` | Working. Reads a repository's source files with Tree-sitter, driven by one query file per language, and falls back to Universal Ctags and then to a file-level record. Produces a record per file and a record per definition -- signature, documentation, imports, calls labelled by confidence, reverse edges, and a link to the exact lines -- and never a source body. The parser set is the optional `extractium[code]` install. Nothing a repository holds is executed, and a notebook's saved outputs are never read. See [GitHub repository indexing](github-repository-indexing.md). |
| Repository source | `extractium/sources/dspace.py`, `dspace_client.py` | Working, and registered as an entry point. Reads named collections of a DSpace 7 repository through its own interface: one document per deposit, carrying the abstract, the authors, the subjects, the three kinds of address a deposit holds, and the text the repository extracted from the deposited files. A collection is confirmed before it is searched, and rebuilds read only what the repository says changed. See [Indexing a DSpace repository](dspace-repository-indexing.md). |
| Video source | `extractium/sources/youtube.py`, `youtube_client.py` | Working, and registered as an entry point. Indexes what is said in a video: each stretch of a caption track becomes one section addressed at the moment it begins, so a citation opens the video at the quoted words. Channels and playlists are listed through the YouTube Data API with a key from the environment; naming videos individually needs no key. Everything read is stored under `cache_dir` and meant to be committed, because YouTube refuses caption requests from cloud-provider addresses and a scheduled build can only reuse what a person fetched. The caption library is the optional `extractium[youtube]` install; a build reading only stored transcripts does without it. |
| Adapters | `extractium/adapters/container.py`, `llmstxt.py`, `sqlite_out.py`, `okf.py` | Working, and registered as entry points. The container writer produces the version 4 file; the llms.txt writer produces `llms.txt` and `llms-full.txt`; the SQLite writer produces `compendium.sqlite`, the same content in tables a SQL consumer can query; the Open Knowledge Format writer produces the `okf/` folder, one Markdown file per page with the front matter that format defines. `extractium/adapters/base.py` holds the output folder helper, the shared text helpers the Markdown writers share, and the local-content guardrail every adapter goes through. |
| Local source | `extractium/sources/local.py` | Working, and registered as an entry point. Reads Markdown, plain text, and HTML from a folder; marks every document `local`; records a path relative to that folder as the URL; refuses a file whose real location is outside it. |
| Clients | `extractium/search.py`, `clients/js/extractium-client.js` | Working. Each reads the version 4 container, refuses a file that fails any reader check, and runs the same hybrid search: cosine similarity, BM25, reciprocal rank fusion, a corpus-relative relevance cutoff, diversity selection with a per-section cap, and resolution of a matched window to its whole section. The caller supplies the query embedder. A committed golden container and query vector hold both to the same ranking. |
| Local MCP servers | `examples/mcp/local-python/server.py`, `examples/mcp/local-node/server.js` | Working. One file per runtime, over the client library beside it. Each speaks JSON-RPC on standard input and output, answers both eras of the Model Context Protocol, and exposes one tool, `search_kb`, that returns whole sections with their addresses. The index address comes from the environment, must be HTTPS away from the loopback address, and is cached under a digest of itself. Examples, not part of the installed package. See [how to connect an MCP client](how-to/connect-an-mcp-client.md). |
| Operations | `run.sh`, `run.bat`, `requirements-lock.txt`, `.github/workflows/build-compendium.yml`, `examples/data-repo/` | Working. One command builds locally on either platform from a hash-checked lock file; the workflow runs weekly and on a button press, reuses the crawl cache between runs, and publishes through the official GitHub Pages actions only. The data-repository template is what an organization copies for its own content. |
| Command line | `extractium/cli.py` | Working. `extractium build --config config.yaml`, with `--out-dir`, `--max-pages`, and `--float32-vecs`; progress on standard error, the summary on standard output, and a distinct exit code for a bad configuration, an empty crawl, and an unwritable output. |

Every component above is built. No placeholder files remain in the package.

The test suite passes: 1,303 Python tests as of 2026-09-11, plus 36 Node tests for the JavaScript client (`node --test clients/js`) and 24 for the local Node MCP server (`node --test examples/mcp/local-node`).


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

Specification: section 6.


## Conclusion

A build now runs end to end, and what it writes can be read back. The settings layer, the registry, and the data models are in place; the web source crawls through the site handlers to produce documents; one build step turns those documents into a scored compendium; the container and `llms.txt` adapters write it from the command line; the Python and JavaScript clients search the result identically; and one command, locally or on a weekly schedule, does the whole thing and publishes it. A folder on the operator's own machine can be indexed, with every output dropping that content unless it opted in, and every build now checks what it read for likely protected health information and writes two reports for review. GitHub repositories are read through the API, with their code analyzed into records a search can find a definition in, and a DSpace repository's deposits are read through its own interface. Every build result can also be written as a folder of Markdown, in the Open Knowledge Format, which a person reads in any Markdown viewer. An assistant on the operator's own machine can search the result through either of two local MCP servers. A channel's videos are indexed from their captions, each stretch citable at the moment it was said. What is not built yet is the hosted MCP examples. That order, with a done-when rule for each step, is the [implementation plan](implementation-plan.md); the GitHub and code-analysis work is designed in detail in [GitHub repository indexing](github-repository-indexing.md).


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Extractium™ specification](extractium-spec.md) — the intended design, data model, and plugin protocols.
* [Implementation plan](implementation-plan.md) — the phased order of work.
* [Container format](container-format.md) — the flagship output, byte by byte.
* [GitHub repository indexing](github-repository-indexing.md) — the design for the GitHub API source and the code analysis on top of it.
* [Data flow](data-flow.md) — what happens to content between the site and the output folder.
* [Running a build](usage.md) — the command line, its options, and its exit codes.
* [Configuration reference](configuration.md) — every setting in `config.yaml` as it exists now.
* [tests/reference/build_kb_index_reference.py](../tests/reference/build_kb_index_reference.py) — the frozen original the port is measured against.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
