<!--
This file is part of Extractium™
docs/configuration.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-16
Summary: Reference for the Extractium build configuration file: the
global settings, the sources list, the outputs list, the options each
built-in type accepts, how the URL pattern lists interact, and the error
messages the loader produces.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Configuration Reference

[← Back to README](../README.md)


## Summary

Extractium™ reads its settings from one small YAML file, usually called `config.yaml`. The file lists the sources to read, the outputs to write, and a few global settings. This page lists every setting, what it does, and what happens when you leave it out. Use it when you set up a build, and again when you need to work out why a crawl reached the wrong pages.

A ready-to-copy starting point ships with the project: [examples/config.example.yaml](../examples/config.example.yaml). To check a file without running a build, load it from Python:

```python
from extractium.config import load_config

settings = load_config("config.yaml")
print(settings.sources[0].options["seed_url"], settings.max_pages)
```


## Where the file goes

Extractium™ keeps the engine and your organization's data apart. Put `config.yaml` in your own project folder, next to the output you publish, and run the build from that folder. Paths inside the file are read from wherever you run the build.

To start:

1. Copy `examples/config.example.yaml` into your project folder as `config.yaml`.
2. Change `seed_url` under the web source to the page you want the crawl to start from.
3. Delete every line you do not need. Anything you leave out uses its default.


## The shape of the file

The file has three parts. Only `sources` is required.

```yaml
sources:                 # required: at least one source
  - type: web
    label: Example Knowledge Base
    seed_url: 'https://example.edu/TDClient/000/ExampleOrg/Home/'

outputs:                 # optional: defaults to container + llmstxt
  - type: container
  - type: llmstxt

max_pages: 500           # optional global settings
```

Each entry in `sources` and `outputs` names a `type` and then that type's own options. The type is the name of a plug-in. The built-in types are listed below. A plug-in you drop into the `plugins/` folder can add more. See the [plug-in architecture](plugin-architecture.md) page.

Every source also needs a `label`. See "Naming your sources" below.


## Global settings

| Setting | Type | Default | What it does |
|---|---|---|---|
| `name` | text | title of the first page crawled | Display name of the compendium, the collection this build writes, recorded in every output. |
| `slug` | text | `compendium` | The short name this compendium goes by. It names the output files that give no `file` of their own: `<slug>.json` for the container and `<slug>.sqlite` for the database, so `slug: efdc-compendium` publishes `efdc-compendium.json`. Lowercase letters, digits, and hyphens, up to 64 characters, because the name ends up in a web address. |
| `out_dir` | text | `dist` | Folder every output is written under. |
| `cache_dir` | text | `.kb_cache` | Folder for fetched content between builds. Name a visible folder, such as `kb-cache`, if your build reads YouTube: part of that folder has to be committed. See the `youtube` source below. |
| `max_pages` | whole number | `10000` | The most a source may read, counted in the source's own unit: pages for a `web` crawl (document files included), videos for `youtube`, deposits for `dspace`, files for `local`, and concept files for `okf`. Each source counts its own against it, so two sources may read twice as many between them. A source that stops here says so in the log. Must be 1 or more. A `github_api` source has two ceilings of its own, `max_repositories` and `max_files_per_repository`, and meets `max_pages` only when it falls back to crawling a repository's documentation pages. |
| `delay_seconds` | number | `0.5` | The least time, in seconds, between two requests to the same site. It holds across every source and every worker in the build. Use `0` for no wait. |
| `parallel_sources` | whole number | `4` | How many sources run at the same time. `1` runs them one after another. See "Reading sources at the same time" below. |
| `parallel_pages` | whole number | `4` | How many page fetches one web crawl keeps in flight. `1` fetches one page at a time. Pages are still visited and indexed in the same order either way. |
| `user_agent` | text | `Extractium/<version> (+https://github.com/DepressionCenter/extractium)` | How the crawler introduces itself to each site. Sent with every request, including the one for `robots.txt`. |
| `respect_robots_txt` | true or false | `true` | Whether each site's `robots.txt` rules are honored. Turning it off also lets a page that refuses the crawler be retried once as a browser. See "How robots.txt is read" and "What happens when a site refuses the crawler" below. |
| `transport` | `auto`, `browser`, or `plain` | `auto` | How the crawler opens its connections. `auto` makes an ordinary request and, only when the answer is a bot-protection challenge, retries once over a browser-shaped handshake, keeping that choice for the host. `browser` uses the handshake from the first request. `plain` never does. The crawler's own `user_agent` is sent either way. See "How a site behind bot protection is read" below. |
| `rebuild` | `full` or `incremental` | `full` | What happens to a page this build did not see. `full` publishes exactly what was read. `incremental` also keeps the pages of the last build that this one did not reach, unless the server confirmed them gone. See "Full and incremental rebuilds" below. |
| `phi_lint` | `local`, `all`, or `off` | `local` | Which content the check for protected health information scans. |
| `keywords` | true or false | `true` | Whether every section is named with keywords and every page with tags, from the text alone. Needs the `keywords` extra; without it the build says so once and goes on. See "Keywords and tags" below. |
| `github_owners` | list of text | empty | Extra GitHub accounts this build may follow links into. See "Which GitHub accounts a build reads" below. |

Quote the value when you turn the check off (`phi_lint: 'off'`). YAML reads a bare `off` as the word false, and the build refuses it with a message naming the setting.

See "The check for protected health information" below for what the check does.

### Reading sources at the same time

A build with several sources runs up to `parallel_sources` of them at once, and each web crawl keeps up to `parallel_pages` fetches in flight. Both are on by default because they change how long a build takes and nothing else:

- A site is never asked faster than `delay_seconds` allows. The pause is kept per site, across every source and every worker, so two sources that read the same site together still send one request per pause between them.
- The result is the same. Sources hand their pages over in the order they are listed, whichever finished first, so a page two sources both reach still goes to the one listed first. A crawl visits, follows, and indexes pages in the order a one-at-a-time crawl would.
- The log is readable. When more than one source runs at once, every progress line starts with the label of the source it belongs to, such as `Depression Center Website | [  12] https://...`. A crawl's own lines for one page stay together under that page's line.
- Stopping still works. Ctrl+C, or a failure in one source, ends the other sources at their next page rather than at the end of their crawl.

Set both to `1` for a build that runs everything one after another with an unprefixed log, which is useful when you are reading the log closely.

```yaml
parallel_sources: 1
parallel_pages: 1
```

### Which GitHub accounts a build reads

A GitHub account name can turn up anywhere: in a README's credits, in a list of dependencies, in a fork notice, in somebody's profile link. If a build followed all of them, one link would pull thousands of other people's repositories into your index.

So a build reads a GitHub account only when you named it. That means:

- an account named by a `github_api` source, under `org`, `user`, or `url`;
- the account in the address a `web` source starts from;
- an account you listed in `github_owners`.

Nothing else is read, however often it is linked to.

`github_owners` says "you may follow links into this account". It does not say "index everything this account has published". Only naming an account as a source does that:

| You did this | The account is read | Its whole account is listed |
|---|---|---|
| Named it as a source, by owner address | Yes | Yes |
| Named one of its repositories as a source | That repository | No |
| Added it to `github_owners` | Repositories reached from what is in scope | No |
| Did not name it | No | No |

Write exact account names. Patterns and addresses are refused, because a pattern that matches more accounts than you meant is the exact mistake this list prevents.

```yaml
github_owners:
  - some-collaborator
```

The rule covers `github.com`, `raw.githubusercontent.com`, and `<account>.github.io`, since one account owns content on all three. Accounts left out are counted and reported once at the end of the build, so you can see what was held back and add it if you did want it:

```text
  coverage : Not read; add to github_owners to include: some-other-org (14 links), a-contributor (3 links)
```


## Sources

Every entry needs a `type` and a `label`. The options below are per type. An option you leave out takes its default.


### Naming your sources

Every source must give itself a name:

```yaml
sources:
  - type: web
    label: Depression Center Website
    seed_url: 'https://example.org/'

  - type: web
    label: Peer-to-Peer Program
    seed_url: 'https://peer.example.org/'
```

| Option | Type | Default | What it does |
|---|---|---|---|
| `label` | text | none (required) | The name a reader sees for this source. At most 60 characters. |

The label travels with every section the source produces. It heads a section in `llms.txt`, it is stored in the index as `source_label`, and a search client uses it to say where an answer came from.

The label is required rather than guessed because both sources above are of type `web`. Nothing in the address or the page says which is the main site and which is a program microsite. Only you know that. Without a label, a search result could say no more than "web", and a reader could not tell the two apart.

Keep it short and use the name people actually say. "Video Library" is better than "YouTube channel for the center".

Two sources may share a label on purpose. Two sibling collections of one repository are one place to a person looking for an answer, so giving both the same label puts them under one heading.

### `web`: crawl a website

| Option | Type | Default | What it does |
|---|---|---|---|
| `seed_url` | text | one of these two is required | The page the crawl starts from. Must begin with `http://` or `https://`. |
| `seed_urls` | list of text | one of these two is required | Several pages to start from, for a site whose sections do not link to one another. Still one crawl. |
| `include_patterns` | list of patterns | empty (see below) | Pages the crawl is allowed to visit. |
| `leaf_patterns` | list of patterns | empty | Single pages on other hosts that the site links to. Fetched and indexed, never followed for links. See "Single pages on another host" below. |
| `crawl_exclude_patterns` | list of patterns | asset files plus what the enabled handlers add | Pages the crawl must not fetch. |
| `index_exclude_patterns` | list of patterns | asset files plus what the enabled handlers add | Pages the crawl may visit, but whose content stays out of the index. |
| `extra_crawl_exclude_patterns` | list of patterns | empty | Pages the crawl must not fetch, added to the list above rather than replacing it. The usual way to keep one site's own navigation out. |
| `extra_index_exclude_patterns` | list of patterns | empty | Pages to leave out of the index, added to the list above rather than replacing it. |
| `site_handlers` | list of names | every installed handler | Which site handlers take part. `[]` means the generic handler only. The generic handler always takes part, and always last. |
| `read_documents` | true or false | `false` | Whether a link to a Word, OpenDocument, RTF, or PDF file in scope is fetched and its text indexed. See "Reading document files" below. |

A page whose text runs past 200,000 characters, such as a site that publishes everything on one page, is indexed as an outline (its title, opening paragraph, headings, and most frequent terms) rather than chunked whole, and the log says so. The same ceiling applies to repository files; [GitHub repository indexing](github-repository-indexing.md) lists it with the others under "The ceilings".

A short entry is normal:

```yaml
sources:
  - type: web
    label: Example Website
    seed_url: 'https://example.edu/TDClient/000/ExampleOrg/Home/'
```

#### Starting in more than one place

Some sites have sections that do not link to one another: two sibling collections in a repository, a microsite nobody links to from the main navigation. Give `seed_urls` instead of `seed_url` and the crawl starts at each of them:

```yaml
sources:
  - type: web
    label: Example Website
    seed_urls:
      - 'https://library.example/collections/first-collection'
      - 'https://library.example/collections/second-collection'
```

Give one or the other, never both.

This is one crawl, not two sources, and the difference matters. One crawl keeps one list of the pages it has visited, so a page reachable from both starting points is fetched once and indexed once. It also shares one `max_pages` budget and one set of patterns. Two sources covering the same ground would each fetch that page.

Scope is worked out from every seed. A link is followed if it is inside the scope of any of them, so two seeds on different hosts put both hosts in scope. If you need something narrower than a whole host, write `include_patterns`.

#### When a seed redirects

Short links are convenient and they hide where they go. `https://example.edu/kb` might land on a portal at another address entirely.

The crawl works out what it is allowed to visit from the address you wrote, so after such a redirect every link on the page it received would be out of scope, and the crawl would stop after one page. The build notices this and refuses the seed, naming the address to use instead:

```text
SKIP https://example.edu/kb -- it redirects to https://portal.example/TDClient/210/Org/Home/,
which is outside what this source may crawl. Nothing there could be followed, so the crawl
would index one page and stop. Use https://portal.example/TDClient/210/Org/Home/ as the seed
instead, or add an include pattern that covers it.
```

Put the address it names in your settings file. A redirect that stays in scope, such as `http` to `https` or a missing trailing slash, is normal and passes without comment.

Every other page is checked the same way. A page inside the site that sends the crawler to another host, or to an address the exclude patterns cover, is skipped with the landing address named, because what arrived is not this site's content and would otherwise be indexed under this site's address. Add the other place to `include_patterns`, or as a source of its own, if it should be indexed.

### Reading document files

Three sources can read document files: `web`, `local`, and `github_api`. Each has a `read_documents` setting, off by default. Turn it on and the source reads `.docx`, `.odt`, `.rtf`, `.pdf`, `.pptx`, and `.odp` files into text, with the headings kept so the index cuts a long document into sections the way it cuts a web page, and a slide deck one section per slide.

The Word, OpenDocument, RTF, and slide readers are built into the tool and need no extra software. The PDF reader uses the `pypdf` library, which is the `pdf` extra. The build scripts and the scheduled workflow install it from the lock file; a developer install names it:

```bash
pip install "extractium[pdf]"
```

Without it, every PDF is skipped with a line that says so, and everything else is read.

What is read from a Word, OpenDocument, or RTF file:

- Headings, paragraphs, lists, and tables. A table becomes rows of cells.
- The file's own properties: its title, subject, keywords, and description, which some authors fill in under File, Properties. The subject, keywords, and description are indexed as the first paragraph of the document, so a search finds a file by what its author said it was about. When a file is longer than the 200,000-character ceiling and is indexed as an outline, those properties are what the outline keeps.
- The title, in this order: the first heading in the text, then the title in the properties, then the first line when it is short, then the file name.

What is read from a PDF:

- The text of each page, in order. A page becomes one paragraph, or several where the file's own layout leaves blank lines.
- Headings that say where you are. A PDF with bookmarks gets a heading from each bookmark, placed before the page it points to with the page number appended, so a manual is cut at its chapters and a citation names the page. A PDF without bookmarks gets a `Page N` heading before every page, unless it has only one.
- The title, subject, and keywords from the file's document properties. The subject and keywords open the indexed text, as for the other formats. The title is the properties title, then the first line of the first page when it is short, then the file name; a heading the reader made from a page number is never a title. A properties title that ends in a file extension, as a PDF made from a Word file often has, loses the extension.

What is read from a PowerPoint or OpenDocument presentation:

- Every slide, in the order the deck shows them, under a heading that numbers it and carries the slide's title: `Slide 2: Warning signs`, or `Slide 3` for a slide with no title. The index cuts the deck at those headings, so a search result cites the slide.
- The text on each slide, top to bottom, with bulleted lines marked as list items, and tables as rows of cells.
- The speaker notes of each slide, as one paragraph that begins `Notes:`, so a reader can tell what was said from what was shown.
- The title, subject, keywords, and description from the file's properties, as for the other formats. The title is the properties title, then the first slide's title, then the first line of the first slide when it is short, then the file name; a slide heading is never the deck's title.

What is not read:

- The old binary `.doc` and `.ppt` formats. They have no safe reader, so such a file is named as unreadable rather than guessed at. Save it as `.docx` or `.pptx` to have it indexed.
- An encrypted PDF. It is skipped and named, and no password is ever tried.
- A PDF whose pages hold no text, which is what a scanned document looks like to a reader. It is skipped with `likely scanned images` in the line. There is no text recognition.
- Pages past the five-hundredth of one PDF. The text ends with a line saying how many pages were not read.
- Spreadsheets (`.xlsx`, `.ods`).
- Pictures on slides, the slide number, the date, and the header and footer boxes of a deck.
- Pictures, comments, footnotes, headers, footers, and tracked deletions inside a file.

A PDF is read in a separate process with a time limit of 30 seconds per file. A file that runs past it is skipped with `the reader gave up after 30 seconds`, and the next file starts a fresh process. The limit is there because a malformed PDF can keep a parser busy for a very long time, and a process can be stopped where a thread cannot.

On a `web` source, a link to a document file is fetched only when it is in scope, like any other link. Most document files sit on another host, such as a content-delivery network, so a `leaf_patterns` entry is usually needed to reach them:

```yaml
sources:
  - type: web
    label: Example Program
    seed_url: https://program.example.org/
    read_documents: true
    leaf_patterns:
      - '^https://files\.example\.org/'
```

A file is never followed for links, so a document on another host never starts a crawl of that host. The same file linked under two addresses, such as with and without a download flag, is fetched twice but indexed once. A file larger than 20,000,000 bytes is skipped and named. A file that answers with a web page, such as a sign-in page, is skipped with the landing address named.

On a TeamDynamix portal, the list of files attached to an article is not in the article's page; the portal loads it separately. With `read_documents` on, the crawl fetches that list for each article, one request per article that counts as a page, and reads the files it links. Each file is served at an address that names it by identifier alone, such as `Shared/FileOpen?AttachmentID=...&ItemID=...`, so the format is decided from the bytes, and the document is titled by the file name the portal sends when the file itself carries no title. The portal links every file twice, to view and to download; the crawl fetches it once. With the setting off, neither the list nor the files are fetched.

On a `local` source, turning the setting on adds `**/*.docx`, `**/*.odt`, `**/*.rtf`, `**/*.pdf`, `**/*.pptx`, and `**/*.odp` to the default globs. A document file your own globs select while the setting is off is skipped with a line saying so, never read as text.

On a `github_api` source, document files in a repository are downloaded one request each, and the text read from each is cached under the file's blob name, so a rebuild reads nothing again. The `max_file_bytes` ceiling applies to them as to every file.

Every document's text goes through the same check for protected health information as every page. A file shared on a website is exactly where a stray identifier turns up, so consider `phi_lint: all` on a build that reads documents.

### `local`: read files from a folder

| Option | Type | Default | What it does |
|---|---|---|---|
| `path` | text | none (required) | The folder to read. |
| `include_globs` | list of glob patterns | `**/*.md`, `**/*.txt`, `**/*.html`, plus `**/*.docx`, `**/*.odt`, `**/*.rtf`, and `**/*.pdf` when `read_documents` is on | Which files under the folder are read. |
| `read_documents` | true or false | `false` | Whether Word, OpenDocument, RTF, and PDF files are read into text. See "Reading document files" above. |

Content from a local source stays out of every output unless that output sets `include_local: true`. See "Outputs" below.

The `path` is the folder to read. Files are read as UTF-8. A file the patterns select but whose real location is outside the folder, reached through a shortcut or a symbolic link, is skipped and the reason is printed. A folder that does not exist stops the build, so a mistyped path does not look like an empty folder.

Markdown, plain text, and HTML are read by default. Word, OpenDocument, RTF, PDF, PowerPoint, and OpenDocument presentation files are read when `read_documents` is on. Spreadsheet files are not read.

### `github_api`: read repositories through the GitHub API

| Option | Type | Default | What it does |
|---|---|---|---|
| `org` | text | none | A GitHub organization. Reads its public repositories. |
| `user` | text | none | A GitHub user. Reads that person's own public repositories. |
| `url` | text | none | A GitHub address. An owner address reads that owner's repositories; a repository address reads that one repository. |
| `include_repos` | list of text | empty | Repository names to read. Empty means all of them. |
| `exclude_repos` | list of text | empty | Repository names to leave out. An exclusion always wins. |
| `include_forks` | true or false | `false` | Reads forks too. Off by default, because a project and several forks of it fill the index with near-identical copies. |
| `include_archived` | true or false | `true` | Reads archived repositories. On by default, because archived documentation is still documentation. |
| `include_code` | true or false | `true` | Reads the structure of the repository's code as well as its documentation. See "Reading the code" below. |
| `ctags_fallback` | true or false | `true` | Lets Universal Ctags read the languages no grammar covers, when it is installed. Set it to `false` to keep a build from launching any other program at all. |
| `read_documents` | true or false | `false` | Whether Word, OpenDocument, RTF, and PDF files in a repository are read into text, one request each. See "Reading document files" above. |
| `max_file_bytes` | whole number | `2000000` | Largest single file to download. Anything larger is skipped, and every skipped file is named in the log. Raise it for a repository whose documentation is a few large files; a text file over 200,000 characters is then indexed as an outline rather than whole, as [GitHub repository indexing](github-repository-indexing.md) explains under "The ceilings". |
| `max_repositories` | whole number | `100` | The most repositories of an account to read, in the order GitHub lists them, which is alphabetical. Every repository past it is named in the log and counted in the summary. Name the ones you want in `include_repos` to choose which count. A single repository named by `url` is never subject to it. |
| `max_files_per_repository` | whole number | `1000` | The most indexable files one repository contributes. Files are read in a fixed order, the root README first, then the other READMEs, the rest of the documentation, the project files, document files, and code last, so what a larger repository loses is code, never its README. The log names how many files of each kind were left out, and the repository's summary record says so too. |

Give exactly one of `org`, `user`, or `url`. Two is an error, not a request for both.

An account listing leaves out repositories whose names start with a dot, such as `.github` and `.github-private`. They hold the account's profile, issue templates, and workflow templates rather than a project's documentation. Name one in `include_repos` to read it.

```yaml
sources:
  - type: github_api
    label: Example Repositories
    org: DepressionCenter
    exclude_repos:
      - old-prototype
```

Most of the time you do not need this type at all. Point a `web` source at a GitHub address and it reads the API by itself:

```yaml
sources:
  - type: web
    label: Example Website
    seed_url: https://github.com/DepressionCenter/extractium
```

What gets read: README files, Markdown, plain text, and the other documentation a repository carries, plus short project files such as `pyproject.toml`, `DESCRIPTION`, `package.json`, `Dockerfile`, and the workflow files under `.github/workflows/`, plus its source files when `include_code` is on, plus its Word, OpenDocument, RTF, and PDF files when `read_documents` is on.

What is never read: build output, installed environments, vendored and generated folders, and test folders with their fixtures; every folder or file whose name starts with a dot, apart from the workflow files, `.gitmodules`, and `.env.example`; licence, notice, citation, and code-of-conduct files, and the instruction files written for coding agents; dependency lock files; C and C++ headers; minified and bundled scripts; single-file libraries such as the sqlite amalgamation and jQuery; settings files such as `.toml`, `.yml`, `.json`, and `.ini` that are not project files; style sheets; binaries, images, and media; and anything holding a credential. That includes `bin/` and `dist/`, which hold what a build produced, and `data/`, which holds the files a project reads and writes rather than anything written to be read. Skipping `data/` also keeps a folder of participant records out of an index by default. A page or script over 500,000 bytes is skipped as generated. [GitHub repository indexing](github-repository-indexing.md) lists every rule under "What gets skipped".

Reading the code: with `include_code` on, each source file gets a record naming what it defines, what it brings in, and which files reach into it, and each definition in it gets a record of its own: the signature, the documentation somebody wrote for it, what it calls, and a link to its exact lines on GitHub. No source body is ever indexed. To read the implementation you follow the link.

Code analysis needs the parser set, which is an optional install:

```bash
pip install "extractium[code]"
```

Without it a build still reads every source file and records its path, language, length, and link, but not what is inside it. The same is true of a language nobody has published a grammar for. Python, JavaScript, TypeScript, shell, Lua, C#, SQL, Kotlin, Swift, PowerShell, MATLAB, Go, and Rust are parsed. R is not: no R grammar is published for Python, so an R file is read by Universal Ctags where that is installed and recorded by name where it is not. Stata is recorded by name everywhere. The repository's own summary record names which of these happened, so a reader can see the gap.

Notebooks, R Markdown, Quarto, Lua Server Pages, and HTML pages are read twice over: their prose is indexed as documentation, and the code inside them is parsed with the language it is written in. A notebook's saved outputs are never read, because they can hold printed rows of real data.

Code multiplies the size of an index. Reading this project's own repository produces about 135 documentation records, or about 1,900 records with `include_code` on, and a 10 MB index file rather than a 4 MB one. Keep that in mind before pointing a build at a whole account. Set `include_code: false` on sources where the code is not what people are searching for.

How files are downloaded: a repository is normally downloaded once, as a single archive, and the wanted files are read out of it in memory. Nothing is ever extracted to disk. This spends one request per repository instead of one per file, which matters because reading GitHub anonymously allows only about sixty requests an hour in total. A repository too large to hold in memory has its files requested one at a time instead. Either way, each file is stored under its blob name, so the next build downloads nothing that has not changed.

Tokens: set `GITHUB_TOKEN` in the environment to raise the request limit. It never goes in the configuration file, in an output, in a log line, or in the cache. A token raises how much a build can read. It never widens what a build may publish, and private repositories are never indexed.

When GitHub cannot be read, the build tries three ways in order: with a token, without one, and finally an ordinary crawl of the documentation pages. The first two produce exactly the same result for a public repository. The third reads documentation only and runs no code analysis. Whatever happens, the summary names each repository and the way it was read:

```text
  coverage : DepressionCenter/extractium  tier 2 (public API)  documentation, code analysis
```

A refused token drops to reading GitHub anonymously and says so. A misspelled account name stops the build instead, because a quiet fall back would give you a strange, empty result rather than an error.

### `youtube`: read captions

Indexes what is said in a video, not the video itself. Each stretch of a transcript becomes a section addressed at the moment it begins, so an answer can cite a link that opens the video at the words it quoted.

| Option | Type | Default | What it does |
|---|---|---|---|
| `channel_id` | text | none | A channel to read. Any way of naming it works; see below. |
| `playlist_ids` | list of text | empty | Playlists to read, as ids or as addresses. |
| `video_ids` | list of text | empty | Single videos, as ids or as any address that names one. |
| `languages` | list of text | `en` | Caption languages to ask for, in order of preference. The first track that exists is used. |
| `include_playlists` | true or false | `true` | Whether the channel's own playlists are read as well as its uploads. |
| `only_channel_videos` | true or false | `true` | Whether a video found through a playlist is indexed only when the channel published it. |
| `delay_seconds` | number | the build's own | Seconds between requests to YouTube. Never less than 1; see below. |
| `audio_fallback` | true or false | `true` | Whether a video whose caption request YouTube refuses is transcribed from its audio instead. The build scripts install the audio packages; a developer install names the `whisper` extra, and without it the setting does nothing. See "When YouTube refuses the machine" below. |

At least one of `channel_id`, `playlist_ids`, or `video_ids` is required.

```yaml
sources:
  - type: youtube
    label: Example Video Library
    channel_id: "https://www.youtube.com/@ExampleChannel"
    languages: ["en"]
```

#### Naming a channel

Use whichever form your browser showed you. All of these mean the same channel, and a trailing `/videos` or `/playlists` is ignored:

| Written as | Example |
|---|---|
| A handle | `@ExampleChannel` |
| A handle's address | `https://www.youtube.com/@ExampleChannel` |
| A custom address | `https://www.youtube.com/examplechannel` |
| The id | `UCxxxxxxxxxxxxxxxxxxxxxx` |
| The id's address | `https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx` |

Anything but the last two costs one request, once: the channel page states its own id, and that answer is stored so later builds cost nothing. A value that is not a channel at all is refused when the settings file is read, not halfway through a build.

Playlists and videos work the same way. A playlist may be its id or any address with `list=` in it; a video may be its id, a `watch?v=` address, a `youtu.be` short link, or a `/shorts/`, `/live/`, or `/embed/` address.

#### Videos linked from other sites

A page crawled by a `web` source may link to a video. The crawl never follows a YouTube link, but it collects the videos those links name, and once every source has run it offers them to each `youtube` source in the build. A source reads a linked video only when its publisher is known and is a channel the source names; a source that names no channel reads none of them, a video whose publisher cannot be read is left out, and `only_channel_videos` does not change this. The publisher comes from the Data API when a key is set, and from YouTube's public oEmbed endpoint for any video the API did not describe, or for every video when there is no key or the key is refused. An unlisted video is described by both.

The summary says what became of the linked videos, and then lists their publishers, one channel per line, with how many videos it published, how many were read, and whether it is a channel the source names:

```text
69 video(s) linked from crawled pages: 47 read, 19 left out because another channel published them, 3 left out because YouTube would not say who published them
  @ExampleCenter           47 linked  47 read  a channel this source names
  @ExampleHospital         11 linked   0 read  another channel; left out
  @ExampleUniversity        8 linked   0 read  another channel; left out
  not reported by YouTube   3 linked   0 read  publisher unknown; left out
```

A video YouTube will not describe is private, removed, or has embedding switched off. A video a named channel published that was still not read is counted too, with the reason: YouTube refused the machine, or `max_pages` was reached. The publisher list is how you decide whether to name another channel on the source.

#### What gets read from a channel

Both of these, every time, whether or not you asked for a playlist:

1. Everything the channel published, read from its uploads playlist. That includes its shorts and its past live streams, which the "Videos" tab on the site leaves out.
2. The playlists the channel shows, and the videos in them. Turn this off with `include_playlists: false`.

A playlist is a list of whatever its owner chose, so a channel's playlists routinely hold other people's videos: a conference talk, a partner's explainer, something the owner simply liked. By default those are left out, because indexing them would put another organization's words in your compendium under your name. The build says how many it left out. Set `only_channel_videos: false` to index them anyway.

A video you named yourself under `video_ids` is always indexed. Naming it is your decision and this rule does not second-guess it.

#### The API key, and when you need one

You do not need one. Without a key, channels and playlists are listed by reading YouTube's own pages, and titles come from a public endpoint that needs no key either.

A key gets you one thing: the whole of a long listing. See the next section.

The key is read from the `YOUTUBE_API_KEY` environment variable, never from this file. A key is a credential, and this file is committed to a repository beside the output it produced.

```bash
export YOUTUBE_API_KEY=EXAMPLE_API_KEY      # macOS, Linux
$env:YOUTUBE_API_KEY = 'EXAMPLE_API_KEY'    # PowerShell
```

#### Why a long listing stops at 100 videos without a key

YouTube's `robots.txt` allows the channel and playlist pages this build reads. It disallows `/youtubei/`, which is the address a page calls for its next batch when you scroll. Extractium honors `robots.txt` by default, so one allowed request gets the newest 100 videos of a listing and stops there. The build says so, once, and says which listings it stopped short on.

You have two ways past it:

| Do this | And you get |
|---|---|
| Set `YOUTUBE_API_KEY` | The whole listing, through the documented API, with no rule bent. This is the recommended path. |
| Set `respect_robots_txt: false` | The whole listing, by paging the way the page itself does. This is the same switch that lets a challenged page be retried as a browser, and it applies to every source in the build, not just this one. Use it only for content you own or have permission to read. |

A listing that came back with fewer than 30 items is the whole listing, and nothing is said about it: a four-video playlist has no second page.

#### Why a YouTube build has to run on your own machine

YouTube refuses caption requests that come from cloud-provider addresses, and GitHub Actions runs on a cloud provider. A scheduled build therefore cannot read a transcript, however it is configured.

Extractium works around this by storing everything it reads under `cache_dir`:

| Path | What it holds |
|---|---|
| `<cache_dir>/youtube/videos/<video id>.json` | One video's title, description, tags, caption language, and timed caption lines, whether they came from the caption track or from the audio. A file written by hand needs only the caption lines. |
| `<cache_dir>/youtube/audio/` | Audio being transcribed, one temporary folder per video, removed when the transcript is stored. Empty between builds. |
| `<cache_dir>/youtube/listings/<playlist id>.json` | The videos a playlist held when it was last listed. |

Build once on your own machine, commit that folder, and every later build reads it instead of asking YouTube. This is the one cache you must not delete: it is the only copy of the captions your compendium is built from. Because it has to be committed, name a visible `cache_dir` such as `kb-cache` rather than leaving the default `.kb_cache`, which most projects ignore.

A stored transcript has no expiry date. A build uses it because it exists, not because it was checked against YouTube, since checking is exactly what a cloud runner cannot do. To pick up corrected captions, delete that video's file and build again on a machine YouTube answers.

The [data repository template](../examples/data-repo/kb-cache/README.md) shows the folder with its files in place.

#### Pointing a build straight at YouTube

You can skip the `youtube` source entirely and put a YouTube address in a `web` source's `seed_url`. The build recognises it and reads captions instead of crawling:

```yaml
sources:
  - type: web
    label: Example Video Library
    seed_url: "https://www.youtube.com/@ExampleChannel"
```

A channel address reads that channel, a `playlist?list=` address reads that playlist, and a watch address, a `youtu.be` link, or a `/shorts/` address reads that one video. Use the `youtube` source itself when you want to set `languages` or any of the options above.

YouTube addresses are never crawled as pages, wherever they turn up. A video's words are in its caption track, so a crawled YouTube page gives a title and nothing else. If a build finds YouTube links while crawling your site, it says how many and leaves them alone; add a `youtube` source to index them.

#### How fast it asks

YouTube tolerates far less than a documentation site does. A run that asked for about 145 transcripts back to back was refused partway through, and everything after that would have been refused too.

So this source waits at least one second between requests, whatever the build's `delay_seconds` says. Set the source's own `delay_seconds` higher if you are reading a large channel and would rather be sure:

```yaml
sources:
  - type: youtube
    label: Example Video Library
    channel_id: "https://www.youtube.com/@ExampleChannel"
    delay_seconds: 2
```

A few hundred videos therefore takes a few minutes on the first run. It costs nothing afterwards: stored transcripts are read from disk with no pause at all.

If YouTube does refuse the machine partway through, the build keeps every video it had already read, stops asking for more, and says the result is incomplete. Build again later, or on another machine, and it picks up where it left off from the stored transcripts.

#### When YouTube refuses the machine

YouTube refuses caption requests from cloud-provider addresses, from shared addresses such as a mobile carrier's, and from any address that has asked too often. It does not gate the audio the same way. The build scripts and the scheduled workflow install the audio packages from the lock file, so a refused video is transcribed from its audio instead: the audio track is downloaded with yt-dlp, transcribed on the CPU with faster-whisper, and stored beside the other transcripts, with the video's title, description, and tags as the downloader reports them. Once one request has been refused in a build, every later video goes straight to the audio, so a refused build costs one refused request and not one per video.

A developer install has to name the extra:

```bash
pip install -e ".[whisper]"
```

A few things to know:

- One model, everywhere. Every build uses Whisper's `base.en`, its smallest English model, on the CPU with 8-bit weights, so two machines transcribing the same video store the same words. The model is about 75 MB and downloads once, into the same cache the embedding model uses. It reads a talk well enough to search; it does not know speaker names, and neither do YouTube's own automatic captions.
- Speed. On a plain laptop CPU it transcribes about ten to fifteen minutes of speech per minute, so a one-hour talk takes four to six minutes. A channel of two hundred talks is an afternoon, once, because a stored transcript is never fetched again.
- Disk. The audio of a video is downloaded under `<cache_dir>/youtube/audio/` while it is transcribed and removed as soon as the transcript is stored. Nothing over 500 MB is downloaded.
- Weight. The extra pulls in about 200 MB of packages. It is in the lock file anyway, because YouTube refuses captions to most machines that build on a schedule, so the audio path is the usual one rather than the exception. Commit the cache after a build, and later builds read the store instead of transcribing again.
- Set `audio_fallback: false` on a source to keep a refused build from reaching for the audio even where the packages are installed.

The audio path speaks to YouTube the way the caption library does, through the interface YouTube's own player uses, and it runs nothing it finds on the page: no JavaScript runtime is configured for the downloader, and no post-processing is asked of it.

#### What you need installed

Fetching captions needs one extra package. The build scripts and the scheduled workflow install it from the lock file. A developer install names it:

```bash
pip install "extractium[youtube]"
```

A build that reads only stored transcripts does not need it, which is what makes a scheduled run work on a plain install.

#### What a video without captions does

Nothing stops. The video is skipped, the build says how many were skipped, and the rest are indexed. A video whose owner turned captions off has nothing to read, and that is a normal thing to meet rather than a broken build.

### `dspace`: read a repository's deposits

Reads scholarly deposits out of a DSpace repository, such as the University of Michigan Library's Deep Blue, through the repository's own interface rather than by crawling its pages.

| Option | Type | Default | What it does |
|---|---|---|---|
| `api_url` | text | none (required) | Where the repository's interface lives, such as `https://repository.example.edu/server/api`. |
| `site_url` | text | none (required) | Where a reader opens a deposit. Recorded on every document, so a search result is a link a person can follow. |
| `collections` | list of text | none (at least one) | Which collections to read. See "Naming a collection" below. |
| `include_full_text` | true or false | `true` | Indexes the text the repository extracted from each deposit's files. `false` indexes each deposit's description alone. |
| `max_file_bytes` | whole number | `2000000` | Largest extracted text file to read. Anything larger is skipped, and every skipped file is named in the log. |

```yaml
sources:
  - type: dspace
    label: Deep Blue Documents
    api_url: https://backend.production.deepblue-documents.lib.umich.edu/server/api
    site_url: https://deepblue.lib.umich.edu
    collections:
      - https://hdl.handle.net/2027.42/195355
      - https://hdl.handle.net/2027.42/195645
```

The two addresses are different hosts, and neither one implies the other. `site_url` is the site a person opens. `api_url` is the interface behind it, and it is not guessable: it is named in the reader site's own settings, under `dspaceServer`. Point `api_url` at the reader site and the build stops with a message saying the address answered a web page rather than data.

Naming a collection: write each collection whichever way you have it in hand. All four mean the same thing:

| Written as | Example |
|---|---|
| The handle link the repository publishes | `https://hdl.handle.net/2027.42/195355` |
| A handle on its own | `2027.42/195355` |
| The address a browser shows after following that link | `https://deepblue.lib.umich.edu/collections/3acf951c-e107-4b8d-8f7d-ced171665b11` |
| The collection's identifier on its own | `3acf951c-e107-4b8d-8f7d-ced171665b11` |

Collections are listed, never discovered. A repository holds the deposits of everybody at a university, so a build reads the collections it was given and nothing it merely found a link to. This is the same rule as `github_owners`, and it matters more here: a search scope the repository does not recognize is answered with every deposit it holds rather than refused. Each collection is therefore confirmed to exist before anything is searched, which is also how its name is read. A collection the repository does not have stops the build and is named, because a quiet skip would look like an empty collection.

What gets read: one document per deposit, holding its abstract first, then its authors, date, subjects, rights, publisher, and every address it carries, then the text of its files. The opening of the abstract is also the deposit's summary and the subjects are its tags, as the "Summaries, keywords, and tags" section describes. A deposit's address list is sorted into three kinds and all three are kept: its handle (the permanent citation), its DOI (how the work is cited in the literature), and any other address, which is often the project's own documentation.

Where the file text comes from: the repository extracted it when the file was deposited, and this source reads that. No PDF reader, no Word reader, no archive handling, and no new dependency. A deposit whose files hold no readable text, such as a poster deposited as an image, is still indexed from its description, and the record says plainly that its file contents are not in the index.

Set `phi_lint: 'all'` for a build with this source. The default scans only content read from a folder on your computer, because that is the content nobody has published. A deposit in a public repository was published deliberately, but text a machine pulled out of a research poster is exactly where a stray identifier is most likely to sit, and reading it is worth one setting. Expect a long report: a scholarly deposit names its authors, and a poster often prints an email address, so the check flags them. Every line in that report is a question for a person, not a verdict. See "The check for protected health information" below.

Rebuilds: the repository reports when each deposit last changed, and that stamp is stored beside the stored text. A collection nobody has touched costs one request per hundred deposits and downloads nothing. The summary says how much of each collection is description alone:

```text
  Deep Blue Documents  42 deposit(s)  35 with file text  7 description only
```

### `okf`: read a knowledge bundle

| Option | Type | Default | What it does |
|---|---|---|---|
| `path` | text | none (required) | The bundle folder to read. |

Reads an Open Knowledge Format bundle, such as the `okf` output writes, from this tool or any other that follows the format. Every Markdown file under the folder except the reserved `index.md` and `log.md` is a concept: its front matter names the address it was read from (`resource`), its `title`, and its `type`, which becomes the content type again. The title heading and the source line under the front matter are not indexed twice.

A concept whose resource is a `local:` address was read from a folder by the build that wrote the bundle, and stays local here, so every output drops it unless that output sets `include_local: true`. A concept whose resource is a web address is not local: the bundle is a copy of published pages. A resource that is anything else is refused and the file skipped, with the reason printed. A file the folder reaches through a shortcut or a symbolic link to somewhere else is skipped the way the `local` source skips one.

```yaml
sources:
  - type: okf
    label: Partner Knowledge Base
    path: ./partner-okf
```

### Source types from plug-ins

A type that is not one of the built-in types above is passed to the registry as written, with its options unchecked. The plug-in that answers to that name checks its own options. If no plug-in answers to it, the build stops with a message listing the known names.


## Outputs

Leave `outputs` out to write the two defaults: the container file and the `llms.txt` pair. Every output accepts `include_local`.

| Type | Options | Default | What it writes |
|---|---|---|---|
| `container` | `file`, `gzip` | `<slug>.json`, or `<slug>.json.gz` with `gzip: true` | The binary compendium every search client reads. See the [container format](container-format.md). `gzip: true` writes the same bytes compressed; both clients recognize the compressed form by its signature, and the JavaScript client's `inflateContainer` runs before its loader. |
| `llmstxt` | none | | `llms.txt` and `llms-full.txt`. |
| `sqlite` | `file` | `<slug>.sqlite` | A SQLite database with the same content. |
| `okf` | none | | An Open Knowledge Format folder of Markdown files, written as `okf/` under `out_dir`. |

| Option on every output | Type | Default | What it does |
|---|---|---|---|
| `include_local` | true or false | `false` | Lets content from `local` sources into this output. |

A `file` is always a relative path under `out_dir`. An absolute path, or one that climbs out with `..`, is refused. Leave `file` out and the output is named after the `slug` global setting, which is the usual choice: one short name, and every file follows it.

```yaml
slug: example-compendium    # writes example-compendium.json and example-compendium.sqlite
outputs:
  - type: container
  - type: llmstxt
  - type: sqlite
    include_local: true      # this file stays on your machine, so local content is fine
```

An output type that is not one of the four above is passed to the registry as written, like a plug-in source type.

The `okf` output writes a folder rather than a file. Inside `out_dir/okf/` you get:

| File | What it holds |
|---|---|
| `index.md` | Every page as a link, grouped under the name of the source it came from. |
| `log.md` | One dated entry naming the build that wrote the folder. |
| `<source name>/<page>.md` | One page: what it is, where it was read from, and its text. |

Each file is named after the page's title, plus a short code taken from its address so two pages with the same title stay two files. Many sites give every page the same first heading, so when a title is shared the end of the address is added to it as well: `Extractium (configuration.md)`.

Any Markdown viewer opens the folder. A program that reads Open Knowledge Format v0.2 sees each page as a concept, using the block at the top of each file.

The folder holds the text of every page, so decide what to publish exactly as you would for the container. A build removes a file it wrote in an earlier build when that page is no longer in the compendium, and names each removal in its log. A file you added to the folder by hand is never touched. See "Full and incremental rebuilds" below.

The SQLite file holds the same content as the container, including the text of every section, in tables you can query with SQL. It is not a description of the data; a service that answers a search has to return the text it matched. Treat it exactly as you treat the container when you decide what to publish.


## Full and incremental rebuilds

Every build writes a manifest beside the cache, `previous-build.json`, holding the sections of every published page and the date each page was last seen. It never holds content read from a local folder, because a data repository that indexes video commits its cache folder.

With `rebuild: full`, the default, the outputs hold exactly what this build read. A page that was not reached is not in them, whatever the reason.

With `rebuild: incremental`, a page the last build had and this build did not see is carried forward from the manifest, re-chunked and re-embedded with everything else, so it stays searchable with the section identifiers it had. Three rules decide which pages that covers:

- Only a page from a `web` source is carried forward. A crawl reaches pages by following links and can miss one that is still there, because a site was down for the hour the build ran or a page is no longer linked. Every other source lists its content through an interface, so a page absent from its listing is gone.
- A page the server confirmed gone is dropped. A `404` or `410` answer is the server saying the page no longer exists; a `500`, a timeout, or a refusal says nothing about whether it exists, and such a page is kept.
- A page whose source is no longer in the settings file is dropped with it.

The build log names each page kept and the date it was last seen, and the summary counts what was kept and what was dropped. The published files carry no per-page date; the manifest does.

Full is the default on purpose. A page taken down deliberately must leave the published index on the next build, and in incremental mode it does so only when the server answers that it is gone. If a site can take a page down without answering `404` for its address, for example by redirecting every old address to its home page, run that build in full mode.

The Open Knowledge Format output follows the compendium in both modes: a concept file this tool wrote in an earlier build for a page that is no longer in the compendium is removed, and the build log names it. A file somebody added to the folder by hand is never touched.

```yaml
rebuild: incremental
```


## Summaries, keywords, and tags

Every page carries a summary and tags, and every section up to five keywords, so a reader can see what a page is about without reading it and can filter pages by subject. No language model is involved.

Where a source already knows what a page says about itself, the build uses that and computes nothing in its place:

| Source | Summary | Tags |
|---|---|---|
| YouTube | The video's description, as its publisher wrote it. | The tags its publisher gave it. Both come from the Data API, so a build with no key indexes the transcript without them; once read, both are stored beside the transcript and reused. |
| GitHub | The repository's description, on its README and its repository summary. | The repository's topics, on every record read from it. |
| TeamDynamix | The article's Summary field, which the portal writes into the page's Open Graph description. | The tags shown under the article's title. |
| DSpace | The first two paragraphs of the deposit's abstract. | The subject terms it was catalogued under. |
| Any web page | Its Open Graph description, else its meta description. | Its `article:tag` elements, else its comma-separated meta keywords. |

A summary is cut at 600 characters, at a word. Tags are kept in the order given, each once, at most twenty, and one longer than 80 characters is dropped. A page whose source gives no summary is described by an excerpt of its text. Every page is also tagged from its text by the keyword step below, after whatever its source gave, because an author tags a page once and rarely again while the text is read as it stands today. The step works from the text and from the vectors the build computes anyway:

1. A statistical extractor, YAKE, proposes up to fifteen candidate phrases of one to three words from the section's own text. It scores a phrase by how often its words occur, where they first appear, whether they are capitalized, and how varied the words around them are.
2. The candidates are embedded with the same model the build uses for search, and ranked by how close each one sits to the section's own vector. The five closest that do not repeat one another are the section's keywords, closest first: a phrase whose words all lie inside a phrase already chosen, or that contains one, is passed over. That is why a phrase that names the subject outranks one that merely occurs often.
3. A page's tags are the categories its source recorded, outermost first, then the tags its source gave it, then the keywords at least half of its sections share, the most widely shared first, until the page holds eight tags beyond its categories. A keyword whose words all lie inside one of the source's tags, or that contains one, is passed over, so "sleep" is not added beside "sleep research"; a category rules out only its exact repeat, so "sleep hygiene" is still added under a "Sleep" category. A one-section page is tagged with its categories, its source's tags, and its keywords. A page carried forward unchanged from the last build keeps the tags it had.

Where they appear:

| Output | What it carries |
|---|---|
| Container | `summary`, `keywords`, and `tags` on every section, with `enriched_at` (UTC) and `enrich_ver`. |
| SQLite | The same five columns on `parents`, the lists as JSON arrays. |
| Open Knowledge Format | The summary as each concept file's description, the tags in its tag list, and a `keywords` list in its front matter. |
| `llms.txt` | Each page's entry describes the page with its summary, or with an excerpt of its first section when it has none, and ends with `Keywords: ...`: the page's tags beyond its categories or, when it has none, the first section's keywords. |

What was found is stored under `<cache_dir>/enrichment/keywords.json`, keyed by section, with a digest of the text it came from. A rebuild names afresh only the sections whose text changed, and embeds nothing for the rest.

The extractor is the `keywords` extra. The build script installs it from the lock file; a developer install names it (`pip install -e ".[keywords]"`). Without it, the build prints one line saying so and goes on, and every output leaves the fields empty. To switch the step off:

```yaml
keywords: false
```


## The check for protected health information

Every build scans the text its sources produced for the shapes identifiers usually take, and writes two reports you can read before you publish anything. The `phi_lint` setting decides what it looks at:

| Value | What it scans |
|---|---|
| `local` (default) | Only content read from a `local` source. That is the content that was never published. |
| `all` | Every document, including crawled web pages. |
| `'off'` | Nothing. Quote the value; YAML reads a bare `off` as false. |

Two files are written to the folder you ran the build from, never to `out_dir`:

| File | Who it is for |
|---|---|
| `phi-lint-report.json` | A program or an AI assistant. Counts, and one entry per finding. |
| `phi-lint-report.txt` | A person. The same findings, grouped by file, with what to do next. |

Neither report copies the text it matched. It names the file and the line, so you open the file and look. A report that quoted what it found would be a second copy of the identifiers, saved somewhere nobody guards.

The check reads shapes, not meaning. It will miss things, and it will flag things that are fine. A clean result never means content is safe to publish. The reports say so, and so does this page. See [the compliance page](compliance.md) for what the check does and does not cover.


## How the URL patterns work

The four pattern lists on a web source hold regular expressions. Each pattern is matched against the whole URL, and upper and lower case are treated the same. Wrap patterns in single quotes so YAML keeps your backslashes as you typed them. This section is the full rule set; [how to crawl a site](how-to/crawl-a-site.md) shows the usual way of arriving at a good set of patterns, one trial run at a time.

### The order of the checks

For each link the crawler finds:

1. Off-site links are dropped, unless they match an entry in `include_patterns`. This is how you add a second site.
2. Files that are not readable text are dropped: images, archives, office documents, fonts, media, and source code files. With `read_documents` on, Word, OpenDocument, RTF, and PDF files pass this check and are read.
3. `include_patterns` decides what is in scope. If the list is empty, the crawler works the scope out from the seed URL instead (see below). If the list has entries, a URL must match at least one.
4. `crawl_exclude_patterns` removes what is left. An exclusion always wins over an inclusion.
5. A link dropped by the first check gets one more chance: if it matches an entry in `leaf_patterns`, and the page linking to it is inside the scope worked out from the seed, it is fetched as a leaf. The second and fourth checks apply to it too. See "Single pages on another host" below.

Pages that survive the checks are fetched. A fetched page whose URL matches `index_exclude_patterns` still has its links followed, but its own text is left out of the index. That is what you want for menu and category pages: they lead to real articles but say nothing themselves.

### Automatic scope

Leaving `include_patterns` out (the default) keeps the crawl close to home:

- A TeamDynamix portal URL keeps the crawl inside that portal's `/TDClient/<number>/<name>/` folder. So a seed of `https://example.edu/TDClient/000/ExampleOrg/Home/` limits the crawl to `https://example.edu/TDClient/000/ExampleOrg/`. This rule belongs to the `tdx` site handler, so switching that handler off drops it along with its exclusions.
- Any other URL keeps the crawl on the same site, meaning the same scheme and host.

This is usually the right setting. Add patterns only when one build has to cover more than one place.

### Single pages on another host

Some sites keep their content elsewhere: a program page whose handouts are Google Docs, or whose files sit on a content-delivery network. An `include_patterns` entry for the other host would reach them, but it would also follow every link found there, and it replaces the automatic scope, so the site itself has to be restated. `leaf_patterns` is for this case.

A leaf is a page on another host that a page of the site links to. It is fetched and indexed under the source's label, and its own links are never read, so the crawl never spreads to the other host. A leaf linked only from another leaf is never reached, and neither is one linked only from a page on a second site that `include_patterns` added: the page linking to a leaf has to be inside the scope worked out from the seed. The automatic scope stays as it is, so nothing has to be restated.

```yaml
sources:
  - type: web
    label: Example Program
    seed_url: https://program.example.org/
    read_documents: true
    leaf_patterns:
      - '^https://docs\.google\.com/'
      - '^https://files\.example\.org/'
```

Everything else applies to a leaf as to any page. A file that is not readable text is left alone, so a leaf pattern for a file host reaches its Word and PDF files with `read_documents` on and never its image or video files. A `crawl_exclude_patterns` entry wins over a leaf pattern. The other host's `robots.txt` is read and obeyed. A leaf counts toward `max_pages`. A leaf that redirects somewhere no leaf pattern covers is skipped with the landing address named. The log marks each leaf with `(leaf; its links are not followed)` under its line, and lists the patterns as `Leaf pats:` at the start of the crawl.

A link that is inside the crawl's own scope is followed as usual even when a leaf pattern also matches it. Leaf patterns only ever add pages; they never take a page out of the crawl.

### What the built-in exclusions cover

You get the two exclusion lists for free. Each list is the sum of two parts:

1. Files that hold no readable text: images, archives, office documents, fonts, media, and source code. Always included, except that `read_documents` takes Word, OpenDocument, RTF, and PDF files off the list for that source.
2. What each enabled site handler adds. The generic handler, which is always on, skips search forms, sign-in pages, print views, per-person pages, the folders that hold programs rather than pages (`cgi-bin`, `cdn-cgi`, `scripts`, and `api`, wherever they sit in a path), and the faceted and searched views a Drupal site makes of a listing (`?f[0]=topic:12`, `search_api_fulltext=`), each of which is a subset of the plain listing. The `tdx` handler adds the TeamDynamix portal's login, print, file-download, and person views, and every narrowed view of its question listing (by category, by tag, or by answered and unanswered), because the flat question listing already pages through every question. It puts the knowledge-base category and tag listings on the index list. The `github` handler adds the housekeeping pages of code-hosting sites, such as issues, pull requests, branches, forks, and settings, and puts folder listings (`/tree/`) on the index list. The `google_docs` handler keeps Google Forms, Google Drive, and Google's sign-in host out of every crawl.

Category, tag, and folder listings are worth following but not worth indexing, which is why they sit in the index list only. Switching a handler off with `site_handlers` also drops the patterns it would have added.

This split matters most on a TeamDynamix portal, which publishes no sitemap and no full article index. Its category and tag listings are the only route to most of its articles, so they have to be crawled; they are pure navigation, so they must not be indexed. If you write your own `crawl_exclude_patterns`, do not put a listing page in it, or the build will only find what the home page links to.

Write patterns for the URL shape a site actually serves. A page reached as `.../issues` and as `.../issues/12` needs a pattern that matches both, and a portal that writes a tag as `?CategoryID=0&TagID=8245` needs one that matches a query parameter, not a path.

### Which site handler reads a page

For each page it fetches, the crawler asks the enabled site handlers, in order, which one recognizes the URL. `tdx` claims any `teamdynamix.*` host. `github` claims GitHub, GitLab, `git.<organization>` hosts, and GitHub Pages. `google_docs` claims a document, spreadsheet, or presentation on `docs.google.com`. `generic` claims everything else and is always consulted last. The handler that claims a page decides which URL to request, whether to expect HTML or plain text, the page title, the content node, and the categories recorded on every section. A handler may also fold the several addresses one page is linked under into one, so the page is fetched once and cited by one address.

### Shared Google Docs, Sheets, and Slides

A Google Docs, Sheets, or Slides file shared as "anyone with the link" can be read without a key or a sign-in. The `google_docs` handler, on by default, requests the file's export instead of its editing page: plain text for a document or a presentation, and the first sheet as CSV for a spreadsheet. The file is indexed under its one address, `https://docs.google.com/document/d/<id>`, whether it was linked as `/edit`, `/edit?usp=sharing`, `/view`, or `/preview`, and its title is the first line of the export.

Google's hosts are off-site for every seed, so a file is reached only through a `leaf_patterns` entry (or an `include_patterns` entry, which also works but restates the site):

```yaml
sources:
  - type: web
    label: Example Program
    seed_url: https://program.example.org/
    leaf_patterns:
      - '^https://docs\.google\.com/'
```

A file that is not shared answers its export with a sign-in page. The build reports that, with the landing address on `accounts.google.com`, and skips the file; nothing is ever retried with a credential. Google Forms, Drive folder listings, and the sign-in host are never fetched. The exports are what Google documents, not a stable interface, so a change on Google's side shows up as every file being skipped with the same message. Every export goes through the check for protected health information like any page.

### How robots.txt is read

With `respect_robots_txt` on (the default), the crawler reads `robots.txt` once per site, with the configured `user_agent`, before fetching anything from that site. Rules written for `extractium` by name apply, then rules for `*`.

| The site answers | What the crawler does |
|---|---|
| 200 with rules | Follows the rules. A disallowed page is skipped and reported. |
| 404 or another 4xx | Treats the site as having no rules. |
| 5xx, or no answer at all | Skips every page on that site and reports why. |

Skipping a whole site when its rules cannot be read is deliberate. A crawler that cannot read a site's rules must not guess that it is welcome. Switch `respect_robots_txt` off only for a site you own.

### What happens when a site refuses the crawler

Some sites sit behind a filter that turns away anything that does not look like a web browser, no matter what their `robots.txt` allows. The page answers `403 Forbidden` to the crawler and opens normally in a browser.

By default, Extractium reports the refusal and moves on. It does not disguise itself, because a tool that names itself and then works around a site's own filter is not really naming itself.

Setting `respect_robots_txt: false` changes that, on the grounds that you only turn the check off for sites you own or have permission for. With it off:

- Every page is still requested with your `user_agent` first.
- A page that answers `401`, `403`, or `429` to that is requested once more with a common browser User-Agent.
- Both attempts are printed, so the log always shows which identity got the page.
- A page that is simply missing (`404`) or broken (`5xx`) is never retried. Those are not refusals.

Pages that were never refused are still fetched under your own `user_agent`, so a site that would have served the crawler happily is never misled.

Leave `respect_robots_txt` at `true` unless you own the sites in your crawl scope. Turning it off means both parts of this: robots rules are ignored, and a refused page is retried as a browser.

### How a site behind bot protection is read

Some sites sit behind a service that scores the connection itself, not the name the crawler gives. Such a site answers `403` with the header `cf-mitigated: challenge` to every page, whatever `robots.txt` allows, and whatever `user_agent` is sent. [Reading a site behind bot protection](bot-protection-transport.md) records what was measured.

With `transport: auto`, the default, the crawler makes its ordinary request first. When the answer is that challenge, and only then, it asks once more over a connection opened the way a browser opens one, with the same `user_agent`, the same conditional headers, and the same pause between requests. A host that was challenged once is read that way from then on, so it is not asked twice for every page. The log says so once per host:

```text
transport: example.org served over the browser transport (a plain request was answered with a challenge)
```

and the summary lists the same hosts at the end. A `403` without that header is a refusal of another kind, such as a block on the network the build runs from, and is left alone.

`transport: plain` never retries; a challenged site is skipped page by page, and the log says why. `transport: browser` opens every connection the browser way from the start, which saves one refused request per host on a site known to challenge; it is not needed to read such a site, only quicker.

Nothing about this changes what the crawler may ask for. `robots.txt` is still read first and still obeyed; the crawler still names itself; the pause between requests still applies. It changes what a server is willing to talk to, not what the crawler is allowed to read.

### Turning a default list off

Leaving a list out gives you the default. Writing an empty list turns the default off completely:

```yaml
sources:
  - type: web
    label: Example Website
    seed_url: 'https://example.edu/docs/'
    crawl_exclude_patterns: []   # fetch everything in scope, with no exclusions
```

Do this only when you know why. With no exclusions, a crawl will happily fetch sign-in pages and print views. Files that hold no readable text are still skipped: that check runs on every link whatever the lists say.

Writing `crawl_exclude_patterns` with entries replaces the built-in list the same way. To keep the built-in list and add to it, which is what you want nearly every time, use `extra_crawl_exclude_patterns` instead:

```yaml
sources:
  - type: web
    label: Example Website
    seed_url: 'https://example.edu/'
    extra_crawl_exclude_patterns:
      - '/our-members\?'          # every filtered view of the member directory
```

The same pair exists for the index list: `index_exclude_patterns` replaces, `extra_index_exclude_patterns` adds.


## When something is wrong

Extractium checks the whole file before a build starts, and stops on the first problem it finds. Every message names the file and the setting. A problem inside a list entry also names the entry's position and type, such as `sources entry 2 (web)`.

| Message | Cause | Fix |
|---|---|---|
| `sources is required` | The file is empty, or has no `sources` list. | Add a `sources` list with at least one entry. |
| `sources must list at least one source` | The list is empty. | Add an entry. |
| `sources entry 1: type is required` | An entry has no `type`. | Add `type: web` (or another type). |
| `sources entry 1 (web): seed_url is required` | A web source has no seed. | Add `seed_url`, or `seed_urls` for several. |
| `give either seed_url or seed_urls, not both` | A web source has both keys. | Keep one. `seed_urls` covers the single-seed case too. |
| `it redirects to ... which is outside what this source may crawl` | The seed is a short link to somewhere else. | Use the address the message names. |
| `seed_url must start with http:// or https://` | The URL uses another scheme, such as `file:`, or has no scheme at all. | Use the full web address. |
| `seed_url belongs inside a sources entry` | The file uses the old single-seed layout. | Move `seed_url` under a `- type: web` entry. |
| `unrecognized setting(s): max_page` | A setting name is misspelled. The message lists the names Extractium knows. | Correct the spelling. |
| `sources entry 1 (web): unrecognized setting(s): seed` | An option name inside an entry is misspelled. | Correct the spelling. |
| `max_pages must be a whole number, not str` | The value is in quotes, such as `'500'`. | Remove the quotes. |
| `respect_robots_txt must be true or false, not str` | The value is `yes` or `"true"`. | Write `true` or `false` without quotes. |
| `phi_lint must be one of all, local, off` | The value is not one of the three modes. | Pick one of the three. |
| `include_patterns must be a list of patterns, not str` | One pattern was written on the same line as the option name. | Write it as a one-item list, with `- ` in front. |
| `... is not a valid regular expression` | A pattern has an unbalanced bracket or a stray backslash. | Check the pattern the message quotes. |
| `outputs must list at least one output` | The list is empty. | Remove `outputs` to get the defaults, or add an entry. |
| `file must be a relative path inside out_dir` | An output file name is absolute or uses `..`. | Use a plain name or a subfolder under `out_dir`. |
| `configuration file is not valid YAML` | The file has a YAML syntax error, such as an unclosed quote. | Check the line the message names. |

A misspelled setting is treated as an error on purpose. If Extractium ignored it, a typo such as `max_page` would leave the real ceiling at 10,000 and nobody would notice.


## Safety notes

- The file is read with a plain-data YAML reader. A configuration file cannot run code, even if someone hands you one.
- Only `http` and `https` seeds are accepted. A `file:` seed would pull content off your own disk into an index whose web-facing outputs assume everything in it was already published.
- Output files must stay under `out_dir`, so a configuration file cannot direct a build to overwrite a file elsewhere on the disk.
- The `user_agent` value cannot contain line breaks, so the file cannot add extra request headers.
- The crawler honors `robots.txt` by default and stops at a site whose rules it cannot read, so a configuration file cannot make it fetch pages a site has asked crawlers to leave alone unless you switch the check off.
- Keep passwords, tokens, and participant identifiers out of this file. It is meant to be committed to a repository. Sources that need a token read it from the environment.
- Content from `local` sources is left out of every output unless that output says `include_local: true`. Publishing is the normal use of every output, so the safe default is the one that cannot leak by omission.
- A `local` source refuses a file whose real location is outside the folder you named, so a shortcut or a symbolic link cannot pull in content from elsewhere on the disk.
- The reports from the check for protected health information are written where you ran the build, never into `out_dir`, so a scheduled build cannot publish them by accident.
- Very complicated patterns can make matching slow on long URLs. Keep patterns short and plain.


## Conclusion

You now know every setting a build accepts, what you get for free, and how to read the error messages. Copy `examples/config.example.yaml`, set the web source's `seed_url`, and leave the rest alone until you have a reason to change it. To understand what happens after the file is read, read the [data flow](data-flow.md) page.


## Additional Resources

* [Extractium™ README](../README.md): project overview and quick start.
* [examples/config.example.yaml](../examples/config.example.yaml): commented example file to copy.
* [How to crawl a site](how-to/crawl-a-site.md): choosing source types and tuning these settings by trial run.
* [How to install](how-to/install.md): the optional extras some sources need.
* [extractium/config.py](../extractium/config.py): the settings, defaults, and checks in code.
* [extractium/core/registry.py](../extractium/core/registry.py): how a `type` or site handler name is resolved to a plug-in.
* [extractium/core/fetch.py](../extractium/core/fetch.py): the crawl scope rules, the User-Agent, and the `robots.txt` policy.
* [extractium/sources/web.py](../extractium/sources/web.py): the crawl loop that acts on a `web` entry.
* [Robots Exclusion Protocol, RFC 9309](https://www.rfc-editor.org/rfc/rfc9309): the rules the `robots.txt` policy follows.
* [Container format](container-format.md): the file the `container` output writes.
* [Plug-in architecture](plugin-architecture.md): how to add a source or output type of your own.
* [Extractium™ specification](extractium-spec.md): the design behind these settings.
* [YAML 1.2 specification](https://yaml.org/spec/1.2.2/): the file format's own reference.
* [Python regular expression syntax](https://docs.python.org/3/library/re.html#regular-expression-syntax): how the patterns are written.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
