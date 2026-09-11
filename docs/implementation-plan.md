<!--
This file is part of Extractium™
docs/implementation-plan.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-11
Summary: The phased plan for building Extractium™: why the project is
worth building, the design decisions the plan relies on, and thirteen
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

Phase 10, the code analysis, is the one deliberate exception, and it says so in its own text. Splitting a parser layer in half would leave a release that parses code and renders nothing, which is worse than a longer phase. Every other phase keeps to the rule.


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

*Finished 2026-09-04, commit 45ac7a6. The runner reachability check was run on 2026-09-08 and its result recorded in the specification, section 6; the throwaway workflow file has been deleted.*

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

*Finished 2026-09-04 on branch `phase-2-web-crawl`. The portal serves article HTML to the truthful User-Agent; no override is needed (specification, section 6).*

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

*Finished 2026-09-08 on branch `phase-3-build-and-outputs`. The local-content guardrail moved forward from Phase 6 into `extractium/adapters/base.py`, so no adapter was ever written without it; Phase 6 keeps the local source, the PHI lint, and the command-line notice.*

### Phase 4: JavaScript and Python clients

**Goal.** Read the container back and search it, identically, in two languages.

**Deliverables.**

- `clients/js/extractium-client.js`: one file, no dependencies, no build step. Parses the container, dequantizes vectors, runs cosine and BM25 retrieval, fuses them by reciprocal rank, applies the calibration threshold and diversity selection, and resolves hits to parents. The caller supplies the query vector, so the same file runs in a browser, in Node, or on an edge runtime.
- `extractium/search.py`: the same algorithm in Python, with an injected query embedder.
- A contract test: the Python suite writes a small container to `tests/golden/`, and the JavaScript tests, run with `node --test`, rank a fixed query vector against it and expect the same order.

**Tests.** Unit tests for each stage in both languages; the contract test; a malformed-file test for each reader check in the container checklist.

**Documentation.** New `how-to/search-a-compendium.md`; new `SKILLS.md` at the repository root describing how an AI agent uses the static files and the clients.

**Done when** both clients return the same ranked parents for the golden file.

*Finished 2026-09-08 on branch `phase-4-5-clients-and-operations`. The cross-encoder reranker the original browser code runs after diversity selection was left out: it needs a second model, and the specification does not list one for the clients.*

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

*Finished 2026-09-08 on the same branch as Phase 4. The lock file is generated with `uv pip compile --universal --generate-hashes`. The workflow's shape is pinned by tests, but no scheduled run has completed on GitHub yet, so the button-press check is still owed; the run scripts were exercised on Windows only.*

### Phase 6: SQLite adapter, local files, PHI lint, guardrail

**Goal.** Index local folders safely.

**Deliverables.**

- `extractium/adapters/sqlite_out.py`: tables for metadata, parents, children, BM25 terms and postings, and vectors, with the grain of each table stated in comments.
- `extractium/sources/local.py`: reads Markdown, text, and HTML from a folder; marks every parent `local: true`; uses paths relative to the folder as URLs.
- `extractium/core/phi_lint.py`: pattern checks for likely protected health information; a report file in the working directory, never in the output folder; wording that never claims absence.
- The command line's notice naming every output that includes local content. The guardrail itself, in `extractium/adapters/base.py`, was written in Phase 3 with the first two adapters, so no output has ever shipped without it.

**Tests.** Local parents are absent from every output by default and present only when opted in. The lint flags synthetic identifiers and its output never contains the phrase "no PHI". Row counts per table match the compendium.

**Documentation.** `configuration.md` gains the local source and the `include_local` option; `compliance.md` describes the lint's limits; `data-flow.md` shows where local content can and cannot go.

**Done when** a build with a local source publishes nothing local by default.

*Finished 2026-09-09 on branch `phase-6-local-files-and-sqlite`. The pattern set grew beyond the four rules this phase first scoped: it now covers the HIPAA Safe Harbor identifiers a pattern can reach, in two tiers, with the date rules anchored to a birth or clinical label so ordinary documentation is not flagged. The lint writes two reports, one for a program and one for a person, and neither copies the text it matched. No dependency was added; the gap that leaves is recorded in `compliance.md`. The command-line notice shipped in Phase 3 with the guardrail.*

### Phase 7: GitHub API source

**Goal.** Read a code organization through the API instead of scraping it, and keep working when there is no token or no API at all.

The detailed design for this phase and the next is [GitHub repository indexing](github-repository-indexing.md). Read it first.

**Deliverables.**

- `extractium/sources/github_api.py`: resolves an organization, a user, or one repository; enumerates repositories with pagination; takes a complete tree inventory, walking subtrees when GitHub marks the recursive tree truncated; filters paths before downloading anything; indexes documentation and selected project manifests in full; uses `GITHUB_TOKEN` when present.
- The three-tier ingestion ladder, applied the same way to an explicit `github_api` source and to a `web` seed that points at GitHub: authenticated API, then unauthenticated API with the same capability, then a documentation-only crawl that runs no code analysis. A refused token drops a tier rather than failing the build.
- A per-run ledger of URLs already turned into documents, so a demotion neither loses a repository nor fetches one twice, and the requested scope survives the demotion.
- A coverage report: every repository's tier, named in the progress output and in the build summary.
- Blob caching by SHA under `.kb_cache/github/`, and rate-limit handling that reads the response headers.
- Two `content_type` values: `manifest` and `repo_map`.
- The GitHub site handler gains the hook that offers the API source for a GitHub seed URL. The web source stays host-agnostic.
- The account guardrail: a GitHub account is read only when the operator named it, as a source or in the new global `github_owners` setting. Being allowed lets links into that account be followed; only naming an account as a source lists the whole account. Enforced both in API promotion and in crawl scope, because a GitHub seed makes every account on the host same-origin. Skipped accounts are counted and reported once. This needs an optional scope hook on the site-handler protocol, which `derive_auto_prefix` already records as missing; the TeamDynamix rule stays in core for now.

**Tests.** Every API response faked from committed fixtures; no test contacts GitHub. Organization, user, and repository scopes; truncated trees and subtree walking; rate-limit headers and 401, 403, 404, and 429; each rung of the ladder including a refused token and a failure partway through a run; scope preserved and nothing fetched twice after a demotion; the file filter across manifests, binaries, oversized files, `.env`, and `.env.example`; an unnamed account linked from a README, a fork notice, and a contributor profile is read by neither the API nor the crawler, on `github.com`, `raw.githubusercontent.com`, and `github.io` alike; a `github_owners` entry is followed but never enumerated whole; no token in any output, log, or cache file.

**Documentation.** `configuration.md` gains the full `github_api` option set; `examples/config.example.yaml` gains the example; the specification's source table is updated; `github-repository-indexing.md` records what the checks found.

**Done when** an organization indexes through the API with a token, indexes identically without one, still produces its documentation with a coverage note when the API cannot be used at all, and reads no account the operator did not name.

*Finished 2026-09-09 on branch `phase-7-github-api-source`. The source is three modules rather than one: the REST transport, the path rules, and the source itself, because one file holding all three would have been about nine hundred lines. Two things came out differently from the design. Walking a truncated tree is keyed on each folder's path, not on its tree object: two folders with identical contents share one object name, and keying on that silently loses every file in the second one, which a test now pins. And the file classifier checks manifests before documentation, so `requirements.txt` keeps the label that says what it is instead of being read as prose. Review changed one default: a repository is read as one archive whenever it fits in memory, rather than only when many files are wanted. Requests are what a build runs out of, not bytes. Files taken out of an archive are stored under their blob names, so the archive route and the single-file route share one cache and an unchanged repository downloads nothing. The site-handler protocol gained the three optional hooks the design asked for; the TeamDynamix scope rule could now move out of core and has not, since that is not this phase's work.*

### Phase 8: Browser-compatible transport for challenged sites

**Goal.** Read a site that sits behind a bot-protection service, without running a browser and without pretending to be a person.

The design is [Reading a site behind bot protection](bot-protection-transport.md). Read it first; the behaviour was measured against three live sites and the findings are recorded there.

**Why it is needed.** Three of the Eisenberg Family Depression Center's own five sources answer `403` with `cf-mitigated: challenge` to every request the crawler makes. The center cannot change the rule: the service is managed by the university, and a skip rule for a crawler is exactly what such a rule exists to refuse. Measured on 2026-09-10, the refusal has nothing to do with the `User-Agent`, which is what made it look unfixable: a real Chrome `User-Agent` is refused identically. It is the TLS handshake that is being read, and a crawler that completes the handshake the way a browser does is served normally, with no challenge raised and no script run.

**Deliverables.**

- A transport layer under `extractium/core/transport.py`: one function that returns the session the fetch layer should use, so the choice of transport is made in one place and every source inherits it.
- `curl_cffi` as a runtime dependency, pinned in `requirements-lock.txt`, with its bundled native library recorded in `compliance.md`.
- The crawler keeps its own `User-Agent`. It identifies itself as Extractium, with the project address, on every request. Only the handshake changes.
- `robots.txt` is still read and still obeyed, and is still fetched before anything else. A site that refuses the crawler in `robots.txt` stays refused; this phase changes what a server will talk to, never what the crawler is allowed to ask for.
- Conditional requests preserved: `If-None-Match` and `If-Modified-Since` must still produce `304`, or every rebuild becomes a full refetch.
- A `transport` setting with values `auto`, `browser`, and `plain`. `auto` is the default: a plain request first, and a single retry over the browser transport when a response is a challenge. A build says which transport served each host, once per host, so the choice is never invisible.
- The three-line explanation a person needs when a site is refused for a reason this phase cannot fix, such as an address-based block.

**Tests.** Every response faked; no test contacts a live site. A challenged response retried once and only once; a plain `403` that is not a challenge left alone; `robots.txt` still obeyed when the browser transport is in use; a conditional request still returning `304`; the per-host report naming the transport; `transport: plain` refusing to retry; the delay between requests still applied on the retry path; no cookie, header, or fingerprint written to the cache or any output.

**Documentation.** `bot-protection-transport.md` records what was measured and when; `configuration.md` gains the `transport` setting; `compliance.md` gains the new dependency and the honest-identification posture; `troubleshooting.md` replaces the "site refuses the crawler" entry; `examples/config.efdc.yaml` loses its warning block.

**Done when** all five Depression Center sources index from one build, the crawler still names itself Extractium on every request, `robots.txt` is still obeyed, a second build of an unchanged site downloads nothing, and the build reports which transport served each host.

### Phase 9: DSpace repository source

**Goal.** Index scholarly deposits held in a DSpace repository, starting with the University of Michigan Library's Deep Blue.

The design is [Indexing a DSpace repository](dspace-repository-indexing.md). Read it first; the interface was checked against Deep Blue and the findings are recorded there.

**Why it is not a crawl.** A Deep Blue collection page is about 650 KB of markup holding roughly 2,300 characters of navigation text, with the list of deposits absent from the HTML. The repository publishes a machine interface instead, and that interface already holds the text of every deposited file, extracted when the file was deposited.

**Deliverables.**

- `extractium/sources/dspace.py`: reads named collections through the DSpace 7 interface; one document per deposit, carrying its abstract, authors, date, subjects, rights, identifiers, and the extracted text of its files.
- Built as `dspace` rather than as Deep Blue. Nothing in it is specific to one repository; the two addresses and the two collection identifiers are settings.
- The three kinds of address in `dc.identifier.uri` told apart and all kept: the handle, the DOI, and whatever else the depositor pointed at, which is often the project's own documentation.
- Text read from the repository's own `TEXT` bundle. No PDF library, no Word reader, no archive handling, and no new dependency.
- Incremental builds from the `lastModified` the listing carries per deposit: a collection nobody has touched costs one request and downloads nothing.
- Collections are named in the settings file, never discovered. The same rule as `github_owners`, for the same reason.
- `repository` added to the `source_type` vocabulary.
- No fall back to crawling. The pages a crawler could reach hold no deposits, so an unreadable interface is reported and the source stops.

**Tests.** Every response faked from committed fixtures; no test reaches Deep Blue. Paging; an empty collection and one that does not exist; the three identifier kinds told apart; a deposit with extracted text, one with none, and one whose only file is an image; the size ceiling; an unchanged collection downloading nothing; a withdrawn deposit disappearing; an identifier that is not a UUID refused; an interface address that answers HTML reported clearly.

**Documentation.** `configuration.md` gains the type; the specification's source table gains the row; `dspace-repository-indexing.md` records what the checks found; `compliance.md` gains the posture, in particular that the check for protected health information covers extracted document text.

**Done when** both Deep Blue collections index from their identifiers alone, every deposit carries its abstract and its identifiers, a deposit whose file holds no readable text is still indexed and says so, and a second build of an unchanged collection downloads nothing.

*Finished 2026-09-10 on branch `phase-9-dspace-source`. The source is two modules, the interface client and the source itself, as the GitHub source is. Three checks against Deep Blue changed the design. The listing takes `embed=bundles/bitstreams`, which was an open question: one request now brings back a hundred deposits with their metadata, their change stamps, and every file attached to them, so nothing costs a second request per deposit. A handle resolves through the interface's own `pid/find` address, which answers with a redirect naming the record it belongs to, so a collection can be configured as the handle link a repository publishes rather than only as an identifier, and a handle naming one deposit is refused rather than searched. And the reason a collection is confirmed before it is searched turned out to be safety rather than convenience: a search scope the interface does not recognize is answered with the whole repository, all 176,555 deposits of it, so a typo would have indexed a university's holdings. Two smaller findings: one deposit's extracted text is a single newline, so the source counts readable text rather than counting bundles, which puts the coverage at 35 of 42 rather than 36; and a deposit's text is stored only when it was read whole, so raising `max_file_bytes` takes effect on the next build instead of waiting for the deposit to change. One thing the design asked for is not done: it said the check for protected health information must cover extracted document text, and the default `phi_lint: local` does not, because a deposit in a public repository was published deliberately. Setting `phi_lint: 'all'` covers it; the gap and the lever are written down in `compliance.md` rather than left implicit. Categories hold the collection name alone, not the label as well, since the configuration applies the label to every record after the source runs.*

### Phase 10: Lightweight static code analysis

**Goal.** Make code findable — where a symbol is defined, what a file holds, what imports and calls it — with no clone, compiler, Language Server Protocol client, or language model.

**This phase is larger than one week, and is planned that way.** It is not split further, because a parser layer that produces records nothing renders is worse than no parser layer. The design is in [GitHub repository indexing](github-repository-indexing.md).

**Deliverables.**

- `extractium/code/`: a language registry, a Tree-sitter engine driven by per-language query files, an extractor for code embedded in notebooks, R Markdown, Lua Server Pages, and HTML, a relationship resolver, a deterministic renderer, and an optional Universal Ctags fallback.
- Language coverage for Python, JavaScript, TypeScript, R, shell, Lua, C#, HTML, Markdown, SQL, Kotlin, Swift, PowerShell, and MATLAB, each subject to a recorded license, maintenance, and cross-platform wheel check. Stata is expected to fall to the file-metadata tier; whatever it does, the reason is recorded.
- File records and symbol records carrying structure, never source bodies, per the specification, section 5. File summaries come from the file's own documentation, its header `Summary:` line, its directory README, or a template over parser facts — never from a guess.
- Import edges; call edges labelled `resolved`, `probable`, or `unresolved`; reverse edges computed from the finished graph.
- One repository map per repository, naming the tier that read it, and one owner map for an owner-level request.
- Analysis caching keyed on blob SHA, parser, grammar, and schema version.
- Two `content_type` values: `code_file` and `code_symbol`.
- The fix for near-duplicate collapse treating two symbols in one file as two pages, which otherwise drops legitimate near-identical symbols.

**Tests.** Per-language fixtures for every supported capture, including a file with recoverable syntax errors; embedded code in `.Rmd`, `.ipynb`, `.lsp`, and HTML, with notebook outputs never read; relationship resolution across a small synthetic repository at all three confidence levels; a fake Ctags executable proving no shell invocation and refusal of malformed output; cache invalidation on each key; a test that near-identical symbols in one file all survive; the security set — archive paths, symbolic links, traversal, shell characters and newlines in filenames, invalid UTF-8, impossible declared sizes.

**Documentation.** `github-repository-indexing.md` records every gate result; `compliance.md` gains the no-execution and untrusted-content posture and the new dependencies; `architecture.md` and the specification's source table are updated; `configuration.md` gains `include_code` and `ctags_fallback`.

**Done when** every listed language is parsed, analyzed by Ctags, or recorded at the metadata tier with the reason written down; symbol records carry structure and links but no bodies; maps name their tier; and the parser set installs and runs on Windows, macOS, and Linux on the oldest and newest supported Python versions.

*Finished 2026-09-11 on branch `phase-10-code-analysis`. The parser layer is seven modules and thirteen query files under `extractium/code/`, and the whole parser set is an optional install (`extractium[code]`) rather than a requirement, so a documentation-only build carries none of it and a machine without it still records every source file by name. The dependency gate changed two things. R, which the design gave high confidence, has no grammar published to the Python package index at all — a search of the whole index found 289 `tree-sitter` packages and none for R — so R falls to Universal Ctags where it is installed and to a file-level record where it is not; this is the largest gap in the phase and it is named in every repository's summary record rather than left silent. And the language bundle that would have closed it stopped shipping its grammars at version 1.0: it now downloads compiled grammars from the network on first use, which is the same risk this project refused when it removed the reference script's install-at-import helper, so fourteen individually pinned MIT-licensed packages were taken instead. Stata was settled as the design recommended: a file-level record, and no pattern-matching reader pretending to parse it. Two bugs the design half-predicted were found and fixed: near-duplicate collapse treated two definitions in one file as two pages, and — worse, because nothing had predicted it — the step that indexes a page once compared normalised addresses, which have no fragment, and threw away 1,809 of 1,944 records on a real repository before it was caught. Both are pinned by tests. The cache key gained a seventh part, a fingerprint of this project's own query file, because editing extraction rules must reparse. The Lua Server Pages delimiters were checked against the implementations rather than assumed, which the design had asked for and which paid: the Kepler project's Lua Pages forms and RealTime Logic's Barracuda Application Server `<?lsp` form are both read, and an XHTML page's opening `<?xml` line is not mistaken for Lua. Verified end to end against this project's own repository: 95 code files analyzed, 1,944 records, and the protected-health-information check run over all of them with `phi_lint: 'all'`.*

### Phase 11: Open Knowledge Format output

**Goal.** Write the Open Knowledge Format, as an output of equal standing to the container file.

This has nothing to do with GitHub. It is a serialization of whatever the build produced, and it must work identically for a TeamDynamix portal, a local folder, and a code repository. It is a phase of its own so that it is never built around one source's shape.

**Deliverables.**

- `extractium/adapters/okf.py`: one Markdown file per parent group with OKF v0.2 front matter (`type`, `title`, `description`, `resource`, `tags`, `generated`, `sources`), plus `index.md` and `log.md`. No archive; OKF defines none.
- Local parents dropped unless the output opts in, through the shared adapter base, as for every other output.

**Tests.** Front matter validated against the fields above; the same compendium written from a portal crawl, a local folder, and a GitHub source produces the same structure with no source-specific branches; the local-content guardrail holds.

**Documentation.** `configuration.md` marks the `okf` output as implemented; the specification's output table does the same.

**Done when** the folder opens in any Markdown viewer and the adapter contains no reference to any particular source.

### Phase 12: Local MCP servers

**Goal.** Let an AI assistant on the user's own machine search the index.

**Deliverables.**

- `examples/mcp/local-node/`: a package run with `npx` that downloads and caches the container from its published URL, embeds queries with transformers.js, and exposes one `search_kb` tool over the JavaScript client.
- `examples/mcp/local-python/`: the same over `extractium.search`.

**Tests.** Tool call round trip against the golden container in each runtime.

**Documentation.** `how-to/connect-an-mcp-client.md`; `SKILLS.md` updated.

**Done when** an MCP client lists the tool and gets ranked parents back.

### Phase 13: YouTube source

**Goal.** Index a channel's captions.

**Deliverables.**

- `extractium/sources/youtube.py`: accepts explicit video ids, playlist ids, and a channel id; lists playlists and channels through the YouTube Data API with a key from the environment; fetches captions with `youtube-transcript-api`; caches each transcript under the cache folder; writes one document per video with parents that deep-link to a timestamp.
- The data-repository template gains a committed transcript cache, because YouTube blocks requests from cloud runners and the Actions workflow must reuse transcripts fetched locally.

**Tests.** Faked API and transcript responses; caching; the timestamp link format.

**Documentation.** `configuration.md` gains the type; `troubleshooting.md` gains the blocked-IP entry.

**Done when** a playlist indexes locally and the Actions run reuses the cache without touching YouTube.

### Phase 14: Remote MCP examples and platform prompts

**Goal.** Show how the published index is searched from a hosted endpoint, with no server of your own.

**Deliverables.**

- `examples/mcp/valtown/`: loads the container from its published URL, caches it in blob storage, and answers BM25 queries; optional embedding through an external service.
- `examples/mcp/cloudflare/`: imports the SQLite output into D1 and answers BM25 queries from it, because the free plan's 10 ms CPU budget rules out parsing the container per request; optional query embedding through Workers AI with the same model.
- `examples/wrappers/`: system prompts for hosted assistants that point at the static files.

**Tests.** Each example runs locally with its platform's development tool against the golden container.

**Documentation.** `how-to/deploy-a-remote-mcp-server.md`; the specification's access-tier table marks the tiers as implemented.

**Done when** both examples answer a query from a fresh deployment.

### After Phase 14

Not scheduled, kept in the specification as future work: an enrichment pass with a local language model; speech-to-text for videos without captions; clients in other languages; Parquet and DuckDB outputs; reading OKF bundles from other tools; loading plugins from git URLs. Optical character recognition for image-only deposits, and reading DSpace communities rather than named collections, sit here too. Migrating Field Station AI to the JavaScript client and the current container version is a task for that repository, not this one.


## Checks made outside the code

Three facts about other systems decide parts of this plan. Each is verified early and recorded in the specification when checked.

| Check | When | What it decides |
|---|---|---|
| Do GitHub Actions runners reach the TeamDynamix portal and GitHub? | Phase 1 | Whether the Actions template can build the knowledge base, or only local runs can. Checked 2026-09-08: all three URLs answered 200 from an `ubuntu-24.04` runner, so a cloud build works. |
| Does the portal serve article HTML to a truthful User-Agent? | Phase 2 | Whether the default User-Agent needs a documented override for that site. Checked 2026-09-04: it does; no override. |
| Does the real portal build with `--max-pages 25` open in the Python client? | Phase 3 | That the pipeline works outside the fixtures. Checked 2026-09-08 at 500 pages: the build produces the same sections, windows, keyword statistics, and vector bytes as the reference script, and the file passes every step of the reader checklist. |


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
* [GitHub repository indexing](github-repository-indexing.md) — the detailed design for Phases 7 and 10.
* [Indexing a DSpace repository](dspace-repository-indexing.md) — the detailed design for Phase 9.
* [Reading a site behind bot protection](bot-protection-transport.md) — the detailed design for Phase 8, with what was measured against three live sites.
* [Configuration reference](configuration.md) — the settings file as it exists now.
* [Field Station AI](https://github.com/DepressionCenter/FieldStationAI) — the project the engine was extracted from and its bundled version 2 index.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
