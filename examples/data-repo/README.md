<!--
This file is part of Extractium™
examples/data-repo/README.md
Author(s): Gabriel Mongefranco
Created: 2026-09-08
Last Modified: 2026-09-08
Summary: README for the data-repository template: what the folder is, how
to turn it into your own repository, how the weekly build runs, and what
gets published.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Example Org Knowledge Base

## A data repository built with Extractium™

[← Back to the Extractium README](../../README.md)


## Summary

This folder is a template. Copy it into a new repository of your own, change two lines, and you have a knowledge base that rebuilds itself every week and publishes to GitHub Pages. Your content and settings live here; the tool that builds them lives in the [Extractium repository](https://github.com/DepressionCenter/extractium). Keeping the two apart means you can update either one without disturbing the other.


## What is in the template

| File | What it is |
|---|---|
| `config.yaml` | What to crawl and what to write. The one file you edit. |
| `.github/workflows/build-compendium.yml` | The weekly build. Runs on a schedule and on a button press, and publishes the result. |


## Set it up

1. **Make your own repository.** Copy the contents of this folder into it. A new empty repository on GitHub is enough.
2. **Point it at your site.** In `config.yaml`, change `seed_url` to the page your documentation starts from, and `name` to your organization's name.
3. **Turn on Pages.** In the repository, open **Settings → Pages** and set **Source** to **GitHub Actions**. Nothing is published until you do.
4. **Run it once by hand.** Open the **Actions** tab, choose **Build compendium**, and press **Run workflow**. Set *Visit at most this many pages* to `25` for the first run.
5. **Check what it found.** When the run finishes, open the published site and read `llms.txt`. It lists every page that was indexed, one line each. If pages you did not expect are in there, tighten the patterns in `config.yaml` and run it again.
6. **Let it run weekly.** Once the list looks right, remove the page cap and leave the schedule alone. It runs every Monday morning UTC.


## What gets published

The build writes three files and the workflow publishes the folder that holds them:

| File | What it is |
|---|---|
| `kb-index.json` | The search index: text, vectors, and keyword statistics in one file, for the Extractium clients. |
| `llms.txt` | A short index, one line per page, for a language model that browses the web. |
| `llms-full.txt` | The whole indexed text, in reading order. |

They are served at your Pages URL, for example `https://example-org.github.io/knowledge-base/kb-index.json`.


## Choosing the version of the tool

The workflow's `EXTRACTIUM_REF` setting names the version of Extractium to build with. It starts at `main`. Change it to a release tag once you want your builds to stay on a fixed version, so a change in the tool never arrives unannounced in a scheduled run.


## Building on your own machine instead

Some sources cannot be reached from a cloud runner: a folder of local files, and YouTube captions. For those, clone the Extractium repository, put your `config.yaml` beside it, and run `run.sh` (macOS, Linux) or `run.bat` (Windows). The script builds and then prints what to commit. [How to run a weekly build](../../docs/how-to/run-a-weekly-build.md) covers both paths.


## A note on private content

Everything published here is public the moment the build finishes. Extractium keeps content read from local folders out of every output unless that output explicitly opts in, and the build says so in its summary when an output does. Before you turn that option on, read [the compliance page](../../docs/compliance.md).


## Conclusion

Change the seed URL, turn on Pages, press the button once, and the rest is automatic. If a run fails, [troubleshooting](../../docs/troubleshooting.md) lists the failures seen so far and what to do about each.


## Additional Resources

* [Extractium™ README](../../README.md) — what the tool is and how to install it.
* [Configuration reference](../../docs/configuration.md) — every setting in `config.yaml`.
* [How to run a weekly build](../../docs/how-to/run-a-weekly-build.md) — the scheduled build and the local one, step by step.
* [How to publish to GitHub Pages](../../docs/how-to/publish-to-github-pages.md) — the publishing settings and how to check them.
* [How to search a compendium](../../docs/how-to/search-a-compendium.md) — using the published index from Python or JavaScript.
* [Troubleshooting](../../docs/troubleshooting.md) — known failures, causes, and fixes.


[← Back to the Extractium README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
