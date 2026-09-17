<!--
This file is part of Extractium™
docs/extractium-spec.md
Author(s): Gabriel Mongefranco
Created: 2026-08-16
Last Modified: 2026-09-17
Summary: The design of Extractium™: what the tool is for, how its parts
fit together, what it reads, what it writes, and what it will never do.
Written for developers and plug-in authors.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Specification

[← Back to README](../README.md)


## Summary

This page is the design of Extractium™: what the tool is for, how its parts fit together, what it reads, what it writes, and what it will never do. It is written for developers and plug-in authors. For how the code is organized module by module, read the [architecture](architecture.md) page.

- License: GPL-3.0-or-later for code. All dependencies must be compatible with it.
- Home: the DepressionCenter GitHub organization.


## 1. Overview

Extractium is a lean knowledge-base compiler. It crawls an organization's public sources, normalizes everything into one set of parent and child text chunks with embeddings and BM25 statistics, then serializes that one result into several output formats. The set of outputs is called a *compendium*. It is meant for static hosting, such as GitHub Pages, with no server behind it.

It is the crawling and indexing engine extracted from Field Station AI's `build-kb-index.py`, generalized behind a configuration file and a plug-in registry so any research center or organization can build its own compendium. Field Station AI keeps its own bundled index.

### Design priorities, in order

1. Lightweight. Runs on GitHub Actions free runners and on modest laptops. Safe for low-resource consumers such as browser-based language models.
2. Fast. One crawl, one embedding pass, then cheap serializations. Unchanged pages are never fetched twice.
3. Friendly. A non-developer can press one button in GitHub or double-click one script. Only one setting is required. Everything else has a working default.
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
|   local | okf | github_api | dspace | youtube                |
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
|   container (v4) | llmstxt | sqlite | okf                    |
+-------------------------------------------------------------+
        |
        v
out_dir/  ->  commit to GitHub Pages, or any static host
```

In words: the configuration file names the sources and outputs. The registry finds the matching plugins. Each source produces documents; the web source asks its site handlers how to read each page it visits. The core engine turns all documents into one scored compendium, once. Each adapter then writes that compendium in its own format into the output folder, which is published as static files.

### Key invariants

- One crawl and one embedding pass per build. Adapters never fetch a URL or run a model.
- Fetching, caching, chunking, embedding, BM25, calibration, and the build step are core. Everything else is a plug-in.
- Built-in plug-ins register through the same mechanism an external plug-in uses. They are plug-ins that happen to ship with the tool, and they serve as the reference implementations.

### 2.1 Plug-in kinds

Three kinds, each a small duck-typed protocol.

Source: enumerates and fetches documents.

| Member | Meaning |
|---|---|
| `name` | Registry key and the `type:` value in `config.yaml`. |
| `__init__(options)` | Receives the validated options for its entry in `sources:`. |
| `fetch(session, cache, progress)` | Yields `Document` records. Takes the HTTP session and a progress callback from the caller; never constructs a session or prints. |
| `configure(registry, settings)` | Optional. Receives the plugin registry and the global crawl settings after construction, for a source that takes part in a web crawl. |
| `read_found_links(session, cache, progress, links)` | Optional. Called once every source has run, with the addresses the site handlers collected during the crawls and held back. Yields documents like `fetch`, under the source's own rule for what a link found on somebody's page may add. |

Site handler: takes part in the web crawl for URLs it recognizes. Not a crawler, because link discovery stays in the web source.

| Member | Meaning |
|---|---|
| `name` | Registry key and the value used in `site_handlers:`. |
| `matches(url)` | True when this handler reads the page. Handlers are consulted in registration order; `generic` is always last. |
| `fetch_url(url)` | The URL to actually request (for example, a GitHub blob page rewritten to its raw file). |
| `expects_html(url)` | Whether the response for that URL is HTML to parse or plain text to wrap. Decided per URL because one host serves both kinds of page. |
| `extract(soup, url)` | Returns the title, the content node, the categories list, and the page's own summary and tags where it states them, or nothing when the page holds no indexable content and is only a link-discovery hop. |
| `source_type`, `content_type(url)` | Metadata values recorded on every parent. See section 3.4. |
| `default_crawl_exclude_patterns`, `default_index_exclude_patterns` | Patterns the handler adds to the crawl when it is enabled. |
| `document_url_patterns` | Optional. Addresses on the handler's host that serve a document file without naming its extension. While the source reads documents they are fetched as files and read, and the same patterns are set aside from the handler's exclude lists. |
| `attachment_listing_urls(soup, url)` | Optional. The addresses where the page's host lists the files attached to it, when that list is not in the page. While the source reads documents each is queued as a page of the crawl and its links are read; consulted for pages whose links are followed. |
| `scope_prefix(seed_url)` | Optional. May narrow the default crawl scope for a seed on a host the handler knows, returning the prefix the crawl stays inside, or None. Consulted only when the source has no include patterns. |
| `observe_link(url)` | Optional. Sees every link the crawl discovers, in scope or not, before the scope check, and returns nothing. For a handler that collects addresses another source should read. |
| `configure(settings)` | Optional. Receives the build's global crawl settings after construction, for a handler whose rules depend on what the settings file says. |
| `allows(url)` | Optional. May veto a URL the crawl would otherwise follow. Every handler that defines it is asked about every URL, and one refusal keeps the URL out of scope. |
| `offer_source(seed_url)` | Optional. May name a better source for a crawl's seed, as a source name and its options. Consulted for the seed only, never for a link found mid-crawl. |

Adapter: writes one output format.

| Member | Meaning |
|---|---|
| `name` | Registry key and the `type:` value in `outputs:`. |
| `write(compendium, out_dir, options)` | Writes files under `out_dir`. A shared base drops local parents unless `options.include_local` is true (section 7). |

### 2.2 Registry and resolution order

The registry resolves each kind in this order, first match wins:

1. Modules in the `plugins/` directory beside the settings file that expose `register()`.
2. Installed packages that declare entry points in the groups `extractium.sources`, `extractium.site_handlers`, and `extractium.adapters`.
3. Built-ins, which are declared through those same entry-point groups in this package.

Loading a module from `plugins/` executes code you placed there. It is the same trust level as `config.yaml`, and it is documented rather than sandboxed. A plug-in shared between projects is installed as a package, which pip can do from a git address at a pinned commit. The tool has no git loader of its own, because pip's trust model is the one to use.

### 2.3 Why site handlers instead of three crawlers

The crawl is one graph: a knowledge-base article links to a repository README, and the same queue must follow that link. Splitting the loop into separate source plug-ins per host would either duplicate it or break the graph. So host-specific knowledge lives in site handlers that the one crawler consults, and each handler ships enabled and can be switched off.


## 3. Data model

### 3.1 Documents

A source yields `Document` records: the source URL, a title, the content (a parsed HTML node or plain text), `source_type`, `source_label`, `content_type`, `categories`, `local`, and, where the source knows them, the page's own `summary` and `tags`. The core engine never sees a source's fetch details.

One page is indexed once, however many sources reach it. Documents are compared by their normalized address across every source in a build; the first source to produce a page keeps it, later sources are told they were too late, and the build reports how many pages that happened to. A section of a site that is already crawled belongs to that crawl as a second `seed_urls` entry rather than to a source of its own.

### 3.2 Parents and children

- Parents are full sections: one per `h2`/`h3` heading, cut at a maximum length. They are the context unit shown to a language model and the unit of citation.
- Children are small overlapping windows of a parent: the search unit that is embedded and matched. A child references its parent by position (`pid`) and, in the container, by character offsets into the parent's text.

Searching children and returning parents is "small-to-big" retrieval: precise matches, enough context to answer.

Near-duplicate collapse removes a child that is near-identical to one already kept from another page. Children of one page are never collapsed into each other. The step exists to remove boilerplate many pages share, and two passages of one article are not that. The rule also removes a dependence on heading length: a child is embedded as its parent's heading followed by its own text, so an article with a long title gives every one of its children a long identical prefix, and comparing them without this rule discards real content as duplication. Measured on the Depression Center portal, recovering 119 truncated article titles cost 86 sections without it, of which only 14 were duplicates by their text alone.

### 3.3 Stable identifiers

A parent's `id` is the first 16 hexadecimal characters of `sha1(normalized_url + NUL + heading + NUL + ordinal)`, where the ordinal counts parents on the same page that share a heading. The ordinal exists because a long section is cut into several parents with one heading. A child's id is derived, never stored: parent id, a hyphen, and the child's ordinal within its parent. Ids survive a rebuild when the page URL and heading are unchanged.

### 3.4 Per-parent metadata

| Field | Values |
|---|---|
| `source_type` | `kb` (TeamDynamix portal), `github`, `web`, `youtube`, `local`, `repository` (a scholarly repository such as a DSpace instance) |
| `source_label` | The name a reader sees for the source, from its required `label` setting. At most 60 characters, never empty. Groups the sections of `llms.txt` |
| `content_type` | `article`, `readme`, `wiki`, `release_notes`, `page`, `text`, `video_transcript`, `manifest`, `repo_map`, `code_file`, `code_symbol` |
| `categories` | Hierarchy from the source, outermost first: TeamDynamix breadcrumbs, repository paths. Empty when none. |
| `local` | `true` for local-filesystem sources (section 7). |
| `weight` | Per-document multiplier applied after rank fusion; `1.0` by default. |
| Enrichment fields | `summary`, `tags`, `keywords`, `enriched_at`, `enrich_ver`: carried by every section. A source sets `summary` and `tags` from what the page says about itself (a video's description and tags, a repository's description and topics, an article's summary and tag list, a page's meta description and keywords); the keyword step (section 10) fills `keywords` on every section, adds to every page's `tags` the keywords its sections share after whatever the source gave, and leaves `summary` null where the source gave none. The container writes a field only when it is set, so a file with no enrichment is laid out as before; the SQLite `parents` table holds them as nullable columns, the lists as JSON arrays; the Open Knowledge Format front matter takes the summary as the description, the tags into its tag list, and the keywords as a `keywords` list; `llms.txt` ends each page's entry with the page's keywords. |

### 3.5 Embeddings

- Model: `BAAI/bge-small-en-v1.5` (browser id `Xenova/bge-small-en-v1.5`), 384 dimensions, int8 quantized by default.
- The asymmetric retrieval convention is part of the format: a query is prefixed with `Represent this sentence for searching relevant passages: ` (trailing space included); indexed passages get no prefix. Every output records the prefix, because a model-id check alone does not catch a prefix change.


## 4. Output formats

The [architecture](architecture.md) page says which module writes each format.

| Format | Files | Notes |
|---|---|---|
| Binary container, version 4 | `<slug>.json`, `compendium.json` by default; `<slug>.json.gz` with `gzip: true` | The main output. Four-byte header length, minified JSON header, raw vector bytes. Children carry offsets, not text. Fully specified in the [container format](container-format.md) page. Planned, Phase 20 of the [implementation plan](implementation-plan.md): two files from one build, `<slug>.json.gz` (light, the default) and `<slug>-full.json.gz`. The light file holds one section per page whose text is the page's description and keywords. The full file holds every section except code records. `gzip: false` writes `.json` names. |
| llms.txt | `llms.txt`, `llms-full.txt` | Root manifest and full concatenation for web-browsing language models. Planned, Phase 19 of the [implementation plan](implementation-plan.md): `llms.txt`, `llms/<source>.txt`, and `llms/<source>/<group>.txt` in place of these two files. An index of sources, then one index file per source, split by category past 500 entries. Links and descriptions only. No code records, and no `llms-full.txt`. |
| SQLite | `<slug>.sqlite`, `compendium.sqlite` by default | Standard-library `sqlite3`, no new dependency. Tables for metadata, parents, children, BM25 terms and postings, int8 vectors. Also the import source for a hosted SQLite service (section 9.3). Planned, Phases 20 and 21 of the [implementation plan](implementation-plan.md): the only single-file output that carries code records, with postings stored by integer term id. |
| OKF bundle | `okf/` directory with `index.md`, `log.md`, one Markdown file per page | Open Knowledge Format v0.2: YAML front matter with `type`, `title`, `description`, `resource`, `tags`, `generated`, `sources`. `type` is the only field the format requires, and it names the record's content type in words. Concept files are filed under the name of the source that produced them. Every name is built from an allowlist, so a page title can never reach outside the folder. OKF defines no archive packaging, so none is written. A file the tool wrote for a page no longer in the compendium is removed on the next build. |
| gzip container | the container output's `gzip` option | The same bytes through gzip, recognized by the gzip signature rather than the name. The Python client inflates inside `load_container`. The JavaScript client's `inflateContainer` runs before `loadContainer`, through `DecompressionStream`. |

Decided against: a JSONL file with a separate vector file, because there is no ecosystem behind it and the container covers the case; Parquet and DuckDB outputs, because no consumer asked for them and each would add a dependency for a format the SQLite output already serves.

The `okf` source reads a bundle in this format back, from this tool or any other (section 5).


## 5. Sources and site handlers

| Kind | Name | Notes |
|---|---|---|
| Source | `web` | Core crawler. Scope: same origin plus a prefix, or explicit include patterns. Consults site handlers per URL. Where every request lands is checked against the scope, so a redirect off the site or to an excluded address is skipped rather than indexed. |
| Site handler | `generic` | Core fallback: common content selectors, boilerplate stripping. |
| Site handler | `tdx` | TeamDynamix portals: content selectors, title prefix stripping, recovery of a title the portal cut short, breadcrumb categories, `/TDClient/<n>/<slug>/` scope, portal exclude patterns. |
| Site handler | `youtube` | Recognition only, in both directions. Every address on a YouTube host is refused for crawling, because the page is a shell around a player and its words are in the caption track. The count held back is reported once with the advice to add a video source. A channel, playlist, or watch address given as a crawl seed is offered to the `youtube` source instead, in whichever form it was written, which is the same seed promotion the GitHub handler performs. Videos linked from crawled pages are collected for the `youtube` source to decide about. Extracts nothing. |
| Site handler | `github` | GitHub and generic git hosts: blob-to-raw rewriting for Markdown and text, wiki and release-notes extraction, repo root and tree pages as link hops only, code-host exclude patterns, and the account guardrail (section 6). |
| Site handler | `google_docs` | Google Docs, Sheets, and Slides files shared with the link, on `docs.google.com`. Claims a file's address only, folds its `/edit`, `/view`, and `/preview` link shapes into one address through the protocol's `canonical_url` hook, and requests the plain-text export (CSV for the first sheet of a spreadsheet) the way the GitHub handler requests a raw file. The export is served from a delivery host, which the `landing_allowed` hook accepts. A file that is not shared answers with a sign-in page, which the fetch layer refuses with the landing address named; nothing is retried with a credential. Forms, Drive folders, and the sign-in host are on its exclude list. Reached through `leaf_patterns` (or `include_patterns`), because the host is off-site for every seed. Checked against Google on 2026-09-15: `docs.google.com/robots.txt` allows `/document`, `/spreadsheets`, and `/presentation` for every agent, a shared presentation answered its text export as `text/plain` from `googleusercontent.com`, and a shared document did the same with a byte-order mark, which the fetch layer drops. |
| Source | `local` | Markdown, text, and HTML files under a folder, plus Word, OpenDocument, RTF, PDF, and slide files with `read_documents` on. Guardrail in section 7. |
| Source | Document readers | `extractium/readers/`: Word (`.docx`), OpenDocument text (`.odt`), PowerPoint (`.pptx`), and OpenDocument presentations (`.odp`) read with `zipfile` and `xml.etree`, RTF read by a small parser of the text runs, all standard library; and PDF read with `pypdf`, the optional `pdf` extra, in a child process with a 30-second limit per file that is killed and replaced when it runs out, a 500-page ceiling, and on POSIX an address-space limit. Headings, paragraphs, lists, and tables become Markdown-like text, so the chunker cuts a document at its headings; a PDF's headings come from its bookmarks with the page number appended, or from the page numbers alone, so each section names its page; a deck gets one numbered heading per slide carrying the slide's title, with its speaker notes marked as notes, so each section names its slide. The title, subject, keywords, and description from the file's properties are read too, with the last three indexed as the document's first paragraph. The format is decided from the first bytes; the binary `.doc` and `.ppt` are refused by name; an archive entry over its ceiling and any XML part carrying a document type declaration are refused before parsing; an encrypted PDF and one whose pages hold no text are refused with the reason. Behind `read_documents` on the `web`, `local`, and `github_api` sources, off by default: on a crawl, a document link in scope is fetched as bytes and indexed once however many addresses reach it; in a repository, one request per file with the text cached under the blob name; in a folder, the document globs join the defaults. |
| Source | `github_api` | Organization, user, or single-repository ingestion through the REST API: complete tree inventory, documentation and project manifests in full, blob caching by SHA. Three tiers, tried in order and applied to an explicit source and to a GitHub `web` seed alike: authenticated API, unauthenticated API with identical capability, then a documentation-only crawl that runs no code analysis. A token raises the request budget. It never widens what may be published. Only accounts you named are read, whatever links to them (section 6). Vendored, generated, and test folders, dotfiles, housekeeping files, headers, lock files, and settings files are never read; `max_repositories` (100) and `max_files_per_repository` (1,000, the root README first and code last) cap what one account contributes, and the build's `max_pages` reaches only the documentation crawl. See [GitHub repository indexing](github-repository-indexing.md). |
| Source | `youtube` | Captions only. No key is needed: a channel may be named by handle, by custom address, by watch-page address, or by id, and anything but an id is resolved once against the channel's own page and stored. Listings come from the Data API when `YOUTUBE_API_KEY` is set and from YouTube's own pages when it is not, and a channel's uploads playlist is derived from its id rather than asked for. The keyless path stops where YouTube's robots.txt does, at the newest hundred of a listing, and says which listings it stopped short on. Paging further, and the one browser-identity retry a refused page gets, both require `respect_robots_txt: false`. A channel's uploads and the playlists it shows are both read, and a video in a playlist that another channel published is left out unless `only_channel_videos` is turned off, because a playlist holds whatever its owner chose. A video linked from a page another source crawled is offered to this source after every source has run, and is read only when its publisher is known and is a channel this source names. That rule is not relaxed by `only_channel_videos`, and a source naming no channel reads no linked video. YouTube blocks cloud-provider IP ranges, so transcripts are fetched on a person's computer and stored under `cache_dir` to be committed. A CI run reuses that store and does not reach YouTube at all. Nothing stored is revalidated, because revalidating is the thing a runner cannot do. Each stretch of a transcript is one parent, addressed at the moment it begins, so a citation opens the video at the quoted words. `llms.txt` and the OKF bundle group those stretches back into one video. The caption library is an optional install (`extractium[youtube]`), so a build that reads only stored transcripts does not need it. A video whose captions are off is skipped and counted, not fatal. |
| Source | GitHub code structure | Tree-sitter analysis of repository code, inside the `github_api` source: signatures, documentation, imports, calls labelled `resolved`, `probable`, or `unresolved`, reverse edges, and repository and account maps. Never raw code bodies, and no language model. A symbol record links to its lines on GitHub instead of copying them. The parser set is the `extractium[code]` extra, pinned in the lock file the build scripts install from; a developer install without it still records every source file at the file-metadata tier. Universal Ctags is an optional second parser, run with an argument array, no shell, and no configuration file. No R grammar is published for Python, so R falls to Ctags or to a file-level record. Stata always does. Notebooks, R Markdown, Lua Server Pages, and HTML have their prose indexed and their embedded code parsed, and a notebook's saved outputs are never read. See [GitHub repository indexing](github-repository-indexing.md). |
| Source | `dspace` | Scholarly deposits in a DSpace 7 repository, such as the University of Michigan Library's Deep Blue. Named collections only, never discovered. One document per deposit: abstract, authors, date, subjects, rights, and the handle, DOI, and any other address the depositor gave, all kept apart. File contents come from the repository's own extracted-text bundle, so no PDF, Word, or archive reader is added. Incremental from the per-deposit modification stamp the listing carries, which arrives with the files in one request per hundred deposits. No fall back to crawling, because the pages a crawler reaches hold no deposits. A collection is confirmed to exist before it is searched, because a scope the interface does not recognize is answered with the whole repository rather than refused. See [Indexing a DSpace repository](dspace-repository-indexing.md). |
| Source | `okf` | An Open Knowledge Format bundle on disk: one document per concept file, addressed at the resource its front matter names, with the concept's type read back as the content type. A concept whose resource is a `local:` address stays local. A resource that is not a web address is refused. The two reserved files are ignored, and a file outside the bundle folder is never read. |

Decided against: a speech-to-text fallback for videos without captions. Of 65 videos sampled from a real channel on 2026-09-11, 64 had English captions, 37 of those generated by YouTube itself, and none had captions missing or disabled. The one gap was a video captioned in Spanish only, which the `languages` setting covers. Decoding media to recover speech this project can already read as text is a large dependency and a malformed-input risk for a problem that did not occur. Video indexing is therefore captions from YouTube only: no other video host, and no local media file. An organization that needs those can write a source plug-in.

Explicitly out: spreadsheet files (a shared Google Sheet is read through its CSV export; `.xlsx` and `.ods` files are not read), OAuth connectors to cloud drives (sync to a local folder instead), SQL connectors (contributed plug-ins), and MCP as a core concern (servers are thin examples over the client libraries; section 9.3).


## 6. Crawler etiquette

The crawler identifies itself and respects the sites it reads.

- `user_agent` defaults to `Extractium/<version> (+https://github.com/DepressionCenter/extractium)`. The original script sent a browser User-Agent; a tool distributed to other organizations does not.
- `respect_robots_txt` defaults to true, using the standard library's parser. It can be switched off for a site you own.
- `delay_seconds` (default 0.5) paces requests; `max_pages` (default 10,000) is a safety ceiling on what one source reads, in the source's own unit: pages for a crawl, videos, deposits, files, or concept files for the other kinds. A `github_api` source has its own `max_repositories` and `max_files_per_repository` and meets `max_pages` only in its documentation-crawl fallback.
- The pause is kept per host, and it lives in the session every source fetches through rather than in any one source. Sources run at the same time (`parallel_sources`, default 4) and a crawl keeps several fetches in flight (`parallel_pages`, default 4), so a pause taken by one source would not stop another from asking the same host in the same moment. The session waits until one delay has passed since the last request start to that host, whichever thread made it, and hosts never wait for one another. A crawl handed a bare session by a library caller is not paced.
- Whether the TeamDynamix portal serves article HTML to the truthful User-Agent was checked against the real portal on 2026-09-04. It does: the home page, the knowledge-base listing, and an article page all answered 200 with the article body in `#divMainContent`. No override is needed. Two details from the same check shape the code: the portal's `robots.txt` answers 406 when a request accepts only HTML, so the robots request sends a plain-text Accept header; and the article breadcrumb is an `ol.breadcrumb` whose linked items are the hierarchy and whose unlinked last item is the page itself.
- Whether a GitHub Actions runner reaches the sites this project indexes was checked on 2026-09-08, from an `ubuntu-24.04` runner sending the truthful User-Agent. All three answered 200: the TeamDynamix portal home page (32,845 bytes of `text/html`), `https://github.com/DepressionCenter` (308,048 bytes of `text/html`), and a `raw.githubusercontent.com` README (12,210 bytes of `text/plain`). A cloud runner can therefore build the compendium; local runs stay necessary only for sources a runner cannot reach, such as local folders and YouTube.
- Three sites in the Depression Center's own crawl scope, `depressioncenter.org`, `p2p.depressioncenter.org`, and `code.depressioncenter.org`, answer `403` with `cf-mitigated: challenge` to any client whose TLS handshake is not a browser's, whatever `User-Agent` it sends; their `robots.txt` allows every crawler, so the block is a content-delivery filter rather than a stated policy. Measured on 2026-09-10 and recorded in [reading a site behind bot protection](bot-protection-transport.md). The `transport` setting answers it: `auto`, the default, retries a challenged request once over a browser-shaped handshake and keeps that choice for the host; `browser` starts that way; `plain` never does. The crawler names itself Extractium over either connection, `robots.txt` is read first and obeyed as before, and the choice is reported once per host and in the build summary. A `403` without the challenge header is left alone.
- `respect_robots_txt: false` is your statement that you own the sites in scope, and it carries a second effect. With it off, a page that answers 401, 403, or 429 to the configured `user_agent` is requested once more with a common browser User-Agent, and both attempts are reported. Pages that were never refused are still fetched under the configured agent, and a 404 or a 5xx is never retried, because neither is a refusal. The two behaviours travel together deliberately: presenting as a browser is only defensible where ignoring robots rules already is.
- When a site's `robots.txt` cannot be read (a 5xx answer or a network failure), every URL on that site is skipped and the reason is reported. A 4xx answer means the site publishes no rules. This is the robots exclusion standard's rule (RFC 9309) and it fails closed on purpose.
- A GitHub account is read only when you named it: as the owner of a `github_api` source, as the owner in a GitHub `web` seed, or in the global `github_owners` list. Account names appear in READMEs, dependency lists, fork notices, and contributor links, and following them turns a one-organization build into a crawl of thousands of strangers' repositories. The rule is deny by default, holds exact names rather than patterns, applies to `github.com`, `raw.githubusercontent.com`, and `<owner>.github.io`, and is enforced in crawl scope as well as in API promotion, because a GitHub seed puts every account on the host inside the seed origin. Being allowed lets links into an account be followed; only naming an account as a source lists that account's repositories. Skipped accounts are counted and reported once.
- `leaf_patterns` names single pages on other hosts. A link that is out of scope but matches one is fetched and indexed when the page linking to it sits inside the scope derived from a seed, and its own links are never read, so the crawl never spreads to that host and a leaf linked only from another leaf, or only from a site an include pattern added, is never reached. The asset filter, the crawl exclude list, the handlers' own rules, the other host's `robots.txt`, and `max_pages` apply to a leaf as to any page, and a leaf that redirects to an address no leaf pattern covers is skipped. This is how a one-page site whose resources are shared Google files and files on a delivery network is indexed without crawling either host.
- Omitting `crawl_exclude_patterns` or `index_exclude_patterns` means the host-independent asset patterns plus whatever each enabled site handler contributes, so switching a handler off also drops its exclusions. An explicit list, including an empty one, is used as written. `extra_crawl_exclude_patterns` and `extra_index_exclude_patterns` are appended to whichever list applies, so one site's own navigation can be kept out without restating the built-in list. The TeamDynamix portal-folder scope rule (`/TDClient/<n>/<slug>/`) lives in the `tdx` handler, through the protocol's `scope_prefix` hook, so core knows no host and switching the handler off drops the rule. The GitHub account rule uses the `allows` hook the same way.
- A handler's default patterns are written for the URL shapes its sites really serve. A code host serves a listing both bare (`/issues`) and with a sub-path (`/issues/12`), and a portal writes a facet as a query parameter (`?CategoryID=0&TagID=8245`) as well as a path. A pattern that covers only one shape is inert against the other. The frozen reference script spent 150 pages of a 500-page crawl on listings that produced no indexed content for exactly that reason.
- Because every enabled handler's patterns apply to every URL in a crawl, a handler's segment patterns are anchored to the paths its own sites use. Without that, the code host's `/projects` rule would also exclude an ordinary site's `/project` page.
- Category and tag listings belong on the index list and never on the crawl list. A TeamDynamix portal publishes no sitemap and no full article index, so those listings are the only route to most of its articles; they are also pure navigation, so their own text is not indexed. The portal writes an unfiltered listing as `TagID=0`, so a rule keyed on the presence of a tag parameter would skip the widest discovery page it has.
- The portal's question listing is the exception: it is one flat, paged list of every question, so its narrowed views (`CategoryID`, `TagID`, `Filter=answered`, `Filter=unanswered`, in any combination) are excluded from the crawl. Checked against the Depression Center portal on 2026-09-14, the flat list reached all 31 questions across three pages, and the other 84 listing views reached nothing it did not. The portal writes the flat list as `CategoryID=0&TagID=0` as well as bare, and both forms stay crawled. Knowledge-base category and tag listings are unaffected, because there is no flat article listing. Person pages (`/People/`) are excluded too: each redirects to the institution's sign-in, and a listing links to one for every question's author.


## 7. Local files and confidentiality

A local folder can hold content that must never be published. The rules:

- Every parent from a local source carries `local: true`, and its URL is `local:` followed by the path relative to the source folder. Absolute paths never reach an output.
- Every adapter drops local parents by default. An output opts in with `include_local: true` on its `outputs:` entry, and the command line prints a notice naming each output that includes local content. The default is safe because publishing is the normal use of every output, including the container.
- The PHI lint runs on local content by default (`phi_lint: local`), can run on everything (`all`), or be switched off. It is heuristic and flag-only: it reports likely matches for a person to review and must never claim absence. The phrase "no PHI" is forbidden in its output; zero matches are reported as "0 pattern matches (this does not confirm absence of PHI)". The report is written to the working directory, never to the output folder.


## 8. Cache

- `.kb_cache/` holds `pages/` (fetched text), `meta.json` (validators, content hashes, and the file name a server gave a document), `github/` (`repositories/` for metadata and trees, `blobs/` for file bodies keyed by blob SHA, and `analysis/` for parser output keyed by blob SHA and parser signature), `repository/` (the text a DSpace repository extracted from each deposit), and `youtube/` (`videos/` and `listings/`). `previous-build.json` is the manifest of the last build's published sections, which an incremental rebuild carries unseen pages forward from. It never holds a section read from a local folder. `enrichment/keywords.json` holds what the keyword step found for every section of the last build, keyed by section id with a digest of the section's text. `embeddings/` is reserved for delta builds. Nothing under `github/` ever holds a token, and nothing under `youtube/` ever holds a key.
- Revalidation uses conditional GET (`If-None-Match`, `If-Modified-Since`, honoring 304), not HEAD probing: several servers omit validators on HEAD.
- A content SHA-256 is stored per page so a future delta build can skip unchanged chunks.
- On GitHub Actions, `.kb_cache/` persists between runs through the cache action, keyed on a hash of the configuration file.


## 9. Clients and access

### 9.1 Client libraries

| Language | Notes |
|---|---|
| JavaScript | One file, no dependencies, no build step. Parses the container, runs hybrid search (cosine, BM25, reciprocal rank fusion, calibration threshold, diversity selection), resolves hits to parents. The caller supplies the query embedding, so the same file runs in a browser, in Node, and on edge runtimes. |
| Python | The same algorithm in `extractium.search`, with an injected query embedder. Used by the tests and the local Python MCP server. |
| Others | Go, PowerShell, R, Lua, Julia are welcome as contributed clients against the [container format](container-format.md). |

### 9.2 Access tiers

The compendium on a static host is the single source of truth; every access method is a thin layer over it.

| Tier | Method | Search quality | Hosting cost |
|---|---|---|---|
| 0 | Static files (`llms.txt`, `llms-full.txt`, container, SQLite) fetched directly by web-browsing agents | Model-dependent, no ranking | None |
| 1 | Local MCP server on your own computer (Node or Python). The index is downloaded and cached, and the query is embedded locally | Full hybrid: vectors, BM25, fusion | None |
| 2 | Remote stateless MCP server on a hosted runtime | BM25, or hybrid where the host offers a compatible embedding model | None or existing account |
| 3 | Hosted assistant wrappers (system prompt plus Tier 0 URLs) | Model-dependent | None |

Tier 2 detail, from the hosts' published limits: a Cloudflare Worker on the free plan has 10 milliseconds of CPU per request and a 3 MB script limit, so it cannot parse a multi-megabyte JSON header on every call; the example imports the SQLite output into D1 and answers BM25 queries from it, with optional query embedding through Workers AI, which serves the same `bge-small-en-v1.5` model. A Val Town HTTP val has 4 GiB of memory and a one-minute wall-clock limit on the free plan, so it can hold the whole container in memory after fetching it from the published URL. Both hosted servers speak the protocol's Streamable HTTP binding in its stateless form: one endpoint, one POST per message, one JSON object back, no session and no server-sent stream. Each takes an optional bearer token and an optional origin allowlist, because a hosted endpoint is otherwise open to anyone who finds its address.

### 9.3 MCP servers are examples, not core

They live under `examples/mcp/`: `local-node/` and `local-python/` (Tier 1), `valtown/` and `cloudflare/` (Tier 2). Each is a small program over a client library and the published compendium. Hosted assistant prompts (Tier 3) live under `examples/wrappers/` as plain text. `docs/using-a-compendium.md` tells AI agents how to use every tier.

Each Tier 1 server is one file that speaks JSON-RPC over standard input and output, exposes one tool named `search_kb`, and answers both eras of the protocol: the stateless revision, which declares its version in every request's `_meta`, and the older `initialize` handshake that most clients still open with. The index address comes from the environment and must be HTTPS, except on the loopback address. The downloaded file is cached under a digest of its address and revalidated with a conditional request. Neither server writes anything anywhere, and neither embeds a model into the repository. The Python one uses the package Extractium™ already installs, and the Node one loads transformers.js when a search first runs. The Node example runs from a checkout rather than through `npx`, because the JavaScript client it imports is not published to a package registry.

The two Tier 2 servers share a protocol core with the Node examples (`examples/mcp/shared/`). The tool definition, the answer shape, both eras of the protocol, and the Streamable HTTP binding are written once, and each hosted example adds only where its index comes from and how it searches. The Val Town example holds the container in memory, keeps a copy in the val's blob store, and answers with BM25 alone unless an HTTP embedding service is configured, in which case it runs the clients' hybrid search unchanged. The Cloudflare example never reads the container. A build's SQLite output is exported as SQL statements and loaded into D1. That output stores each term's text once and its postings by integer term id, in a table that is its own index, and it names the layout in a `sqlite.schema` row of its `meta` table; the export and the Worker both check the row and refuse a database with another layout. BM25 ranking runs inside the database with every term bound as a parameter, and the optional Workers AI binding re-ranks those keyword candidates by vector similarity and fuses the two rankings as the clients do. That last point is the one difference in search quality: on Cloudflare a section that shares no term with the question cannot appear, hybrid or not. The Tier 3 prompts are two plain-text files under `examples/wrappers/`, one for a platform that browses and one for a platform that can call a remote tool.


## 10. Enrichment

Every section carries five enrichment fields (section 3.4). The keyword step fills four of them; the summary waits for a pass that does not exist yet.

- Keywords and tags ship with every build (`keywords: true`, the default) and need no model beyond the embedding model the build already loads, no network, and no GPU. YAKE proposes up to fifteen candidate phrases of one to three words from each section's text. The candidates are embedded and ranked by cosine similarity to the section's own vector, the mean of its windows' vectors, and the five closest that do not repeat one another (a phrase inside, or containing, one already chosen is passed over) are its `keywords`, closest first. A page's `tags` are its source's categories, then the keywords at least half of its sections share, up to eight. `enriched_at` is the build time and `enrich_ver` names the step's version. Results are stored under `.kb_cache/enrichment/keywords.json`, keyed by section id and text digest, so a rebuild recomputes only changed sections. The extractor is the optional `keywords` extra; a build without it says so and leaves the fields null.
- A summary pass, if one is added, follows these rules: a local language model only (small instruct model), GPU-gated, delta-only, parent-only. No API calls, ever. It populates `summary` through the same `.kb_cache/enrichment/` layer.


## 11. Operations

- Refresh cadence: weekly. The GitHub Actions template runs on a schedule and on a "Run workflow" button press. Publishing uses only the official GitHub Pages actions. Every action is pinned to a commit digest, and the template installs a named release of the tool.
- Two rebuild modes, chosen by the `rebuild` setting. `full`, the default, publishes exactly what the build read. `incremental` also carries forward a web page the last build published and this one did not reach, unless the server confirmed it gone with a 404 or 410 or its source left the settings file; every other source is authoritative about its own content. Full is the default because a page taken down on purpose must leave the published index on the next build. The Open Knowledge Format folder mirrors the compendium in both modes, removing only files this tool wrote.
- A build runs up to `parallel_sources` sources at once, each in a thread over the one session, and collects their documents in file order, so the rule that the first source to reach a page keeps it does not depend on which thread finished first. Progress lines are prefixed with the source label while more than one source runs. A failure in one source, or Ctrl+C, stops the others at their next progress line. Within a crawl, up to `parallel_pages` fetches are in flight while pages are taken, followed, and yielded in the one-at-a-time order, and each page's own progress lines are replayed under its line.
- Local run: `run.bat` or `run.sh` creates a virtual environment, installs pinned dependencies from a committed lock file, builds, and prints what to commit. This is the primary path for sources a cloud runner cannot reach (local folders, YouTube).
- Data and configuration are kept apart from the tool. The tool repository holds the engine. Each organization keeps a small data repository with its `config.yaml`, its transcript cache when it uses YouTube, and the published output folder. A template for that repository ships under `examples/data-repo/`.


## 12. Configuration file

The loader in `extractium/config.py` reads this schema, and the [configuration reference](configuration.md) documents every setting. Unknown keys stop the build, at the top level and inside each built-in source or output entry.

Minimal file:

```yaml
sources:
  - type: web
    label: Example Website
    seed_url: https://example.edu/TDClient/000/ExampleOrg/Home/
```

Every setting, with its default where one exists. The commented example that ships as [examples/config.example.yaml](../examples/config.example.yaml) holds the same settings with a paragraph on each, and the two are kept in step.

```yaml
name: Example Org Knowledge Base   # default: title of the first crawled page
slug: compendium                    # names the output files: <slug>.json, <slug>.sqlite
out_dir: dist                       # every adapter writes under here
cache_dir: .kb_cache
delay_seconds: 0.5                  # least time between two requests to one host
max_pages: 10000
parallel_sources: 4                 # sources run at once; 1 = one after another
parallel_pages: 4                   # page fetches a crawl keeps in flight
user_agent: Extractium/0.2 (+https://github.com/DepressionCenter/extractium)
respect_robots_txt: true
transport: auto                     # auto | browser | plain
rebuild: full                       # full | incremental
phi_lint: local                     # local | all | off
keywords: true                      # name sections with keywords and pages with tags
github_owners: []                   # extra GitHub accounts this build may follow links
                                    # into; deny by default, exact names, never patterns

sources:
  - type: web
    label: Example Website
    seed_url: https://example.edu/TDClient/000/ExampleOrg/Home/
    include_patterns: []            # empty = scope from the seed URL
    leaf_patterns: []               # single pages on other hosts the site links to; never followed
    crawl_exclude_patterns: []      # omit = handler defaults + asset extensions
    index_exclude_patterns: []
    extra_crawl_exclude_patterns: []  # added to whichever list applies
    extra_index_exclude_patterns: []
    site_handlers: [tdx, github]    # omit = all installed; [] = generic only
    read_documents: false           # fetch and read linked Word, OpenDocument, RTF, PDF, and slide files
  - type: web
    label: Example Library
    seed_urls:                      # several starting points, still one crawl
      - https://library.example/collections/first-collection
      - https://library.example/collections/second-collection
  - type: local
    label: Internal Notes
    path: ./internal-docs
    include_globs: ["**/*.md", "**/*.txt", "**/*.html"]
    read_documents: false           # true adds **/*.docx, **/*.odt, **/*.rtf, **/*.pdf, **/*.pptx, **/*.odp to the globs
  - type: github_api
    label: Example Repositories
    org: example-org                # exactly one of org, user, or url
    include_repos: []               # empty = every repository that matches
    exclude_repos: []               # an exclusion always wins
    include_forks: false
    include_archived: true
    include_code: true              # read the structure of the code, not only the docs
    ctags_fallback: true            # let Universal Ctags read languages no grammar covers
    read_documents: false           # read Word, OpenDocument, RTF, PDF, and slide files, one request each
    max_file_bytes: 2000000         # uses GITHUB_TOKEN from the environment when set
    max_repositories: 100           # alphabetical; the rest are named in the log
    max_files_per_repository: 1000  # the root README is always read first, code last
  - type: dspace
    label: Example Repository
    api_url: https://repository.example.edu/server/api
    site_url: https://repository.example.edu
    collections:
      - https://hdl.handle.net/9999.1/1001      # a handle link, or a collection identifier
    include_full_text: true
    max_file_bytes: 2000000
  - type: okf
    label: Example Bundle
    path: ./partner-okf              # an Open Knowledge Format folder, from any tool
  - type: youtube
    label: Example Video Library
    channel_id: https://www.youtube.com/@ExampleChannel   # handle, address, or id; no key needed
    playlist_ids: []
    video_ids: []
    languages: [en]
    include_playlists: true         # the channel's playlists as well as its uploads
    only_channel_videos: true       # skip playlist videos another channel published
    delay_seconds: 1                # seconds between requests to YouTube; never less than 1

outputs:                            # omit = container + llmstxt
  - type: container         # written as <slug>.json; file: overrides
    include_local: false
    gzip: false             # true writes <slug>.json.gz, the same bytes compressed
  - type: llmstxt
  - type: sqlite            # written as <slug>.sqlite; file: overrides
    include_local: true
  - type: okf
```

Keys and API tokens never go in this file. `GITHUB_TOKEN` and `YOUTUBE_API_KEY` are read from the environment, and both are optional.


## 13. Repository structure

```
extractium/
├── extractium/                  # Python package (the engine)
│   ├── core/                    # fetch, cache, chunk, embed, bm25, dedup, calibration,
│   │                            # keywords, phi_lint, registry, models, build
│   ├── sources/                 # web (core crawler); site handlers generic, tdx, github, youtube,
│   │                            # google_docs; sources local, okf, github_api, dspace, youtube
│   ├── readers/                 # Word, OpenDocument, RTF, slides (standard library) and PDF (pypdf,
│   │                            # in a killable child process) readers
│   ├── code/                    # Tree-sitter registry, engine, query files, embedded-code
│   │                            # extraction, relationships, rendering, ctags fallback
│   ├── adapters/                # container, llmstxt, sqlite_out, okf
│   ├── search.py                # Python client
│   └── cli.py                   # extractium build --config config.yaml
├── clients/
│   └── js/                      # extractium-client.js and its tests
├── plugins/                     # operator drop-in plugin dir (ships empty)
├── docs/                        # specification, architecture, configuration, container
│                                # format, design notes, how-to pages
├── examples/
│   ├── config.example.yaml
│   ├── data-repo/               # template for an organization's data repository
│   ├── mcp/                     # local-node, local-python, valtown, cloudflare
│   └── wrappers/                # hosted-assistant system prompts
├── tests/                       # pytest suite, fixtures, golden files, frozen reference script
├── .github/workflows/build-compendium.yml   # template workflow for adopters
├── run.bat / run.sh             # double-click entry points
├── requirements-lock.txt        # pinned dependencies
├── SKILLS.md                    # index of the agent skills under skills/
├── skills/                      # agent skills: project preferences and reusable guidance
├── AGENTS.md, README.md, LICENSE, NOTICE, pyproject.toml
```

Documentation serves four audiences: people building an index, core developers, plug-in developers, and AI agents consuming a compendium.


## 14. History

The design has had three revisions: v0.1 on 2026-08-16, v0.2 on 2026-09-04, and v0.3 on 2026-09-12. The git history of this page records each change. The largest were the move from three crawlers to one crawler with site handlers (v0.2), the required source `label` and container version 4 (v0.3), the optional hooks on the site-handler and source protocols (v0.3), and the `rebuild` setting (v0.3).


## Conclusion

You now know the design of Extractium™: one crawler with pluggable site handlers, one build step, several cheap outputs, and thin clients over a static file. Keep this page and the architecture page in agreement with the code.


## Additional Resources

* [Extractium™ README](../README.md): project overview and quick start.
* [Architecture](architecture.md): how the code is organized, module by module.
* [Container format](container-format.md): the main output, byte by byte.
* [GitHub repository indexing](github-repository-indexing.md): the GitHub API source and the code-analysis design, sections 5 and 8 in detail.
* [Configuration reference](configuration.md): every setting in the settings file.
* [Field Station AI](https://github.com/DepressionCenter/FieldStationAI): the project the engine was extracted from.
* [Open Knowledge Format specification](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md): the OKF v0.2 format the OKF adapter writes.
* [llms.txt proposal](https://llmstxt.org/): the convention the llms.txt adapter follows.
* [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits/): the constraints behind the Tier 2 design.
* [Val Town limits](https://www.val.town/limits): the same, for the Val Town example.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
