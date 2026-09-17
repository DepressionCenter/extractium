<!--
This file is part of Extractium™
docs/usage.md
Author(s): Gabriel Mongefranco
Created: 2026-09-08
Last Modified: 2026-09-17
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

This page shows you how to build your compendium, the searchable collection of everything you publish, from the command line. You write one settings file, run one command, and get a folder of files you can publish anywhere that serves static files. You do not need to write code. For what every setting in the file means, read the [configuration reference](configuration.md).


## Before you start

You need three things:

1. Python 3.10 or newer.
2. Extractium™ installed. The [installation guide](how-to/install.md) covers both options: the build scripts `run.sh` and `run.bat`, which install and build in one step, and `pip install -e .` in a Python development environment. It also explains the optional extras, `dev`, `code`, and `youtube`.
3. A settings file. The `init` command below writes one for you. You can also copy [examples/config.example.yaml](../examples/config.example.yaml), name it `config.yaml`, and change `seed_url` to your own site.

The first build downloads the embedding model, about 130 MB. Later builds reuse it.


## Writing a first settings file

```
python -m extractium.cli init
```

This asks three questions and writes `config.yaml` in the current folder:

```
Creating config.yaml. Press Enter to accept a default shown in brackets.

Name of your compendium [Compendium]: EFDC Compendium
Short name for the output files (lowercase letters, digits, hyphens) [efdc-compendium]:
Website to start crawling from, such as https://example.edu/docs/: https://example.edu/kb/

Wrote config.yaml. Every setting is explained in its comments; add more sources or outputs there.
Next: python -m extractium.cli build --config config.yaml --max-pages 25
```

The file it writes is the commented example that ships with the project, with those three values filled in, so every other setting is explained where you would change it. The one web source is labelled `Website`. Rename it in the file if you like.

The build scripts `run.sh` and `run.bat` run this command for you when there is no `config.yaml`, then build with a page limit.

| Option | What it does |
|---|---|
| `--name TEXT` | The name, without asking. |
| `--slug TEXT` | The short name, without asking. When `--name` is given and this is not, the short name is derived from the name. |
| `--seed-url URL` | The website, without asking. Must start with `http://` or `https://`. |
| `--output FILE` | Where to write the file. `config.yaml` by default. |
| `--force` | Replace the file if it already exists. Without it, an existing file is left alone. |

Give all three values as flags and the command asks nothing, which is the form for a script. It exits with code 2 for a value it cannot accept or a file it will not replace, and 4 when the file cannot be written.


## The build command

```
python -m extractium.cli build --config config.yaml
```

This reads the settings file, visits your sources, and writes every output into the folder the file names (`dist` unless you change it).

There is a shorter form:

```
extractium build --config config.yaml
```

It needs Python's scripts folder on your `PATH`, which it often is not after a user install. The module form above always works, so this page uses it. See [Troubleshooting](troubleshooting.md) for how to add the folder if you want the short form.

### Options

| Option | What it does |
|---|---|
| `--config FILE` | Path to the settings file. Required. |
| `--out-dir DIR` | Write the outputs here instead of the folder the settings file names. |
| `--max-pages N` | Read at most N pages per source: web pages, videos, deposits, or files, whichever the source reads. Overrides the setting in the file. |
| `--float32-vecs` | Store the vectors at full precision instead of the compressed default. The file grows about four times. Use it only if you are comparing search quality. |
| `--version` | Print the version and stop. |

### Environment variables

Two settings are read from the environment and never from the settings file. Both are optional.

| Variable | Used by | Without it |
|---|---|---|
| `GITHUB_TOKEN` | The `github_api` source, and a GitHub address used as the seed of a `web` source | The same content is read through the public API, at a lower request limit. Either way, an account contributes at most `max_repositories` repositories of `max_files_per_repository` files each; the [configuration reference](configuration.md) explains both. |
| `YOUTUBE_API_KEY` | The `youtube` source | Listings come from YouTube's own pages and stop at the newest hundred videos of each one. |

Neither value reaches a log line, an error message, a cache file, or an output. See [how to crawl a site](how-to/crawl-a-site.md) for when each one is worth setting.

The run scripts read three more, which choose which copy of Extractium™ a script saved on its own downloads: `EXTRACTIUM_REF` (a release tag, or a branch such as `main` for unreleased work), `EXTRACTIUM_REPO`, and `EXTRACTIUM_DIR`. The build itself never reads them. [How to run a weekly build](how-to/run-a-weekly-build.md) explains each under "Building with a branch instead of a release".


## Try a small run first

A first run against a new site is the best time to catch a URL pattern that is broader than you meant. Limit it:

```
python -m extractium.cli build --config config.yaml --max-pages 25 --out-dir trial
```

Open `trial/llms.txt`, then the file it links to under `trial/llms/`. That file lists every page that was indexed from the source, one line each. If you see pages you did not expect, tighten `include_patterns` or add a `crawl_exclude_patterns` entry, and run again. When the list looks right, remove the limit.


## What you get

With the default settings, the output folder holds the search index and the llms.txt index files:

| File | What it is |
|---|---|
| `compendium.json.gz` | The light search index: one entry per page, holding the page's description and keywords, with vectors and keyword statistics. Small enough for a search box on a web page or a free hosted server. Despite the name it is partly binary, and it is compressed with gzip; the clients inflate it for you. The [container format](container-format.md) page describes it byte by byte. |
| `compendium-full.json.gz` | The full search index: the text of every section, in the same format. For a client that needs to quote the page text and can afford a larger download. |
| `llms.txt` | A short index of your sources, for a language model that browses the web. Each entry names a source, says what it is, and links to that source's index file. |
| `llms/` | One index file per source, listing its pages with a link and a description each. A source with more than 500 pages gets a folder of files, one per section of the source. |

The llms.txt files are meant to be read whole inside a language model's context window, so they are kept short and they list documentation only, never source code. The full text of every page is in the full search index, and in the `okf` folder if you add that output. Neither search index holds source code either. Code analysis from a GitHub source is written to the `sqlite` and `okf` outputs only, and the summary at the end of the build says so.

Add a `sqlite` output for [a database](sqlite-database.md) with the same content, or an `okf` output for a folder of Markdown files. See the [configuration reference](configuration.md).

Publish the folder as it is. Nothing in it needs a server or a database.


## Reading the summary

When a build finishes it prints a summary:

```
Built 'Example Org Knowledge Base' at 2026-09-08T14:30:00Z
  sections : 812
  windows  : 1944
  sources  : 233
  wrote    : dist/compendium.json.gz (0.12 MB)
  wrote    : dist/compendium-full.json.gz (0.84 MB)
  wrote    : dist/llms.txt (0.00 MB)
  wrote    : dist/llms/example-org-website.txt (0.04 MB)
  wrote    : dist/okf (235 files, 1.18 MB)
```

- Sections are the blocks of text a search returns and an answer cites.
- Windows are the smaller pieces that are searched. There are usually more windows than sections.
- Sources is how many pages contributed at least one section. Pages that were visited but held nothing to index do not count.
- Each `wrote` line names a file and its size. An output that writes a folder of files, such as the Open Knowledge Format output, is named once as a folder with a count.

While the build runs, it prints progress to the error stream and the summary to the output stream, so you can save the summary and still watch the run:

```
python -m extractium.cli build --config config.yaml > build-summary.txt
```

Sources run several at a time by default, so their progress lines arrive mixed together. Each line then starts with the label of the source it belongs to:

```
U-M Health Research Resource Library | [  12] https://portal.example/TDClient/000/ExampleOrg/KB/ArticleDet?ID=12
Depression Center Website | [   3] https://example.org/about
```

Set `parallel_sources: 1` in the settings file to run the sources one after another with the plain log. The [configuration reference](configuration.md) explains both settings under "Reading sources at the same time".

If any output contains content read from a local folder, the summary says so on its own line. That only happens when you set `include_local: true` on that output.


## Indexing a folder on your own computer

A `local` source reads Markdown, plain text, and HTML files from a folder. Use it for material that is not on a website. Two rules keep it safe:

- Nothing from a local folder reaches an output unless that output asks for it with `include_local: true`. You cannot leak local content by forgetting a setting.
- No path from your disk travels with the content. A file is recorded as `local:` plus its path relative to the folder you named.

Every build also checks what it read for likely protected health information (PHI), and writes two reports to the folder you ran the build from:

```
phi-lint-report.txt    for you to read
phi-lint-report.json   for a program or an AI assistant
```

The text report lists each file and line to look at, and what to do about it. Neither report copies what it found, so the report never becomes a second copy of the identifiers. Read it, fix what needs fixing, and delete it when you are done. A clean report does not mean the content is safe to publish. Only a person can decide that. See the [configuration reference](configuration.md) for the `phi_lint` setting and the [compliance page](compliance.md) for what the check does not cover.


## Exit codes

The exit code tells a scheduled build what went wrong without anyone reading the log.

| Code | Meaning | What to do |
|---|---|---|
| 0 | The build finished and wrote its outputs. | Nothing. |
| 1 | Something unexpected failed. | Read the message. It names the failure without printing an internal trace. |
| 2 | The settings file is missing, or holds a value the build cannot act on. Also used when a source or output names a plug-in that is not installed. | Fix the file. The message names the setting. |
| 3 | The sources produced nothing worth indexing, so nothing was written. | Check the seed URL and the include and exclude patterns. A trial run with `--max-pages 25` usually shows why. |
| 4 | An output could not be written. | Check that the output folder is writable and that the disk has room. |


## Running it again

Extractium™ keeps fetched pages in a cache folder, `.kb_cache` unless you change it. A second run asks each site whether its pages changed and downloads only the ones that did, so a weekly rebuild is much faster than the first one.

Add `.kb_cache/` to your `.gitignore`. Deleting the folder is safe. The next build downloads everything again.

The one exception is a build that reads YouTube. Captions are stored under `<cache_dir>/youtube/`, and a scheduled build cannot fetch them again, because YouTube refuses caption requests from cloud-provider addresses. Such a build names a visible folder as its `cache_dir` and commits it. See the `youtube` section of the [configuration reference](configuration.md).


## Conclusion

You can now run a build, limit it for a trial, read what it produced, and tell from the exit code what went wrong. Next, read the [configuration reference](configuration.md) to tune what gets crawled, or [how to deploy](how-to/deploy.md) to decide where the build should run and where its outputs should live.


## Additional Resources

* [Extractium™ README](../README.md): project overview and quick start.
* [Installation guide](how-to/install.md): the two ways to install, and the optional extras.
* [How to crawl a site](how-to/crawl-a-site.md): choosing source types, tuning patterns, and reading what a build reports.
* [Configuration reference](configuration.md): every setting in `config.yaml`.
* [Data flow](data-flow.md): where content enters, how it is changed, and where it lands.
* [Container format](container-format.md): the index file, byte by byte.
* [examples/config.example.yaml](../examples/config.example.yaml): a commented settings file to copy.
* [llmstxt.org](https://llmstxt.org/): the convention the `llms.txt` files follow.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
