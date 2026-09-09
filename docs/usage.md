<!--
This file is part of Extractium™
docs/usage.md
Author(s): Gabriel Mongefranco
Created: 2026-09-08
Last Modified: 2026-09-09
Summary: How to run an Extractium build from the command line: the build
command and each of its options, what lands in the output folder, what the
summary tells you, what each exit code means, and how to try a small run
before a full one.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Running a Build

[← Back to README](../README.md)


## Summary

This page shows you how to build your knowledge index. You write one settings file, run one command, and get a folder of files you can publish anywhere that serves static files. It is written for anyone who runs the build, whether or not they write code. For what every setting in the file means, read the [configuration reference](configuration.md).


## Before you start

You need three things:

1. Python 3.10 or newer.
2. Extractium installed: `pip install -e .` from a copy of this repository.
3. A settings file. Copy [examples/config.example.yaml](../examples/config.example.yaml), name it `config.yaml`, and change the seed URL to your own site.

The first build downloads the embedding model, about 130 MB. Later builds reuse it.


## The build command

```
extractium build --config config.yaml
```

That reads the settings file, visits your sources, and writes every output into the folder the file names (`dist` unless you change it).

You can also run it as a module, which is useful when the console script is not on your path:

```
python -m extractium.cli build --config config.yaml
```

### Options

| Option | What it does |
|---|---|
| `--config FILE` | Path to the settings file. Required. |
| `--out-dir DIR` | Write the outputs here instead of the folder the settings file names. |
| `--max-pages N` | Visit at most N pages. Overrides the setting in the file. |
| `--float32-vecs` | Store the vectors at full precision instead of the compressed default. The file grows about four times. Use it only if you are comparing search quality. |
| `--version` | Print the version and stop. |


## Try a small run first

A first run against a new site is a good place to find a pattern that is broader than you meant. Cap it:

```
extractium build --config config.yaml --max-pages 25 --out-dir trial
```

Look at `trial/llms.txt`. It lists every page that was indexed, one line each. If pages you did not expect are in there, tighten `include_patterns` or add a `crawl_exclude_patterns` entry, and run again. When the list looks right, drop the cap.


## What you get

With the default settings, the output folder holds three files:

| File | What it is |
|---|---|
| `kb-index.json` | The search index: text, vectors, and keyword statistics in one file. Despite the name it is partly binary; the `.json` extension keeps static hosts serving it correctly. The [container format](container-format.md) page describes it byte by byte. |
| `llms.txt` | A short index, one line per page, for a language model that browses the web. |
| `llms-full.txt` | The whole indexed text, in reading order. |

Publish the folder as it is. Nothing needs a server or a database.


## Reading the summary

When a build finishes it prints a summary:

```
Built 'Example Org Knowledge Base' at 2026-09-08T14:30:00Z
  sections : 812
  windows  : 1944
  sources  : 233
  wrote    : dist/kb-index.json (2.71 MB)
  wrote    : dist/llms.txt (0.04 MB)
  wrote    : dist/llms-full.txt (1.12 MB)
```

- **sections** are the blocks of text a search returns and an answer cites.
- **windows** are the smaller pieces that are actually searched. There are usually more of them than sections.
- **sources** is how many pages contributed at least one section. Pages that were visited but held nothing to index do not count.

While the build runs, it prints progress to the error stream and the summary to the output stream. So you can save the summary and still watch the run:

```
extractium build --config config.yaml > build-summary.txt
```

If any output contains content read from a local folder, the summary says so on its own line. That never happens unless you set `include_local: true` on that output.


## Indexing a folder on your own machine

A `local` source reads Markdown, plain text, and HTML files from a folder. Use it for material that is not on a website. Two rules make it safe to use:

- **Nothing local reaches an output unless that output asks for it** with `include_local: true`. The default cannot leak by being forgotten.
- **No path from your disk travels with the content.** A file is recorded as `local:` plus its path relative to the folder you named.

Every build also checks what it read for likely protected health information, and writes two reports where you ran the build:

```
phi-lint-report.txt    for you to read
phi-lint-report.json   for a program or an AI assistant
```

The text report lists each file and line to look at, and what to do about it. Neither report copies what it found, so it never becomes a second copy of the identifiers. Read it, fix what needs fixing, and delete it when you are done. **A clean report does not mean content is safe to publish.** Only a person can decide that. See [the configuration reference](configuration.md) for the `phi_lint` setting and [the compliance page](compliance.md) for what the check does not cover.


## Exit codes

A scheduled build can tell what went wrong without anyone reading the log.

| Code | Meaning | What to do |
|---|---|---|
| 0 | The build finished and wrote its outputs. | Nothing. |
| 1 | Something unexpected failed. | Read the message. It names the failure without printing an internal trace. |
| 2 | The settings file is missing, or holds a value the build cannot act on. Also used when a source or output names a plugin that is not installed. | Fix the file. The message names the setting. |
| 3 | The sources produced nothing worth indexing, so nothing was written. | Check the seed URL and the include and exclude patterns. A trial run with `--max-pages 25` usually shows why. |
| 4 | An output could not be written. | Check that the output folder is writable and that the disk has room. |


## Running it again

Extractium keeps fetched pages in a cache folder, `.kb_cache` unless you change it. A second run asks each site whether its pages changed and downloads only the ones that did, so a weekly rebuild is much faster than the first one.

Add `.kb_cache/` to your `.gitignore`. Deleting the folder is safe: the next build simply downloads everything again.


## Conclusion

You can now run a build, cap it for a trial, read what it produced, and tell from the exit code what went wrong. Next, read the [configuration reference](configuration.md) to tune what gets crawled, or the [data flow](data-flow.md) page to see what happens to your content between the crawl and the output folder.


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Configuration reference](configuration.md) — every setting in `config.yaml`.
* [Data flow](data-flow.md) — where content enters, how it is changed, and where it lands.
* [Container format](container-format.md) — the index file, byte by byte.
* [examples/config.example.yaml](../examples/config.example.yaml) — a commented settings file to copy.
* [llmstxt.org](https://llmstxt.org/) — the convention the `llms.txt` files follow.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
