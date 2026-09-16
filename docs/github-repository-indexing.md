<!--
This file is part of Extractium™
docs/github-repository-indexing.md
Author(s): Gabriel Mongefranco
Created: 2026-09-09
Last Modified: 2026-09-16
Summary: How Extractium reads GitHub repositories: the three-tier
ingestion ladder, the account guardrail, authentication, repository
selection, file filtering, caching, and the lightweight static code
analysis with its Tree-sitter language set and the records it produces.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## GitHub Repository Indexing

[← Back to README](../README.md)


## Summary

This page explains how Extractium™ reads a GitHub organization, user, or repository. It has two parts. The first is a source that talks to the GitHub API instead of scraping web pages, and that keeps working whatever happens: if a token is missing it uses the public API, and if the API cannot be used at all it falls back to a documentation-only crawl. The second is fast, local code analysis on top of that source, so a search can find where a function is defined and what calls it, without copying any code into the index.

Read this page if you maintain, review, or audit the GitHub parts of Extractium™. You need to know what a repository is. You do not need to know the GitHub API, Tree-sitter, or how a parser works. Each is explained where it comes up. The settings themselves are documented in the [configuration reference](configuration.md).


## Part 1: The GitHub API source

### Goal

Point Extractium™ at `github.com/DepressionCenter` and get every public repository's documentation into the index, without crawling a single rendered web page, and without the build failing when there is no token.

### The ingestion ladder

Extractium™ tries three ways of reading GitHub, in order, and stops at the first one that works.

| Tier | Name | What it needs | Documentation | Code analysis |
|---|---|---|---|---|
| 1 | Authenticated API | `GITHUB_TOKEN` in the environment | Complete | Yes |
| 2 | Unauthenticated API | Nothing | Complete | Yes |
| 3 | Documentation-only crawl | Nothing | Whatever the crawler can find | No |

Three rules govern the ladder:

1. Tier 2 is not a reduced mode. A public repository read without a token gets exactly the same treatment as one read with a token: the same files, the same records, the same code analysis. A token buys API capacity, not capability. Anything that indexes at tier 1 indexes at tier 2.
2. Tier 3 indexes documentation only. The crawler reads READMEs, Markdown, and the text documentation it can reach through links. It never scrapes a source-code page, and it never runs code analysis. GitHub's file viewer builds its content in the browser from an embedded data payload, so scraping it yields markup, not source. A parse of that would be worse than no parse.
3. The ladder applies to every GitHub source. It runs the same way for a `web` source whose seed URL happens to be a GitHub address and for an explicitly configured `github_api` source. An explicit source does not get a different ladder. It gets a louder report.

### Moving down the ladder

A tier is abandoned only when it cannot proceed. Recoverable reasons include:

- GitHub is unreachable or returning server errors.
- The request is refused for the credential in use.
- The remaining rate-limit budget cannot cover the work, and the reset is too far away to wait for.
- Repository enumeration fails before any useful content is produced.

A rejected token has its own rule: if the supplied credentials are refused, the source drops to tier 2 and carries on. A bad token is a mistake in your environment, not a reason to lose the build. The report names it, because a silently ignored token looks identical to a token that worked.

### What is not a tier change

Some failures are yours to fix, and quietly demoting them would turn a typo into a strange, empty result. These stop the source instead:

- A configuration file that names neither an owner nor a repository, or names more than one selector.
- An owner or repository that GitHub reports does not exist. Crawling `github.com/DperessionCenter` produces a 404 page, not a compendium.
- An output path or cache path the build cannot write.

The distinction is simple. The ladder handles "we could not reach GitHub", never "you asked for the wrong thing".

### Not losing or repeating work

A run can fail halfway. If the API read eight repositories out of twenty and then lost its budget, tier 3 must not fetch those eight again.

The source therefore keeps a ledger of every URL it has already turned into a document. The ledger is per run, in memory, and the crawler consults it as an exclusion list. This is the same mechanism that stops a successful API run from being crawled a second time through HTML. The partial case is just the general case.

Scope is preserved across a demotion as well. If the request was one repository, tier 3 crawls that one repository and does not widen to the owner's other work.

### Saying what happened

Every demotion is reported twice: once as it happens, through the progress callback, and once in the summary at the end of the build.

The summary states, per repository, which tier read it and what is therefore missing:

```text
DepressionCenter/extractium      tier 1 (authenticated API)     documentation, code analysis
DepressionCenter/ShareR          tier 2 (public API)            documentation, code analysis
DepressionCenter/FieldStationAI  tier 3 (documentation crawl)   documentation only; no code analysis
```

When an account holds more repositories than `max_repositories`, or a repository holds more indexable files than `max_files_per_repository`, the summary says so after the coverage lines:

```text
3 repository(ies) not read: max_repositories is 100; name them in include_repos to choose which are read
1 repository(ies) cut at 1000 files by max_files_per_repository: DepressionCenter/large-monorepo
```

The log names each one as it happens:

```text
  some-archive: not read; max_repositories is 100 (name it in include_repos to choose which repositories are read)
  DepressionCenter/large-monorepo: reading 1000 of 4212 indexable file(s); max_files_per_repository leaves out 3212 (3212 code)
```

The same facts are recorded inside the repository-map document the code analysis writes, so a person searching the finished index can see the coverage without going back to the build log. A cut repository's summary reads `Files indexed: 1000 of 4212 indexable files; the rest were left out by max_files_per_repository.` A gap the reader cannot see is a gap that will be mistaken for an answer.

### Recognizing a GitHub address

The `web` source stays host-agnostic. It does not learn GitHub rules. Instead, a site handler may offer a better source for a seed URL, and the GitHub handler is where that offer is made. GitHub knowledge stays in the GitHub file.

| Address | What is indexed |
|---|---|
| `github.com/OWNER` | Every selected public repository that owner has |
| `github.com/OWNER/REPO` | That one repository |
| Anything deeper under `github.com/OWNER/REPO/` | That one repository |
| `raw.githubusercontent.com/...` | That one file, as an ordinary crawl |
| `OWNER.github.io/...` | An ordinary web crawl |
| Any other git host | An ordinary web crawl |

A repository address never expands into every repository its owner has. An owner address means "this owner's repositories". A repository address means "this repository". Getting this backwards would turn a small request into hours of work and an index full of content nobody asked for.

The offer applies to the seed URL only. A link to some repository found halfway through crawling an unrelated website stays an ordinary link. Otherwise one stray mention could pull an entire GitHub account into a small site crawl.

### Only the accounts you asked for

GitHub account names turn up everywhere: in a README's credits, in a dependency list, in a fork notice, in a contributor's profile link, in an article that happens to cite somebody's project. Following them is how a build meant to read one organization ends up indexing thousands of strangers' repositories.

The rule: a GitHub account is read only when you named it. Everything else on the host is out of scope, whatever links to it and however it was found.

The allowed set is built from what your configuration asked for:

- every `org`, `user`, or `url` owner named by a `github_api` source;
- the owner in the address of any `web` source whose seed points at GitHub;
- any account listed in the `github_owners` setting, which exists so you can add one deliberately.

Nothing else joins that set. There is no rule that adds an account because it was linked, forked, depended on, or mentioned often.

Allowed is not the same as enumerated, and the difference matters:

| You did this | The account is read | Its whole account is listed |
|---|---|---|
| Named it as a source, by owner address | Yes | Yes |
| Named one of its repositories as a source | Yes, that repository | No |
| Added it to `github_owners` | Yes, repositories reached from what is in scope | No |
| Did not name it at all | No | No |

So adding an account to `github_owners` says "you may follow links into this account". It never says "index everything this account has ever published". Only naming an owner as a source does that.

The check reads the account out of the address, so it covers every GitHub-shaped host: `github.com/OWNER/...`, `raw.githubusercontent.com/OWNER/...`, and `OWNER.github.io`.

It is enforced in two places, because one is not enough. A disallowed account is never promoted to the API source, and it is never in crawl scope. The second half is the important one. A crawl seeded at `github.com/DepressionCenter` has `github.com` as its origin, and the default scope rule keeps a crawl to its origin. Without this rule every account on the host would be same-origin and therefore in scope.

Skipped accounts are counted and reported once at the end of the build, not once per link:

```text
Not read; add to github_owners to include: some-other-org (14 links), a-contributor (3 links)
```

That way you can see what was held back and add an account if you did want it, or see that the guardrail worked.

The rule reaches the crawler through two optional hooks on the site-handler protocol. `configure` hands the handler the build's settings after construction, and `allows` lets it veto any URL the crawl would otherwise follow. A handler that defines neither behaves as before. The same hook family carries the TeamDynamix portal-folder scope, through `scope_prefix`, so core knows no host at all. See the [plug-in architecture](plugin-architecture.md).

The API source also checks the owner GitHub reports. The owner arrives in an API response, which is untrusted like anything else read at runtime. A repository reporting an owner you did not name is skipped, so the rule holds even if a listing returns something unexpected.

### Telling an organization from a user

The source does not guess, and does not probe two endpoints to find out. It reads the account once and looks at the type GitHub reports. If it is an organization, it lists the organization's public repositories. If it is a user, it lists that user's own public repositories. If the account cannot be read at all, that is a ladder event, not a guess.

For a repository address, it fetches the repository directly. The repository's own metadata says who owns it and what kind of account that is.

### Authentication

The source reads `GITHUB_TOKEN` from the environment. The token:

- never appears in `config.yaml`;
- never appears in any output file;
- never appears in a log line, a progress message, or an error;
- travels only in a request header;
- is never handed to a parser, a subprocess, or a cache file.

The source indexes public repositories only, even when the token could read private ones. The confidentiality guardrail in the specification, section 7, separates local content from published content. It has no concept of a remote repository that is private, so an authenticated repository is not treated as ordinary public web content. A token raises the request budget. It does not widen what may be published.

### Choosing repositories

Defaults:

| Kind | Default | Why |
|---|---|---|
| Public | Included | The only kind the source reads. |
| Fork | Excluded | Indexing a project and several forks of it fills the index with near-identical copies. |
| Archived | Included | Archived documentation is still documentation. Dropping it silently loses history. |
| Empty | Skipped | Nothing to read. |
| Disabled | Skipped | Nothing to read. |
| Housekeeping (`.github`, `.github-private`) | Skipped | A name starting with a dot holds the account's profile, issue templates, and workflow templates, not a project's documentation. |

Configuration overrides the first three, and naming a housekeeping repository in `include_repos` reads it.

### Taking inventory before downloading

For each selected repository, in order: resolve the default branch, resolve the commit and tree it points at, request the recursive Git tree, and look at every path in it before asking for a single file body.

If GitHub marks the recursive tree truncated, the source walks the subtrees until the inventory is complete. A truncated tree that is treated as complete produces a repository that looks fully indexed and is not, which is the worst failure available here because it is invisible. The walk is keyed on each folder's path, which is unique, rather than on its tree object, because two folders holding identical files share one object and a walk keyed on the object would silently lose the second folder. A request ceiling covers the pathological case of a folder that reports itself as its own child.

The inventory gives a path, an object type, a blob SHA, and usually a size. That is enough to decide what is worth downloading.

### What gets indexed

Documentation is indexed in full. Its text goes through the normal chunker, exactly like a web page. "In full" means no summary replaces the original. The existing section and window limits may split a long file across several parents, which is ordinary behavior.

Files read as documentation:

`README*`, `*.md`, `*.markdown`, `*.txt`, `*.rst`, `*.adoc`, `*.asciidoc`, `CHANGELOG*`, `CHANGES*`, `HISTORY*`, `CONTRIBUTING*`, `SECURITY*`, `AUTHORS*`, `CONTRIBUTORS*`, `GOVERNANCE*`, `SUPPORT*`, `MAINTAINERS*`

These are the files people search: what changed, how to contribute, where to report a vulnerability, who wrote it. `LICENSE`, `NOTICE`, `CITATION`, and `CODE_OF_CONDUCT` files are not among them; they carry the same words in every project, and the housekeeping rule below skips them.

A `README.md` inside `docs/`, inside a package, or inside an examples folder counts the same as the one at the repository root.

Project and build files are indexed as text, with a short fixed heading naming their role. They often explain a project faster than its source does:

`pyproject.toml`, `requirements*.txt`, `setup.cfg`, `package.json`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, `build.gradle.kts`, `DESCRIPTION` and `NAMESPACE` (R packages), `renv.lock`, `Gemfile`, `composer.json`, `environment.yml`, `environment.yaml`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `CMakeLists.txt`, `codemeta.json`, project and solution files, and the GitHub Actions workflow files under `.github/workflows/` at the repository root.

Manifests are classified before documentation and before the settings rule, because `requirements.txt` carries a documentation extension and would otherwise be read as prose, and `pyproject.toml` carries a settings extension and would otherwise not be read at all.

Word, OpenDocument, RTF, PDF, and slide files (`.docx`, `.odt`, `.rtf`, `.pdf`, `.pptx`, `.odp`) are read into text, with their headings and their own keywords and description, a deck one section per slide, when the source sets `read_documents: true`. Each is downloaded on its own, one request per file, and the text read from it is cached under the file's blob name so a rebuild reads nothing again. The setting is off by default. The [configuration reference](configuration.md) explains the readers under "Reading document files".

Dependency lock files are excluded. A lock file is recognised by `lock` as a word in its name, so `package-lock.json`, `yarn.lock`, `uv.lock`, `poetry.lock`, `Cargo.lock`, `flake.lock`, and `requirements-lock.txt` are all caught, plus `go.sum`, `gradle.lockfile`, and `bun.lockb`, which carry no such word. They are long, they are mostly package names and version numbers, and the matching manifest already records what the project declared. `renv.lock` is the exception, because an R project's `DESCRIPTION` often does not pin anything and the lock file is where the real environment is written down. The word has to stand alone, so `deadlock.md` is prose and `lock.py` is code.

Three dotfiles are read: `.gitmodules`, `.env.example` with its `.env.sample` and `.env.template` siblings, and the workflow files at the repository root. Every other folder or file whose name starts with a dot is skipped, as the next section says.

### What gets skipped

Every rule reads a path only, so a repository is filtered from its inventory before a single file body is requested. The rules, in the order they are checked:

- **Folders that are never read**, matched as whole path segments so that `binder/` is not `bin/` and `database-notes.md` is not `data/`:
  - Build output and installed environments: `node_modules/`, `vendor/`, `dist/`, `build/`, `target/`, `coverage/`, `htmlcov/`, `venv/`, `env/`, `__pycache__/`, `bower_components/`, `packrat/`, `site-packages/`, `obj/`, `bin/`, `data/`, and `renv/library/`. A `bin/` folder holds what a build produced, which is a copy of source already in the repository. A `data/` folder holds the files a project reads and writes rather than anything written to be read, and skipping it also keeps a folder of participant records out of an index by default. The cost is the occasional README inside one of them, which is a good trade in this field.
  - Vendored code: `third_party/`, `thirdparty/`, `third-party/`, `3rdparty/`, `external/`, `externals/`, `extern/`, `deps/`, `contrib/`, `submodules/`, `vendored/`, `vendors/`.
  - Generated code: `generated/`, `__generated__/`, `gen/`, `autogen/`, `autogenerated/`, `codegen/`.
  - Test suites and what they hold: `tests/`, `test/`, `testing/`, `spec/`, `specs/`, `__tests__/`, `fixtures/`, `fixture/`, `testdata/`, `test_data/`, `golden/`, `snapshots/`, `__snapshots__/`, `mocks/`, `__mocks__/`. A fixture folder holds copies of other people's pages, and a golden folder holds a program's output. Only folders are skipped: a `test_app.py` beside its code is still read.
- **Dotfiles and dot-folders.** Any path segment that starts with a dot: `.git/`, `.venv/`, `.idea/`, `.vscode/`, `.github/` apart from the root workflow files, `.claude/`, `.gitignore`, `.editorconfig`, `.pre-commit-config.yaml`, and the rest. They are settings for programs, not writing for people. The exceptions are named in the section above.
- **Anything holding a credential**: `.env` and its variants, `.netrc`, `.npmrc`, `.pypirc`, SSH private keys, and files with a key, certificate, or keystore extension. A private key committed by mistake is still a private key; it is never downloaded, never cached, and never indexed.
- **Lock files**, as the section above describes.
- **Generated files recognised by name**: protocol buffer output (`*.pb.go`, `*_pb2.py`), designer and generated C# (`*.g.cs`, `*.Designer.cs`), anything marked `*.generated.*`, minified files (`*.min.js`, `*.min.css`), bundled scripts (`*.bundle.js`, `*.chunk.js`, `*.umd.js`, `*.esm.js`), and source maps.
- **Single-file libraries projects copy in whole**: the sqlite amalgamation (`sqlite3.c`, `sqlite3.h`, `sqlite3ext.h`), `cJSON`, the `stb_*.h` headers, `miniz`, and jQuery, Bootstrap, Lodash, Moment, D3, and three.js by their own file names. A `shell.c` beside `sqlite3.c` is not assumed to be sqlite's, and `d3chart.js` is somebody's chart.
- **Housekeeping files**: `LICENSE`, `LICENCE`, `COPYING`, `NOTICE`, `CITATION`, and `CODE_OF_CONDUCT` with any extension or none, and the instruction files written for coding agents rather than for people: `CLAUDE.md`, `AGENTS.md`, `CONVENTIONS.md`, `CODEX.md`, `GEMINI.md`, `SKILLS.md`, and `copilot-instructions.md`. Every project carries the same words in these. A code file that merely sounds like one, such as `agent.py` or `notice.py`, is still code.
- **C and C++ headers** (`.h`, `.hpp`, `.hh`, `.hxx`, `.inl`, `.tpp`, `.ipp`). A header declares what its source file defines, and the source file is the one the parsers read. A vendored library's public headers are also where a repository's forty thousand files come from.
- **Binary and media files**: executables, compiled objects, archives, images including SVG, audio, video, fonts, stored data, spreadsheets, presentations, and the binary `.doc` format, which has no reader.
- **Settings, styling, and query files** that are not project manifests: `.toml`, `.yml`, `.yaml`, `.json`, `.ini`, `.cfg`, `.conf`, `.properties`, `.xml`, `.css`, `.scss`, `.sass`, `.less`, and `.scm`. None is prose, and none is code the parsers know. `pyproject.toml`, `package.json`, `environment.yml`, and `pom.xml` are manifests and are read.
- **A page or script too long to have been written by hand.** An `.html`, `.htm`, `.js`, `.mjs`, `.cjs`, or `.jsx` file over 500,000 bytes, by the size the inventory reports, is a rendered report, a data dictionary, or a bundled application, and is skipped with a line saying so. A long Markdown manual is a manual, and is not held to this.

Submodules are not followed. The tree lists one as a commit entry with nothing under it. The `.gitmodules` file itself is indexed as a manifest.

An incremental rebuild carries forward every page the last build published that this build did not reach, so a licence file or a header indexed by an earlier version of the tool stays in the index until a full rebuild.

### The ceilings

Three ceilings are set in the settings file. `max_file_bytes` sets a maximum size per file, with a conservative default of 2,000,000 bytes; nothing above it is downloaded or parsed. `max_repositories`, default 100, is the most repositories of an account that are read, in the order GitHub lists them, which is alphabetical; the repositories past it are named in the log and the summary, and `include_repos` chooses which ones count. `max_files_per_repository`, default 1,000, is the most indexable files one repository contributes; files are read in a fixed order, so the root README is never the file left out. The build's `max_pages` setting does not count files read through the API. It applies to the documentation crawl the source falls back to, which is an ordinary crawl and counts pages like any other.

The other ceilings are fixed, and each exists because some repository has been seen to go past it with files that mean nothing to a reader:

| Ceiling | Value | What happens past it |
|---|---|---|
| Repositories per account, `max_repositories` | 100 | The repository is not read and not marked as read. The log names it and says how to choose which repositories count. A single repository named by `url` is never subject to it. |
| Files per repository, `max_files_per_repository` | 1,000 indexable files | Files are ranked, the root README first, then the other READMEs shallowest first, the rest of the documentation, the manifests, document files, and code last, and the first thousand are read. The log says how many of each kind were left out, and the repository's summary record says how many files it holds. |
| File size, `max_file_bytes` | 2,000,000 bytes | The file is not downloaded. Checked against the inventory and again against the downloaded body, in case the listing understated it. |
| Page or script written by hand | 500,000 bytes | An HTML or JavaScript file over it is skipped as generated, by the size the inventory reports, so no request is spent on it. |
| Text indexed whole | 200,000 characters | A documentation file or a page's text longer than this, here and in a web crawl alike, is indexed as a compact record: its title, its opening paragraph, its headings, and the forty terms it uses most, with a line saying the file was indexed that way. About 35,000 words, so a manual passes whole and a rendered data table does not. |
| Parse length | 1,500,000 characters | A code file longer than this is recorded by name, language, and length and not parsed. A page, notebook, or R Markdown file over it still has its text indexed; only the code inside goes unparsed. |
| Code files per repository | 3,000 | Files past the ceiling are named in the log and not parsed. A repository with more is a monorepo or a vendored tree, and a directory of thousands of tiny generated files is exactly what this stops. |
| Code blocks per container | 500 | Cells or chunks past it are not parsed. A generated notebook can hold thousands. |
| Notebook size | 20,000,000 bytes | Not read. Larger than `max_file_bytes`, so it applies only when that ceiling was raised. |
| Symbols from Universal Ctags | 2,000 per file | Later tags are dropped. |
| Definition depth | 3 levels | A definition nested deeper is a helper inside a helper and is not recorded. |
| Signature, documentation, constant value | 400, 800, and 80 characters | Cut, with an ellipsis. |
| Archive held in memory | 80,000,000 bytes, or a repository GitHub reports over 60,000 KiB | The repository is read one file at a time instead. |
| Listing pages | 100 pages of 100 | An account with more repositories than that is outside what one compendium holds. |

A skipped file always produces a progress event naming the repository, the path, and the reason. A selected file is never dropped in silence. An index quietly missing its largest documentation file is worse than one that says it skipped it.

A page whose content is written by script indexes as nearly nothing, because scripts are code and not text: a SchemaSpy `columns.html` holds its whole dictionary in one script as JSON, and its text is a dozen column headings. The per-table pages beside it carry the same columns as real tables, and those are what the index holds.

### Downloading: one archive, or one file at a time

One archive is the default. The scarce resource is requests, not bytes. Reading GitHub anonymously allows roughly sixty requests an hour for the whole build, and a single documentation-heavy repository can spend all of them one file at a time. The same content arrives in one request as an archive. A repository is therefore downloaded whole unless there is a reason not to.

Files are requested one at a time in two cases: the repository is larger than the memory ceiling, or the archive could not be read. An unreadable archive is not the end of that repository. Its files are asked for individually instead.

Before either route is chosen, everything already in the blob cache is taken out of the plan. A repository nobody has changed since the last build therefore needs no download at all. A repository with one changed file downloads one archive rather than one file, which is the cost of this default.

Both routes fill the same cache, keyed by the blob name Git gives those exact bytes, so a file read out of an archive is never downloaded again by either route.

If neither route is possible, because the repository is too large for an archive and has more files than the remaining request budget covers, that repository is reported and skipped, with a message saying authenticated access would fix it.

Archive handling is safe on every platform. Entries are streamed into memory and read there with the standard library's own archive reader. There is no external `tar` program and no shell, so nothing depends on what is installed. Nothing is extracted to disk, which is what makes the platform question go away: an archive path is only ever compared as text and its bytes read, never used to create a file. Windows' illegal file names, its path separators, and its path-length limit therefore never come into it, and no symbolic link is ever created. Only regular files are read, so a symbolic link or a device entry inside an archive is ignored rather than followed. The only file written is a cache entry named by its blob name, which is forty hexadecimal characters and legal everywhere.

### Rate limits

The source reads the rate-limit headers on every response and acts on them:

- It honors `Retry-After` when GitHub sends it.
- It honors the reset time when the remaining count reaches zero.
- It never retries in a tight loop, and never loops forever.
- It prefers moving down the ladder over waiting out a long reset.
- It asks for repository listings at the largest page size the API allows.

### Caching

GitHub gives every file body a blob SHA, which is an ideal cache key: the same SHA means the same bytes, whatever branch or path points at it.

```text
.kb_cache/
    github/
        repositories/   Repository metadata and trees, keyed by repository and tree SHA
        blobs/          File bodies, keyed by blob SHA
        analysis/       Parser output, keyed by blob SHA and parser signature
```

Nothing under `.kb_cache/github/` ever contains a token. A cache test checks this rather than assuming it.

### Configuration

The options an explicit source takes. The [configuration reference](configuration.md) explains each one:

```yaml
sources:
  - type: github_api
    label: Example Repositories
    org: DepressionCenter          # exactly one of org, user, or url
    include_repos: []              # empty means all matching repositories
    exclude_repos: []              # exclusion wins over inclusion
    include_forks: false
    include_archived: true
    include_code: true             # read the structure of the code as well as the docs
    read_documents: false          # read Word, OpenDocument, RTF, PDF, and slide files into text
    max_file_bytes: 2000000
    max_repositories: 100          # alphabetical; the rest are named in the log
    max_files_per_repository: 1000 # the root README is always read first, code last
```

Rules:

- Exactly one of `org`, `user`, or `url`. Two selectors is an error, not a merge.
- `include_repos` and `exclude_repos` match repository names, not URLs.
- No setting turns on private repositories.

Automatic handling needs no configuration at all:

```yaml
sources:
  - type: web
    label: Example Website
    seed_url: https://github.com/DepressionCenter/extractium
```

`github_owners` is a global setting rather than a source option, because it governs the whole crawl graph. A link found by one source can lead anywhere, so a guardrail that lived on one entry would leave the others open:

```yaml
github_owners:
  - some-collaborator
```

It holds exact account names, never patterns. This is deny by default: the list says what is allowed, and a pattern that quietly matches more accounts than intended is the failure this rule exists to prevent. An empty or absent list means the build reads only the accounts its own sources named.

### When something goes wrong

| Class | Examples | What happens |
|---|---|---|
| Source-fatal | Owner does not exist; every request blocked before any enumeration | The ladder runs. If tier 3 also cannot start, the source reports and stops |
| Repository-fatal | Metadata unreadable; default branch unresolvable; tree cannot be completed | Report that repository, move to the next one |
| File-local | Blob vanished between tree and download; over the size ceiling; binary content found after download | Report the path, keep going |

One bad repository does not destroy an organization-wide build. One bad file does not destroy a repository.

### Records this source produces

Every document keeps `source_type = github`. Two `content_type` values belong to this source:

| Value | What it is |
|---|---|
| `manifest` | A project or build file indexed as text |
| `repo_map` | The synthetic per-repository summary: the file inventory, and the code structure when the parsers ran |

`readme`, `text`, `wiki`, and `release_notes` are the other values a document from GitHub carries.

Categories use the existing hierarchy, not a second GitHub-only system. `DepressionCenter/extractium/extractium/core/build.py` becomes `DepressionCenter`, `extractium`, `extractium`, `core`.

### Where the source's code is

| File | What it holds |
|---|---|
| `extractium/sources/github_client.py` | The REST transport: the token, paginated listings, trees, file bodies, one archive read in memory, rate-limit headers, and the split between a failure to work around and a failure only you can fix |
| `extractium/sources/github_files.py` | Which paths are documentation, which are project files, and which are never downloaded |
| `extractium/sources/github_api.py` | The source itself: the ladder, repository selection, the ledger, the records, and the coverage report |
| `extractium/sources/github.py` | The site handler, which also offers the API source for a GitHub seed and enforces the account rule in crawl scope |


## Part 2: Lightweight static code analysis

### Goal

Make a repository's code findable without cloning it, compiling it, running it, or sending it to a language model. A search can answer: where is this defined, what does this file contain, what does it import, what calls it, and where do I click to read it.

### What a record holds, and what it never holds

Records carry structure, not source text. This follows the specification, section 5: signatures, documentation, and purpose, never raw code bodies.

The reason is not squeamishness about publishing public code. It is that the compendium is one static file, around 10 MB, searched with vectors from `bge-small-en-v1.5`, a model trained on short English passages. Source bodies would multiply the file size and embed poorly, so they would cost a great deal and retrieve badly. A signature, a docstring, and a link to the exact lines on GitHub retrieve better and cost almost nothing.

So a symbol record holds the name, the kind, the exact signature, the documentation attached to it, its relationships, its location, and a link. To read the implementation, you follow the link.

### Where a file summary comes from

A summary can be produced honestly without a language model. In order of preference, the first that exists is used:

1. The file's own documentation: a Python module docstring, a Rust `//!` block, a JSDoc `@fileoverview`, a Lua or R leading comment block, roxygen `@title` and `@description`.
2. A structured header. This organization's own convention puts a `Summary:` line in every file header, so any repository following it already carries a written summary.
3. The nearest README: a short excerpt from the README in the file's own directory, attributed as such.
4. A deterministic template over what the parser found, for example: "Python module defining 4 functions and 1 class; imports 3 local modules; contains no module-level executable code."

The first three are quotations. The fourth is arithmetic. None of them is a guess. A summary never asserts something the parser did not observe. "This function validates permissions" is never written unless "validates permissions" was written by a human in the file.

### Languages

Each language below was checked against the dependency gate on 2026-09-10, and Windows batch on 2026-09-15.

| Language | Files | How it is read | Grammar package and license |
|---|---|---|---|
| Python | `.py`, `.pyi` | Parsed | `tree-sitter-python`, MIT |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | Parsed | `tree-sitter-javascript`, MIT |
| TypeScript | `.ts`, `.tsx`, `.mts`, `.cts` | Parsed | `tree-sitter-typescript`, MIT |
| Shell | `.sh`, `.bash`, `.zsh`, `.ksh` | Parsed | `tree-sitter-bash`, MIT |
| Lua | `.lua`, and Lua inside `.lsp` | Parsed | `tree-sitter-lua`, MIT |
| C# | `.cs` | Parsed | `tree-sitter-c-sharp`, MIT |
| HTML | `.html`, `.htm` | Parsed for the code inside it | `tree-sitter-html`, MIT |
| Markdown | `.md` | Indexed as documentation, not as code | `tree-sitter-markdown`, MIT |
| SQL | `.sql` | Parsed | `tree-sitter-sql`, MIT |
| Kotlin | `.kt`, `.kts` | Parsed | `tree-sitter-kotlin`, MIT |
| Swift | `.swift` | Parsed | `tree-sitter-swift`, MIT |
| PowerShell | `.ps1`, `.psm1`, `.psd1` | Parsed; Universal Ctags when the grammar will not load | `tree-sitter-powershell`, MIT |
| Windows batch | `.bat`, `.cmd` | Parsed: each label is a function, named as written, and every command run is a call | `tree-sitter-batch`, MIT |
| MATLAB | `.m` | Parsed, unless the file opens like Objective-C | `tree-sitter-matlab`, MIT |
| Go | `.go` | Parsed; a method is recorded under its own name, with its receiver kept in the signature | `tree-sitter-go`, MIT |
| Rust | `.rs` | Parsed; an `impl` block is recorded as a class named for its type, so its methods belong to that type | `tree-sitter-rust`, MIT |
| R | `.R`, `.r` | Universal Ctags, or its outline | None published |
| C, C++, Java, Ruby, PHP, Perl, Julia, SAS | Their usual extensions | Universal Ctags, or its outline | None taken; see below |
| Stata, Visual Basic | `.do`, `.ado`; `.vb`, `.bas` | Its outline | None published |

Two languages are included specifically for this field:

- SQL, because registry pulls, REDCap exports, and cohort definitions in health research are written in it, and they encode the study definitions people most often need to look up.
- MATLAB, because behavioral and physiological analysis code (Psychtoolbox tasks, actigraphy, continuous glucose monitoring signal processing) is still commonly MATLAB, and that work is exactly what a diabetes or mental-health repository holds.

R is the gap, and it is a bigger one than Stata. A great deal of the analysis code in health research is written in R. There is no R grammar on the Python package index: a search of the whole index on 2026-09-10 found 289 packages whose name starts with `tree-sitter`, and not one of them is R. So an R file is read by Universal Ctags where that is installed, and recorded with its path, language, length, and link where it is not. Publishing an R grammar, or installing Universal Ctags, is what closes this.

The eight languages read by Universal Ctags alone are not the field's languages: grammars exist for most of them, and one can be added the way the others were when a repository in scope needs it. Go and Rust were added that way, when a repository in scope turned out to be written in Go. Until then a file in one of them is recorded with its symbols where Ctags is installed and with its outline where it is not.

Stata has no maintained grammar and no Ctags parser, so a Stata file carries its path, language, length, and link and nothing more. A pattern-matching reader was considered and rejected. It would be a parser that lies at the edges of the language, and a file honestly labelled as unparsed is better than a file described wrongly.

MATLAB and Objective-C share the `.m` extension. A file opening with `#import`, `@interface`, `@implementation`, or `@protocol` is Objective-C, and it keeps its outline rather than being parsed by the MATLAB grammar into confident nonsense.

### Files that hold another language inside them

Several formats in this field are containers, not languages. The embedded code is pulled out and parsed with the grammar it belongs to.

| Container | Inner language | How |
|---|---|---|
| R Markdown (`.Rmd`) and Quarto (`.qmd`) | R, Python, and others | Parse the Markdown, index the prose as documentation, parse each fenced chunk with the grammar its label names |
| Jupyter notebook (`.ipynb`) | Usually Python or R | Read the JSON, index Markdown cells as documentation, parse code cells with the kernel's grammar. Outputs are never indexed |
| HTML | JavaScript | Parse the document, index the text, parse `<script>` contents with the JavaScript grammar |
| Lua Server Pages (`.lsp`) | Lua | Parse the surrounding HTML, index the text, parse each embedded Lua block with the Lua grammar |

Lua Server Pages works the way PHP does: an HTML page with blocks of Lua inside it. Nothing runs to read one. The reader finds the delimiters, hands each block to the Lua grammar, and hands the rest to the HTML path, so a `.lsp` file yields both its page text and its Lua symbols.

Two implementations spell the opening delimiter differently, and both are read:

| Written as | Where it comes from |
|---|---|
| `<?lua … ?>` | The Kepler project's Lua Pages, which CGILua serves |
| `<? … ?>` and `<?= … ?>` | The same, short forms |
| `<% … %>` and `<%= … %>` | The same, the alternative pair |
| `<?lsp … ?>` and `<?lsp= … ?>` | RealTime Logic's Barracuda Application Server |

An equals sign after the opening delimiter means "print this expression", which is still Lua and is read as Lua. `<?xml … ?>` is the one processing instruction that is not. An LSP page serving XHTML opens with it, and it is left alone.

Notebooks matter more than their place in this table suggests. In this field a great deal of real analysis lives in `.ipynb` and `.Rmd` files and nowhere else. They also carry the greatest privacy risk in the whole feature: a notebook's stored outputs can contain printed rows of real participant data. That is why outputs are never read, and why the protected-health-information check should be pointed at code records before any of them are published (`phi_lint: 'all'`).

### What is not used, and why

No compiler, no build step, no container runtime, no graph database, no language model, and no Language Server Protocol client.

The last one is worth separating from Lua Server Pages, which shares the initials and is nothing like it. A Language Server Protocol client would mean a per-language daemon installed, launched, and shut down on three operating systems, which is against everything this feature is for. Lua Server Pages is a file format, costs nothing, and is supported.

### How the parser layer is arranged

One registry maps a file to a language, a grammar, and a set of queries. Without it, every new language would become another branch in the GitHub code.

The registry holds, per language: the extensions and bare filenames it claims, the grammar package and version, the grammar's license, the query file, and which captures that language supports. The last field matters because not every concept exists everywhere. Asking a Bash grammar for class inheritance returns nothing, not an error.

Extraction rules live in small query files, one per language, so the engine stays generic:

```text
extractium/code/queries/python.scm
extractium/code/queries/lua.scm
```

Where a query is adapted from a grammar's own tag queries, its license and attribution are preserved.

### The dependency gate

Before a grammar became a dependency, each was checked and recorded for: a license compatible with GPL v3 or later; wheels for Windows, macOS, and Linux with no compiler; support for the project's Python range; active maintenance; no known critical vulnerability; and a version that the existing lock process can pin.

What the gate found, on 2026-09-10, and for the batch, Go, and Rust grammars on 2026-09-15: every grammar in the table above is published under the MIT license. Each ships wheels for Windows, macOS, and Linux that need no compiler, and each declares Python 3.9 or 3.10 as its floor, covering this project's range. Every version is pinned in `pyproject.toml` under the `code` extra, and the lock file is generated with that extra, so the build scripts and the scheduled workflow install the parsers with everything else.

The set is still an extra rather than a requirement of the package: a developer install names it, as `pip install -e ".[code]"`, and a computer without it still records every code file with its path, language, length, and link. A test holds the lock file to the extra, so a grammar cannot be added to one and left out of the other.

A bundle was evaluated and rejected. `tree-sitter-language-pack` ships 371 languages, including R, under one MIT license, and it looked like the answer to the R gap. From version 1.0.0 it stopped shipping the grammars: the package is two megabytes, and it downloads compiled grammars from the network the first time a language is used. That is a build quietly fetching native code mid-crawl, which is the same supply-chain risk this project refused when it removed the reference script's install-at-import helper. The version that still bundled its grammars is a year old and on a line nobody maintains. So the individual grammar packages were taken instead: seventeen packages, each pinned, each auditable, and none of them fetches anything at run time.

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

A test file beside the code it tests is indexed, because a test is often the clearest statement of what something is supposed to do. A test folder is not: `tests/`, `spec/`, `__tests__/`, and their fixture, golden, and snapshot folders hold copies of other people's pages and a program's recorded output, which nobody searches a code index for.

A few limits keep the records useful: a definition nested more than three levels deep is skipped as a helper inside a helper, a name like `__author__` is skipped as header boilerplate, and a file over about 1.5 million characters is not parsed at all, though a page or notebook that long still has its text indexed. The table under "The ceilings" above lists every limit. The progress log names every file left out and why.

### File and symbol records

A file record is compact and lists what the file defines, imports, exports, which files it reaches into, and which reach into it. It names the analysis that produced it: `tree-sitter`, `ctags`, or `file metadata only`. That last label is what an unsupported language gets, and it is much better than the file disappearing.

A symbol record names the repository, path, language, symbol, and kind, then the signature, the documentation, the imports it uses, the calls it makes, the files it relates to, and a link to its exact lines. It does not contain the body.

### Line links, identifiers, and the near-duplicate collapse

A file record links to its normal GitHub file URL. A symbol record adds a line fragment: `.../blob/main/path/to/file.py#L42-L88`.

This is safe for identifiers. Parent identifiers hash a normalized URL, and `normalise` in [core/fetch.py](../extractium/core/fetch.py) strips the fragment, so moving line numbers do not change a file's identity, and two symbols in one file stay distinct because the symbol name is part of the heading. Two definitions in a file can share a name (an overloaded method, or a function declared twice for two platforms), so the second occurrence of a heading in a repository is numbered and the records stay distinct.

Two build steps compare pages by address, and both need care with code records:

- The near-duplicate collapse in [core/dedup.py](../extractium/core/dedup.py) protects a page's own repetitions from being collapsed into each other. It takes a page key that ignores the fragment, so one file counts as one page and its own definitions never collapse into each other, while boilerplate shared between different files is still collapsed. Near-identical small functions, repeated test setup, and generated accessors are common and legitimate, and would otherwise be dropped as if they were shared web-page boilerplate.
- The step that indexes a page once however many sources reached it compares normalised addresses, and a normalised address has no fragment. For code records it compares the address and the heading together, so every definition in a file survives, while two sources reaching one web page still index it once. Without that rule, measured against this project's own repository, 1,809 of 1,944 records were thrown away and only the first definition of each file survived.

### Relationships between files

After the files are parsed, an in-memory symbol table is built for the repository: qualified name, short name, module, path, kind, location. Relationships are then resolved against it.

Imports come first, because they are cheap and usually reliable: Python absolute and relative imports, JavaScript and TypeScript relative imports, R `source()` and `library()` where the path is visible in the text, C and C++ local includes, C# namespaces, Kotlin and Java packages, Lua `require`, and PowerShell dot-sourcing. Imports of external packages are recorded as external dependencies and not matched to local files.

Calls are resolved conservatively, with the confidence stated on every edge:

| Confidence | Example |
|---|---|
| `resolved` | A call inside one file to a uniquely named function in that file |
| `probable` | A call through a symbol that file explicitly imported |
| `unresolved` | `obj.save()` where nothing static says what `obj` is |

A guessed cross-file call is never reported as certain. Reverse edges (imported by, called by, inherited by, implemented by) are computed from the finished graph, never by parsing anything twice.

### Repository and owner maps

Each repository gets one synthetic map document: name, description, primary language, topics, license, default branch, the ingestion tier that read it, its important documentation, its manifests, its likely entry points, its top-level directories, its major definitions and modules, its file dependencies, its cross-file calls with confidence, and its tests. A large repository may need several parents, which the chunker handles.

An owner-level request also gets one owner map listing every repository with its description, primary language, topics, and archived status. This is what lets a question like "which Depression Center project handles knowledge-base indexing?" find the right repository before searching inside it.

### Universal Ctags as a second parser

Tree-sitter always goes first. Ctags is used only when there is no grammar for the file, the grammar will not load, a query does not match the installed grammar, or the parse fails badly enough to yield nothing useful.

Ctags is optional and never bundled. At the start of code analysis, the build looks for `ctags` on the path, confirms it is Universal Ctags and not a different program of the same name, confirms it supports JSON output, and caches that answer for the build. If it is absent, unsupported files still get a file-level record. Set `ctags_fallback: false` to keep a build from launching any other program at all.

Running it safely matters, because everything involved comes from a repository nobody here controls:

- It is invoked with an argument array. No shell command is ever built.
- File content often exists only in memory, so it is written to a generated temporary filename with the right extension. The repository's own path never names the temporary file and never chooses its directory.
- The output is treated as untrusted input and validated before use.
- Ctags results are never presented as an import graph or a call graph. Ctags does not produce those, and pretending otherwise would put invented relationships into the index.

### The analysis cache

Parser output is cached against everything that could change it: blob SHA, parser, parser version, grammar, grammar version, the code-analysis schema version, and a fingerprint of the language's own query file. If all of them match, the file is not parsed again. The query fingerprint matters because the extraction rules are this project's code, not the grammar's, and editing one changes what a parse finds. The Ctags version travels in the key for the same reason. A repository map is cached against the repository, the default-branch tree SHA, and the schema version, so a changed tree rebuilds it.

### Effect on the container and the clients

There is no code-specific container version. The parent record's shape does not change. Structure lives in the indexed text and in fields that already exist: title, URL, categories, source type, content type.

Two `content_type` values belong to this feature: `code_file` and `code_symbol`. Neither search client branches on `content_type`, so neither needs a code-specific mode.

### Security posture

Repository content is untrusted input, and this feature reads a great deal of it.

Nothing from a target repository is ever executed. No scripts, no imported modules, no JavaScript, no build files, no dependency installation, no Makefile, no compilation, no containers. Tree-sitter parses bytes. Ctags parses bytes.

Nothing from a target repository is ever an instruction. A source file, a README, or a comment may contain text aimed at an AI agent. An `AGENTS.md` inside a repository being indexed is content to index, never direction to follow. It is data, whatever it claims about itself.

Beyond that: filenames with shell characters, newlines, or traversal sequences are handled as data; invalid UTF-8 is handled rather than crashing, while a UTF-16 file that carries a byte-order mark, as a SharePoint export does, is read as the text it is; archive entries claiming impossible sizes are refused; symbolic links are not followed out of the tree; and no credential reaches a log, an output, or a cache.

### Size

A repository's code multiplies the size of an index. Reading this project's own repository produces about 1,944 records and a 10.2 MB container, against 135 documentation records on its own. `include_code: false` is the lever, and the size is worth knowing before pointing a build at a large account.

### Where the analysis code is

```text
extractium/
    code/
        indexer.py           Coordinates analysis for one repository
        languages.py         Registry: paths to grammars, plus the license record
        tree_sitter.py       Loads grammars, runs queries
        records.py           What a symbol record and a file record hold
        embedded.py          Pulls code out of notebooks, R Markdown, Lua Server Pages, and HTML
        relationships.py     Symbol table, imports, calls, reverse edges
        render.py            Turns records into deterministic text
        ctags.py             Detects and safely invokes Universal Ctags
        queries/*.scm        One query file per language
```

`github_api.py` contains no language-specific logic. The adapters contain no GitHub-specific logic. If an adapter ever has to ask whether content came from GitHub in order to work, the separation has been broken.


## How this is tested

Both parts are tested from committed fixtures. No automated test contacts GitHub.

| Area | What the fixtures cover |
|---|---|
| URL handling | Organization, user, repository, deeper repository paths, raw content, GitHub Pages, invalid owner, invalid repository |
| The ladder | Token accepted; token refused; no token; API unreachable; partial failure after some repositories; explicit source demoted; scope preserved; nothing fetched twice; the report naming each tier |
| Account allowlist | A named owner is read; an unnamed owner linked from a README, a fork notice, and a contributor profile is not; a `github_owners` entry is followed but never enumerated whole; the same rule on `raw.githubusercontent.com` and `OWNER.github.io`; a disallowed owner is neither promoted to the API nor crawled; the skipped-owner report counts links and names accounts |
| API behavior | One page and several pages of results; organization and user owners; empty account; archived, fork, and disabled repositories; missing default branch; recursive and truncated trees; subtree walking; blob and archive fetches; rate-limit headers; 401, 403, 404, and 429; a repository disappearing mid-run |
| File filtering | `tests/test_github_files.py`: Markdown, plain text, extensionless README, manifests, source, test folders and test files beside code, vendored and generated folders, generated and bundled files by name, single-file libraries and their look-alikes, headers, housekeeping and agent-instruction files and the code files that merely sound like them, every dotfile and the three exceptions, lock files by the word and the exceptions, settings and styling extensions, binaries, a page too long to be hand-written, the reading order. `tests/test_source_github_api.py`: oversized files, `.env`, `.env.example`, the two ceilings and their log and summary lines. |
| Parsing | Per language: definitions, signatures, documentation, imports, exports, calls, inheritance, constants, annotations, module-level code, and a file with recoverable syntax errors |
| Embedded code | An `.Rmd` with R and Python chunks, an `.ipynb` with outputs present, an HTML file with inline script, an `.lsp` page with several Lua blocks |
| Relationships | Same-file calls, relative imports, aliases, local includes, unique and ambiguous names, dynamic calls, reverse edges, all three confidence levels |
| Ctags | A fake executable for determinism; no shell invocation; JSON capability detection; malformed output refused; absence does not break Tree-sitter files |
| Caching | Same blob not downloaded twice; same signature not reparsed; changed blob, grammar version, or schema version invalidates; changed tree rebuilds the map; no cache file contains a token |
| Security | Malicious archive paths; symbolic links; traversal; shell characters and newlines in filenames; invalid UTF-8; impossible declared sizes; private repository metadata ignored even when fixture credentials could read it; no credential in any log line |

Performance is checked by properties, not by a stopwatch: one tree inventory per repository, filtering before download, no HTML crawl after a successful API read, one parse per changed blob, results reused by blob SHA, and no compiler, server, or model anywhere in the path. Embedding remains the most expensive step of a build.


## Out of scope

Private GitHub repositories; GitLab or GitHub Enterprise ingestion; Language Server Protocol clients; compilers; type resolution; control-flow or data-flow analysis; whole-program analysis; runtime tracing; building, running, or installing anything from an indexed repository; vulnerability scanning; free-form language-model code summaries; graph databases; and automatic submodule recursion.

Each can be revisited when there is a concrete retrieval benefit worth its cost.


## Conclusion

The GitHub source makes GitHub an ordinary source rather than a special website, and makes it hard to break: a token helps, its absence costs nothing, and a total API failure still leaves you with the documentation and an honest account of what is missing. The code analysis adds structure on top, with symbols, signatures, imports, calls, and maps, while keeping the index small by linking to code instead of copying it.

The rest of the build is unchanged by either. Sources produce documents, one build produces one compendium, and every output serializes it without knowing where any of it came from. To point a build at GitHub, see the `github_api` section of the [configuration reference](configuration.md).


## Additional Resources

* [Extractium™ README](../README.md): project overview and quick start.
* [Extractium™ specification](extractium-spec.md): the design: sources in section 5, confidentiality in section 7, the cache in section 8.
* [Architecture](architecture.md): how the code is organized.
* [Plug-in architecture](plugin-architecture.md): the optional site-handler hooks the account rule uses.
* [Configuration reference](configuration.md): the settings file.
* [Container format](container-format.md): the index file and the checklist any reader must satisfy.
* [Data flow](data-flow.md): where content goes between a source and an output.
* [Compliance and posture](compliance.md): the controls that exist and the gaps that are known.
* [GitHub REST API documentation](https://docs.github.com/en/rest): the endpoints this source calls.
* [Tree-sitter](https://tree-sitter.github.io/tree-sitter/): the parser library the code analysis uses.
* [Universal Ctags](https://ctags.io/): the optional second parser.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
