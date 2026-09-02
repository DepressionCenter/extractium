<!--
This file is part of Extractium™
docs/extractium-spec.md
Author(s): Gabriel Mongefranco
Created: 2026-08-16
Last Modified: 2026-09-02
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
# Extractium™ - High-Level Specification

> Extractium™ builds a compendium: a portable, static, multi-format knowledge index any LLM can consume.

- Status: Draft v0.1
- License: GPL-3.0-or-later (all dependencies must be GPLv3-compatible)
- Home: DepressionCenter GitHub organization (new repo, initialized from EFDC-Repo-Template)
- Companion: FieldStationAI consumes the JS client library as the reference implementation

---

## 1. Overview

Extractium is a lean knowledge-base compiler. It crawls an organization's public sources (TeamDynamix client portal KB, GitHub org, YouTube channel, generic websites, local files), normalizes everything into one set of parent/child text chunks with embeddings and BM25 postings, then serializes that single chunk set into multiple output formats (a "compendium") suitable for static hosting on GitHub Pages.

It is the crawling/indexing engine extracted from FieldStationAI's `build-kb-index.py`, generalized behind a config file and a plugin registry so any research center or organization can produce its own compendium.

### Design priorities (in order)

1. **Lightweight** - runs on GitHub Actions free runners and modest laptops; safe for low-resource consumers like WebLLM browser clients.
2. **Ultra fast** - one crawl, one embedding pass, N cheap serializations; aggressive caching so unchanged sources are never re-fetched.
3. **Friendly and easy** - an admin assistant can double-click a script and commit the output. Minimal required configuration; sane defaults for everything.
4. Then: security, accessibility, good software engineering.

### Non-goals

- No live server, database, or API required at any point. Output is flat files.
- No heavyweight RAG frameworks (LangChain, LlamaIndex, OpenRAG, Docker stacks).
- No cloud LLM calls during builds (PHI safety, offline-first).
- Not a documentation generator; code indexing extracts the API surface, never raw code bodies.

---

## 2. Architecture

```
config.yaml (per org)
        |
        v
+---------------------------------------------------------------+
| SOURCE PLUGINS (registry)                                     |
|   built-in: web, tdx, github, youtube-captions, local         |
|   external: plugins/ drop-in dir (same protocol)              |
+---------------------------------------------------------------+
        |
        v
+---------------------------------------------------------------+
| CORE ENGINE (not pluggable)                                   |
|   fetch + conditional-GET cache (.kb_cache/)                  |
|   extract -> parent/child chunking (small-to-big)             |
|   embed (bge-small-en-v1.5, int8 quantized)                   |
|   near-dup collapse, BM25 postings, calibration stats         |
|   PHI lint (heuristic, flag-only, never certifies absence)    |
+---------------------------------------------------------------+
        |
        v
+---------------------------------------------------------------+
| ADAPTER PLUGINS (registry)                                    |
|   built-in: container, okf, llmstxt, sqlite                   |
|   pure functions over (parents, children, meta) -> dist/      |
+---------------------------------------------------------------+
        |
        v
dist/  ->  commit to GitHub Pages (or any static host)
```

Key invariants:

- One crawl and one embedding pass per build. Adapters never re-fetch or re-embed.
- URL fetching, caching, chunking, embedding, and BM25 are **core**. Everything else is a plugin.
- Built-in sources and adapters register through the exact same registry an external plugin would use; they are plugins that happen to ship in the box and serve as reference implementations.

### Plugin protocol (duck-typed)

- Source plugin: module exposing `register()` returning a class with `name`, `__init__(config)`, `fetch()` (yields documents), `etag()` (cache hint).
- Adapter plugin: `name`, `write(parents, children, meta, out_dir)`.
- Resolution order: local `plugins/` dir > entry points > built-ins. (Git-URL plugin loading and trust gates are deferred; the protocol must not preclude them.)

---

## 3. Data model

### Chunks

- **Parents**: full sections (context units). **Children**: small overlapping windows (search units, embedded). Children reference parents by `pid`.
- **Stable IDs** (required in v1): `id = sha1(normalized_source_url + "\x00" + parent_heading_path)[:16]` on parents; children derive `id` from parent id + ordinal. IDs must survive rebuilds when content is unchanged.

### Per-parent metadata

- `source_type`: `kb` | `github` | `youtube` | `web` | `local`
- `content_type`: `article` | `readme` | `video_transcript` | `page` | ...
- `categories`: hierarchical, from source-native structure (TDX breadcrumbs, repo paths)
- `local`: boolean; true for local-filesystem sources (see section 6)
- Enrichment-ready nullable fields, reserved now, populated by a deferred enrichment phase: `summary`, `tags`, `keywords`, `enriched_at`, `enrich_ver`. Adapters serialize them when present and skip them when null.

### Embeddings

- Model: `BAAI/bge-small-en-v1.5` (browser id `Xenova/bge-small-en-v1.5`), 384 dims, int8 quantized by default.
- The asymmetric retrieval convention is part of the format contract and must be recorded in every output's metadata: queries are prefixed with `Represent this sentence for searching relevant passages: ` (trailing space included); indexed passages get no prefix. Symmetric comparisons use no prefix on either side. A model-id check alone does not catch a prefix-convention change.

---

## 4. Output formats (the compendium)

| Format | File(s) | Phase | Notes |
|---|---|---|---|
| Binary container | `kb-index.json` (name configurable) | Core | Flagship. 4-byte LE uint32 header length + minified JSON header + raw int8/float32 vector bytes. Single-file import; proven in FieldStationAI/WebLLM. `.json` extension kept for static-host friendliness. |
| OKF bundle | `okf/` dir (`index.md`, `log.md`, `concepts/*.md`) + `compendium.okf.zip` | Core | Google Open Knowledge Format (v0.2 spec); YAML frontmatter per concept; the LLM-native output. |
| llms.txt | `llms.txt`, `llms-full.txt` | Core | Root manifest + full concatenation for web-crawling LLMs. |
| SQLite | `compendium.sqlite` | Core | Python stdlib `sqlite3`, zero new deps. For non-web apps. Tables: parents, chunks, bm25_postings, vectors (BLOB). |
| gzip container variant | `--gzip` flag | Next | For self-hosted cases; browsers decode via native `DecompressionStream`. Not a format change. |
| Parquet | optional extra | Future | `[parquet]` install extra only. |
| DuckDB | optional extra | Future | `[duckdb]` install extra only. |
| JSONL + i8 pair | - | Never | No real ecosystem behind it; the container covers the use case. |

OKF **ingestion** (reading compendia produced by other OKF tools as a source) is a possible future phase.

---

## 5. Sources

| Source | Phase | Notes |
|---|---|---|
| Generic web crawl | Core | Scope rules: same-origin + prefix; TDX-aware prefix isolation (`/TDClient/<n>/`). |
| TDX client portal | Core | Content selectors, title normalization, breadcrumb categories. |
| GitHub org | Core | readme/md/txt via raw URLs (current behavior). |
| YouTube captions | Core | `youtube-transcript-api` (MIT). Captions only; near-zero compute. |
| Local filesystem | Core | With web-output guardrail (section 6). |
| GitHub code (AST) | Next | AST-based structure extraction: Python `ast` stdlib, tree-sitter (MIT) if multi-language. One "module overview" parent per significant directory (signatures + docstrings + purpose). Never raw code bodies. No LLM. |
| Whisper transcription fallback | Future | For videos with no captions. External/optional plugin. |
| OKF bundles from other tools | Future | Maybe. |

Explicitly out: Excel extraction, OAuth cloud-drive connectors (users sync to a local folder), SQL connectors (contrib plugin territory), MCP as a core-engine concern (MCP servers ship as thin examples over the client libraries; see section 8.2).

---

## 6. Local files and confidentiality

Local sources risk publishing confidential content to the web. Guardrail:

- Chunks from local sources carry `local: true`.
- Web-facing adapters (llms.txt, OKF) **exclude** local chunks by default.
- Container and SQLite (private-consumption formats) include them.
- Single override flag: `--include-local-in-web`.
- PHI lint always runs on local content. The linter may flag likely PHI and must never claim absence ("no PHI detected" wording is forbidden).

---

## 7. Cache

- `.kb_cache/` with layers: `pages/` (fetched text), `meta.json` (validators), and reserved `embeddings/` + `enrichment/` for delta builds.
- Revalidation via **conditional GET** (`If-None-Match` / `If-Modified-Since`, honoring 304), not HEAD probing.
- Content sha256 stored per page to enable future delta chunk/embed skipping.
- On CI, `.kb_cache/` persists between runs via `actions/cache` keyed on a config hash.

---

## 8. Client libraries

| Language | Phase | Notes |
|---|---|---|
| JavaScript | Core | Extracted from FieldStationAI `index.html` (container parse, int8 dequant, BM25 + cosine + RRF fusion, calibration threshold). FieldStationAI becomes the reference consumer. |
| Python | Core | Same hybrid search, mirrors the JS client. |
| Go | Next | Ships with the Go CLI (`search`, `serve`, `serve mcp`). MCP use case is confirmed; see section 8.2. |
| PowerShell | Next | IT/admin lane; no one else ships a PS vector-search client. |
| Lua | Future | |
| R | Future | Corpus analysis + hybrid search; CRAN later. Deferred, not dropped. |
| Julia | Future | |

### 8.1 Access tiers (consuming a compendium)

The compendium on GitHub Pages is the single source of truth; every access
method is a thin layer over it. Tiers, cheapest and most universal first:

| Tier | Method | Search quality | Hosting cost | Phase |
|---|---|---|---|---|
| 0 | Static compendium (`llms.txt`, `llms-full.txt`, container, SQLite) fetched directly by web-browsing agents | LLM-dependent (no ranking) | None (GitHub Pages) | Core |
| 1 | Local MCP server via `npx` (wraps the JS client; index downloaded + cached on user's machine) | Full hybrid: vector + BM25 + RRF | None (user's compute) | Next |
| 2 | Remote stateless MCP (Streamable HTTP, JSON responses, BM25-only) on Cloudflare Workers free tier and/or TDX iPaaS | BM25 only (no server-side embedding) | None / existing infra | Next |
| 3 | Platform wrappers (GPT, Gemini Gem, Copilot Studio agent): system prompt + Tier 0 URLs | LLM-dependent | None | Next |

Tier 1 is the only tier with semantic search, because query embedding runs on
the consumer's machine. Tier 2 stays BM25-only by design: the compendium
already ships postings, document lengths, and df stats, so a remote server
needs no ML runtime. `SKILLS.md` documents all tiers for AI agents.

### 8.2 MCP servers (examples, not core)

MCP servers live under `examples/mcp/`, never in the engine. Two reference
implementations:

- `examples/mcp/local-node/` - published as an npm package; runs on the
  user's machine (`npx`), fetches and caches the container from the
  compendium URL, exposes a `search_kb` tool via the JS client's hybrid
  search.
- `examples/mcp/stateless-remote/` - single-endpoint stateless Streamable
  HTTP server (POSTed JSON-RPC in, `application/json` out; no
  `Mcp-Session-Id`; `notifications/initialized` returns 202/empty).
  BM25-only. Deploy targets: Cloudflare Workers (free tier) and TDX iPaaS
  Node custom tasks. Same search code, two hosts.

Platform wrapper prompts (Tier 3) live under `examples/wrappers/` as plain
text system prompts pointing at the compendium URLs.

---

## 9. Enrichment (deferred; schema-ready now)

- Local LLM only (small instruct model), GPU-gated, delta-only, parent-only. No API calls ever.
- Populates the reserved nullable fields (`summary`, `tags`, `keywords`, `enriched_at`, `enrich_ver`) via the `.kb_cache/enrichment/` layer.
- Keyword extraction that ships now, without an LLM: YAKE (MIT, tiny) + embedding-similarity keywords.

---

## 10. Operations

- Refresh cadence: monthly, manual. GitHub Actions template with `schedule` cron + `workflow_dispatch` (the "click a button" run). GitLab CI file maintained in parallel.
- Double-click entry point for non-technical users: a wrapper script (`run.bat` / `run.sh`) that installs deps if needed, builds, and prints "commit the dist/ folder" instructions.
- Data/config separation: the tool repo holds the engine; each organization keeps a small data repo with its `config.yaml` and the published `dist/` on GitHub Pages.

---

## 11. Repository structure

```
extractium/
├── extractium/                  # Python package (the engine)
│   ├── core/                    # fetch, cache, chunk, embed, bm25, dedup, calibration, phi_lint, registry
│   ├── sources/                 # built-in source plugins: web.py, tdx.py, github.py, youtube.py, local.py
│   ├── adapters/                # built-in adapters: container.py, okf.py, llmstxt.py, sqlite_out.py
│   └── cli.py                   # extractium build --config config.yaml
├── clients/
│   ├── js/                      # reference JS client library (from FieldStationAI)
│   └── python/                  # Python client library
├── plugins/                     # user drop-in plugin dir (documented, ships empty)
├── docs/                        # this spec, plugin dev guide, consumer guide (4 audiences)
├── examples/
│   ├── config.example.yaml
│   ├── mcp/
│   │   ├── local-node/          # npm-published local MCP server (npx), wraps JS client
│   │   └── stateless-remote/    # stateless Streamable HTTP MCP, BM25-only (Workers / TDX iPaaS)
│   └── wrappers/                # GPT / Gemini Gem / Copilot Studio system prompts
├── .github/workflows/build-kb.yml   # template workflow for adopters
├── .gitlab-ci.yml               # maintainer CI
├── run.bat / run.sh             # admin-assistant double-click entry points
├── AGENTS.md                    # EFDC template conventions carried forward
├── SKILLS.md                    # guidance for AI agents consuming a compendium
├── README.md
├── LICENSE                      # GPL-3.0-or-later
├── NOTICE
└── pyproject.toml               # single-repo PyPI package; extras: [parquet], [duckdb], [dev]
```

Documentation targets four audiences: end users building an index, core developers, plugin developers, and AI agents consuming a compendium.

---

## 12. Roadmap

| Phase | Contents |
|---|---|
| **1 - Core (MVP)** | Extract engine from `build-kb-index.py` with no behavior change; conditional-GET cache fix; stable IDs; config.yaml; plugin registry; sources: web/tdx/github/youtube-captions/local (+ guardrail); adapters: container/okf/llmstxt/sqlite; PHI lint; JS + Python clients; run scripts; CI templates; docs. |
| **2 - Next** | Go CLI + Go client (`search`, `serve`, `serve mcp`); PowerShell client; GitHub code AST source plugin; gzip container flag; MCP example servers (local npm + stateless remote for Cloudflare Workers / TDX iPaaS); platform wrapper prompts (GPT, Gem, Copilot). |
| **3 - Future** | Enrichment layer (local LLM); Whisper fallback; Lua/R/Julia clients; Parquet/DuckDB extras; OKF ingestion from other tools; git-URL plugin loading with trust gates. |
| **Never** | JSONL+i8 output; Excel extraction; cloud-drive OAuth connectors; heavyweight framework dependencies; cloud-LLM enrichment. |
