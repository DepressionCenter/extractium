<!--
This file is part of Extractium™
docs/implementation-plan.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-12
Summary: The phased plan for building Extractium™: why the project is
worth building, the design decisions the plan relies on, and the
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

*Finished 2026-09-12 on branch `feat-compendium-slug`, four phases late. The design was measured on 2026-09-10 and then mistaken for shipped, which the documentation audit for Phase 15 caught: the plan had no finished note, the design page said "Planned", and the Depression Center's own settings file still carried its warning block. What shipped is the design as written, in one module, `extractium/core/transport.py`: one function returns the session a build fetches through, and the automatic session retries a challenged request once over the browser handshake and keeps that choice per host. Two details the design did not spell out. `robots.txt` does not settle a host's transport, because the filter never challenges a static file, so a host's first plain success on `robots.txt` said nothing and, in the first run, produced a misleading "plain" line before the "browser" one. And the browser session is built on first need rather than at start, so a build that is never challenged never loads the native library. `curl_cffi` 0.16.3 is the dependency, pinned with hashes for every wheel; the lock was regenerated with the documented command and gained only it, `cffi`, and `pycparser`. Verified against the live sites the same day: a build with `depressioncenter.org` and `code.depressioncenter.org` as seeds read eight pages, both hosts reported over the browser transport once each, and the cache held page text and validators only. The done-when rule's first clause, all five sources in one build, is covered by the EFDC settings file this change completes; it was not run whole here, because a full build of every source takes hours and this check needed only the challenged hosts.*

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

*Finished 2026-09-11 on branch `phase-11-okf-output`. The adapter is one module, `extractium/adapters/okf.py`, and it writes `okf/` under the output folder: the two reserved files at the root, and one concept file per page filed under the name of the source that produced it. Grouping by that name, rather than by the kind of source, is the only grouping that keeps the writer source-agnostic: the name is a setting the operator wrote, and a test reads the module's own text to prove no source is named in it. Three decisions came out of reading the format's specification rather than the plan. `type` is the only field it requires, so it carries the record's content type in words ("Project README", "Code Symbol"), with a fallback for a content type a plugin invents. Front matter is written by the YAML library instead of by hand, because a page title holding a colon or a quotation mark would otherwise end the block early and turn the page's own text into metadata. And file names are built from an allowlist plus a digest of the address, so a title of `../../etc/passwd`, or of `CON`, cannot decide where a file lands. Running it over this project's own `/docs` folder found the one thing no unit test would have: every page there carries the same first heading, so all eighteen concepts were named "Extractium" and the index offered eighteen identical links. A page whose title is shared now carries the end of its address as well, in its file name, its index link, and its own title. Two smaller things surfaced while building it: the summary line the command prints named every file written, which a folder of hundreds turns into an unreadable wall, so an output that writes more than eight files is now summarized as a folder with a count; and the helpers the two Markdown writers share moved into `extractium/adapters/base.py` rather than being written twice. The folder is never pruned, because deleting files nobody asked to delete is the worse failure; `log.md` names the build that last wrote it, and the gap is recorded in `compliance.md`.*

### Phase 12: Local MCP servers

**Goal.** Let an AI assistant on the user's own machine search the index.

**Deliverables.**

- `examples/mcp/local-node/`: a package run with `npx` that downloads and caches the container from its published URL, embeds queries with transformers.js, and exposes one `search_kb` tool over the JavaScript client.
- `examples/mcp/local-python/`: the same over `extractium.search`.

**Tests.** Tool call round trip against the golden container in each runtime.

**Documentation.** `how-to/connect-an-mcp-client.md`; `SKILLS.md` updated.

**Done when** an MCP client lists the tool and gets ranked parents back.

*Finished 2026-09-11 on branch `phase-12-local-mcp-servers`. Two servers, one file each, over the client library in the same repository. Reading the protocol before writing them changed the shape of both: the current revision, 2026-07-28, has no `initialize` handshake at all — it is stateless, every request declares its own version in `_meta`, and a server must answer `server/discover` — while every client shipping today still opens with `initialize` against one of the older revisions. Each server therefore answers both eras, decided per request, and a request naming a revision neither era covers is refused with the list of revisions it does speak rather than half-served. Neither server takes a dependency on a protocol library; the whole transport is newline-delimited JSON-RPC, which is a hundred lines and no supply chain. The `npx` delivery the plan named is not done, and the reason is structural rather than incidental: the package would have to carry the JavaScript client, which is not published to any registry, so the Node server runs from a checkout by path and both READMEs say so. Publishing the client is the prerequisite, and it is not this phase's work. The index address is configuration rather than an argument, and it must be HTTPS away from the loopback address, because an assistant that reads a swapped index cannot tell. The download is cached under a digest of its own address and revalidated with a conditional request, and an unreachable host falls back to the cached copy rather than failing a question a person asked. Every answer opens with the line saying the sections are quoted evidence and not instructions, which is the same rule `SKILLS.md` states, moved to where a model actually reads it. One thing the golden compendium cannot test: its vectors come from a stand-in embedder, so every query matches everything, and the empty-result path had to be exercised with a compendium that returns nothing rather than with a question nobody asked. The Node package's one dependency, transformers.js, reaches two packages with high-severity advisories, in image decoding and in install-time unpacking, through version ranges that stop short of the releases that fix them; two `overrides` entries lift both to patched versions, and the embedding model was then run end to end on that tree to confirm the lift holds.*

### Phase 13: YouTube source

**Goal.** Index a channel's captions.

**Deliverables.**

- `extractium/sources/youtube.py`: accepts explicit video ids, playlist ids, and a channel id; lists playlists and channels (optionally through the YouTube Data API with a key from the environment); fetches captions with `youtube-transcript-api` or web crawling; caches each transcript under the cache folder; writes one document per video with parents that deep-link to a timestamp.
- The data-repository template gains a committed transcript cache, because YouTube typically blocks requests from cloud runners and the Actions workflow may have to reuse transcripts fetched locally.

**Tests.** Faked API and transcript responses; caching; the timestamp link format.

**Documentation.** `configuration.md` gains the type; `troubleshooting.md` gains the blocked-IP entry.

**Done when** a playlist indexes locally and the Actions run reuses the cache without touching YouTube.

*Finished 2026-09-11 on branch `phase-13-youtube-source`. The captions come from `youtube-transcript-api` rather than from crawling, which the deliverable left open: it is MIT-licensed, its only dependency beyond `requests` is `defusedxml`, and it carries no advisory, while scraping captions means parsing the player's own response and breaking whenever that changes. It is an optional install, `extractium[youtube]`, for a reason that turned out to matter more than the download size: a build that reads only stored transcripts never calls it, and that is exactly the build a hosted runner performs, so a scheduled run needs the package not at all. One deliberate departure from the deliverable's wording: a video becomes one document per stretch of transcript rather than one document with several parents, because a parent's address is the document's address and the timestamp has to live in the address for a citation to open the video at the quoted words. That made the section grain visible in two outputs -- `llms.txt` and the OKF bundle both group by address, so a forty-minute talk would have listed as twenty pages -- and both now group a video's stretches back into the video, through one helper in `adapters/base.py` scoped to this source type, because `t` means something else on other sites. Two other things the service forced: a channel's uploads playlist is derived from its id by swapping the leading `UC` for `UU`, which saves a request per channel, and a build with no API key names videos through the public oEmbed endpoint, so explicit `video_ids` still get real titles instead of bare identifiers. The store is the part to understand before changing anything here. Nothing under `<cache_dir>/youtube/` is revalidated, and that is not an oversight: YouTube refuses caption requests from cloud-provider addresses, so a runner cannot check a transcript even to confirm one it already holds. A stored transcript is therefore authoritative until somebody deletes the file, the data-repository template names a visible `cache_dir` so the folder can be committed, and `kb-cache/README.md` there says so in the place an operator will look. The key never reaches a message: the Data API takes it as a query parameter, so a failed request is reported by name rather than by quoting the exception, which would carry the whole address, and a test checks every classified answer for it. Verified end to end against real YouTube: a public video's captions fetched, chunked, embedded, and written, then the same build repeated behind a dead proxy with the model offline, which succeeded from the store alone and reported `1 from the cache, 0 fetched from YouTube`. The playlist half of the done-when rule is covered by tests against a faked Data API and not against the live one, because listing needs a key this machine does not have.*

*Extended the same day, still on branch `phase-13-youtube-source`, after the first version proved unusable for its actual purpose: pointing it at a real channel. A channel had to be named by its id, and nobody has that; what a browser shows is `youtube.com/@Name`. So a channel, a playlist, and a video may now each be written as an identifier or as any address that names one, resolved once against the channel's own page and stored, and checked when the settings file is read rather than halfway through a build. Listing without an API key follows, from YouTube's own pages, which makes the whole source work with no credential. Two things bounded that. YouTube's robots.txt allows the channel and playlist pages but disallows `/youtubei/`, the endpoint a page calls for its next batch, so the keyless path reads the newest hundred of a listing and says which listings it stopped short on; paging further and the one browser-identity retry a refused page gets both sit behind `respect_robots_txt: false`, the switch phase 8 already defined, rather than behind a new rule of this source's own. And a page carries continuation tokens for shelves unrelated to the listing, so a short listing is treated as complete: without that a four-video playlist claimed to be truncated, and thirty playlists each said so at length. A channel's uploads playlist is read rather than its videos tab, because it holds the shorts and past streams the tab omits and serves a hundred per request rather than thirty, and because a channel with no shorts answers those tabs with its home page, whose shelves carry other people's videos. The playlists a channel shows are read too, which raised the question the operator asked next: a playlist holds whatever its owner chose, so a video in one is indexed only when one of the configured channels published it, from the publisher the Data API and the public endpoint each already report. Verified against the live channel: `@DepressionCenter` resolved, 245 videos and 36 playlists with robots off, 100 and 30 with it respected. That run also found the last defect, which no test would have: after about 145 requests YouTube began refusing this machine, and one refusal threw away a build that had already read a hundred videos. A block now keeps what was read, stops asking, and reports the build as incomplete; it is fatal only when nothing was read at all. A YouTube address may also be a crawl seed now, through the same `offer_source` hook the GitHub handler uses: a site handler recognises a channel, playlist, or watch address and hands the seed to the video source, so `seed_url: https://www.youtube.com/@ExampleChannel` reads captions rather than crawling a player page. The handler refuses every YouTube address for crawling in the other direction, and counts what it held back, because a crawled YouTube page yields a title and nothing else. Verified with a real seed: a watch address produced 25 sections and one `llms.txt` entry under the video's own title, with the build offline and reading only the committed store.

Still not built: following a YouTube link found while crawling something else and indexing it. The handler sees such a link and reports it, but the crawl drops an off-host link before any handler is consulted about following it, so collecting those links and handing them to the video source needs a hook in the crawler's own link pipeline rather than a change to this source. That is a core change with its own review, and it belongs in its own phase.*

### Phase 14: Remote MCP examples and platform prompts

**Goal.** Show how the published index is searched from a hosted endpoint, with no server of your own.

**Deliverables.**

- `examples/mcp/valtown/`: loads the container from its published URL, caches it in blob storage, and answers BM25 queries; optional embedding through an external service.
- `examples/mcp/cloudflare/`: imports the SQLite output into D1 and answers BM25 queries from it, because the free plan's 10 ms CPU budget rules out parsing the container per request; optional query embedding through Workers AI with the same model.
- `examples/wrappers/`: system prompts for hosted assistants that point at the static files.

**Tests.** Each example runs locally with its platform's development tool against the golden container.

**Documentation.** `how-to/deploy-a-remote-mcp-server.md`; the specification's access-tier table marks the tiers as implemented.

**Done when** both examples answer a query from a fresh deployment.

*Finished 2026-09-12 on branch `phase-14-remote-mcp`. The first thing built was neither example but the layer under them: the Node local server's protocol handling, tool definition, and answer rendering moved into `examples/mcp/shared/`, and a Streamable HTTP binding was written beside them once, because two hosted servers each carrying their own copy of both eras of the protocol was the duplication the engineering rules forbid. The binding is the protocol's stateless form only: one POST per message, one JSON object back, no session, no server-sent stream, GET and DELETE refused, and the mirrored headers checked against the body. Each hosted server then became a small file saying where its index comes from and how it searches. Two things the plan named came out differently. The Val Town example does not answer BM25 alone: it does by default, but it runs the clients' whole hybrid search when an HTTP embedding service is configured, since the container is already in memory and the clients' code already does it; what was not done is exercising any real embedding service, so the shape is tested against a fake one and the README says so. And the Cloudflare example's optional hybrid search is narrower than the clients': the vector ranking runs over the fifty keyword candidates rather than over every window, because reading every vector from D1 per question would not fit the CPU budget, so a section sharing no term with the question cannot appear there. The test proves it still returns the clients' recorded ranking for the golden query, which it does because that query's answers share terms with it. Loading D1 needed a script rather than a file copy, `export_d1.py`, which writes the SQLite output as INSERT statements batched under D1's statement limit with every literal escaped; the golden compendium's export is committed and checked against a fresh one. One gate a hosted endpoint wants and a local one does not was added to both: an optional bearer token compared in constant time, and an optional origin allowlist. Verified: the Worker ran under `wrangler dev` against a local D1 loaded from the golden export and answered the contract query with the expected sections; the val ran in Node with its store and fetch faked. Val Town is reached two ways, both without installing anything: `push.py` assembles the six files for pasting into the browser, or, with a token, pushes them through the platform's REST API, tested call by call against a fake of it. Two things the live platform taught that the documentation had not: the account route is `/v1/me`, not `/v2/me`, and the free plan caps the number of unlisted and private vals, so the source is public by default, which it is anyway. The done-when rule asked for a fresh deployment on each platform. Val Town's was made on 2026-09-12 from this machine with `push.py`: the first run created the val, the second found it by name and updated every file, and the endpoint answered the golden compendium's contract query, over a published copy of that compendium, with the sections the clients rank as relevant. Cloudflare's was not: no logged-in account was available to the session, so that deployment is owed and belongs to the maintainer. The Cloudflare tests use Node's built-in SQLite module as the stand-in for D1, which sets Node 22.5 as their floor; the Worker itself has no such floor.*

### Phase 15: Documentation pass

**Goal.** Bring the README, every page under `docs/`, the example settings files, and the repository's metadata files into agreement with the code as it stands after Phase 14, and add the guides an adopter is missing.

**Why it is needed.** Each phase updated the pages it touched and no phase read the whole set against the code. An audit on 2026-09-11, after Phase 13 merged, found the defects listed below. Most are small: a page says a thing is planned when it was built, or built when it was built differently. Together they would mislead a new hire who reads the documentation first, which is the reader the documentation is for. The audit also found no page at all on installing, on the deployment choices, or on the plugin architecture as one picture.

**Order of work.** Corrections first, the README second, new pages last: a new page that cites a stale one inherits its defect. If the week runs out, the new pages move to a phase of their own rather than being rushed.

**What the audit found: the README.**

| Where | What is wrong | What to do |
|---|---|---|
| Description | The project-status sentence says a build writes the index and the two clients search it, which was true after Phase 4. | Say what exists: five source types, four outputs, two clients, two local search servers, and the hosted examples once Phase 14 lands. |
| Quick start | Installs `[dev,code]` and says nothing about the one-command scripts, the `youtube` extra, or the two optional environment variables. | Show the two ways in: `run.sh` or `run.bat` for a person, `pip install -e` for a developer. Name the three extras and when each is needed. Say that `GITHUB_TOKEN` and `YOUTUBE_API_KEY` are optional and come from the environment only. |
| Description | No picture of the whole. | Add a Mermaid diagram of sources, the engine, the outputs, and who consumes them: a browser search page, a script, a local assistant through the Model Context Protocol, a hosted assistant reading `llms.txt`, and a hosted endpoint once Phase 14 exists. Put the same information in a paragraph beside it, because the diagram carries nothing to a screen reader. |
| Preview image | `images/Repo-preview.png` is the template's own placeholder, byte for byte. | Replace it with a real image of a build or the diagram, or remove the commented-out line. |
| Documentation | The page list omits the architecture, compliance, and publishing pages, the three design pages, and the new guides. | List every page, one line each, as the README template asks; the detail stays in `docs/README.md`. |
| Credits | No library or external project is listed. | List each one the way the [EFDC repository template](https://github.com/DepressionCenter/EFDC-Repo-Template) does: name, what it does, how this project uses it, license, link. Runtime: `requests`, `beautifulsoup4`, `sentence-transformers`, `numpy`, `Markdown`, `PyYAML`. Optional: `tree-sitter` and the thirteen grammars, `youtube-transcript-api`, Universal Ctags. Development: `pytest`, `pytest-cov`, `uv` for the lock file. Examples: `@huggingface/transformers` and the ONNX runtime it brings. Also the `BAAI/bge-small-en-v1.5` model, the Open Knowledge Format, the `llms.txt` convention, and Field Station AI. Read each license from the package's own metadata when writing the line; the audit read them from the installed versions and found Apache-2.0, MIT, and BSD-3-Clause, and nothing incompatible with GPL v3 or later. |
| Citation | The DOI is still the template placeholder. | Fill it in or leave it; the maintainer's call. |

**What the audit found: `docs/`.**

| Page | What is wrong | What to do |
|---|---|---|
| `README.md` | The bot-protection line says the transport is planned for Phase 8; the architecture line says the page lists placeholders, and none remain. New pages are not listed. | Rewrite the two lines, add the new pages, and group the two maintainer-only pages (the page template and the session prompt) under their own heading so a reader looking for user documentation does not open them first. |
| `architecture.md` | The registry row lists the built-in sources, handlers, and adapters and omits `youtube` from both plugin kinds and `okf` from the adapters. The summary still mentions placeholder modules. The fetch row does not mention the browser-identity retry that `respect_robots_txt: false` allows. The settled decisions stop at eight, and every later decision lives only in a phase note on this page. The conclusion is one paragraph of two hundred words. | Correct the rows. Add the decisions made since Phase 5 as numbered entries, each with its reason and its specification section, as the first eight are: optional installs for the parsers and the caption library, the committed YouTube store, one page indexed once across sources, and a video as one document per stretch. Break the conclusion into short paragraphs. |
| `extractium-spec.md` | Still "Draft v0.2 (2026-09-04)" with no list of what changed since. The architecture diagram and section 4 say container version 3; the file is version 4. Sections 4 and 5 mark some built rows "built" and leave others unmarked. Section 6 says the handler protocol has no scope hook; it has had one since Phase 7. Section 3.4 dates content types by phase number. Section 8 omits the `repository/` and `github/analysis/` cache folders. Section 9.3 describes the Val Town, Cloudflare, and wrapper examples as if they existed. Section 12's example says a channel needs `YOUTUBE_API_KEY`, marks `include_code` as reserved, and omits `dspace`, `seed_urls`, `ctags_fallback`, `include_playlists`, `only_channel_videos`, and the per-source `delay_seconds`. Section 14's YouTube line is superseded. The page carries the code header rather than the documentation header. | Bump to v0.3 with a section listing the changes. Correct every item above. Mark every built row the same way, or drop the marks and let the architecture page say what is built. Regenerate the section 12 example from `examples/config.example.yaml` and keep the two in step. |
| `configuration.md` | Current, and the largest page in the folder at about seven hundred lines. | Read it once against `extractium/config.py` for any default that drifted, and check that every key in `SOURCE_OPTION_KEYS` and `OUTPUT_OPTION_KEYS` has a row. Consider moving the four-part "how the URL patterns work" section to the new crawling guide and leaving a pointer. |
| `data-flow.md` | The content-type list stops at `video_transcript` and omits `manifest`, `repo_map`, `code_file`, and `code_symbol`. The diagram's output list omits the SQLite file. The cache section omits the repository text cache. Code analysis, which produces records from a file rather than from a page, is not in the flow at all. | Add the missing types, the missing folder, and one paragraph on where a code file's records enter the flow. |
| `compliance.md` | The known gap saying the scheduled workflow has never been observed running is dated 2026-09-08 and may no longer be true. There is no control row for the browser-identity retry, which Phase 8 said this page would gain. The test counts and the review date will be stale by the time this phase runs. | Confirm whether a scheduled run has completed and record the date or keep the gap. Add the retry row, stating that it sits behind `respect_robots_txt: false` and reports both attempts. Refresh the counts and dates in the same change. |
| `container-format.md` | The status paragraph says the clients that read the file are scheduled for Phase 4. They were built in Phase 4. | Say the clients exist and name them. |
| `usage.md` | The install line differs from the README's, and neither mentions the extras. The environment variables and the run scripts are absent. The cache paragraph tells the reader to ignore the cache folder without the YouTube exception. | Keep this page as the command reference: point installation at the new installation guide, add the two variables, and add the exception. |
| `troubleshooting.md` | Current. | Add entries only for failures the new guides turn up while being checked. |
| `bot-protection-transport.md` | Says the transport is planned and not built. That is true: there is no `transport` setting, no `curl_cffi` dependency, and no `core/transport.py`. What was built instead, in the same pull request, is the browser-identity retry behind `respect_robots_txt: false`. Phase 8 above carries no finished note, and `examples/config.efdc.yaml` still opens with the "before the first run" warning the phase was meant to remove. | The maintainer decides whether the handshake transport is still wanted. Either way, add a status note to Phase 8 and to this page saying what was built instead and what was not, and take the warning block out of the settings file or bring it up to date. |
| `github-repository-indexing.md` | A design record, and mostly right to keep as one. But its configuration example still says `include_code: true  # Phase 10; ignored until then`, and its tier table and record table date things by phase. | Leave the history sections. Correct every line that states the present. |
| `dspace-repository-indexing.md` | Current. | Nothing beyond the link check. |
| `doc-template.md` | Its heading form, the project title and the page title on one H1, disagrees with `AGENTS.md` section 16 and with every page in the folder, which use the title as H1 and the page name as H2. | Make the template match the pages. |
| `session-prompt-template.md` | The reading list mentions placeholder modules with `TODO` comments. None remain. | Drop that clause. Check the rest against the workflow the maintainer actually uses. |
| `how-to/run-a-weekly-build.md`, `how-to/publish-to-github-pages.md`, `how-to/search-a-compendium.md`, `how-to/connect-an-mcp-client.md` | Current. | Link check, and cross-links to the new guides. |
| `using-a-compendium.md` | Current until Phase 14, which adds the hosted tier it says is not built. It lived at the repository root as `SKILLS.md` until that name was taken by the agent skills index the repository template introduced. | Update in Phase 14; confirm here. |

**What the audit found: examples and metadata.**

| File | What is wrong | What to do |
|---|---|---|
| `examples/config.example.yaml` | The YouTube comment says listing a channel needs a key. It has not since Phase 13 was extended. The per-source `delay_seconds` is not shown. | Correct the comment and add the setting. |
| `examples/config.efdc.yaml` | Opens with a Phase 8 warning block about three sites answering 403. The YouTube entry says the source is "not yet available" and "arrives in phase 13", and that it will need a key. | Bring the whole file up to date and turn the YouTube source on, since the channel resolves without a key. |
| `CITATION.cff`, `.zenodo.json` | Two placeholder co-authors with placeholder ORCID identifiers, left from the template. | Remove them, or replace them with real people. |
| `examples/data-repo/README.md`, `examples/mcp/*/README.md` | Current. | Link check. |

**New pages.** Four, each following the page structure in `AGENTS.md` section 16.

- `how-to/install.md`: the supported Python versions; the three extras and what each one is for; the one-command scripts against `pip install -e`; what the lock file pins, how to regenerate it, and that it lists CUDA packages which install on Linux only, so a Linux install downloads far more than a Windows one; what the first build downloads; how to check an install with `--version` and the test suite.
- `how-to/crawl-a-site.md`: how to choose a source type for each kind of content; the trial run and how to read `llms.txt`; tuning the include and exclude patterns, moved here from the configuration reference or summarised from it; the two optional environment variables; what a build reports and what each notice means; when a build has to run on your own machine. `usage.md` stays the command reference this page points at.
- `how-to/deploy.md`: the deployment choices side by side. Build on your own machine and publish nowhere; build on GitHub and publish to Pages; publish the output folder to any static host; the separate data repository. For each, what it needs (secrets, the crawl cache, the committed YouTube store), what it costs, and what it cannot reach. Then how the outputs are consumed in each case: the browser client, a script, a local assistant, a hosted assistant reading `llms.txt`, and the hosted endpoints from Phase 14.
- `plugin-architecture.md`: the three plugin kinds, the registry's resolution order, the three protocols with every member and every optional hook, and how a source, a site handler, and an adapter each fit into a build. One Mermaid diagram of the whole and one of a build's sequence, each with the same information in prose beside it. A minimal working example of each kind, dropped into `plugins/`, and a pointer to the built-in that serves as the reference implementation for each. Written for a plugin author who has read nothing else.

**Tests.** A test over `docs/`, the README, `SKILLS.md`, `skills/`, and the example READMEs that every relative link resolves to a file, every page carries the license comment, one H1, an H2 subtitle, the two back links, and the Summary, Conclusion, and Additional Resources headings, and no heading level is skipped. A test that every YAML block in `configuration.md`, the specification's section 12, and `examples/` loads through `load_config`, so a documented setting that does not exist fails the build rather than misleading a reader. The existing suite still passes.

**Done when** a new hire can install, build, publish, and connect an assistant from the README and `docs/` alone, without opening the code; every YAML example in the documentation loads; and a search of `docs/` for "planned", "not yet", "placeholder", and "phase" outside this page and the three design pages finds nothing that is no longer true.

*Finished 2026-09-12 on branch `phase-15-documentation-pass`. Every correction in the three audit tables was applied or found already made by the two pull requests that landed after the audit: the transport shipped in Phase 8's late delivery, so the bot-protection page, the EFDC settings file, and the plan's own Phase 8 entry were already current, and the YouTube comments in both settings files already said no key is needed. The specification is v0.3 with a change list, a status column in place of the phase columns, the version 4 container, the three optional handler hooks, every cache folder, and a settings example that carries every setting and loads. The architecture page gained decisions 9 through 13. The two template co-authors were removed from the citation files. The four new pages exist, and the documentation index groups the maintainer pages under their own heading. The two tests the phase asked for are in `tests/test_docs.py`, with a third that loads the three example plugins from the plugin architecture page through the registry and runs each one; a YAML block that shows one setting is loaded on top of a minimal source so its keys are still checked, and a block that is not a settings mapping, such as a workflow line, is skipped. Two items were left to the maintainer, as the audit allowed: the DOI in the citation is still the template placeholder, and the placeholder preview image is no longer referenced but still sits under `images/`. The "how the URL patterns work" section stayed in the configuration reference with a pointer from the crawling guide, since moving it would have broken the links other pages already carry.*

### After Phase 15

What is left is listed here so a reader of this page knows what was deferred and what was ruled out, and why. A decision recorded here is meant to save somebody proposing the same thing again from first principles.

#### Still open

Not scheduled, kept in the specification as future work: an enrichment pass with a local language model; clients in other languages; Parquet and DuckDB outputs; reading OKF bundles from other tools; loading plugins from git URLs. Optical character recognition for image-only deposits, and reading DSpace communities rather than named collections, sit here too. Migrating Field Station AI to the JavaScript client and the current container version is a task for that repository, not this one.

Following a YouTube link found while crawling something else belongs here as well. The site handler already sees such a link and reports it, but the crawl discards an off-host address before any handler is asked whether to follow it, so collecting those and handing them to the video source needs a hook in the crawler's own link pipeline. That is a core change and wants its own phase.

#### Decided against

**Speech-to-text for videos without captions.** Dropped on evidence rather than on principle. Sampling 65 of the 145 videos on a real channel on 2026-09-11 found English captions on 64 of them, 37 of those generated by YouTube itself, and not one video with captions missing or turned off. The one gap was a video captioned in Spanish only, which is a language to add to the `languages` setting and not a model to run. A speech-to-text pass would mean shipping several hundred megabytes and a large amount of processing to solve a problem that did not occur once, so the project lets YouTube do that work.

**Video from anywhere but YouTube.** The same reasoning fixes the scope of video indexing: captions from YouTube, and no other video host or local media file. Reading video from anywhere else means decoding media, which is a class of dependency and of malformed-input risk this project has avoided everywhere else, and it buys nothing for the documentation a knowledge base is built from. An organization that needs it can write a source plugin, which is what the plugin registry is for.


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
