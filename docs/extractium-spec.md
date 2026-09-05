<!--
This file is part of Extractium™
docs/extractium-spec.md
Author(s): Gabriel Mongefranco
Created: 2026-08-16
Last Modified: 2026-09-04
Summary: Provides a high-level specification of the Extractium™ project, in Markdown format.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License along
with this program. If not, see <https://www.gnu.org/licenses/>.

-->

# Extractium™

## High-Level Specification

[← Back to README](../README.md)


## Summary

This page is the intended design of Extractium™: what the tool is for, how its parts fit together, what it reads, what it writes, and what it will never do. It is written for developers and plugin authors. For what is built today, read [Architecture and Current State](architecture.md). For the order in which the design gets built, read the [implementation plan](implementation-plan.md).

- Status: Draft v0.2 (2026-09-04). Supersedes v0.1 (2026-08-16); section 14 lists the changes.
- License: GPL-3.0-or-later for code; all dependencies must be compatible with it.
- Home: the DepressionCenter GitHub organization.

Where this page and the architecture page disagree, this page says what is intended and that page says what exists.


## 1. Overview

Extractium is a lean knowledge-base compiler. It crawls an organization's public sources, normalizes everything into one set of parent and child text chunks with embeddings and BM25 statistics, then serializes that one result into several output formats. The set of outputs is called a *compendium*. It is meant for static hosting, such as GitHub Pages, with no server behind it.

It is the crawling and indexing engine extracted from Field Station AI's `build-kb-index.py`, generalized behind a configuration file and a plugin registry so any research center or organization can build its own compendium. Field Station AI keeps its own bundled index; moving it onto the Extractium client library is a later task in that repository.

### Design priorities, in order

1. **Lightweight.** Runs on GitHub Actions free runners and on modest laptops. Safe for low-resource consumers such as browser-based language models.
2. **Fast.** One crawl, one embedding pass, then cheap serializations. Unchanged pages are never fetched twice.
3. **Friendly.** A non-developer can press one button in GitHub or double-click one script. Only one setting is required; everything else has a working default.
4. Then security, accessibility, and engineering quality.

### Non-goals

- No live server, database, or API is required at any point. Output is flat files.
- No heavyweight retrieval frameworks (LangChain, LlamaIndex, container stacks).
- No cloud language-model calls during a build. Builds work offline and never send content out.
- Not a documentation generator. Code sources will describe a repository's API surface, never raw code bodies.
- Not a general web archiver. A crawl stays inside its configured scope and honors `robots.txt`.


## 2. Architecture

```
config.yaml (one per organization)
        |
        v
+-------------------------------------------------------------+
| REGISTRY  resolves plugins: plugins/ dir > entry points >    |
|           built-ins                                          |
+-------------------------------------------------------------+
        |
        v
+-------------------------------------------------------------+
| SOURCES (plugins)  produce Documents                         |
|   web (core crawler) -> consults SITE HANDLERS per URL:      |
|       generic (core) | tdx | github        (on by default)   |
|   local | github_api | youtube                               |
+-------------------------------------------------------------+
        |
        v
+-------------------------------------------------------------+
| CORE ENGINE (not pluggable)                                  |
|   fetch + conditional-GET cache (.kb_cache/)                 |
|   chunk -> parents and children, stable ids                  |
|   embed (bge-small-en-v1.5, int8), near-duplicate collapse,  |
|   BM25 statistics, calibration, PHI lint                     |
|   build -> one Compendium                                    |
+-------------------------------------------------------------+
        |
        v
+-------------------------------------------------------------+
| ADAPTERS (plugins)  serialize the Compendium                 |
|   container (v3) | llmstxt | sqlite | okf                    |
+-------------------------------------------------------------+
        |
        v
out_dir/  ->  commit to GitHub Pages, or any static host
```

In words: the configuration file names the sources and outputs. The registry finds the matching plugins. Each source produces documents; the web source asks its site handlers how to read each page it visits. The core engine turns all documents into one scored compendium, once. Each adapter then writes that compendium in its own format into the output folder, which is published as static files.

### Key invariants

- One crawl and one embedding pass per build. Adapters never fetch a URL or run a model.
- Fetching, caching, chunking, embedding, BM25, calibration, and the build step are **core**. Everything else is a plugin.
- Built-in plugins register through the same mechanism an external plugin uses. They are plugins that happen to ship in the box, and they serve as the reference implementations.

### 2.1 Plugin kinds

Three kinds, each a small duck-typed protocol.

**Source.** Enumerates and fetches documents.

| Member | Meaning |
|---|---|
| `name` | Registry key and the `type:` value in `config.yaml`. |
| `__init__(options)` | Receives the validated options for its entry in `sources:`. |
| `fetch(session, cache, progress)` | Yields `Document` records. Takes the HTTP session and a progress callback from the caller; never constructs a session or prints. |

**Site handler.** Takes part in the web crawl for URLs it recognizes. Not a crawler: link discovery stays in the web source.

| Member | Meaning |
|---|---|
| `name` | Registry key and the value used in `site_handlers:`. |
| `matches(url)` | True when this handler reads the page. Handlers are consulted in registration order; `generic` is always last. |
| `fetch_url(url)` | The URL to actually request (for example, a GitHub blob page rewritten to its raw file). |
| `expects_html(url)` | Whether the response for that URL is HTML to parse or plain text to wrap. Decided per URL because one host serves both kinds of page. |
| `extract(soup, url)` | Returns the title, the content node, and the categories list, or nothing when the page holds no indexable content and is only a link-discovery hop. |
| `source_type`, `content_type(url)` | Metadata values recorded on every parent. See section 3.4. |
| `default_crawl_exclude_patterns`, `default_index_exclude_patterns` | Patterns the handler adds to the crawl when it is enabled. |

**Adapter.** Writes one output format.

| Member | Meaning |
|---|---|
| `name` | Registry key and the `type:` value in `outputs:`. |
| `write(compendium, out_dir, options)` | Writes files under `out_dir`. A shared base drops local parents unless `options.include_local` is true (section 7). |

### 2.2 Registry and resolution order

The registry resolves each kind in this order, first match wins:

1. Modules in the operator's `plugins/` directory that expose `register()`.
2. Installed packages that declare entry points in the groups `extractium.sources`, `extractium.site_handlers`, and `extractium.adapters`.
3. Built-ins, which are declared through those same entry-point groups in this package.

Loading a module from `plugins/` executes code the operator placed there. It is the same trust level as `config.yaml`, and it is documented rather than sandboxed. Loading plugins from git URLs, with trust gates, is future work; the protocol must not prevent it.

### 2.3 Why site handlers instead of three crawlers

The original script crawls TeamDynamix, GitHub, and ordinary pages with one loop, because the crawl is one graph: a knowledge-base article links to a repository README, and the same queue must follow that link. Splitting the loop into three source plugins would either duplicate it or break the graph. So host-specific knowledge lives in site handlers that the one crawler consults, and each handler ships enabled and can be switched off.


## 3. Data model

### 3.1 Documents

A source yields `Document` records: the source URL, a title, the content (a parsed HTML node or plain text), `source_type`, `content_type`, `categories`, and `local`. The core engine never sees a source's fetch details.

### 3.2 Parents and children

- **Parents** are full sections: one per `h2`/`h3` heading, cut at a maximum length. They are the context unit shown to a language model and the unit of citation.
- **Children** are small overlapping windows of a parent: the search unit that is embedded and matched. A child references its parent by position (`pid`) and, in the container, by character offsets into the parent's text.

Searching children and returning parents is "small-to-big" retrieval: precise matches, enough context to answer.

### 3.3 Stable identifiers

A parent's `id` is the first 16 hexadecimal characters of `sha1(normalized_url + NUL + heading + NUL + ordinal)`, where the ordinal counts parents on the same page that share a heading. The ordinal exists because a long section is cut into several parents with one heading. A child's id is derived, never stored: parent id, a hyphen, and the child's ordinal within its parent. Ids survive a rebuild when the page URL and heading are unchanged.

### 3.4 Per-parent metadata

| Field | Values |
|---|---|
| `source_type` | `kb` (TeamDynamix portal), `github`, `web`, `youtube`, `local` |
| `content_type` | `article`, `readme`, `wiki`, `release_notes`, `page`, `text`, `video_transcript` |
| `categories` | Hierarchy from the source, outermost first: TeamDynamix breadcrumbs, repository paths. Empty when none. |
| `local` | `true` for local-filesystem sources (section 7). |
| `weight` | Per-document multiplier applied after rank fusion; `1.0` by default. |
| Enrichment fields | `summary`, `tags`, `keywords`, `enriched_at`, `enrich_ver`: reserved, null until the deferred enrichment pass exists (section 10). Adapters write them when present and skip them when null. |

### 3.5 Embeddings

- Model: `BAAI/bge-small-en-v1.5` (browser id `Xenova/bge-small-en-v1.5`), 384 dimensions, int8 quantized by default.
- The asymmetric retrieval convention is part of the format: a query is prefixed with `Represent this sentence for searching relevant passages: ` (trailing space included); indexed passages get no prefix. Every output records the prefix, because a model-id check alone does not catch a prefix change.


## 4. Output formats

| Format | Files | Plan phase | Notes |
|---|---|---|---|
| Binary container, version 3 | `kb-index.json` (name configurable) | 3 | Flagship. Four-byte header length, minified JSON header, raw vector bytes. Children carry offsets, not text. Fully specified in the [container format](container-format.md) page. |
| llms.txt | `llms.txt`, `llms-full.txt` | 3 | Root manifest and full concatenation for web-browsing language models. |
| SQLite | `compendium.sqlite` | 6 | Standard-library `sqlite3`, no new dependency. Tables for metadata, parents, children, BM25 terms and postings, int8 vectors. Also the import source for a hosted SQLite service (section 9.3). |
| OKF bundle | directory with `index.md`, `log.md`, one Markdown file per page | 7 | Open Knowledge Format v0.2: YAML front matter with `type`, `title`, `description`, `resource`, `tags`, `generated`, `sources`. OKF defines no archive packaging, so none is written. |
| gzip container | `--gzip` flag | later | Same format, compressed; browsers decode with `DecompressionStream`. |
| Parquet, DuckDB | install extras | future | `[parquet]` and `[duckdb]` extras only. |
| JSONL plus separate vector file | none | never | No ecosystem behind it; the container covers the case. |

Reading OKF bundles produced by other tools, as a source, is possible future work.


## 5. Sources and site handlers

| Kind | Name | Plan phase | Notes |
|---|---|---|---|
| Source | `web` | 2 | Core crawler. Scope: same origin plus a prefix, or explicit include patterns. Consults site handlers per URL. |
| Site handler | `generic` | 2 | Core fallback: common content selectors, boilerplate stripping. |
| Site handler | `tdx` | 2 | TeamDynamix portals: content selectors, title prefix stripping, breadcrumb categories, `/TDClient/<n>/<slug>/` scope, portal exclude patterns. |
| Site handler | `github` | 2 | GitHub and generic git hosts: blob-to-raw rewriting for Markdown and text, wiki and release-notes extraction, repo root and tree pages as link hops only, code-host exclude patterns. |
| Source | `local` | 6 | Markdown, text, and HTML files under a folder. Guardrail in section 7. |
| Source | `github_api` | 7 | Organization enumeration through the REST API; README and Markdown through raw URLs; uses `GITHUB_TOKEN` when present. |
| Source | `youtube` | 9 | Captions only. Explicit video ids need no key; playlists and channels are listed through the YouTube Data API with `YOUTUBE_API_KEY` from the environment. YouTube blocks cloud-provider IP ranges, so transcripts are fetched on an operator's machine and cached; a CI run reuses the cache. Parents deep-link to a timestamp. |
| Source | GitHub code structure | future | AST-based module overviews (signatures, docstrings, purpose). Never raw code bodies. No language model. |
| Source | Speech-to-text fallback | future | For videos without captions. External, optional plugin. |
| Source | OKF bundles from other tools | future | Maybe. |

Explicitly out: spreadsheet extraction, OAuth connectors to cloud drives (users sync to a local folder instead), SQL connectors (contributed plugins), and MCP as a core concern (servers are thin examples over the client libraries; section 9.3).


## 6. Crawler etiquette

The crawler identifies itself and respects the sites it reads.

- `user_agent` defaults to `Extractium/<version> (+https://github.com/DepressionCenter/extractium)`. The original script sent a browser User-Agent; a tool distributed to other organizations does not.
- `respect_robots_txt` defaults to true, using the standard library's parser. It can be switched off for a site the operator owns.
- `delay_seconds` (default 0.5) paces requests; `max_pages` (default 10,000) is a safety ceiling.
- Whether the TeamDynamix portal serves article HTML to the truthful User-Agent was checked against the real portal on 2026-09-04. It does: the home page, the knowledge-base listing, and an article page all answered 200 with the article body in `#divMainContent`. No override is needed. Two details from the same check shape the code: the portal's `robots.txt` answers 406 when a request accepts only HTML, so the robots request sends a plain-text Accept header; and the article breadcrumb is an `ol.breadcrumb` whose linked items are the hierarchy and whose unlinked last item is the page itself.
- When a site's `robots.txt` cannot be read (a 5xx answer or a network failure), every URL on that site is skipped and the reason is reported. A 4xx answer means the site publishes no rules. This is the robots exclusion standard's rule (RFC 9309) and it fails closed on purpose.
- Omitting `crawl_exclude_patterns` or `index_exclude_patterns` means the host-independent asset patterns plus whatever each enabled site handler contributes, so switching a handler off also drops its exclusions. An explicit list, including an empty one, is used as written. The TeamDynamix portal-folder scope rule (`/TDClient/<n>/<slug>/`) stays in core, because the handler protocol has no scope hook.


## 7. Local files and confidentiality

A local folder can hold content that must never be published. The rules:

- Every parent from a local source carries `local: true`, and its URL is `local:` followed by the path relative to the source folder. Absolute paths never reach an output.
- **Every adapter drops local parents by default.** An output opts in with `include_local: true` on its `outputs:` entry, and the command line prints a notice naming each output that includes local content. The default is safe because publishing is the normal use of every output, including the container.
- The PHI lint runs on local content by default (`phi_lint: local`), can run on everything (`all`), or be switched off. It is heuristic and flag-only: it reports likely matches for a person to review and must never claim absence. The phrase "no PHI" is forbidden in its output; zero matches are reported as "0 pattern matches (this does not confirm absence of PHI)". The report is written to the working directory, never to the output folder.


## 8. Cache

- `.kb_cache/` holds `pages/` (fetched text), `meta.json` (validators and content hashes), and `youtube/` (transcripts). `embeddings/` and `enrichment/` are reserved for delta builds.
- Revalidation uses conditional GET (`If-None-Match`, `If-Modified-Since`, honoring 304), not HEAD probing: several servers omit validators on HEAD.
- A content SHA-256 is stored per page so a future delta build can skip unchanged chunks.
- On GitHub Actions, `.kb_cache/` persists between runs through the cache action, keyed on a hash of the configuration file.


## 9. Clients and access

### 9.1 Client libraries

| Language | Plan phase | Notes |
|---|---|---|
| JavaScript | 4 | One file, no dependencies, no build step. Parses the container, runs hybrid search (cosine, BM25, reciprocal rank fusion, calibration threshold, diversity selection), resolves hits to parents. The caller supplies the query embedding, so the same file runs in a browser, in Node, and on edge runtimes. |
| Python | 4 | The same algorithm in `extractium.search`, with an injected query embedder. Used by the tests and the local Python MCP server. |
| Others | contributed | Go, PowerShell, R, Lua, Julia are welcome as contributed clients against the [container format](container-format.md). None is scheduled. |

### 9.2 Access tiers

The compendium on a static host is the single source of truth; every access method is a thin layer over it.

| Tier | Method | Search quality | Hosting cost | Plan phase |
|---|---|---|---|---|
| 0 | Static files (`llms.txt`, `llms-full.txt`, container, SQLite) fetched directly by web-browsing agents | Model-dependent; no ranking | None | 3 |
| 1 | Local MCP server on the user's machine (Node via `npx`, or Python); index downloaded and cached; query embedded locally | Full hybrid: vectors, BM25, fusion | None | 8 |
| 2 | Remote stateless MCP server on a hosted runtime | BM25; hybrid where the host offers a compatible embedding model | None or existing account | 10 |
| 3 | Hosted assistant wrappers (system prompt plus Tier 0 URLs) | Model-dependent | None | 10 |

Tier 2 detail, from the hosts' published limits: a Cloudflare Worker on the free plan has 10 milliseconds of CPU per request and a 3 MB script limit, so it cannot parse a multi-megabyte JSON header on every call; the example imports the SQLite output into D1 and answers BM25 queries from it, with optional query embedding through Workers AI, which serves the same `bge-small-en-v1.5` model. A Val Town HTTP val has 4 GiB of memory and a one-minute wall-clock limit on the free plan, so it can hold the whole container in memory after fetching it from the published URL.

### 9.3 MCP servers are examples, not core

They live under `examples/mcp/`: `local-node/` and `local-python/` (Tier 1), `valtown/` and `cloudflare/` (Tier 2). Each is a small program over a client library and the published compendium. Hosted assistant prompts (Tier 3) live under `examples/wrappers/` as plain text. `SKILLS.md` at the repository root tells AI agents how to use every tier.


## 10. Enrichment (deferred; schema-ready now)

- A local language model only (small instruct model), GPU-gated, delta-only, parent-only. No API calls, ever.
- Populates the reserved nullable fields (section 3.4) through the `.kb_cache/enrichment/` layer.
- Keyword extraction without a language model (YAKE plus embedding-similarity keywords) may ship earlier as a separate step.


## 11. Operations

- Refresh cadence: weekly. The GitHub Actions template runs on a schedule and on a "Run workflow" button press. Publishing uses only the official GitHub Pages actions.
- Local run: `run.bat` or `run.sh` creates a virtual environment, installs pinned dependencies from a committed lock file, builds, and prints what to commit. This is the primary path for sources a cloud runner cannot reach (local folders, YouTube).
- Data and configuration are kept apart from the tool. The tool repository holds the engine. Each organization keeps a small data repository with its `config.yaml`, its transcript cache when it uses YouTube, and the published output folder. A template for that repository ships under `examples/data-repo/`.


## 12. Configuration file (target schema)

The loader in `extractium/config.py` reads this schema; the [configuration reference](configuration.md) documents every setting. Unknown keys stop the build, at the top level and inside each built-in source or output entry.

Minimal file:

```yaml
sources:
  - type: web
    seed_url: https://example.edu/TDClient/000/ExampleOrg/Home/
```

Every setting:

```yaml
name: Example Org Knowledge Base   # default: title of the first crawled page
out_dir: dist                       # every adapter writes under here
cache_dir: .kb_cache
delay_seconds: 0.5
max_pages: 10000
user_agent: Extractium/0.1 (+https://github.com/DepressionCenter/extractium)
respect_robots_txt: true
phi_lint: local                     # local | all | off

sources:
  - type: web
    seed_url: https://example.edu/TDClient/000/ExampleOrg/Home/
    include_patterns: []            # empty = scope from the seed URL
    crawl_exclude_patterns: []      # omit = handler defaults + asset extensions
    index_exclude_patterns: []
    site_handlers: [tdx, github]    # omit = all installed; [] = generic only
  - type: local
    path: ./internal-docs
    include_globs: ["**/*.md", "**/*.txt", "**/*.html"]
  - type: github_api
    org: example-org                # uses GITHUB_TOKEN from the environment when set
  - type: youtube
    channel_id: UCxxxxxxxxxxxxxxxxxxxxxx   # needs YOUTUBE_API_KEY in the environment
    playlist_ids: []
    video_ids: []
    languages: [en]

outputs:                            # omit = container + llmstxt
  - type: container
    file: kb-index.json
    include_local: false
  - type: llmstxt
  - type: sqlite
    file: compendium.sqlite
    include_local: true
  - type: okf
```

Keys and API tokens never go in this file. They are read from the environment.


## 13. Repository structure (target)

```
extractium/
├── extractium/                  # Python package (the engine)
│   ├── core/                    # fetch, cache, chunk, embed, bm25, dedup, calibration,
│   │                            # phi_lint, registry, models, build
│   ├── sources/                 # web (core crawler); site handlers generic, tdx, github;
│   │                            # sources local, github_api, youtube
│   ├── adapters/                # container, llmstxt, sqlite_out, okf
│   ├── search.py                # Python client
│   └── cli.py                   # extractium build --config config.yaml
├── clients/
│   └── js/                      # extractium-client.js and its tests
├── plugins/                     # operator drop-in plugin dir (ships empty)
├── docs/                        # specification, architecture, configuration, container
│                                # format, implementation plan, how-to pages
├── examples/
│   ├── config.example.yaml
│   ├── data-repo/               # template for an organization's data repository
│   ├── mcp/                     # local-node, local-python, valtown, cloudflare
│   └── wrappers/                # hosted-assistant system prompts
├── tests/                       # pytest suite, fixtures, golden files, frozen reference script
├── .github/workflows/build-compendium.yml   # template workflow for adopters
├── run.bat / run.sh             # double-click entry points
├── requirements-lock.txt        # pinned dependencies
├── SKILLS.md                    # guidance for AI agents consuming a compendium
├── AGENTS.md, README.md, LICENSE, NOTICE, pyproject.toml
```

Documentation serves four audiences: people building an index, core developers, plugin developers, and AI agents consuming a compendium.


## 14. Changes from v0.1

- Site handlers replace the separate `tdx` and `github` source plugins; one web crawler is core, and the handlers are on-by-default plugins (section 2).
- Three plugin kinds and a stated resolution order (section 2.1, 2.2).
- Stable identifiers include an ordinal so split sections do not collide (section 3.3).
- The container is version 3 from the start; children carry offsets, not text. No version 2 output (section 4, [container format](container-format.md)).
- Every adapter excludes local content unless the output opts in; the earlier rule let the container include it (section 7).
- The OKF adapter writes a directory only; OKF defines no `.zip` packaging (section 4).
- Crawler etiquette: a truthful User-Agent and `robots.txt` by default (section 6).
- YouTube: enumeration through the Data API or explicit lists; transcripts fetched locally and cached because cloud runners are blocked (section 5).
- Remote MCP examples account for Cloudflare's CPU limit and use Workers AI for optional hybrid search (section 9.2).
- Clients: JavaScript and Python are the only scheduled clients (section 9.1).
- Refresh cadence is weekly, with the local run as the primary path (section 11).
- A `sources:` and `outputs:` configuration schema (section 12).
- The roadmap moved to the implementation plan (section 15).


## 15. Roadmap

The order of work, sized in phases of about one week, is in the [implementation plan](implementation-plan.md). The plan is the authority on sequence; this page is the authority on design.


## Conclusion

You now know what Extractium is meant to become: one crawler with pluggable site handlers, one build step, several cheap outputs, and thin clients over a static file. Build in the order the implementation plan gives, and keep this page and the architecture page in agreement with the code.


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Architecture and Current State](architecture.md) — what exists in the repository today.
* [Implementation plan](implementation-plan.md) — the phased order of work.
* [Container format](container-format.md) — the flagship output, byte by byte.
* [Configuration reference](configuration.md) — the settings file as it exists now.
* [Field Station AI](https://github.com/DepressionCenter/FieldStationAI) — the project the engine was extracted from.
* [Open Knowledge Format specification](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md) — the OKF v0.2 format the OKF adapter writes.
* [llms.txt proposal](https://llmstxt.org/) — the convention the llms.txt adapter follows.
* [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits/) — the constraints behind the Tier 2 design.
* [Val Town limits](https://www.val.town/limits) — the same, for the Val Town example.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
