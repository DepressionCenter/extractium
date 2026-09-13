<!--
This file is part of Extractium™
docs/how-to/crawl-a-site.md
Author(s): Gabriel Mongefranco
Created: 2026-09-12
Last Modified: 2026-09-12
Summary: How to set up your first real build: choosing a source type
for each kind of content, the trial run and how to read llms.txt,
tuning the include and exclude patterns, the two optional environment
variables, what a build reports and what each notice means, and when a
build has to run on your own machine.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Crawl a Site

[← Back to README](../../README.md)


## Summary

This page takes you from an installed tool to a settings file you trust. You choose a source type for each kind of content, run a small trial, read what it indexed, tighten the patterns, and repeat until the page list is right. It also explains every notice a build prints, so nothing in the log is a mystery. It is written for whoever sets up a knowledge base, whether or not they write code. [Running a build](../usage.md) is the command reference this page points at, and the [configuration reference](../configuration.md) holds every setting.


## Step 1: Choose a source type for each kind of content

A settings file lists sources. Each one has a type, a label, and a few options. Pick the type by where the content lives.

| Where the content is | Source type | What to write |
|---|---|---|
| A website, including a TeamDynamix portal | `web` | The page the crawl starts from, as `seed_url`. The crawl stays inside that site. |
| A website whose sections do not link to one another | `web` | Several starting pages, as `seed_urls`. Still one crawl, one page budget, and one set of patterns. |
| A GitHub organization, user, or repository | `github_api` | The account or repository, as `org`, `user`, or `url`. Read through the API, never page by page. A `web` source whose seed is a GitHub address does the same thing by itself. |
| A DSpace repository, such as a university library's | `dspace` | The interface address, the reader address, and the collections to read. Collections are listed, never discovered. |
| A YouTube channel, playlist, or video | `youtube` | The channel as you would type it in a browser. Each stretch of a caption track becomes a section cited at the moment it was said. |
| A folder on your own machine | `local` | The folder path. Nothing from it reaches an output unless that output sets `include_local: true`. |
| A knowledge bundle another build wrote | `okf` | The folder of an Open Knowledge Format bundle, from this tool or any other. Each concept keeps the address it was read from. |

Every source needs a `label`: the name a reader sees for it, such as "Staff Handbook". It heads a section in `llms.txt` and travels with every section in the index, so a search result can say where its answer came from.

A section of a site you already crawl is not a source of its own. It belongs to that crawl as a second entry in `seed_urls`. A page two sources both reach is indexed once, by whichever reached it first, and the build says how many pages that happened to.

Start with one `web` source. Copy [examples/config.example.yaml](../../examples/config.example.yaml) to `config.yaml`, set the seed URL, and leave everything else alone. [examples/config.efdc.yaml](../../examples/config.efdc.yaml) is a complete file that uses every type, to copy from once you need more.


## Step 2: Run a small trial

Cap the first run so a pattern broader than you meant costs seconds rather than an hour:

```
python -m extractium.cli build --config config.yaml --max-pages 25 --out-dir trial
```

The run prints progress to the error stream and a summary to the output stream. When it finishes, open `trial/llms.txt`. It lists every page that was indexed, one line each, grouped under the label of the source it came from.

Read that list with three questions:

1. Are there pages you did not expect? A search form, a login page, a tag listing, a print view, or a page from another site means the crawl is reaching further than you meant.
2. Are pages you expected missing? Raise the cap a little and look again before changing anything else; twenty-five pages is not many.
3. Are the titles right? A title that is the site's name rather than the page's means a site handler is not reading that page the way you hoped. [Troubleshooting](../troubleshooting.md) has an entry for that.


## Step 3: Tune the patterns

Three lists on a `web` source decide what is fetched and what is indexed. Each holds regular expressions matched against the whole URL.

| List | What it does | Default |
|---|---|---|
| `include_patterns` | Pages the crawl may visit. A URL must match one of them. | Empty, which means the crawl works out its scope from the seed URL: the site, or the portal's own folder. |
| `crawl_exclude_patterns` | Pages the crawl must not fetch at all. Checked after the include list, so an entry here always wins. | Files that are not readable text, plus what each enabled site handler adds: search forms, logins, print views, tag pages, and code-host housekeeping pages. |
| `index_exclude_patterns` | Pages the crawl may visit and follow links from, but whose own content stays out of the index. | The same defaults. Use it for menu and category pages. |

The usual sequence is:

1. Leave `include_patterns` empty and let the seed decide the scope. Add an entry only to reach more, such as one folder of a second site.
2. Add a `crawl_exclude_patterns` entry for each kind of page you saw in step 2 that should not be fetched. The defaults are still applied when you add your own; write an empty list, `[]`, only to switch them off.
3. Add an `index_exclude_patterns` entry for navigation pages that link to the content but hold none of their own.
4. Run the trial again, then raise the cap, then drop it.

Wrap every pattern in single quotes so YAML keeps a backslash as you typed it, and escape a dot that should match a dot: `'example\.edu'`. The full rules, including the order the checks run in and what the built-in exclusions cover, are in the [configuration reference](../configuration.md) under "How the URL patterns work".


## Step 4: Decide about the two environment variables

Two values are read from the environment and never from a settings file. Both are optional, and most builds set neither.

| Variable | Set it when | Without it |
|---|---|---|
| `GITHUB_TOKEN` | A build reads more than a few GitHub repositories, or runs often enough to meet the public request limit. | The same content is read through the public API, at a lower request limit. The build reports which tier served each repository. |
| `YOUTUBE_API_KEY` | A channel or playlist has more than a hundred videos and you want all of them. | Listings come from YouTube's own pages and stop at the newest hundred of each one, which is where YouTube's `robots.txt` stops the crawler. The build says which listings it stopped short on. |

Set them in the shell before the build, or as repository secrets passed to the build step in a workflow. Neither value reaches a log line, an error message, a cache file, or an output. A token raises the request budget; it never widens what may be published, so a private repository is never indexed.


## Step 5: Read what the build reports

A build explains itself as it runs. The lines below are the ones that carry a decision you may want to change.

| Line | What it means | What to do |
|---|---|---|
| `SKIP <url> -- disallowed by robots.txt` | The site's `robots.txt` forbids that page to crawlers. | Nothing, unless you own the site; then `respect_robots_txt: false` is your statement that you do. |
| `SKIP <url> -- <reason>` | The page could not be fetched: a refusal, a timeout, or an address that is not a page. | Read the reason. A whole site skipped because its `robots.txt` could not be read is deliberate: the rules are unknown, so the crawl fails closed. |
| `SKIP <seed> -- it redirects to <address>, which is outside what this source may crawl` | The seed is a short link to somewhere else. | Use the address the message names as the seed. |
| `SKIP <url> -- it redirects to <address>, ... so what arrived is not this site's content` | A page inside the site sent the crawler somewhere the crawl may not go: another host, or an excluded address. What arrived belongs there, not here. | Nothing, unless that other place should be indexed; then add it to `include_patterns` or as a source of its own. |
| `transport: <host> served over the browser transport` | The site answered a bot-protection challenge, and the build read it over a browser-shaped connection, still naming itself. | Nothing. The summary lists the host again so the choice is on record. See [reading a site behind bot protection](../bot-protection-transport.md). |
| `already indexed by an earlier source, skipped: <url>` | Two sources reached the same page, and the first one kept it. | Nothing, unless it happens to many pages; then fold the overlapping source into the first one as a second `seed_urls` entry. |
| `N linked video(s) were left out: ...` | Pages linked videos, and a `youtube` source in the build could not confirm that a channel it names published them. | Nothing, unless the videos are yours: then name the channel on the `youtube` source. A source naming no channel reads no linked video. |
| `the <handler> handler reads this address through the <source> source` | A `web` seed on GitHub or YouTube was handed to the source that reads that host properly. | Nothing. Give the `github_api` or `youtube` source its own entry if you want its options. |
| `coverage : Not read; add to github_owners to include: <account> (N links)` | Pages linked to GitHub accounts this build was not told to read, and the links were not followed. | Add only the accounts you actually want to `github_owners`. This is the guardrail working, not an error. |
| A repository's tier, such as `tier 2 (public API)` | Which of the three ways of reading GitHub served that repository. Tier 3 is a documentation-only crawl, used when the API could not be. | Set `GITHUB_TOKEN` to reach tier 1. A tier 3 repository has its coverage noted in its repository map as well. |
| `PHI lint (<scope>): N pattern match(es) to review in X of Y document(s). Reports: ...` | The check for protected health information found shapes worth a look, and wrote two reports where you ran the build. | Open the text report and look at each line it names. A clean report is not evidence of anything; a person still decides what is safe to publish. |
| `kept from an earlier build (last seen <date>): <url>` | The build runs in `rebuild: incremental` mode and did not reach this page, and no server said it was gone, so it stays in the index as it was. | Nothing, unless the page really is gone; then a build in `full` mode, or a `404` from the server, removes it. |
| `removed, no longer in the compendium: <path>` | The Open Knowledge Format folder held a file this tool wrote for a page that is no longer in the index. | Nothing. A file somebody added by hand is never removed. |
| `NOTICE   : output '<type>' includes local content; check before publishing.` | An output opted in to content from a `local` source. | Check the file before it leaves the machine. This never happens unless you set `include_local: true`. |

The summary at the end counts the sections, the windows, and the pages that contributed at least one section, then names every file written. [Running a build](../usage.md) explains each line.


## When a build has to run on your own machine

Most builds can run on a schedule on GitHub. Two kinds cannot:

- **A `local` source.** The folder is on your machine, and a cloud runner cannot see it.
- **A `youtube` source, the first time.** YouTube refuses caption requests from cloud-provider addresses. Build once on your own machine, commit the store the build writes under `cache_dir/youtube/`, and a scheduled build reads the transcripts from there without asking YouTube for anything. Name a visible folder as `cache_dir` for that, since the default `.kb_cache` is usually ignored by git.

[How to run a weekly build](run-a-weekly-build.md) covers both commands, and [how to deploy](deploy.md) sets the arrangements side by side.


## Conclusion

You can now write a settings file for each kind of content you have, prove it with a capped run, tighten it by reading `llms.txt`, and understand every notice the build prints on the way. Next, drop the cap, then read [how to deploy](deploy.md) to decide where the build should run and where its outputs should live.


## Additional Resources

* [Extractium™ README](../../README.md) — project overview and quick start.
* [Running a Build](../usage.md) — the command, its options, the summary, and the exit codes.
* [Configuration Reference](../configuration.md) — every setting, and the full rules for the URL patterns.
* [How to Install](install.md) — the optional extras the GitHub and YouTube sources use.
* [How to Run a Weekly Build](run-a-weekly-build.md) — the local script and the scheduled workflow.
* [How to Deploy](deploy.md) — where a build runs and where its outputs live.
* [Troubleshooting](../troubleshooting.md) — failures seen so far, including wrong titles and refused sites.
* [Reading a Site Behind Bot Protection](../bot-protection-transport.md) — what the transport line means and what was measured.
* [GitHub Repository Indexing](../github-repository-indexing.md) — the three tiers and the account guardrail in detail.
* [examples/config.example.yaml](../../examples/config.example.yaml) — the commented file to copy.
* [examples/config.efdc.yaml](../../examples/config.efdc.yaml) — a complete file that uses every source type.
* [Python regular expression syntax](https://docs.python.org/3/library/re.html#regular-expression-syntax) — how the patterns are written.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
