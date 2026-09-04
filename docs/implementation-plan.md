<!--
This file is part of Extractium™
docs/implementation-plan.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-04
Summary: The phased plan for building Extractium™: why the project is
worth building, the design decisions the plan relies on, and eleven
phases of about one week each, with deliverables, tests, documentation,
and a done-when rule for each.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Implementation Plan

[← Back to README](../README.md)


## Summary

This page says what gets built, in what order, and how you know each step is done. It is the working plan for the project, sized so that each phase is about one week of effort for one developer. Read it before starting a phase, and update it when a phase finishes or the scope changes. The target design it builds toward is in the [specification](extractium-spec.md); what exists right now is in [Architecture and Current State](architecture.md).


## Why build this at all

Extractium turns an organization's public documentation into one static file that holds text, vectors, and keyword statistics, so a browser, a script, or a small server can search it with no database and no API. Field Station AI already runs on such a file, built by a single script. No existing crawler or "llms.txt" generator produces a searchable artifact of this kind. The idea is sound; the risk is scope. The first draft of the specification put roughly four projects' worth of work into its first phase. This plan replaces that with small phases that each leave the repository working.

Two facts from the real Field Station AI index shaped the plan:

- The file is 10.0 MB, and 77% of it is JSON. A third of that JSON is child-window text that no search step reads. Version 3 of the container drops it. See the [container format](container-format.md).
- Some hosting targets are tighter than the first draft assumed. Cloudflare Workers on the free plan allow 10 milliseconds of CPU per request, so a remote server cannot parse a multi-megabyte header on every call. That work is last in the plan, with a design that avoids the parse.


## Decisions this plan relies on

Each decision is explained in the specification. They are listed here so a reader of this page alone knows what is fixed.

1. **One web crawler, pluggable site handlers.** The generic crawler is core. TeamDynamix and GitHub page handling are plugins that ship enabled and can be turned off. They are not separate crawlers, because the crawl is one graph: a knowledge-base article links to a repository README and the same loop must follow it.
2. **Three plugin kinds, one registry.** Sources produce documents, site handlers extract content from web pages, adapters write outputs. All three resolve the same way: a local `plugins/` folder, then installed packages, then built-ins.
3. **One build step, many cheap outputs.** Fetching, chunking, and embedding happen once. Every output is a serialization of the same result.
4. **Container version 3 from the start.** No version 2 output. Field Station AI keeps its own version 2 file and is unaffected.
5. **Stable identifiers with an ordinal**, so a long section split into several parents does not produce duplicate ids.
6. **Local content is excluded from every output unless an output opts in.** Publishing is the default use, so the safe default is to leave local files out.
7. **A configuration file that lists sources and outputs**, replacing the single seed URL, before more code depends on the old shape.
8. **A truthful User-Agent and `robots.txt` by default**, both configurable, checked against the real sites before the crawler ships.
9. **Local run first, GitHub Actions second, remote servers last.**


## How phases are sized

Each phase has a goal, a list of deliverables, the tests that prove them, the documentation that must change in the same phase, and a "done when" rule. A phase is about one week for one developer. A phase that grows past that is split, not stretched. The repository must pass its test suite at the end of every phase.


## Phases

### Phase 0: Documentation and TODO comments

**Goal.** Record the settled design before code depends on it.

**Deliverables.**

- Specification revised to v0.2; architecture page lists the decisions as settled; configuration page notes the coming schema change.
- This page and the [container format](container-format.md) page.
- Every placeholder module's header and `TODO` comment describe the capability it will hold, with no reference to plan steps.

**Tests.** The existing suite still passes; the changes are comments and documentation only.

**Done when** every page above exists and a search of the code for plan-step wording finds nothing.

### Phase 1: Configuration schema, plugin registry, data models

**Goal.** Settle the shapes everything else is built on.

**Deliverables.**

- `extractium/config.py` reads a `sources:` list and an `outputs:` list plus the global settings, with per-type validation. Unknown keys still stop the build.
- `extractium/core/registry.py` resolves sources, site handlers, and adapters in the order: `plugins/` folder, installed entry points, built-ins. Entry-point groups are declared in `pyproject.toml`.
- `extractium/core/models.py` defines the `Document` and `Compendium` records and the three plugin protocols.
- A throwaway GitHub Actions workflow that requests the TeamDynamix seed page, `github.com`, and `raw.githubusercontent.com` from a runner and logs the status codes. Deleted after the result is recorded in the specification.

**Tests.** Configuration: valid files, each error message, unknown keys, per-type mistakes. Registry: precedence, duplicate names, a plugin module that fails to import. The existing 41 configuration tests are rewritten for the new schema.

**Documentation.** `configuration.md` rewritten for the new schema; `examples/config.example.yaml` updated.

**Done when** a configuration file with one web source and two outputs loads, and a plugin dropped into `plugins/` shadows a built-in of the same name.

### Phase 2: Web source, site handlers, crawl loop, stable identifiers

**Goal.** Crawl a site end to end through the new structure, matching the reference script.

**Deliverables.**

- `extractium/sources/web.py`: the crawl loop as a source. It takes the HTTP session and a progress callback as parameters; it never constructs its own session and never prints.
- `extractium/sources/generic.py` (core), `extractium/sources/tdx.py`, `extractium/sources/github.py`: site handlers. Host-specific selectors, title rules, categories, and default exclude patterns move here from `chunk.py` and `config.py`.
- `extractium/core/fetch.py`: configurable User-Agent, `robots.txt` support, progress events instead of `print`.
- `extractium/core/chunk.py`: stable parent identifiers.
- A short, throwaway check that the truthful User-Agent receives article HTML from the TeamDynamix portal. If it does not, the TDX handler documents the override.

**Tests.** Crawling the HTML fixtures yields the same parents and children as the reference script, apart from the added id fields. Handler tests migrated from `test_content_extraction.py`. A `robots.txt` disallow is honored. Identifiers are stable across two runs and distinct for split sections.

**Documentation.** Specification updated with the User-Agent check result.

**Done when** the fixture crawl matches the reference and the three handlers are selected by URL.

### Phase 3: Build step, container version 3, llms.txt, command line

**Goal.** A complete build from a configuration file to published files.

**Deliverables.**

- `extractium/core/build.py`: chunk, identify, embed, collapse near-duplicates, remap parents, build BM25 statistics, compute calibration, return one `Compendium`.
- `extractium/core/embed.py` imports the embedding library only when embedding runs, so clients and adapters import without it.
- `extractium/adapters/container.py` writes version 3. `extractium/adapters/llmstxt.py` writes `llms.txt` and `llms-full.txt`.
- `extractium build --config config.yaml`, with `--out-dir`, `--max-pages`, and `--float32-vecs`; progress on standard error; a summary at the end; non-zero exit codes on failure.

**Tests.** Container header matches a committed snapshot; vector bytes equal the reference script's for the same fixtures; `llms.txt` matches a snapshot; exit codes for a missing file, a bad configuration, and an empty crawl.

**Documentation.** `container-format.md` changes status from draft to implemented; new `data-flow.md` and `usage.md`.

**Done when** a build against the fixtures writes both outputs, and a manual run with `--max-pages 25` against the real portal produces a file the Python client in Phase 4 will open.

### Phase 4: JavaScript and Python clients

**Goal.** Read the container back and search it, identically, in two languages.

**Deliverables.**

- `clients/js/extractium-client.js`: one file, no dependencies, no build step. Parses the container, dequantizes vectors, runs cosine and BM25 retrieval, fuses them by reciprocal rank, applies the calibration threshold and diversity selection, and resolves hits to parents. The caller supplies the query vector, so the same file runs in a browser, in Node, or on an edge runtime.
- `extractium/search.py`: the same algorithm in Python, with an injected query embedder.
- A contract test: the Python suite writes a small container to `tests/golden/`, and the JavaScript tests, run with `node --test`, rank a fixed query vector against it and expect the same order.

**Tests.** Unit tests for each stage in both languages; the contract test; a malformed-file test for each reader check in the container checklist.

**Documentation.** New `how-to/search-a-compendium.md`; new `SKILLS.md` at the repository root describing how an AI agent uses the static files and the clients.

**Done when** both clients return the same ranked parents for the golden file.

### Phase 5: Operations (minimum viable product complete)

**Goal.** A non-developer can run the weekly build, locally or from GitHub.

**Deliverables.**

- `run.bat` and `run.sh`: create a virtual environment, install pinned dependencies, run the build, print what to commit.
- `requirements-lock.txt`, generated with a lock tool and committed.
- `.github/workflows/build-compendium.yml`: a template with a weekly schedule and a "Run workflow" button, a cache for `.kb_cache` keyed on the configuration file, and publishing through the official GitHub Pages actions only.
- `examples/data-repo/`: a template for an organization's own data repository (configuration, workflow, README).

**Tests.** The workflow runs on this repository against a small fixture site; the run scripts are exercised on Windows and on a POSIX shell.

**Documentation.** New `how-to/run-a-weekly-build.md`, `how-to/publish-to-github-pages.md`, `compliance.md`; `troubleshooting.md` with entries for failures actually seen.

**Done when** the example data repository builds and publishes from a button press.

### Phase 6: SQLite adapter, local files, PHI lint, guardrail

**Goal.** Index local folders safely.

**Deliverables.**

- `extractium/adapters/sqlite_out.py`: tables for metadata, parents, children, BM25 terms and postings, and vectors, with the grain of each table stated in comments.
- `extractium/sources/local.py`: reads Markdown, text, and HTML from a folder; marks every parent `local: true`; uses paths relative to the folder as URLs.
- `extractium/core/phi_lint.py`: pattern checks for likely protected health information; a report file in the working directory, never in the output folder; wording that never claims absence.
- The guardrail in the adapter base: local parents are dropped from every output unless that output sets `include_local: true`, and the command line names every output that includes them.

**Tests.** Local parents are absent from every output by default and present only when opted in. The lint flags synthetic identifiers and its output never contains the phrase "no PHI". Row counts per table match the compendium.

**Documentation.** `configuration.md` gains the local source and the `include_local` option; `compliance.md` describes the lint's limits; `data-flow.md` shows where local content can and cannot go.

**Done when** a build with a local source publishes nothing local by default.

### Phase 7: GitHub API source and OKF adapter

**Goal.** Enumerate a code organization without scraping, and write the Open Knowledge Format.

**Deliverables.**

- `extractium/sources/github_api.py`: lists an organization's repositories through the REST API, reads README and Markdown files from raw URLs, uses `GITHUB_TOKEN` when present.
- `extractium/adapters/okf.py`: one Markdown file per parent group with OKF v0.2 front matter (`type`, `title`, `description`, `resource`, `tags`, `generated`, `sources`), plus `index.md` and `log.md`. No zip file; OKF defines none.

**Tests.** API responses faked from fixtures; rate-limit handling; OKF front matter validated against the fields above.

**Documentation.** `configuration.md` gains both types; the specification's output table marks OKF as implemented.

**Done when** an organization with two repositories indexes through the API and the OKF folder opens in any Markdown viewer.

### Phase 8: Local MCP servers

**Goal.** Let an AI assistant on the user's own machine search the index.

**Deliverables.**

- `examples/mcp/local-node/`: a package run with `npx` that downloads and caches the container from its published URL, embeds queries with transformers.js, and exposes one `search_kb` tool over the JavaScript client.
- `examples/mcp/local-python/`: the same over `extractium.search`.

**Tests.** Tool call round trip against the golden container in each runtime.

**Documentation.** `how-to/connect-an-mcp-client.md`; `SKILLS.md` updated.

**Done when** an MCP client lists the tool and gets ranked parents back.

### Phase 9: YouTube source

**Goal.** Index a channel's captions.

**Deliverables.**

- `extractium/sources/youtube.py`: accepts explicit video ids, playlist ids, and a channel id; lists playlists and channels through the YouTube Data API with a key from the environment; fetches captions with `youtube-transcript-api`; caches each transcript under the cache folder; writes one document per video with parents that deep-link to a timestamp.
- The data-repository template gains a committed transcript cache, because YouTube blocks requests from cloud runners and the Actions workflow must reuse transcripts fetched locally.

**Tests.** Faked API and transcript responses; caching; the timestamp link format.

**Documentation.** `configuration.md` gains the type; `troubleshooting.md` gains the blocked-IP entry.

**Done when** a playlist indexes locally and the Actions run reuses the cache without touching YouTube.

### Phase 10: Remote MCP examples and platform prompts

**Goal.** Show how the published index is searched from a hosted endpoint, with no server of your own.

**Deliverables.**

- `examples/mcp/valtown/`: loads the container from its published URL, caches it in blob storage, and answers BM25 queries; optional embedding through an external service.
- `examples/mcp/cloudflare/`: imports the SQLite output into D1 and answers BM25 queries from it, because the free plan's 10 ms CPU budget rules out parsing the container per request; optional query embedding through Workers AI with the same model.
- `examples/wrappers/`: system prompts for hosted assistants that point at the static files.

**Tests.** Each example runs locally with its platform's development tool against the golden container.

**Documentation.** `how-to/deploy-a-remote-mcp-server.md`; the specification's access-tier table marks the tiers as implemented.

**Done when** both examples answer a query from a fresh deployment.

### After Phase 10

Not scheduled, kept in the specification as future work: an enrichment pass with a local language model; speech-to-text for videos without captions; clients in other languages; Parquet and DuckDB outputs; reading OKF bundles from other tools; loading plugins from git URLs. Migrating Field Station AI to the JavaScript client and version 3 is a task for that repository, not this one.


## Checks made outside the code

Three facts about other systems decide parts of this plan. Each is verified early and recorded in the specification when checked.

| Check | When | What it decides |
|---|---|---|
| Do GitHub Actions runners reach the TeamDynamix portal and GitHub? | Phase 1 | Whether the Actions template can build the knowledge base, or only local runs can. |
| Does the portal serve article HTML to a truthful User-Agent? | Phase 2 | Whether the default User-Agent needs a documented override for that site. |
| Does the real portal build with `--max-pages 25` open in the Python client? | Phase 3 | That the pipeline works outside the fixtures. |


## Assumptions and risks

- The person running local builds has a machine that can install the CPU build of the embedding stack (a few hundred megabytes) and download the model once (about 130 MB). A smaller runtime is a possible later improvement.
- The TeamDynamix portal and GitHub remain reachable from cloud runners. If not, the local path stays primary and the Actions template says so.
- The embedding model does not change. Changing it changes every vector and the query prefix, and would require a rebuild and a bump of the container version.


## Keeping this page current

When a phase finishes, add a one-line note under its heading with the date and the commit. When scope changes, edit the phase here and the matching section of the specification in the same change. A plan that disagrees with the code is a defect, the same as any other stale page.


## Conclusion

You now know the order of work and what "done" means for each phase. Start with the phase that follows the last completed note on this page, read the specification section it points to, and update this page when you finish.


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Extractium™ specification](extractium-spec.md) — the design each phase builds toward.
* [Architecture and Current State](architecture.md) — what exists in the repository today.
* [Container format](container-format.md) — the file written in Phase 3 and read from Phase 4 on.
* [Configuration reference](configuration.md) — the settings file as it exists now.
* [Field Station AI](https://github.com/DepressionCenter/FieldStationAI) — the project the engine was extracted from and its bundled version 2 index.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
