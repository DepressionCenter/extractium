<!--
This file is part of Extractium™
docs/how-to/run-a-weekly-build.md
Author(s): Gabriel Mongefranco
Created: 2026-09-08
Last Modified: 2026-09-22
Summary: How to keep a compendium current: the one-command build with
run.sh or run.bat on your own computer or a server, how to put it on a
timer there, the scheduled builds on GitHub Actions and on a GitLab
runner, how the crawl cache makes a rebuild cheap, and how to choose.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Run a Weekly Build

[← Back to README](../../README.md)


## Summary

A compendium, the collection a build writes, goes stale as the pages behind it change, so you should rebuild it on a schedule. This page shows you three ways to do that: with one command on your own computer or a server, which you can put on a timer; from a GitLab runner your institution provides; and from GitHub on a weekly timer. You do not need to write code for any of them. Pick the one that suits where your content lives and how large it is.


## Which one do you need?

| Build it | When |
|---|---|
| On your own computer or a server | The usual choice. It reaches every source, including a folder of local files and YouTube captions, and it is the only choice for a large corpus. Put the command on a timer and it is as hands-off as the other two. |
| On a GitLab runner your institution provides | You have a GitLab instance with its own runners, as many universities and hospitals do. The runner is a server you do not have to look after, and the pipeline keeps the output as an artifact behind your sign-in. |
| On GitHub, weekly | A small set of public web pages, no video, and a build that finishes well inside an hour. Nothing to install, nothing to remember, free on a public repository. |

You can combine them. Many groups run the scheduled build on a runner and rebuild by hand after a large content change.

YouTube needs your own computer first, whatever else you use. YouTube refuses caption requests from cloud-provider addresses, so you build once on your own computer, commit the folder `cache_dir` names, and every scheduled build reads the transcripts from there without asking YouTube for anything. [The cache README](../../examples/data-repo/kb-cache/README.md) says what to commit and when to refresh it.

### When a corpus is too large for GitHub

A GitHub-hosted runner has a few processor cores and no graphics card, so it embeds text several times slower than a laptop and transcribes audio far slower still. A job stops after six hours. The crawl cache it restores is capped at 10 GB for the whole repository, and every source's polite delay between requests counts against the clock as much as on your own machine. A corpus of a few hundred pages fits comfortably. One that takes an hour on your own computer will take longer on GitHub and may not finish. For that size, build on your own computer or on a runner you control.


## Build on your own computer

You need Python 3.10 or newer and the script for your operating system, either on its own or inside a clone of this repository. [How to install](install.md) explains both.

1. Run the script from the folder that holds your settings file, `config.yaml`. If there is no settings file yet, the script asks you three questions and writes one:

   ```
   ./run.sh                  # macOS and Linux
   run.bat                   # Windows
   ```

2. Read the summary it prints, then follow the three lines it gives you to commit and push the result.

The script downloads Extractium™ when it is on its own, creates a virtual environment in `.venv`, installs the exact package versions recorded in `requirements-lock.txt`, installs Extractium™ into it, and runs the build. The first run downloads the embedding model, about 130 MB, and takes several minutes, and it stops at 25 pages so you can check the page list in `dist/llms.txt` before building everything. Later runs reuse the environment and the model and build the whole site.

The lock file carries the runtime dependencies and four optional extras: the code parsers, the caption library, the PDF reader, and the keyword extractor. A build made this way therefore analyzes code, reads stored transcripts, reads PDF files, and names every section with keywords. To regenerate the lock file after changing a dependency, run the command recorded in its header:

```bash
uv pip compile pyproject.toml --universal --python-version 3.11 --generate-hashes --extra code --extra youtube --extra pdf --extra keywords -o requirements-lock.txt
```

Keep the header at the top of the file when you do. The command that produced the list is recorded on the line below it.

### Changing what it builds

The script builds from `config.yaml` unless you say otherwise:

```
CONFIG=other-settings.yaml ./run.sh          # macOS and Linux
set CONFIG=other-settings.yaml && run.bat    # Windows
```

### Building with a branch instead of a release

When the script is saved on its own, it downloads the newest published release of Extractium™ into `extractium-src` beside itself. Three variables change that. Set them before running the script, the way `CONFIG` is set above.

| Variable | Default | What it does |
|---|---|---|
| `EXTRACTIUM_REF` | `latest` | Which version to download. `latest` is looked up as the newest published release. A tag such as `v0.2` pins one release. A branch name such as `main` builds with work that has not been released yet, which is how you try a fix before it ships, or test a plug-in against the current code. |
| `EXTRACTIUM_REPO` | `https://github.com/DepressionCenter/extractium` | Where to download from. Point it at a fork to build with your own changes. |
| `EXTRACTIUM_DIR` | `extractium-src` beside the script | Where the download lands. |

```
EXTRACTIUM_REF=main ./run.sh          # macOS and Linux
set EXTRACTIUM_REF=main && run.bat    # Windows
```

The script downloads only when that folder does not already hold Extractium™. To move from a release to a branch, or from one branch to a newer copy of it, delete the folder first, or set `EXTRACTIUM_DIR` to a fresh one. A script run from inside a checkout of the repository downloads nothing and uses the checkout, whatever these variables say.

Anything you pass as an argument goes straight to the build command, and the script then asks no questions, so a limited trial run looks like this:

```
./run.sh --config config.yaml --max-pages 25 --out-dir trial
```

[Running a build](../usage.md) lists every option.

### Putting it on a timer

The script runs the same way from a scheduler as from your keyboard, so a weekly build on your own computer or on a small server is one scheduled task. The computer has to be on at the time; a laptop that is asleep runs nothing.

On Linux or macOS, add one line to your user's crontab with `crontab -e`. This runs every Monday at 06:17 in the machine's own time zone and keeps a log of every run:

```
17 6 * * 1  cd /path/to/your/compendium && ./run.sh >> build.log 2>&1
```

On Windows, create a task from a command prompt opened in the folder that holds your settings file. This runs `run.bat` every Monday at 06:17:

```
schtasks /Create /TN "Extractium weekly build" /SC WEEKLY /D MON /ST 06:17 /TR "cmd /c cd /d %CD% && run.bat >> build.log 2>&1"
```

Run the task once by hand, from the Task Scheduler window or with `schtasks /Run /TN "Extractium weekly build"`, and read `build.log` before trusting the schedule. A scheduled run has no one at the keyboard, so the settings file must already be in place. With none, the script would stop waiting for answers to its questions.

The build writes its outputs to `dist/`, or wherever `out_dir` points. To publish them, add the copy step your host needs to the same line, after the script, as [how to deploy](deploy.md) describes for a static host.


## Build on a GitLab runner

Many institutions run their own GitLab, with runners on servers they own, and let their staff use both without charge. The pipeline at [examples/data-repo/.gitlab-ci.yml](../../examples/data-repo/.gitlab-ci.yml) builds there. It clones Extractium™ at a pinned version, installs the locked dependencies with every hash checked, keeps the crawl cache and the embedding model between runs, and keeps the output folder as a pipeline artifact. The artifact sits behind your GitLab sign-in, so the outputs are not public unless you publish them.

1. Create a project on your GitLab instance for your content and copy the [data repository template](../../examples/data-repo/README.md) into it. The GitHub workflow folder can be left out.
2. Change `seed_url` and `name` in `config.yaml`.
3. Open `.gitlab-ci.yml` and change the `tags` lines to the tag your runners carry, or delete those lines to accept any runner the project may use. Ask whoever runs the instance which tag to use if you are not sure.
4. Open **Build → Pipeline schedules**, press **New schedule**, and set the day and time. The file itself holds no schedule, and a push to the project starts no build.
5. Run it once by hand. Open **Build → Pipelines**, press **New pipeline**, and set the variable `MAX_PAGES` to `25`.
6. When it finishes, open the `build` job, browse its artifact, and read `dist/llms.txt` and the page lists under `dist/llms/`. Tighten the patterns in `config.yaml` if pages you did not expect are there.
7. Leave the schedule alone.

What to know about the file:

- The runner needs to reach github.com to clone the tool. If yours cannot, mirror the Extractium™ repository on your instance and set `EXTRACTIUM_REPO` to the mirror's address.
- A runner that runs jobs in containers uses the `image` line, a standard Python image. A runner that runs jobs on the host itself ignores it and needs Python 3.10 or newer, git, and pip installed there. A runner with a graphics card embeds faster; nothing in the file needs changing for it.
- The job's `timeout` is four hours. The instance may set a lower ceiling, and the lower one wins.
- The artifact expires after three weeks, long enough that the last good build is still there when the next one fails. The newest artifact has a fixed address, for example `<project address>/-/jobs/artifacts/main/raw/dist/compendium.json.gz?job=build`, which a client can read with a sign-in or a project access token.
- Set the variable `PUBLISH_PAGES` to `true`, in the schedule or in **Settings → CI/CD → Variables**, to publish the output folder to GitLab Pages as well. That makes it readable by anyone the instance lets read Pages, which on some instances is everyone. Ask before you turn it on.

The crawl cache behaves as it does on GitHub: it is keyed on the settings file, and a change to that file starts the next run from an empty cache.


## Build on GitHub, weekly

The workflow lives at `.github/workflows/build-compendium.yml`. The version to copy into your own repository, with a matching settings file and README, is in [examples/data-repo/](../../examples/data-repo/README.md). Read "When a corpus is too large for GitHub" above first. This path suits a small public site.

1. Create a repository for your content and copy the template into it.
2. Change `seed_url` and `name` in `config.yaml`.
3. Turn on Pages, as described in [how to publish to GitHub Pages](publish-to-github-pages.md).
4. Open the **Actions** tab, choose **Build compendium**, and press **Run workflow**. For the first run, set *Visit at most this many pages* to `25`.
5. When it finishes, open your published `llms.txt`, follow the link to each source's index file, and check the page list. Tighten the patterns in `config.yaml` if pages you did not expect are there.
6. Leave the schedule alone. It runs every Monday at 06:17 UTC.

### Changing the day or time

The schedule is one line in the workflow:

```yaml
    - cron: "17 6 * * 1"
```

The five fields are minute, hour, day of month, month, and day of the week, in UTC. `1` is Monday. Pick an odd minute rather than `0`. GitHub queues a great many jobs on the hour, and a run scheduled there can start late.

### What the run does

1. Checks out your repository, and Extractium™ at the version your workflow names.
2. Installs the locked dependencies. Every package carries a hash, so a package whose contents do not match what was locked is refused rather than installed.
3. Restores the crawl cache from the last run.
4. Builds the index.
5. Uploads the output folder and publishes it to Pages.

Nothing is written back to your repository. The published files come from the build artifact, so your repository stays small.


## Why a rebuild is cheap

Extractium™ keeps every page it fetches in a cache folder, `.kb_cache`. On the next run it asks each site whether its pages have changed and downloads only the ones that have. A weekly rebuild is far faster than the first build.

The cache is keyed on your settings file. Change what is crawled and the next run starts from an empty cache. That is what you want: a new pattern should be fetched fresh rather than answered from what an old pattern had collected.

Deleting the cache is always safe. It costs time, never correctness.


## Checking that it worked

- On your own computer or a server, `build.log` ends with the summary: how many sections, how many windows, how many pages, and every file written. A run that stopped early ends with the error instead, and the script's exit code is not zero.
- On GitLab, the **Pipelines** page shows a green check mark, the `build` job's log holds the same summary, and the job's artifact holds the files.
- On GitHub, the **Actions** tab shows a green check mark and the log holds the summary. A failed run sends an email to the person who owns the repository.
- Wherever the files are published, `llms.txt` starts with the build time. If that time is old, the last run failed or the schedule is off. [Troubleshooting](../troubleshooting.md) lists the known failures.


## Conclusion

You can now rebuild your compendium on demand from your own computer, put that command on a timer, or leave it to a scheduled run on a GitLab runner or on GitHub. Next, set up publishing with [how to publish to GitHub Pages](publish-to-github-pages.md), or read [how to search a compendium](search-a-compendium.md) to use the file you just built.


## Additional Resources

* [Extractium™ README](../../README.md): project overview and quick start.
* [Installation guide](install.md): the two ways to install, and what the lock file pins.
* [How to Deploy](deploy.md): the deployment choices side by side, and how each one is consumed.
* [Running a Build](../usage.md): every command-line option, the summary, and the exit codes.
* [Configuration Reference](../configuration.md): every setting in `config.yaml`.
* [How to Publish to GitHub Pages](publish-to-github-pages.md): the publishing settings, step by step.
* [How to Search a Compendium](search-a-compendium.md): using the index the build writes.
* [Data repository template](../../examples/data-repo/README.md): the files to copy into your own content repository.
* [Troubleshooting](../troubleshooting.md): known failures, causes, and fixes.
* [POSIX cron expressions on GitHub](https://docs.github.com/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule): the schedule syntax and its limits.
* [GitHub Actions limits](https://docs.github.com/actions/reference/actions-limits): the job time limit and the cache size on a hosted runner.
* [GitLab pipeline schedules](https://docs.gitlab.com/ci/pipelines/schedules/): setting the day and time of a scheduled pipeline.
* [GitLab job artifacts](https://docs.gitlab.com/ci/jobs/job_artifacts/): where the output folder goes and how to download it by address.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
