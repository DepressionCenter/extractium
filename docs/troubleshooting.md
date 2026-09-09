<!--
This file is part of Extractium™
docs/troubleshooting.md
Author(s): Gabriel Mongefranco
Created: 2026-09-08
Last Modified: 2026-09-09
Summary: Failures seen while building and publishing with Extractium:
what each looks like, what causes it, and how to fix it. Covers the run
scripts, the crawl, the scheduled build, publishing, and the search
clients.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Troubleshooting

[← Back to README](../README.md)


## Summary

This page lists failures that have actually happened, with the cause and the fix for each. Find the symptom that matches yours and work from there. If your problem is not here, the [running a build](usage.md) page explains what each exit code means, which usually narrows it down quickly.


## Installing

### `does not appear to be a Python project: neither 'setup.py' nor 'pyproject.toml' found`

**Cause.** `pip install -e .` was run in a folder that does not hold the project. The `.` means "the folder I am in", so an empty folder you just created has nothing to install. This happens when the clone step is skipped, or when a folder is made for the project and the clone is never run inside it.

**Fix.** Get the project first, then install from inside it:

```
git clone https://github.com/DepressionCenter/extractium.git
cd extractium
pip install -e ".[dev]"
```

If you already made an empty folder, delete it or clone into it with `git clone https://github.com/DepressionCenter/extractium.git .` — note the trailing dot.

### `extractium: command not found`, or `The term 'extractium' is not recognized`

**Cause.** The install worked, but the folder pip put the `extractium` command in is not on your `PATH`. It happens after a user install, which pip does automatically when it cannot write to the system Python folder. You will have seen `Defaulting to user installation because normal site-packages is not writeable` earlier in the output.

**Fix.** Run it as a module instead. This always works, whatever your `PATH` says, and it is the same program:

```
python -m extractium.cli build --config config.yaml
```

If you would rather have the short command, add the folder to your `PATH`. To find it:

```
python -c "import sysconfig, os; print(sysconfig.get_path('scripts', os.name + '_user'))"
```

On Windows that is usually `%APPDATA%\Python\Python3xx\Scripts`; on macOS and Linux, usually `~/.local/bin`.


## Running the build

### `run.sh` stops with `$'\r': command not found`

**Cause.** The script was saved with Windows line endings, so every line ends with a carriage return that the shell treats as part of the command.

**Fix.** The repository sets the line endings for `.sh` files, so a fresh clone is correct. If you have an older copy, or your editor rewrote the file, convert it back:

```
sed -i 's/\r$//' run.sh
```

### `In --require-hashes mode, all requirements must have their versions pinned`

**Cause.** Something is being installed that is not in `requirements-lock.txt`. This happens after adding a dependency to `pyproject.toml` without regenerating the lock file.

**Fix.** Regenerate it, keeping the licence header at the top:

```
uv pip compile pyproject.toml --universal --python-version 3.11 --generate-hashes -o requirements-lock.txt
```

### The first build seems to hang

**Cause.** It is downloading the embedding model, about 130 MB, and the progress of that download is not always visible.

**Fix.** Wait. Later builds reuse the model. If it fails, check that the machine can reach `huggingface.co`; some networks block it.

### The build ends with exit code 3 and writes nothing

**Cause.** The crawl found nothing worth indexing. Usually the seed URL is wrong, the include patterns exclude everything, or the site refused the crawler.

**Fix.** Run a small trial and read what it says:

```
python -m extractium.cli build --config config.yaml --max-pages 25 --out-dir trial
```

The progress lines name each page visited and each one skipped, with the reason.

### The build indexes one page and stops

**Cause.** The seed is a short link that redirects somewhere else. The crawl works out what it may visit from the address you wrote, so after the redirect every link on the page it received is out of scope.

**Fix.** The build now catches this and names the address to use:

```text
SKIP https://example.edu/kb -- it redirects to https://portal.example/TDClient/210/Org/Home/,
which is outside what this source may crawl.
```

Put that address in the settings file instead of the short link. If you want the short link kept anyway, add an `include_patterns` entry that covers where it lands.

### The build says it skipped pages an earlier source had already indexed

**Cause.** Two sources are covering the same ground. A website and a section of it, or a portal and a short link into one of its articles.

**Fix.** Often nothing: the page is indexed once, by whichever source reached it first, and the count is there so the overlap is visible rather than silent. If the count is large, the two sources are mostly duplicates of each other and one of them can go. If you want both, and want them separate, narrow one with `include_patterns` so their scopes do not meet.

### Every page is skipped with a message about `robots.txt`

**Cause.** The site's `robots.txt` could not be read. Extractium fails closed: if the rules are unknown, no page on that site is fetched. One real example is a portal that answers a request for `robots.txt` with 406 when the request accepts only HTML.

**Fix.** Open the site's `robots.txt` in a browser and see what it says. If it genuinely disallows crawling, respect that; the answer is to ask the site owner, not to switch the check off. Switch `respect_robots_txt` off only for a site your own group runs.


## Reading GitHub

### The build stops with `GitHub has no account ...`

**Cause.** The account or repository name does not exist on GitHub. Almost always a misspelling.

**Fix.** Check the spelling against the address in your browser. This one failure stops the build on purpose: if it quietly carried on, you would get an index that is empty for no visible reason.

### The summary says a repository was read at `tier 3 (documentation crawl)`

**Cause.** GitHub could not be read through its API for that repository, so the build fell back to crawling its documentation pages. Usually the request budget was spent; sometimes GitHub was unreachable.

**Fix.** Set `GITHUB_TOKEN` in the environment. Reading GitHub anonymously allows roughly sixty requests an hour, which one small organization can use up. A token raises that considerably and changes nothing else about what is indexed.

That line is not an error. It is telling you the index has that repository's documentation and not its code structure.

### The summary says the access token was refused

**Cause.** `GITHUB_TOKEN` is set to a value GitHub did not accept: expired, revoked, or copied incorrectly.

**Fix.** Replace the token. The build carried on reading GitHub anonymously, so you still have your documentation; you had the smaller request budget rather than the larger one. The message exists because a token that was silently ignored looks exactly like a token that worked.

### A repository you expected is missing from the index

**Cause.** One of the defaults left it out. Forks are skipped, so are empty repositories, repositories GitHub has disabled, and private ones.

**Fix.** Read the progress log: every repository left out is named there with its reason. Set `include_forks: true` if forks are what you wanted. Private repositories are never indexed, whatever your token can read.

### The summary says `Not read; add to github_owners to include: ...`

**Cause.** Something in the content linked to a GitHub account your configuration never named, and the build did not follow it.

**Fix.** Nothing, if that is what you wanted, which it usually is: the line is there so you can see the guardrail working. If you did want that account's pages, add its exact name to `github_owners`. That lets links into the account be followed; it does not index everything the account has published.


## The scheduled build

### The run ends with a notice saying there is nothing to build

**Cause.** The workflow found no `config.yaml`. In the Extractium repository itself, that is expected: it holds the tool, not an organization's content.

**Fix.** Copy [examples/data-repo/](../examples/data-repo/README.md) into your own repository and put your settings file there.

### The run fails at "Check out Extractium"

**Cause.** The `EXTRACTIUM_REF` value in the workflow names a branch, tag, or commit that does not exist.

**Fix.** Set it to a reference that does. `main` always exists; a release tag is better for a scheduled build.

### The rebuild takes as long as the first one

**Cause.** The crawl cache was not restored. The cache key includes a hash of the settings file, so any change to `config.yaml` starts a fresh cache on purpose.

**Fix.** Nothing, if you just changed the settings: the next run after that one will be fast again. If the settings have not changed, check the "Restore the crawl cache" step in the log; a cache entry expires after GitHub's own retention period of inactivity.


## Publishing

### The published address returns 404 after a successful run

**Cause.** Pages is not set to publish from Actions, so the deploy had nowhere to go.

**Fix.** Open **Settings → Pages** and set **Source** to **GitHub Actions**, then run the workflow again. [How to publish to GitHub Pages](how-to/publish-to-github-pages.md) has the details.

### The publishing job fails with a permissions error

**Cause.** The repository or organization restricts what a workflow may do, so the job cannot claim the Pages permissions it asks for.

**Fix.** In **Settings → Actions → General**, check that workflows are allowed to run and that the default permissions are not set to a level below what the workflow requests. The workflow asks for `contents: read` overall, and `pages: write` with `id-token: write` in the publishing job alone.

### `llms.txt` lists pages that should not be indexed

**Cause.** An include pattern is broader than intended, or a listing page is being indexed rather than only crawled.

**Fix.** Tighten `include_patterns`, add a `crawl_exclude_patterns` entry for pages that should not be fetched at all, or an `index_exclude_patterns` entry for pages worth following links from but not indexing. The [configuration reference](configuration.md) explains all three.


## Searching a compendium

### `container version 2 is not supported`

**Cause.** The file is a version 2 index, the format Field Station AI ships. The clients here read version 3 only.

**Fix.** Rebuild the index with Extractium, or use that project's own reader for its own file.

### `file was built with ... the vectors are not comparable`

**Cause.** The loader was told which embedding model will embed queries, and the file was built with a different one. Vectors from two models cannot be compared, and the results would be quietly wrong rather than obviously broken.

**Fix.** Use the model the file names in `embedding.model`, or rebuild the index with the model you intend to query with.

### Every search returns an empty list

**Cause.** Usually one of two things: the query is being embedded without the file's query prefix, or the embedder is not the model the file was built with. Both leave every score below the relevance cutoff.

**Fix.** Let the client add the prefix. `index.search(...)` in Python and `index.search(...)` in JavaScript both do it for you; only pass a pre-embedded vector to `searchWithVector` if you have added `index.queryPrefix` yourself. To see what the nearest sections were, search again with `no_threshold` set, which skips the relevance test.

### `vector bytes ... do not match ... children`

**Cause.** The file is truncated or was altered in transit. A common way to cause it is downloading the container with a tool that treats it as text.

**Fix.** Download it again as binary. In a browser, use `response.arrayBuffer()`, never `response.text()`.


## Conclusion

Most failures come down to three things: a pattern that is broader or narrower than you meant, a file that did not arrive intact, or a mismatch between the model that built an index and the model searching it. If you hit something that is not here and work out the cause, add it to this page in the same change.


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Running a Build](usage.md) — options, the summary, and what each exit code means.
* [Configuration Reference](configuration.md) — every setting, including the crawl patterns.
* [How to Run a Weekly Build](how-to/run-a-weekly-build.md) — the local and scheduled builds.
* [How to Publish to GitHub Pages](how-to/publish-to-github-pages.md) — publishing settings and checks.
* [How to Search a Compendium](how-to/search-a-compendium.md) — using the index from Python or JavaScript.
* [Container Format](container-format.md) — the reader checks the error messages come from.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
