<!--
This file is part of Extractium™
docs/configuration.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-10
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

Extractium reads its settings from one small YAML file, usually called `config.yaml`. The file lists the sources to read, the outputs to write, and a few global settings. This page lists every setting, what it does, and what happens when you leave it out. It is written for the person who sets up a build, and for anyone who later has to work out why a crawl reached the wrong pages.

A ready-to-copy starting point ships with the project: [examples/config.example.yaml](../examples/config.example.yaml).


## Status of this feature

The settings file and its checks are in place, in [extractium/config.py](../extractium/config.py), and `extractium build --config config.yaml` reads the file and runs the whole build. You can also load and check a file yourself:

```python
from extractium.config import load_config

settings = load_config("config.yaml")
print(settings.sources[0].options["seed_url"], settings.max_pages)
```

The crawl scope rules (`in_scope`, `derive_auto_prefix`), the User-Agent, and the `robots.txt` policy live in [extractium/core/fetch.py](../extractium/core/fetch.py). The crawl itself is [extractium/sources/web.py](../extractium/sources/web.py). Reading GitHub through its API is [extractium/sources/github_api.py](../extractium/sources/github_api.py). The plugin names used in `type:` and `site_handlers:` are resolved by [extractium/core/registry.py](../extractium/core/registry.py). See [the specification](extractium-spec.md) for the rest of the design.


## Where the file goes

Extractium keeps the engine and your organization's data apart. Put `config.yaml` in your own project folder, next to the output you publish, and run the build from that folder. Paths inside the file are read from wherever you run the build.

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

Each entry in `sources` and `outputs` names a `type` and then that type's own options. The type is the name of a plugin. The built-in types are listed below. A plugin you drop into the `plugins/` folder can add more.

Every source also needs a `label`. See "Naming your sources" below.


## Global settings

| Setting | Type | Default | What it does |
|---|---|---|---|
| `name` | text | title of the first page crawled | Display name of the knowledge base, recorded in every output. |
| `out_dir` | text | `dist` | Folder every output is written under. |
| `cache_dir` | text | `.kb_cache` | Folder for fetched pages between builds. |
| `max_pages` | whole number | `10000` | The most pages one build may visit. Must be 1 or more. |
| `delay_seconds` | number | `0.5` | Seconds to wait between requests. Use `0` for no wait. |
| `user_agent` | text | `Extractium/<version> (+https://github.com/DepressionCenter/extractium)` | How the crawler introduces itself to each site. Sent with every request, including the one for `robots.txt`. |
| `respect_robots_txt` | true or false | `true` | Whether each site's `robots.txt` rules are honored. Turning it off also lets a page that refuses the crawler be retried once as a browser. See "How robots.txt is read" and "What happens when a site refuses the crawler" below. |
| `phi_lint` | `local`, `all`, or `off` | `local` | Which content the check for protected health information scans. |
| `github_owners` | list of text | empty | Extra GitHub accounts this build may follow links into. See "Which GitHub accounts a build reads" below. |

Quote the value when you turn the check off (`phi_lint: 'off'`). YAML reads a bare `off` as the word false, and the build refuses it with a message naming the setting.

See "The check for protected health information" below for what the check does.

### Which GitHub accounts a build reads

A GitHub account name can turn up anywhere: in a README's credits, in a list of dependencies, in a fork notice, in somebody's profile link. If a build followed all of them, one link would pull thousands of other people's repositories into your index.

So a build reads a GitHub account **only when you named it**. That means:

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

**Why it is required rather than guessed.** Both sources above are of type `web`. Nothing in the address or the page says which is the main site and which is a program microsite. Only you know that. Without a label, a search result could say no more than "web", and a reader could not tell the two apart.

Keep it short and use the name people actually say. "Video Library" is better than "YouTube channel for the center".

Two sources may share a label on purpose. Two sibling collections of one repository are one place to a person looking for an answer, so giving both the same label puts them under one heading.

### `web`: crawl a website

| Option | Type | Default | What it does |
|---|---|---|---|
| `seed_url` | text | one of these two is required | The page the crawl starts from. Must begin with `http://` or `https://`. |
| `seed_urls` | list of text | one of these two is required | Several pages to start from, for a site whose sections do not link to one another. Still one crawl. |
| `include_patterns` | list of patterns | empty (see below) | Pages the crawl is allowed to visit. |
| `crawl_exclude_patterns` | list of patterns | asset files plus what the enabled handlers add | Pages the crawl must not fetch. |
| `index_exclude_patterns` | list of patterns | asset files plus what the enabled handlers add | Pages the crawl may visit, but whose content stays out of the index. |
| `site_handlers` | list of names | every installed handler | Which site handlers take part. `[]` means the generic handler only. The generic handler always takes part, and always last. |

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

This is **one crawl**, not two sources, and the difference matters. One crawl keeps one list of the pages it has visited, so a page reachable from both starting points is fetched once and indexed once. It also shares one `max_pages` budget and one set of patterns. Two sources covering the same ground would each fetch that page.

Scope is worked out from every seed. A link is followed if it is inside the scope of any of them, so two seeds on different hosts put both hosts in scope. If you need something narrower than a whole host, write `include_patterns`.

#### When a seed redirects

Short links are convenient and they hide where they go. `https://example.edu/kb` might land on a portal at another address entirely.

That used to produce a nearly empty index with no error. The crawl works out what it is allowed to visit from the address **you wrote**, so after the redirect, every link on the page it received was out of scope, and the crawl stopped after one page.

The build now notices and refuses that seed, naming the address to use instead:

```text
SKIP https://example.edu/kb -- it redirects to https://portal.example/TDClient/210/Org/Home/,
which is outside what this source may crawl. Nothing there could be followed, so the crawl
would index one page and stop. Use https://portal.example/TDClient/210/Org/Home/ as the seed
instead, or add an include pattern that covers it.
```

Put the address it names in your settings file. A redirect that stays in scope, such as `http` to `https` or a missing trailing slash, is normal and passes without comment.

### `local`: read files from a folder

| Option | Type | Default | What it does |
|---|---|---|---|
| `path` | text | none (required) | The folder to read. |
| `include_globs` | list of glob patterns | `**/*.md`, `**/*.txt`, `**/*.html` | Which files under the folder are read. |

Content from a local source stays out of every output unless that output sets `include_local: true`. See "Outputs" below.

The `path` is the folder to read. Files are read as UTF-8. A file the patterns select but whose real location is outside the folder, reached through a shortcut or a symbolic link, is skipped and the reason is printed. A folder that does not exist stops the build, so a mistyped path does not look like an empty folder.

Only Markdown, plain text, and HTML are read. PDF, Word, and spreadsheet files would need extra software the project does not install.

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
| `include_code` | true or false | `true` | Reserved for code analysis, which arrives in phase 10. Accepted and reported today; it changes nothing yet. |
| `max_file_bytes` | whole number | `2000000` | Largest single file to download. Anything larger is skipped, and every skipped file is named in the log. |

Give **exactly one** of `org`, `user`, or `url`. Two is an error, not a request for both.

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

**What gets read.** README files, Markdown, plain text, and the other documentation a repository carries, plus short project files such as `pyproject.toml`, `DESCRIPTION`, `package.json`, and `Dockerfile`. Source files, generated folders, binaries, lock files, and anything holding a credential are never downloaded. `.env.example` is kept, because it documents what a project needs.

**How files are downloaded.** A repository is normally downloaded once, as a single archive, and the wanted files are read out of it in memory. Nothing is ever extracted to disk. This spends one request per repository instead of one per file, which matters because reading GitHub anonymously allows only about sixty requests an hour in total. A repository too large to hold in memory has its files requested one at a time instead. Either way, each file is stored under its blob name, so the next build downloads nothing that has not changed.

**Tokens.** Set `GITHUB_TOKEN` in the environment to raise the request limit. It never goes in the configuration file, in an output, in a log line, or in the cache. A token raises how much a build can read; it never widens what a build may publish, and private repositories are never indexed.

**When GitHub cannot be read.** The build tries three ways in order: with a token, without one, and finally an ordinary crawl of the documentation pages. The first two produce exactly the same result for a public repository. The third reads documentation only and runs no code analysis. Whatever happens, the summary names each repository and the way it was read:

```text
  coverage : DepressionCenter/extractium  tier 2 (public API)  documentation, code analysis
```

A refused token drops to reading GitHub anonymously and says so. A misspelled account name stops the build instead, because a quiet fall back would give you a strange, empty result rather than an error.

### `youtube`: read captions

| Option | Type | Default | What it does |
|---|---|---|---|
| `channel_id` | text | none | A channel to list. |
| `playlist_ids` | list of text | empty | Playlists to list. |
| `video_ids` | list of text | empty | Single videos. |
| `languages` | list of text | `en` | Caption languages to ask for, in order of preference. |

At least one of `channel_id`, `playlist_ids`, or `video_ids` is required. Listing a channel or playlist needs `YOUTUBE_API_KEY` in the environment.

**Planned.** The loader accepts this type, but the source is not built yet, so a build that uses it stops with `no source named 'youtube'`. It arrives in phase 13.

### `dspace`: read a repository's deposits

**Planned.** This type is not built yet, so a build that uses it stops with `no source named 'dspace'`. It arrives in phase 9.

It will read scholarly deposits out of a DSpace repository, such as the University of Michigan Library's Deep Blue, through the repository's own interface rather than by crawling its pages. Collections are named in the settings file and never discovered, the same rule that governs GitHub accounts. Each deposit becomes one document carrying its abstract, its authors and subjects, its handle and DOI, and the text of its files, which the repository has already extracted, so no PDF or Word reader is added to this build.

See [Indexing a DSpace repository](dspace-repository-indexing.md) for the settings it will take and why.

### Source types from plugins

A type that is not one of the five above is passed to the registry as written, with its options unchecked. The plugin that answers to that name checks its own options. If no plugin answers to it, the build stops with a message listing the known names.


## Outputs

Leave `outputs` out to write the two defaults: the container file and the `llms.txt` pair. Every output accepts `include_local`.

| Type | Options | Default | What it writes |
|---|---|---|---|
| `container` | `file` | `kb-index.json` | The binary index every search client reads. See the [container format](container-format.md). |
| `llmstxt` | none | | `llms.txt` and `llms-full.txt`. |
| `sqlite` | `file` | `compendium.sqlite` | A SQLite database with the same content. |
| `okf` | none | | An Open Knowledge Format folder of Markdown files. |

| Option on every output | Type | Default | What it does |
|---|---|---|---|
| `include_local` | true or false | `false` | Lets content from `local` sources into this output. |

A `file` is always a relative path under `out_dir`. An absolute path, or one that climbs out with `..`, is refused.

```yaml
outputs:
  - type: container
    file: kb-index.json
  - type: llmstxt
  - type: sqlite
    include_local: true      # this file stays on your machine, so local content is fine
```

The container, `llmstxt`, and `sqlite` writers exist today. The `okf` writer is built in a later phase of the [implementation plan](implementation-plan.md). An output type that is not one of the four above is passed to the registry as written, like a plugin source type.

The SQLite file holds the same content as the container, including the text of every section, in tables you can query with SQL. It is not a description of the data; a service that answers a search has to return the text it matched. Treat it exactly as you treat the container when you decide what to publish.


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

The check reads shapes, not meaning. It will miss things, and it will flag things that are fine. **A clean result never means content is safe to publish.** The reports say so, and so does this page. See [the compliance page](compliance.md) for what the check does and does not cover.


## How the URL patterns work

The three pattern lists on a web source hold regular expressions. Each pattern is matched against the whole URL, and upper and lower case are treated the same. Wrap patterns in single quotes so YAML keeps your backslashes as you typed them.

### The order of the checks

For each link the crawler finds:

1. **Off-site links** are dropped, unless they match an entry in `include_patterns`. This is how you add a second site.
2. **Files that are not readable text** are dropped: images, archives, office documents, fonts, media, and source code files.
3. **`include_patterns`** decides what is in scope. If the list is empty, the crawler works the scope out from the seed URL instead (see below). If the list has entries, a URL must match at least one.
4. **`crawl_exclude_patterns`** removes what is left. An exclusion always wins over an inclusion.

Pages that survive all four checks are fetched. A fetched page whose URL matches `index_exclude_patterns` still has its links followed, but its own text is left out of the index. That is what you want for menu and category pages: they lead to real articles but say nothing themselves.

### Automatic scope

Leaving `include_patterns` out (the default) keeps the crawl close to home:

- A TeamDynamix portal URL keeps the crawl inside that portal's `/TDClient/<number>/<name>/` folder. So a seed of `https://example.edu/TDClient/000/ExampleOrg/Home/` limits the crawl to `https://example.edu/TDClient/000/ExampleOrg/`.
- Any other URL keeps the crawl on the same site, meaning the same scheme and host.

This is usually the right setting. Add patterns only when one build has to cover more than one place.

### What the built-in exclusions cover

You get the two exclusion lists for free. Each list is the sum of two parts:

1. **Files that hold no readable text**: images, archives, office documents, fonts, media, and source code. Always included.
2. **What each enabled site handler adds.** The generic handler, which is always on, skips search forms, sign-in pages, print views, and per-person pages. The `tdx` handler adds the TeamDynamix portal's login, print, and file-download views, and puts its category and tag listings on the index list. The `github` handler adds the housekeeping pages of code-hosting sites, such as issues, pull requests, branches, forks, and settings, and puts folder listings (`/tree/`) on the index list.

Category, tag, and folder listings are worth following but not worth indexing, which is why they sit in the index list only. Switching a handler off with `site_handlers` also drops the patterns it would have added.

This split matters most on a TeamDynamix portal, which publishes no sitemap and no full article index. Its category and tag listings are the only route to most of its articles, so they have to be crawled; they are pure navigation, so they must not be indexed. If you write your own `crawl_exclude_patterns`, do not put a listing page in it, or the build will only find what the home page links to.

Write patterns for the URL shape a site actually serves. A page reached as `.../issues` and as `.../issues/12` needs a pattern that matches both, and a portal that writes a tag as `?CategoryID=0&TagID=8245` needs one that matches a query parameter, not a path.

### Which site handler reads a page

For each page it fetches, the crawler asks the enabled site handlers, in order, which one recognizes the URL. `tdx` claims any `teamdynamix.*` host. `github` claims GitHub, GitLab, `git.<organization>` hosts, and GitHub Pages. `generic` claims everything else and is always consulted last. The handler that claims a page decides which URL to request, whether to expect HTML or plain text, the page title, the content node, and the categories recorded on every section.

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
- A page that answers `401`, `403`, or `429` to that is requested **once more** with a common browser User-Agent.
- Both attempts are printed, so the log always shows which identity got the page.
- A page that is simply missing (`404`) or broken (`5xx`) is never retried. Those are not refusals.

Pages that were never refused are still fetched under your own `user_agent`, so a site that would have served the crawler happily is never misled.

Leave `respect_robots_txt` at `true` unless you own the sites in your crawl scope. Turning it off means both parts of this: robots rules are ignored, and a refused page is retried as a browser.

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
- The crawler honors `robots.txt` by default and stops at a site whose rules it cannot read, so a configuration file cannot make it fetch pages a site has asked crawlers to leave alone unless the operator switches the check off.
- Keep passwords, tokens, and participant identifiers out of this file. It is meant to be committed to a repository. Sources that need a token read it from the environment.
- Content from `local` sources is left out of every output unless that output says `include_local: true`. Publishing is the normal use of every output, so the safe default is the one that cannot leak by omission.
- A `local` source refuses a file whose real location is outside the folder you named, so a shortcut or a symbolic link cannot pull in content from elsewhere on the disk.
- The reports from the check for protected health information are written where you ran the build, never into `out_dir`, so a scheduled build cannot publish them by accident.
- Very complicated patterns can make matching slow on long URLs. Keep patterns short and plain.


## Conclusion

You now know every setting a build accepts, what you get for free, and how to read the error messages. Copy `examples/config.example.yaml`, set the web source's `seed_url`, and leave the rest alone until you have a reason to change it. To understand what happens after the file is read, read [the specification](extractium-spec.md).


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [examples/config.example.yaml](../examples/config.example.yaml) — commented example file to copy.
* [extractium/config.py](../extractium/config.py) — the settings, defaults, and checks in code.
* [extractium/core/registry.py](../extractium/core/registry.py) — how a `type` or site handler name is resolved to a plugin.
* [extractium/core/fetch.py](../extractium/core/fetch.py) — the crawl scope rules, the User-Agent, and the `robots.txt` policy.
* [extractium/sources/web.py](../extractium/sources/web.py) — the crawl loop that acts on a `web` entry.
* [Robots Exclusion Protocol, RFC 9309](https://www.rfc-editor.org/rfc/rfc9309) — the rules the `robots.txt` policy follows.
* [Container format](container-format.md) — the file the `container` output writes.
* [Implementation plan](implementation-plan.md) — which sources and outputs are built, and when.
* [Extractium™ specification](extractium-spec.md) — architecture, outputs, and roadmap.
* [YAML 1.2 specification](https://yaml.org/spec/1.2.2/) — the file format's own reference.
* [Python regular expression syntax](https://docs.python.org/3/library/re.html#regular-expression-syntax) — how the patterns are written.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
