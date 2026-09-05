<!--
This file is part of Extractium™
docs/configuration.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-04
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

The settings file and its checks are in place, in [extractium/config.py](../extractium/config.py). The web source that acts on a `web` entry and the global crawl settings is in place too. The command that runs a full build is not finished yet, so nothing reads the file for you today. You can still load and check a file yourself:

```python
from extractium.config import load_config

settings = load_config("config.yaml")
print(settings.sources[0].options["seed_url"], settings.max_pages)
```

The crawl scope rules (`in_scope`, `derive_auto_prefix`), the User-Agent, and the `robots.txt` policy live in [extractium/core/fetch.py](../extractium/core/fetch.py). The crawl itself is [extractium/sources/web.py](../extractium/sources/web.py). The plugin names used in `type:` and `site_handlers:` are resolved by [extractium/core/registry.py](../extractium/core/registry.py). See [the specification](extractium-spec.md) for the rest of the design.


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
    seed_url: 'https://example.edu/TDClient/000/ExampleOrg/Home/'

outputs:                 # optional: defaults to container + llmstxt
  - type: container
  - type: llmstxt

max_pages: 500           # optional global settings
```

Each entry in `sources` and `outputs` names a `type` and then that type's own options. The type is the name of a plugin. The built-in types are listed below. A plugin you drop into the `plugins/` folder can add more.


## Global settings

| Setting | Type | Default | What it does |
|---|---|---|---|
| `name` | text | title of the first page crawled | Display name of the knowledge base, recorded in every output. |
| `out_dir` | text | `dist` | Folder every output is written under. |
| `cache_dir` | text | `.kb_cache` | Folder for fetched pages between builds. |
| `max_pages` | whole number | `10000` | The most pages one build may visit. Must be 1 or more. |
| `delay_seconds` | number | `0.5` | Seconds to wait between requests. Use `0` for no wait. |
| `user_agent` | text | `Extractium/<version> (+https://github.com/DepressionCenter/extractium)` | How the crawler introduces itself to each site. Sent with every request, including the one for `robots.txt`. |
| `respect_robots_txt` | true or false | `true` | Whether each site's `robots.txt` rules are honored. See "How robots.txt is read" below. |
| `phi_lint` | `local`, `all`, or `off` | `local` | Which content the protected health information check scans. |

`phi_lint` is validated now; the check that acts on it is not built yet. See [the implementation plan](implementation-plan.md).


## Sources

Every entry needs a `type`. The options below are per type. An option you leave out takes its default.

### `web`: crawl a website

| Option | Type | Default | What it does |
|---|---|---|---|
| `seed_url` | text | none (required) | The page the crawl starts from. Must begin with `http://` or `https://`. |
| `include_patterns` | list of patterns | empty (see below) | Pages the crawl is allowed to visit. |
| `crawl_exclude_patterns` | list of patterns | asset files plus what the enabled handlers add | Pages the crawl must not fetch. |
| `index_exclude_patterns` | list of patterns | asset files plus what the enabled handlers add | Pages the crawl may visit, but whose content stays out of the index. |
| `site_handlers` | list of names | every installed handler | Which site handlers take part. `[]` means the generic handler only. The generic handler always takes part, and always last. |

A short entry is normal:

```yaml
sources:
  - type: web
    seed_url: 'https://example.edu/TDClient/000/ExampleOrg/Home/'
```

### `local`: read files from a folder

| Option | Type | Default | What it does |
|---|---|---|---|
| `path` | text | none (required) | The folder to read. |
| `include_globs` | list of glob patterns | `**/*.md`, `**/*.txt`, `**/*.html` | Which files under the folder are read. |

Content from a local source stays out of every output unless that output sets `include_local: true`. See "Outputs" below.

### `github_api`: list an organization's repositories

| Option | Type | Default | What it does |
|---|---|---|---|
| `org` | text | none (required) | The GitHub organization to list. |

Set `GITHUB_TOKEN` in the environment to raise the API rate limit. The token never goes in the file.

### `youtube`: read captions

| Option | Type | Default | What it does |
|---|---|---|---|
| `channel_id` | text | none | A channel to list. |
| `playlist_ids` | list of text | empty | Playlists to list. |
| `video_ids` | list of text | empty | Single videos. |
| `languages` | list of text | `en` | Caption languages to ask for, in order of preference. |

At least one of `channel_id`, `playlist_ids`, or `video_ids` is required. Listing a channel or playlist needs `YOUTUBE_API_KEY` in the environment.

### Source types from plugins

A type that is not one of the four above is passed to the registry as written, with its options unchecked. The plugin that answers to that name checks its own options. If no plugin answers to it, the build stops with a message listing the known names.


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

Only the settings are validated today. The adapters that write these files are built in later phases of the [implementation plan](implementation-plan.md). An output type that is not one of the four above is passed to the registry as written, like a plugin source type.


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
2. **What each enabled site handler adds.** The generic handler, which is always on, skips search forms, sign-in pages, print views, tag pages, and per-person pages. The `tdx` handler adds the TeamDynamix portal's login, print, file-download, and tag views, and its category listings to the index list. The `github` handler adds the housekeeping pages of code-hosting sites, such as issues, commits, and settings, and folder listings (`/tree/`) to the index list.

Category and folder listings are worth following but not worth indexing, which is why they sit in the index list only. Switching a handler off with `site_handlers` also drops the patterns it would have added.

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

### Turning a default list off

Leaving a list out gives you the default. Writing an empty list turns the default off completely:

```yaml
sources:
  - type: web
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
| `sources entry 1 (web): seed_url is required` | A web source has no seed. | Add `seed_url`. |
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
