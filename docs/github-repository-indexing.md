<!--
This file is part of Extractium™
docs/github-repository-indexing.md
Author(s): Gabriel Mongefranco
Created: 2026-09-09
Last Modified: 2026-09-09
Summary: The design for reading GitHub repositories: the three-tier
ingestion ladder in Phase 7, and the lightweight static code analysis in
Phase 8. Covers URL detection, authentication, repository selection, file
filtering, caching, the Tree-sitter language set, the records produced,
and what each phase must prove before it is done.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## GitHub Repository Indexing

[← Back to README](../README.md)


## Summary

This page explains how Extractium reads a GitHub organization, user, or repository. It covers two phases of work. Phase 7 adds a source that talks to the GitHub API instead of scraping web pages, and it always keeps working: if a token is missing it uses the public API, and if the API cannot be used at all it falls back to a documentation-only crawl. Phase 8 adds fast, local code analysis on top, so a search can find where a function is defined and what calls it.

Read this page before starting either phase. The order of work and the "done when" rules live in the [implementation plan](implementation-plan.md); the settled design rules live in the [specification](extractium-spec.md). This page is the detail those two point at.


## Who this page is for

You are about to build, review, or audit the GitHub parts of Extractium. You know what a repository is. You do not need to know the GitHub API, Tree-sitter, or how a parser works; both are explained where they come up.


## What changed from the earlier plan

The plan used to put the GitHub API source and the Open Knowledge Format output together in one Phase 7. That has been split three ways.

| Phase | Work | Why it is on its own |
|---|---|---|
| 7 | The GitHub API source: documentation, manifests, and the ingestion ladder | About one week. Useful on its own, with no parser involved. |
| 8 | Lightweight static code analysis | Larger than one week, and accepted as such. It needs Phase 7's file contents to exist first. |
| 9 | The Open Knowledge Format output | Nothing to do with GitHub. It is an output format of equal standing to the container file, and it serializes whatever the build produced, whatever the source was. |

Splitting Phase 9 out matters for more than tidiness. An adapter that arrives in a GitHub phase invites the mistake of writing a GitHub-shaped Open Knowledge Format. The format has to work for a TeamDynamix portal and a local folder in exactly the same way.

Everything after Phase 9 moved down by two: the local MCP servers, the YouTube source, and the remote MCP examples are now Phases 10, 11, and 12.


## Phase 7: the GitHub API source

### Goal

Point Extractium at `github.com/DepressionCenter` and get every public repository's documentation into the index, without crawling a single rendered web page, and without the build failing when there is no token.

### The ingestion ladder

This is the heart of the phase. Extractium tries three ways of reading GitHub, in order, and stops at the first one that works.

| Tier | Name | What it needs | Documentation | Code analysis |
|---|---|---|---|---|
| 1 | Authenticated API | `GITHUB_TOKEN` in the environment | Complete | Yes, from Phase 8 |
| 2 | Unauthenticated API | Nothing | Complete | Yes, from Phase 8 |
| 3 | Documentation-only crawl | Nothing | Whatever the crawler can find | **No** |

Three rules govern the ladder. They are the point of the design, so they are stated plainly.

1. **Tier 2 is not a reduced mode.** A public repository read without a token gets exactly the same treatment as one read with a token: the same files, the same records, the same code analysis. A token buys API capacity, not capability. Anything that indexes at tier 1 must index at tier 2.
2. **Tier 3 indexes documentation only.** The crawler reads READMEs, Markdown, and the text documentation it can reach through links. It never scrapes a source-code page, and it never runs code analysis. GitHub's file viewer builds its content in the browser from an embedded data payload, so scraping it yields markup, not source. A parse of that would be worse than no parse.
3. **The ladder applies to every GitHub source.** It runs the same way for a `web` source whose seed URL happens to be a GitHub address and for an explicitly configured `github_api` source. An explicit source does not get a different ladder; it gets a louder report.

The third rule is a correction to an earlier draft, which had explicit sources fail instead of falling back. Falling back is better, as long as nobody is misled about what they got. That is what the reporting rules below are for.

### Moving down the ladder

A tier is abandoned only when it cannot proceed. Recoverable reasons include:

- GitHub is unreachable or returning server errors.
- The request is refused for the credential in use.
- The remaining rate-limit budget cannot cover the work, and the reset is too far away to wait for.
- Repository enumeration fails before any useful content is produced.

A rejected token is a special case with its own rule: **if the supplied credentials are refused, drop to tier 2 and carry on.** A bad token is an operator mistake, not a reason to lose the build. The report has to name it, because a silently ignored token looks identical to a token that worked.

### What is not a tier change

Some failures are the operator's to fix, and quietly demoting them turns a typo into a strange, empty result. These stop the source instead:

- A configuration file that names neither an owner nor a repository, or names more than one selector.
- An owner or repository that GitHub reports does not exist. Crawling `github.com/DperessionCenter` produces a 404 page, not a knowledge base.
- An output path or cache path the build cannot write.

The distinction is simple: the ladder handles *we could not reach GitHub*, never *you asked for the wrong thing*.

### Not losing or repeating work

A run can fail halfway. If the API read eight repositories out of twenty and then lost its budget, tier 3 must not fetch those eight again.

The source therefore keeps a ledger of every URL it has already turned into a document. The ledger is per run, in memory, and the crawler consults it as an exclusion list. This is the same mechanism that stops a successful API run from being crawled a second time through HTML; the partial case is just the general case.

Scope is preserved across a demotion as well. If the request was one repository, tier 3 crawls that one repository and does not widen to the owner's other work.

### Saying what actually happened

Every demotion is reported twice: once as it happens, through the progress callback, and once in the summary at the end of the build.

The summary states, per repository, which tier read it and what is therefore missing. Wording is concrete:

```text
DepressionCenter/extractium      tier 1 (authenticated API)     documentation, code analysis
DepressionCenter/ShareR          tier 2 (public API)            documentation, code analysis
DepressionCenter/FieldStationAI  tier 3 (documentation crawl)   documentation only; no code analysis
```

The same fact is recorded inside the repository-map document that Phase 8 writes, so a person searching the finished index can see the coverage without going back to the build log. A gap the reader cannot see is a gap that will be mistaken for an answer.

### Recognizing a GitHub address

The `web` source stays host-agnostic. It does not learn GitHub rules. Instead, a site handler may offer a better source for a seed URL, and the existing GitHub handler is where that offer is made. GitHub knowledge stays in the GitHub file.

| Address | What is indexed |
|---|---|
| `github.com/OWNER` | Every selected public repository that owner has |
| `github.com/OWNER/REPO` | That one repository |
| Anything deeper under `github.com/OWNER/REPO/` | That one repository |
| `raw.githubusercontent.com/...` | That one file, as it is today |
| `OWNER.github.io/...` | An ordinary web crawl, as it is today |
| Any other git host | Unchanged behavior |

A repository address must never expand into every repository its owner has. An owner address means "this owner's repositories"; a repository address means "this repository". Getting this backwards turns a small request into hours of work and an index full of content nobody asked for.

The offer applies to the **seed URL only**. A link to some repository found halfway through crawling an unrelated website stays an ordinary link. Otherwise one stray mention could pull an entire GitHub account into a small site crawl.

### Telling an organization from a user

Do not guess, and do not probe two endpoints to find out. Read the account once and look at the type GitHub reports. If it is an organization, list the organization's public repositories; if it is a user, list that user's own public repositories. If the account cannot be read at all, that is a ladder event, not a guess.

For a repository address, fetch the repository directly. Its own metadata says who owns it and what kind of account that is.

### Authentication

The source reads `GITHUB_TOKEN` from the environment. The token:

- never appears in `config.yaml`;
- never appears in any output file;
- never appears in a log line, a progress message, or an error;
- travels only in a request header;
- is never handed to a parser, a subprocess, or a cache file.

**Phase 7 indexes public repositories only, even when the token could read private ones.** This is deliberate. The confidentiality guardrail in the specification, section 7, separates local content from published content; it has no concept of a remote repository that is private. Until there is a general policy for confidential remote sources, an authenticated repository must not be treated as ordinary public web content. A token raises the request budget. It does not widen what may be published.

### Choosing repositories

Defaults:

| Kind | Default | Why |
|---|---|---|
| Public | Included | The only kind Phase 7 reads. |
| Fork | Excluded | Indexing a project and several forks of it fills the index with near-identical copies. |
| Archived | Included | Archived documentation is still documentation. Dropping it silently loses history. |
| Empty | Skipped | Nothing to read. |
| Disabled | Skipped | Nothing to read. |

Configuration overrides all of these.

### Taking inventory before downloading

For each selected repository, in order: resolve the default branch, resolve the commit and tree it points at, request the recursive Git tree, and look at every path in it before asking for a single file body.

If GitHub marks the recursive tree truncated, **walk the subtrees until the inventory is complete**. A truncated tree that is treated as complete produces a repository that looks fully indexed and is not. That is the worst failure mode available here, because it is invisible.

The inventory gives a path, an object type, a blob SHA, and usually a size. That is enough to decide what is worth downloading.

### What gets indexed

Documentation is indexed in full. Its text goes through the normal chunker, exactly like a web page. "In full" means no summary replaces the original; the existing section and window limits may split a long file across several parents, which is ordinary behavior.

Files read as documentation:

`README*`, `*.md`, `*.markdown`, `*.txt`, `*.rst`, `*.adoc`, `*.asciidoc`, `LICENSE*`, `NOTICE*`, `CHANGELOG*`, `HISTORY*`, `CONTRIBUTING*`, `SECURITY*`, `CODE_OF_CONDUCT*`, `AUTHORS*`, `CITATION*`

A `README.md` inside `docs/`, inside a package, or inside an examples folder counts the same as the one at the repository root.

Project and build files are indexed as text, with a short fixed heading naming their role. They often explain a project faster than its source does:

`pyproject.toml`, `requirements*.txt`, `setup.cfg`, `package.json`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, `build.gradle.kts`, `DESCRIPTION` and `NAMESPACE` (R packages), `renv.lock`, `Gemfile`, `composer.json`, `environment.yml`, `environment.yaml`, `Dockerfile`, `docker-compose.yml`, `Makefile`, project and solution files, and GitHub Actions workflow files.

Dependency lock files are excluded by default. They are long, they are mostly package names and version numbers, and the matching manifest already records what the project actually declared. `renv.lock` is the exception, because an R project's `DESCRIPTION` often does not pin anything and the lock file is where the real environment is written down.

### What gets skipped

Whole directories that hold generated or third-party code:

```text
.git/  node_modules/  vendor/  dist/  build/  target/
coverage/  .venv/  venv/  __pycache__/  .cache/  renv/library/
```

And these files, wherever they are: binaries, images, audio, video, archives, compiled objects, source maps, minified JavaScript and CSS, Git LFS pointer content, private keys and certificates, and `.env` files.

`.env.example` is kept: it lists the variables a project needs, with fake values, which is documentation.

Submodules are not followed. The `.gitmodules` file itself may be indexed as configuration.

### A ceiling on file size

There is a configurable maximum size per file, with a conservative default. Nothing above it is downloaded or parsed.

A skipped file always produces a progress event naming the repository, the path, and the reason. **A selected file is never dropped in silence.** An index quietly missing its largest documentation file is worse than one that says it skipped it.

### Downloading: one file at a time, or one archive

The inventory makes it possible to choose.

Request files individually when only a small part of the repository is wanted, the files are small, and the remaining request budget makes it reasonable. Download one repository archive instead when many files are wanted, the repository is not enormous, and one download avoids a long run of requests.

The choice reads the API's own rate-limit headers rather than following a fixed file count. If neither option is safe — too many requests, and too large an archive — stop that repository with a message that says authenticated access would fix it. Guessing and doing the expensive thing anyway is not an option.

Archive entries are streamed and read in memory. Nothing is extracted to disk, so no archive path can be used to write anywhere. Only selected regular files are read. Archive paths are never trusted, never joined onto a real directory, and never used to name a temporary file.

### Rate limits

Read the rate-limit headers on every response and act on them:

- Honor `Retry-After` when GitHub sends it.
- Honor the reset time when the remaining count reaches zero.
- Never retry in a tight loop, and never loop forever.
- Prefer moving down the ladder over waiting out a long reset.
- Ask for repository listings at the largest page size the API allows.

### Caching

GitHub gives every file body a blob SHA, which is an ideal cache key: the same SHA means the same bytes, whatever branch or path points at it.

```text
.kb_cache/
    github/
        repositories/   Repository metadata and trees, keyed by repository and tree SHA
        blobs/          File bodies, keyed by blob SHA
        analysis/       Phase 8 parser output, keyed by blob SHA and parser signature
```

Nothing under `.kb_cache/github/` ever contains a token. A cache test checks this rather than assuming it.

### Configuration

The planned options for an explicit source. The reference in [configuration.md](configuration.md) documents only what is implemented today, which is `org` alone; it gains the rest when this phase lands.

```yaml
sources:
  - type: github_api
    org: DepressionCenter          # exactly one of org, user, or url
    include_repos: []              # empty means all matching repositories
    exclude_repos: []              # exclusion wins over inclusion
    include_forks: false
    include_archived: true
    include_code: true             # Phase 8; ignored until then
    max_file_bytes: 2000000
```

Rules:

- Exactly one of `org`, `user`, or `url`. Two selectors is an error, not a merge.
- `include_repos` and `exclude_repos` match repository names, not URLs.
- No setting in Phase 7 turns on private repositories.

Automatic handling needs no configuration at all, and that is the user-facing point of the phase:

```yaml
sources:
  - type: web
    seed_url: https://github.com/DepressionCenter/extractium
```

### When something goes wrong

| Class | Examples | What happens |
|---|---|---|
| Source-fatal | Owner does not exist; every request blocked before any enumeration | The ladder runs; if tier 3 also cannot start, the source reports and stops |
| Repository-fatal | Metadata unreadable; default branch unresolvable; tree cannot be completed | Report that repository, move to the next one |
| File-local | Blob vanished between tree and download; over the size ceiling; binary content found after download | Report the path, keep going |

One bad repository must not destroy an organization-wide build. One bad file must not destroy a repository.

### Records this source produces

Every document keeps `source_type = github`, so existing filters keep working. Two `content_type` values are added for this phase:

| Value | What it is |
|---|---|
| `manifest` | A project or build file indexed as text |
| `repo_map` | The synthetic per-repository summary (written from Phase 8; a metadata-only version exists in Phase 7) |

`readme`, `text`, `wiki`, and `release_notes` are unchanged.

Categories use the existing hierarchy, not a second GitHub-only system. `DepressionCenter/extractium/extractium/core/build.py` becomes `DepressionCenter`, `extractium`, `extractium`, `core`.

### Phase 7 is done when

- A `web` source pointed at an organization, a user, or a repository on GitHub uses the API instead of crawling it.
- An owner address enumerates that owner's repositories; a repository address indexes only that repository.
- A build with no `GITHUB_TOKEN` produces the same documents as a build with one, for public repositories.
- A rejected token drops to tier 2, indexes the same content, and says the token was refused.
- An API failure that cannot be recovered from drops to a documentation-only crawl, keeps the requested scope, does not re-fetch what was already read, and reports the gap.
- An explicit `github_api` source follows the same ladder, with the demotion named in the summary.
- A truncated recursive tree is completed through its subtrees.
- README, Markdown, text documentation, and selected manifests are represented in full.
- A skipped file is always reported.
- The same blob SHA is never downloaded twice.
- No token appears in any output, log, or cache file.
- The whole existing test suite still passes.


## Phase 8: lightweight static code analysis

### Goal

Make a repository's code findable without cloning it, compiling it, running it, or sending it to a language model. A search should answer: where is this defined, what does this file contain, what does it import, what calls it, and where do I click to read it.

This phase is larger than one week and is planned as such. It is still one coherent change set, because a half-built parser layer that produces records nothing renders is worse than none.

### What a record holds, and what it never holds

**Records carry structure, not source text.** This follows the specification, section 5, which fixed the rule before any of this was written: signatures, documentation, and purpose, never raw code bodies.

The reason is not squeamishness about publishing public code. It is that the compendium is one static file, around 10 MB, searched with vectors from `bge-small-en-v1.5` — a model trained on short English passages. Source bodies would multiply the file size and embed poorly, so they would cost a great deal and retrieve badly. A signature, a docstring, and a link to the exact lines on GitHub retrieve better and cost almost nothing.

So a symbol record holds the name, the kind, the exact signature, the documentation attached to it, its relationships, its location, and a link. To read the implementation, you follow the link.

### Where a file summary comes from

A summary is worth having, and one can be produced honestly without a language model. In order of preference, take the first that exists:

1. **The file's own documentation.** A Python module docstring, a Rust `//!` block, a JSDoc `@fileoverview`, a Lua or R leading comment block, roxygen `@title` and `@description`.
2. **A structured header.** This organization's own convention puts a `Summary:` line in every file header, so any repository following it already carries a written summary. Read that line.
3. **The nearest README.** A short excerpt from the README in the file's own directory, attributed as such.
4. **A deterministic template over what the parser found.** For example: *"Python module defining 4 functions and 1 class; imports 3 local modules; contains no module-level executable code."*

The first three are quotations. The fourth is arithmetic. None of them is a guess. **A summary must never assert something the parser did not observe.** "This function validates permissions" is forbidden unless "validates permissions" was written by a human in the file.

### Languages

The following are wanted. Every one of them is subject to the same gate before it becomes a dependency, and **the results of that gate are not yet recorded** — this table lists intent and known risk, not verified fact.

| Language | Files | Confidence a suitable grammar exists |
|---|---|---|
| Python | `.py`, `.pyi` | High |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | High |
| TypeScript | `.ts`, `.tsx` | High |
| R | `.R`, `.r` | High |
| Bash and shell | `.sh`, `.bash`, `.zsh` | High |
| Lua | `.lua` | High |
| C# | `.cs` | High |
| HTML | `.html`, `.htm` | High |
| Markdown | `.md` | High |
| SQL | `.sql` | Medium; several competing grammars, pick one and record why |
| Kotlin | `.kt`, `.kts` | Medium |
| Swift | `.swift` | Medium |
| PowerShell | `.ps1`, `.psm1`, `.psd1` | Medium; community grammar, maintenance must be checked |
| MATLAB | `.m` | Medium; also collides with Objective-C on the extension |
| Stata | `.do`, `.ado` | **Low.** See below. |

Two extra languages beyond the requested set are proposed for this field:

- **SQL**, because registry pulls, REDCap exports, and cohort definitions in health research are written in it, and they encode the study definitions people most often need to look up.
- **MATLAB**, because behavioral and physiological analysis code — Psychtoolbox tasks, actigraphy, continuous glucose monitoring signal processing — is still commonly MATLAB, and that work is exactly what a diabetes or mental-health repository holds.

**Stata is the honest problem in this list.** There is no well-maintained Tree-sitter grammar for it, and Universal Ctags does not cover it either. Three options, to be settled in-phase and recorded:

1. Index Stata files at the file-metadata tier only: path, size, language, link. Truthful, cheap, and shallow.
2. Write a small deterministic reader for `program define`, `capture program drop`, and top-level comment blocks. A regex reader is a parser that lies at the edges, so it would be limited to what it can defend and labeled as pattern-matched, not parsed.
3. Leave Stata out and say so.

Option 1 is the recommendation. Option 2 is acceptable only with the labeling.

### Files that hold another language inside them

Several formats in this field are containers, not languages. Handle them by pulling the embedded code out and parsing it with the grammar it belongs to.

| Container | Inner language | How |
|---|---|---|
| R Markdown (`.Rmd`) and Quarto (`.qmd`) | R, Python, and others | Parse the Markdown, index the prose as documentation, parse each fenced chunk with the grammar its label names |
| Jupyter notebook (`.ipynb`) | Usually Python or R | Read the JSON, index Markdown cells as documentation, parse code cells with the kernel's grammar. **Outputs are never indexed** |
| HTML | JavaScript | Parse the document, index the text, parse `<script>` contents with the JavaScript grammar |

Notebooks matter more than their place in this table suggests. In this field a great deal of real analysis lives in `.ipynb` and `.Rmd` files and nowhere else. They also carry the greatest privacy risk in the whole phase: **a notebook's stored outputs can contain printed rows of real participant data.** That is why outputs are never read, and why the existing protected-health-information lint has to be pointed at whatever this phase produces before any of it is published.

### What is not used, and why

No language server, no compiler, no build step, no container runtime, no graph database, no language model.

Lua language server support was asked about specifically. The answer is no, and the reason is scope rather than capability: a language server is a per-language daemon that has to be installed, launched, kept alive, and shut down on Windows, macOS, and Linux. It would dominate build time and installation size, and the whole point of this phase is a parser that starts instantly and parses bytes. If Lua call resolution turns out to be too weak without one, that is the moment to reconsider — not before.

### How the parser layer is arranged

One registry maps a file to a language, a grammar, and a set of queries. Without it, every new language becomes another branch in the GitHub code, which is how a source turns into a pile of extension checks.

The registry holds, per language: the extensions and bare filenames it claims, the grammar package and version, the grammar's license, the query file, and which captures that language actually supports. The last field matters because not every concept exists everywhere; asking a Bash grammar for class inheritance should return nothing, not an error.

Extraction rules live in small query files, one per language, so the engine stays generic:

```text
extractium/code/queries/python.scm
extractium/code/queries/r.scm
extractium/code/queries/lua.scm
```

Where a query is adapted from a grammar's own tag queries, its license and attribution are preserved.

### The dependency gate

Before any grammar becomes a required dependency, check and **record**: the license is compatible with GPL v3 or later; it installs from a wheel on Windows, macOS, and Linux with no compiler; it supports the project's Python range; it is maintained; it has no known critical vulnerability; and it can be pinned through the existing lock process.

A grammar that fails the gate does not ship as a requirement. It either becomes optional or the language falls to a lower tier. Bundles that ship many grammars at once are worth evaluating, but a bundle's convenience does not replace the license check on what is inside it.

### What is extracted

| Priority | Item |
|---|---|
| Highest | Classes, structs, interfaces, traits and similar type definitions |
| Highest | Functions and methods |
| Highest | Exact signatures |
| Highest | Docstrings and documentation comments |
| Highest | Imports, includes, `use`, `require`, `source()` and equivalents |
| Highest | Exports and public symbols |
| Highest | Module and package declarations |
| Highest | Repository and file maps |
| High | Calls |
| High | Inheritance and interface implementation |
| High | Enums, type aliases, module-level constants |
| High | Decorators, annotations, attributes |
| High | Test functions and test classes |
| High | Entry points and module-level executable code |
| High | Source locations |

Individual variables and every identifier occurrence are deliberately left out. They would add far more noise than retrieval value.

Tests are indexed, not skipped. A test is often the clearest statement of what something is supposed to do, what inputs it accepts, and how it fails.

### File and symbol records

A file record is compact and lists what the file defines, imports, exports, which files it reaches into, and which reach into it. It names the analysis that produced it: `tree-sitter`, `ctags`, or `file metadata only`. That last label is what an unsupported language gets, and it is much better than the file disappearing.

A symbol record names the repository, path, language, symbol, and kind; then the signature, the documentation, the imports it uses, the calls it makes, the files it relates to, and a link to its exact lines. It does not contain the body.

### Line links and a trap in the identifier

A file record links to its normal GitHub file URL. A symbol record adds a line fragment: `.../blob/main/path/to/file.py#L42-L88`.

This is safe for identifiers. Parent identifiers hash a normalized URL, and `normalise` in [core/fetch.py](../extractium/core/fetch.py) strips the fragment, so moving line numbers do not change a file's identity, and two symbols in one file stay distinct because the symbol name is part of the heading.

**It is not safe for near-duplicate collapse, and this has to be handled.** `drop_near_duplicates` in [core/dedup.py](../extractium/core/dedup.py) decides whether two chunks came from the same page by comparing the raw URL string, fragment included. Two symbols in one file therefore look like two different pages, and the rule that protects a page's own repetitions stops protecting them. In code that is a real loss: near-identical small functions, repeated test setup, and generated accessors are common and legitimate, and they would be silently dropped as if they were shared web-page boilerplate.

Two candidate fixes, to be decided in-phase with a test that proves the behavior either way:

1. Give the collapse step a page key that ignores the fragment, so one file is one page again.
2. Keep the fragment out of the stored URL and carry the line range in the record text and the heading instead.

Whichever is chosen, the phase must include a test with several near-identical symbols in one file that asserts they all survive.

### Relationships between files

After the files are parsed, build an in-memory symbol table for the repository: qualified name, short name, module, path, kind, location. Then resolve relationships against it.

Imports come first, because they are cheap and usually reliable: Python absolute and relative imports, JavaScript and TypeScript relative imports, R `source()` and `library()` where the path is visible in the text, C and C++ local includes, C# namespaces, Kotlin and Java packages, Lua `require`, and PowerShell dot-sourcing. Imports of external packages are recorded as external dependencies and not matched to local files.

Calls are resolved conservatively, with the confidence stated on every edge:

| Confidence | Example |
|---|---|
| `resolved` | A call inside one file to a uniquely named function in that file |
| `probable` | A call through a symbol that file explicitly imported |
| `unresolved` | `obj.save()` where nothing static says what `obj` is |

A guessed cross-file call is never reported as certain. Reverse edges — imported by, called by, inherited by, implemented by — are computed from the finished graph, never by parsing anything twice.

### Repository and owner maps

Each repository gets one synthetic map document: name, description, primary language, topics, license, default branch, **the ingestion tier that read it**, its important documentation, its manifests, its likely entry points, its top-level directories, its major definitions and modules, its file dependencies, its cross-file calls with confidence, and its tests. A large repository may need several parents, which the existing chunker already handles.

An owner-level request also gets one owner map listing every repository with its description, primary language, topics, and archived status. This is what lets a question like "which Depression Center project handles knowledge-base indexing?" find the right repository before searching inside it.

### Universal Ctags as a second parser

Tree-sitter always goes first. Ctags is used only when there is no grammar for the file, the grammar will not load, a query does not match the installed grammar, or the parse fails badly enough to yield nothing useful.

Ctags is optional and never bundled. At the start of code analysis, look for `ctags` on the path, confirm it is Universal Ctags and not a different program of the same name, confirm it supports JSON output, and cache that answer for the build. If it is absent, unsupported files still get a file-level record.

Running it safely matters, because everything involved comes from a repository nobody here controls:

- Invoke it with an argument array. Never build a shell command, and never use `shell=True`.
- File content often exists only in memory, so write it to a generated temporary filename with the right extension. **The repository's own path never names the temporary file and never chooses its directory.**
- Treat the output as untrusted input and validate it before use.
- Do not present Ctags results as an import graph or a call graph. It does not produce those, and pretending otherwise would put invented relationships into the index.

### The analysis cache

Parser output is cached against everything that could change it: blob SHA, parser, parser version, grammar, grammar version, and the code-analysis schema version. If all six match, do not parse again. A repository map is cached against the repository, the default-branch tree SHA, and the schema version, so a changed tree rebuilds it.

### Effect on the container and the clients

No new container version. The parent record's shape does not change. Structure lives in the indexed text and in fields that already exist: title, URL, categories, source type, content type.

Two more `content_type` values are added: `code_file` and `code_symbol`. That is a change to a controlled vocabulary the container-format page and both search clients pin, so the phase has to check the reader checklist in [container-format.md](container-format.md) and confirm that neither client needs a code-specific mode. Asserting that it does not is not the same as checking.

### Security posture

Repository content is untrusted input, and this phase reads a great deal of it.

**Nothing from a target repository is ever executed.** No scripts, no imported modules, no JavaScript, no build files, no dependency installation, no Makefile, no compilation, no containers. Tree-sitter parses bytes; Ctags parses bytes.

**Nothing from a target repository is ever an instruction.** A source file, a README, or a comment may contain text aimed at an AI agent. An `AGENTS.md` inside a repository being indexed is content to index, never direction to follow. It is data, whatever it claims about itself.

Beyond that: filenames with shell characters, newlines, or traversal sequences are handled as data; invalid UTF-8 is handled rather than crashing; archive entries claiming impossible sizes are refused; symbolic links are not followed out of the tree; and no credential reaches a log, an output, or a cache.

### Proposed layout

```text
extractium/
    sources/
        github.py            Site handler; also offers the API source for a GitHub seed
        github_api.py        Accounts, enumeration, trees, blobs, archives, cache keys, Documents
    code/
        indexer.py           Coordinates analysis for one repository
        languages.py         Registry: paths to grammars, plus the license record
        tree_sitter.py       Loads grammars, runs queries
        embedded.py          Pulls code out of notebooks, R Markdown, and HTML
        relationships.py     Symbol table, imports, calls, reverse edges
        render.py            Turns records into deterministic text
        ctags.py             Detects and safely invokes Universal Ctags
        queries/*.scm        One query file per language
```

`github_api.py` contains no language-specific logic. The adapters contain no GitHub-specific logic. **If an adapter ever has to ask whether content came from GitHub in order to work, the separation has been broken and the design is wrong.**

### Phase 8 is done when

- Every language in the table above is either analyzed by Tree-sitter, analyzed by Ctags, or recorded at the file-metadata tier, with the gate result recorded for each.
- Notebooks, R Markdown, and HTML have their embedded code parsed, and notebook outputs are never read.
- File records and symbol records are produced, with structure and no source bodies.
- File summaries come from documentation, a header, a README, or a deterministic template, and nothing else.
- Import edges resolve; call edges carry `resolved`, `probable`, or `unresolved`; reverse edges are computed from the graph.
- Repository maps and owner maps are produced, and each repository map names the tier that read it.
- Near-identical symbols in one file survive near-duplicate collapse, proven by a test.
- Unchanged blobs are neither downloaded nor reparsed.
- No repository content is executed, and no repository content is treated as instructions.
- The protected-health-information lint has been run against the records this phase produces.
- Windows, macOS, and Linux all install and run the parser set, on the oldest and newest supported Python versions.
- The whole existing test suite still passes.


## How this is tested

Both phases are tested from committed fixtures. No automated test contacts GitHub.

| Area | What the fixtures must cover |
|---|---|
| URL handling | Organization, user, repository, deeper repository paths, raw content, GitHub Pages, invalid owner, invalid repository |
| The ladder | Token accepted; token refused; no token; API unreachable; partial failure after some repositories; explicit source demoted; scope preserved; nothing fetched twice; the report naming each tier |
| API behavior | One page and several pages of results; organization and user owners; empty account; archived, fork, and disabled repositories; missing default branch; recursive and truncated trees; subtree walking; blob and archive fetches; rate-limit headers; 401, 403, 404, and 429; a repository disappearing mid-run |
| File filtering | Markdown, plain text, extensionless README and LICENSE, manifests, source, tests, vendored code, generated code, minified files, lock files, binaries, oversized files, `.env`, `.env.example`, submodules, LFS pointers |
| Parsing | Per language: definitions, signatures, documentation, imports, exports, calls, inheritance, constants, annotations, module-level code, and a file with recoverable syntax errors |
| Embedded code | An `.Rmd` with R and Python chunks, an `.ipynb` with outputs present, an HTML file with inline script |
| Relationships | Same-file calls, relative imports, aliases, local includes, unique and ambiguous names, dynamic calls, reverse edges, all three confidence levels |
| Ctags | A fake executable for determinism; no shell invocation; JSON capability detection; malformed output refused; absence does not break Tree-sitter files |
| Caching | Same blob not downloaded twice; same signature not reparsed; changed blob, grammar version, or schema version invalidates; changed tree rebuilds the map; **no cache file contains a token** |
| Security | Malicious archive paths; symbolic links; traversal; shell characters and newlines in filenames; invalid UTF-8; impossible declared sizes; private repository metadata ignored even when fixture credentials could read it; no credential in any log line |

Performance is checked by properties, not by a stopwatch: one tree inventory per repository, filtering before download, no HTML crawl after a successful API read, one parse per changed blob, results reused by blob SHA, and no compiler, server, or model anywhere in the path. Embedding should remain the most expensive step of a build; if parsing ever rivals it, something is wrong.


## Risks and open checks

These are unresolved. Each is settled during implementation and the answer is recorded here.

| Open item | Why it matters | Where it is decided |
|---|---|---|
| Grammar licenses, maintenance, and wheels for every language in the table | Decides which languages ship as requirements and which drop a tier | Phase 8, recorded in the language table |
| PowerShell, MATLAB, Swift, Kotlin, and Stata grammar quality | These carry the most risk of being asked for and not delivered | Phase 8 |
| The near-duplicate collapse fix for line fragments | Silently loses real symbols if unhandled | Phase 8, with a test |
| Whether adding four `content_type` values needs anything of the two search clients | The vocabulary is pinned in the container format and both clients | Phase 8, against the reader checklist |
| Whether the protected-health-information lint's patterns behave sensibly on code | Notebooks and fixtures can carry real data | Phase 8 |
| `.m` belonging to both MATLAB and Objective-C | A wrong grammar produces confident nonsense | Phase 8 |


## Out of scope

Not in either phase: private GitHub repositories; GitLab or GitHub Enterprise ingestion; language servers; compilers; type resolution; control-flow or data-flow analysis; whole-program analysis; runtime tracing; building, running, or installing anything from an indexed repository; vulnerability scanning; free-form language-model code summaries; graph databases; a redesign of the embedding cache; and automatic submodule recursion.

Each can be revisited when there is a concrete retrieval benefit worth its cost.


## Conclusion

Phase 7 makes GitHub an ordinary source rather than a special website, and makes it hard to break: a token helps, its absence costs nothing, and a total API failure still leaves you with the documentation and an honest account of what is missing. Phase 8 adds structure on top — symbols, signatures, imports, calls, and maps — while keeping the index small by linking to code instead of copying it.

The existing shape is unchanged throughout. Sources produce documents, one build produces one compendium, and every output serializes it without knowing where any of it came from. Start with the phase that follows the last completed note in the [implementation plan](implementation-plan.md).


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Implementation plan](implementation-plan.md) — the order of work and the "done when" rule for each phase.
* [Extractium™ specification](extractium-spec.md) — the settled design: sources in section 5, confidentiality in section 7, the cache in section 8.
* [Architecture and Current State](architecture.md) — what exists in the repository today.
* [Configuration reference](configuration.md) — the settings file as it is implemented now.
* [Container format](container-format.md) — the index file and the checklist any reader must satisfy.
* [Data flow](data-flow.md) — where content goes between a source and an output.
* [Compliance and posture](compliance.md) — the controls that exist and the gaps that are known.
* [GitHub REST API documentation](https://docs.github.com/en/rest) — the endpoints this source calls.
* [Tree-sitter](https://tree-sitter.github.io/tree-sitter/) — the parser library Phase 8 uses.
* [Universal Ctags](https://ctags.io/) — the optional second parser.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
