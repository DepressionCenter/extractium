<!--
This file is part of Extractium™
docs/how-to/run-a-weekly-build.md
Author(s): Gabriel Mongefranco
Created: 2026-09-08
Last Modified: 2026-09-10
Summary: How to keep a knowledge index current: the one-command local
build with run.sh or run.bat, the scheduled GitHub Actions build, how the
crawl cache makes a rebuild cheap, and how to choose between the two.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Run a Weekly Build

[← Back to README](../../README.md)


## Summary

A knowledge index goes stale as the pages behind it change, so it should be rebuilt on a schedule. This page shows you both ways to do that: from your own machine with one command, and from GitHub on a weekly timer. You do not need to write code for either. Pick the one that suits where your content lives.


## Which one do you need?

| Build it | When |
|---|---|
| On GitHub, weekly | Your sources are public web pages. Nothing to install, nothing to remember. This is the normal choice. |
| On your own machine | Your sources include a folder of local files, or YouTube captions, which a cloud runner cannot reach. Also useful for a first trial run. |

You can use both. Many groups run the weekly build on GitHub and rebuild by hand after a large content change.


## Build on your own machine

You need Python 3.10 or newer and a copy of this repository.

1. Put your settings file, `config.yaml`, in the repository folder. Copy [examples/config.example.yaml](../../examples/config.example.yaml) if you do not have one, and change the seed URL.
2. Run the script for your system:

   ```
   ./run.sh                  # macOS and Linux
   run.bat                   # Windows
   ```

3. Read the summary it prints, then follow the three lines it gives you to commit and push the result.

The script creates a virtual environment in `.venv`, installs the exact package versions recorded in `requirements-lock.txt`, installs Extractium into it, and runs the build. The first run downloads the embedding model, about 130 MB, and takes several minutes. Later runs reuse it.

The lock file holds the runtime dependencies only, so a scheduled build reads a repository's documentation and records its source files by name without reading what is inside them. To analyze code on a schedule as well, regenerate the lock with the optional parser set included:

```bash
uv pip compile pyproject.toml --extra code --universal --python-version 3.11 --generate-hashes -o requirements-lock.txt
```

Keep the header at the top of the file when you do; the command that produced the list is recorded on the line below it.

### Changing what it builds

The script builds from `config.yaml` unless you say otherwise:

```
CONFIG=other-settings.yaml ./run.sh          # macOS and Linux
set CONFIG=other-settings.yaml && run.bat    # Windows
```

Anything you pass as an argument goes straight to the build command, so a capped trial run looks like this:

```
./run.sh --config config.yaml --max-pages 25 --out-dir trial
```

[Running a build](../usage.md) lists every option.


## Build on GitHub, weekly

The workflow lives at `.github/workflows/build-compendium.yml`. The version to copy into your own repository, with a matching settings file and README, is in [examples/data-repo/](../../examples/data-repo/README.md).

1. Create a repository for your content and copy the template into it.
2. Change `seed_url` and `name` in `config.yaml`.
3. Turn on Pages, as described in [how to publish to GitHub Pages](publish-to-github-pages.md).
4. Open the **Actions** tab, choose **Build compendium**, and press **Run workflow**. For the first run, set *Visit at most this many pages* to `25`.
5. When it finishes, open your published `llms.txt` and check the page list. Tighten the patterns in `config.yaml` if pages you did not expect are there.
6. Leave the schedule alone. It runs every Monday at 06:17 UTC.

### Changing the day or time

The schedule is one line in the workflow:

```yaml
    - cron: "17 6 * * 1"
```

The five fields are minute, hour, day of month, month, and day of the week, in UTC. `1` is Monday. Pick an odd minute rather than `0`: GitHub queues a great many jobs on the hour, and a run scheduled there can start late.

### What the run does

1. Checks out your repository, and Extractium at the version your workflow names.
2. Installs the locked dependencies. Every package carries a hash, so a package whose contents do not match what was locked is refused rather than installed.
3. Restores the crawl cache from the last run.
4. Builds the index.
5. Uploads the output folder and publishes it to Pages.

Nothing is written back to your repository. The published files come from the build artifact, so your repository stays small.


## Why a rebuild is cheap

Extractium keeps every page it fetches in a cache folder, `.kb_cache`. On the next run it asks each site whether its pages have changed and downloads only the ones that have. A weekly rebuild is far faster than the first build.

The cache is keyed on your settings file. Change what is crawled and the next run starts from an empty cache, which is what you want: a new pattern should be fetched fresh rather than answered from what an old pattern had collected.

Deleting the cache is always safe. It costs time, never correctness.


## Checking that it worked

- The **Actions** tab shows a green tick and, in the log, the same summary the local build prints: how many sections, how many windows, how many pages, and every file written.
- Your published `llms.txt` starts with the build time. If that time is old, the last run failed or the schedule is off.
- A failed run sends an email to the person who owns the repository. [Troubleshooting](../troubleshooting.md) lists the failures seen so far.


## Conclusion

You can now rebuild your index on demand from your own machine, or leave it to a weekly run on GitHub. Next, set up publishing with [how to publish to GitHub Pages](publish-to-github-pages.md), or read [how to search a compendium](search-a-compendium.md) to use the file you just built.


## Additional Resources

* [Extractium™ README](../../README.md) — project overview and quick start.
* [Running a Build](../usage.md) — every command-line option, the summary, and the exit codes.
* [Configuration Reference](../configuration.md) — every setting in `config.yaml`.
* [How to Publish to GitHub Pages](publish-to-github-pages.md) — the publishing settings, step by step.
* [How to Search a Compendium](search-a-compendium.md) — using the index the build writes.
* [Data repository template](../../examples/data-repo/README.md) — the files to copy into your own content repository.
* [Troubleshooting](../troubleshooting.md) — known failures, causes, and fixes.
* [POSIX cron expressions on GitHub](https://docs.github.com/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule) — the schedule syntax and its limits.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
