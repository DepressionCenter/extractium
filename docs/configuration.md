<!--
This file is part of Extractium™
docs/configuration.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-04
Summary: Reference for the Extractium build configuration file: every
setting, its default, how the three URL pattern lists interact, and the
error messages the loader produces.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Configuration Reference

[← Back to README](../README.md)


## Summary

Extractium reads its settings from one small YAML file, usually called `config.yaml`. This page lists every setting the file may contain, what each one does, and what happens when you leave it out. It is written for the person who sets up a build, and for anyone who later has to work out why a crawl reached the wrong pages.

A ready-to-copy starting point ships with the project: [examples/config.example.yaml](../examples/config.example.yaml).


## Status of this feature

The settings file and its checks are in place, in [extractium/config.py](../extractium/config.py). The command that runs a full build is not finished yet, so nothing reads the file for you today. You can still load and check a file yourself:

```python
from extractium.config import load_config

settings = load_config("config.yaml")
print(settings.seed_url, settings.max_pages)
```

The crawl scope rules these settings feed (`in_scope`, `derive_auto_prefix`) already live in [extractium/core/fetch.py](../extractium/core/fetch.py). See [the specification](extractium-spec.md) for the rest of the plan.


## Where the file goes

Extractium keeps the engine and your organization's data apart. Put `config.yaml` in your own project folder, next to the output you publish, and run the build from that folder. Paths inside the file are read from wherever you run the build.

To start:

1. Copy `examples/config.example.yaml` into your project folder as `config.yaml`.
2. Change `seed_url` to the page you want the crawl to start from.
3. Delete every line you do not need. Anything you leave out uses its default.


## Settings

Only `seed_url` is required.

| Setting | Type | Default | What it does |
|---|---|---|---|
| `seed_url` | text | none (required) | The page the crawl starts from. Must begin with `http://` or `https://`. |
| `out_path` | text | `dist/kb-index.json` | Where the index file is written. |
| `max_pages` | whole number | `10000` | The most pages one build may visit. Must be 1 or more. |
| `delay_seconds` | number | `0.5` | Seconds to wait between requests. Use `0` for no wait. |
| `include_patterns` | list of patterns | empty (see below) | Pages the crawl is allowed to visit. |
| `crawl_exclude_patterns` | list of patterns | built-in list | Pages the crawl must not fetch. |
| `index_exclude_patterns` | list of patterns | built-in list | Pages the crawl may visit, but whose content stays out of the index. |

A short file is normal:

```yaml
seed_url: 'https://example.edu/TDClient/000/ExampleOrg/Home/'
```


## How the URL patterns work

All three lists hold regular expressions. Each pattern is matched against the whole URL, and upper and lower case are treated the same. Wrap patterns in single quotes so YAML keeps your backslashes as you typed them.

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

You get the two exclusion lists for free. They skip search forms, sign-in pages, print views, tag pages, and the housekeeping pages of code-hosting sites, such as issues, commits, and settings. They also skip files that hold no readable text. The index list adds category and folder listings, which are worth following but not worth indexing.

### Turning a default list off

Leaving a list out gives you the default. Writing an empty list turns the default off completely:

```yaml
seed_url: 'https://example.edu/docs/'
crawl_exclude_patterns: []   # fetch everything in scope, with no exclusions
```

Do this only when you know why. With no exclusions, a crawl will happily fetch sign-in pages and print views.


## When something is wrong

Extractium checks the whole file before a build starts, and stops on the first problem it finds. Every message names the file and the setting, so you can go straight to the line.

| Message | Cause | Fix |
|---|---|---|
| `seed_url is required` | The file is empty, or the setting is missing. | Add `seed_url`. |
| `seed_url must start with http:// or https://` | The URL uses another scheme, such as `file:`, or has no scheme at all. | Use the full web address. |
| `unrecognized setting(s): max_page` | A setting name is misspelled. The message lists the names Extractium knows. | Correct the spelling. |
| `max_pages must be a whole number, not str` | The value is in quotes, such as `'500'`. | Remove the quotes. |
| `include_patterns must be a list of patterns, not str` | One pattern was written on the same line as the setting name. | Write it as a one-item list, with `- ` in front. |
| `... is not a valid regular expression` | A pattern has an unbalanced bracket or a stray backslash. | Check the pattern the message quotes. |
| `configuration file is not valid YAML` | The file has a YAML syntax error, such as an unclosed quote. | Check the line the message names. |

A misspelled setting is treated as an error on purpose. If Extractium ignored it, a typo such as `max_page` would leave the real ceiling at 10,000 and nobody would notice.


## Safety notes

- The file is read with a plain-data YAML reader. A configuration file cannot run code, even if someone hands you one.
- Only `http` and `https` seeds are accepted. A `file:` seed would pull content off your own disk into an index whose web-facing outputs assume everything in it was already published.
- Keep passwords, tokens, and participant identifiers out of this file. It is meant to be committed to a repository. Extractium needs none of them.
- Very complicated patterns can make matching slow on long URLs. Keep patterns short and plain.


## Conclusion

You now know every setting a build accepts, what you get for free, and how to read the error messages. Copy `examples/config.example.yaml`, set `seed_url`, and leave the rest alone until you have a reason to change it. To understand what happens after the file is read, read [the specification](extractium-spec.md).


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [examples/config.example.yaml](../examples/config.example.yaml) — commented example file to copy.
* [extractium/config.py](../extractium/config.py) — the settings, defaults, and checks in code.
* [extractium/core/fetch.py](../extractium/core/fetch.py) — the crawl scope rules these settings feed.
* [Extractium™ specification](extractium-spec.md) — architecture, outputs, and roadmap.
* [YAML 1.2 specification](https://yaml.org/spec/1.2.2/) — the file format's own reference.
* [Python regular expression syntax](https://docs.python.org/3/library/re.html#regular-expression-syntax) — how the patterns are written.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
