<!--
This file is part of Extractium™
docs/troubleshooting.md
Author(s): Gabriel Mongefranco
Created: 2026-09-08
Last Modified: 2026-09-12
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

### The build stops with `label is required`

**Cause.** A source in your settings file has no `label`. Every source must give itself the name a reader sees, because two sources of the same type cannot be told apart without one.

**Fix.** Add one line to the entry the message names. The message suggests a name for that type:

```yaml
sources:
  - type: web
    label: Peer-to-Peer Program
    seed_url: 'https://peer.example.org/'
```

Keep it under 60 characters. See [configuration reference](configuration.md).

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


## Reading a repository's code

### The log says `the parser set is not installed`

**Cause.** Code analysis is an optional install, and this machine does not have it.

**Fix.** `pip install "extractium[code]"`. Until then every source file is still indexed, with its path, language, length, and link — just not what is inside it.

### No definitions were found in your R files

**Cause.** No R grammar is published for Python. This is the one language in the wanted set with nothing to install, and it is a real gap rather than a setting you got wrong.

**Fix.** Install Universal Ctags, which reads R, and leave `ctags_fallback` on. Without it, R files are recorded by name and nothing more. The repository's own summary record says which of the two happened.

### The log says `the ctags on this machine is not Universal Ctags`

**Cause.** Several unrelated programs have been called `ctags`. The one on your path is one of the others, and reading its output as if it were Universal Ctags would put invented records into the index.

**Fix.** Install Universal Ctags, or ignore the line: unparsed files keep their outline either way. Set `ctags_fallback: false` if you would rather the build never launched another program at all.

### The index file is much larger than it used to be

**Cause.** Code analysis writes a record per source file and a record per definition in it, so a code-heavy repository multiplies the record count. Reading this project's own repository produces about 135 records without it and about 1,900 with it.

**Fix.** Set `include_code: false` on sources where the code is not what people search for. There is no partial setting: a repository's code is read or it is not.

### A definition you can see in a file is not in the index

**Cause.** One of a few deliberate limits. A definition nested more than three levels deep is skipped as a helper inside a helper; a name like `__author__` is skipped as header boilerplate; a file over about 1.5 million characters is not parsed at all; and a file whose language has no grammar keeps its outline only.

**Fix.** Read the progress log, which names every file left out and why, and the repository summary record, which says how many files each reader handled. If the file is one the parser met a syntax error in, its record says so, and the definitions on either side of the error are still there.


## Reading a document repository

### The build stops saying an address `answered a web page rather than data`

**Cause.** `api_url` is pointing at the site a reader opens rather than at the interface behind it. A repository's reader site answers with its own page for any address it does not recognize, so the build received markup where it expected data.

**Fix.** The two are different hosts, and the interface address is not guessable from the reader's. Open the reader site and look for its `dspaceServer` setting; that value is `api_url`. For Deep Blue it is `https://backend.production.deepblue-documents.lib.umich.edu/server/api`, while a reader opens `https://deepblue.lib.umich.edu`.

### The build stops with `the repository has no collection ...`

**Cause.** The collection identifier or handle does not exist in that repository. Usually a typo, or a collection from a different repository.

**Fix.** Open the collection in a browser and copy either the handle link it publishes or the address the browser shows; both are accepted. This failure stops the build on purpose. A search scope a repository does not recognize is answered with every deposit it holds, so a build that carried on would index the whole repository instead of your collection.

### A deposit is in the index but its file contents are not

**Cause.** The repository has no extracted text for that deposit's files. It happens with a poster deposited as an image, with a PDF that is really a picture of a page, and occasionally with a file whose extraction produced nothing at all.

**Fix.** Nothing to fix in the build, and nothing is hidden: the deposit is still indexed from its abstract and metadata, and the record says its file contents are not in the index. If the file does hold selectable text, the repository can be asked to extract it again; that is a message to the library rather than a change here.

### The progress log says an extracted text file is `over the ... byte ceiling`

**Cause.** The text file is larger than `max_file_bytes`, which is two megabytes by default.

**Fix.** Raise `max_file_bytes` if you want that deposit's contents. The next build reads it: a file left out for its size is not stored as read, so raising the ceiling takes effect without waiting for the deposit itself to change.

### A rebuild downloads every deposit's text again

**Cause.** The cache folder was deleted or moved, or `cache_dir` changed between builds. Stored text is kept under the deposit's identifier and the change stamp the repository reported for it, both of which live in that folder.

**Fix.** Keep `cache_dir` pointed at the same folder between builds. A collection nobody has touched then costs one request per hundred deposits and downloads nothing.


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


### The `okf` folder holds a page that no longer exists on the site

**Cause.** A build writes every page it read and deletes nothing, so a page that has since been taken down stays in the folder from the run that last saw it.

**Fix.** Delete the file, or delete the whole `okf` folder and run the build again. Check `okf/log.md` first: it names the date of the build that last wrote the folder.

### A page appears twice in the `okf` folder under two names

**Cause.** The same page was reached at two addresses, such as one with a trailing slash and one without. Each address is its own page, so each gets its own file.

**Fix.** Look at the `resource` line at the top of each file to see which addresses were read. Add a `crawl_exclude_patterns` entry for the form you do not want.


## Searching a compendium

### `container version 2 is not supported`

**Cause.** The file is a version 2 index, the format Field Station AI ships. The clients here read version 4 only.

**Fix.** Rebuild the index with Extractium, or use that project's own reader for its own file.

### `container version 3 is not supported`

**Cause.** The index was built by an earlier Extractium, before every section carried the name of the source it came from. A version 3 file has no `source_label`, so a client that groups results by source cannot read it correctly.

**Fix.** Rebuild the index. Nothing else is needed: the settings file only has to gain a `label` on each source, which the build will ask for.

### `file was built with ... the vectors are not comparable`

**Cause.** The loader was told which embedding model will embed queries, and the file was built with a different one. Vectors from two models cannot be compared, and the results would be quietly wrong rather than obviously broken.

**Fix.** Use the model the file names in `embedding.model`, or rebuild the index with the model you intend to query with.

### Every search returns an empty list

**Cause.** Usually one of two things: the query is being embedded without the file's query prefix, or the embedder is not the model the file was built with. Both leave every score below the relevance cutoff.

**Fix.** Let the client add the prefix. `index.search(...)` in Python and `index.search(...)` in JavaScript both do it for you; only pass a pre-embedded vector to `searchWithVector` if you have added `index.queryPrefix` yourself. To see what the nearest sections were, search again with `no_threshold` set, which skips the relevance test.

### `vector bytes ... do not match ... children`

**Cause.** The file is truncated or was altered in transit. A common way to cause it is downloading the container with a tool that treats it as text.

**Fix.** Download it again as binary. In a browser, use `response.arrayBuffer()`, never `response.text()`.


## A local search server

### The server prints one line and then seems to hang

**Cause.** That is what it is supposed to do. The server waits for a client to write requests to its standard input, and prints nothing else until one does.

**Fix.** Nothing. Drive it from an assistant, or send it a request yourself as [the how-to page](how-to/connect-an-mcp-client.md) shows.

### The server exits at once with code 2

**Cause.** Neither `EXTRACTIUM_INDEX_URL` nor `EXTRACTIUM_INDEX_PATH` is set, so the server does not know which index to search. A client that starts the server with its own environment often does not pass yours through.

**Fix.** Set one of them in the client's own configuration, in the `env` block beside the command.

### `EXTRACTIUM_INDEX_URL must be an https:// address`

**Cause.** The address is plain HTTP somewhere other than this machine, or is not an address at all. An index fetched over an open connection can be replaced in transit, and the assistant would read the replacement as your organization's documentation.

**Fix.** Publish over HTTPS and use that address. While testing a build you are serving yourself, `http://localhost:...` is accepted.

### The assistant lists no tools

**Cause.** The client could not start the command. A relative path is the usual reason: the client starts the server from a folder you did not choose.

**Fix.** Use a full path to `server.py` or `server.js` in the client configuration, and check the same command runs in a terminal.

### The first search takes minutes

**Cause.** The embedding model, about 130 MB, is downloaded the first time a search runs. The index may be downloading too.

**Fix.** Wait once. Later searches reuse both. Run one search from a terminal before adding the server to an assistant, so the wait does not look like a failure.

### The answer is older than the published index

**Cause.** The host could not be reached, so the server used its cached copy rather than failing. The reason is on its error stream, which most clients show as the server's log.

**Fix.** Check the address answers, then restart the server. To start from nothing, delete the cache folder: `~/.cache/extractium-mcp`, or whatever `EXTRACTIUM_CACHE_DIR` names.

### `npm install` reports high-severity advisories

**Cause.** You are installing without the lockfile, or with an older copy of it. The embedding package reaches `sharp` and `adm-zip` through version ranges that stop short of the releases that fix them.

**Fix.** Install from this folder, so npm reads both `package.json` and `package-lock.json`. The `overrides` block in `package.json` lifts those two packages to patched versions, and `npm audit` then reports nothing. If you see advisories anyway, check that you ran `npm install` inside `examples/mcp/local-node` rather than copying `server.js` elsewhere and installing by hand.


## A hosted search server

### `wrangler dev` stops with `Incorrect type for map entry ... is not of type 'function or ExportedHandler'`

**Cause.** The Workers runtime accepts only handlers as the entry module's exports, and `worker.js` gained a named export that is not one: a constant, an object, or a re-export from another module. The first version of the example failed exactly this way.

**Fix.** Keep `worker.js` to its default export. Put anything a test needs to import in `d1-search.js`, which is where the search already lives.

### The Worker logs `which Workers AI does not serve; using keyword search alone`

**Cause.** The `AI` binding is on, but the `meta` table says the index was built with a model other than `bge-small-en-v1.5`, so Workers AI's vectors would not be comparable with the stored ones.

**Fix.** Nothing is broken: the Worker answers by keywords. To get hybrid search, rebuild with the default model, or leave the binding off.

### The val logs `could not be kept in the blob store`

**Cause.** The container is larger than the plan's blob quota, 10 MB on the free plan. The val still answers, from the copy in memory, but downloads the file again on every cold start.

**Fix.** Move to a plan with a larger quota, publish a smaller index, or accept the download; it costs a few seconds on a cold start and nothing while the val stays warm.

### The endpoint answers `401` to every request

**Cause.** `EXTRACTIUM_BEARER_TOKEN` is set on the platform and the client is not sending it, or is sending a different one.

**Fix.** Add an `Authorization: Bearer <token>` header in the client configuration, as [the how-to page](how-to/deploy-a-remote-mcp-server.md) shows, or unset the token if the endpoint is meant to be open.

### `node --test examples/mcp/cloudflare` fails with `Cannot find module 'node:sqlite'`

**Cause.** The Cloudflare tests stand in for D1 with Node's built-in SQLite module, which arrived in Node 22.5.

**Fix.** Run the tests on Node 22.5 or newer. The Worker itself does not need it; only its tests do.


## A YouTube source

### `no source named 'youtube'`

**Cause.** An older Extractium. The source arrived in phase 13; before that the settings file accepted the type and no code answered to it.

**Fix.** Update Extractium, or pin `EXTRACTIUM_REF` to a version that has it.

### The build stops saying YouTube refused the request

**Cause.** You are building somewhere YouTube blocks, which means almost any cloud runner, including GitHub Actions. YouTube refuses caption requests from cloud-provider addresses. This is not a setting you can change and not a key you can buy.

**Fix.** Build on your own machine, then commit the cache folder so the scheduled run reads the transcripts instead of asking for them. [The cache README](../examples/data-repo/kb-cache/README.md) says what to commit. The message appears only when nothing is stored for that video yet.

### `fetching captions needs youtube-transcript-api`

**Cause.** A transcript has to be fetched and the caption package is not installed.

**Fix.** `pip install "extractium[youtube]"`. You need this on the machine that fetches transcripts, not on one that only reads stored ones.

### `listing a channel or playlist needs a YouTube Data API key`

**Cause.** The source names a `channel_id` or `playlist_ids`, and `YOUTUBE_API_KEY` is not set. Only the Data API can say what a channel holds.

**Fix.** Set the variable, or name the videos individually under `video_ids`, which needs no key. If the listing was read before and stored, the build uses the stored copy and says so instead of stopping.

### `is not a handle` or `does not look like a channel`

**Cause.** The value in `channel_id` is not a channel. A handle, a channel address, a custom address, and the id itself are all accepted, so this usually means an address for something else: a search results page, a watch page, or a different site.

**Fix.** Open the channel in a browser and copy the address from the bar. `https://www.youtube.com/@ExampleChannel` and `.../@ExampleChannel/videos` both work.

### The build says YouTube links were not crawled

**Cause.** Not an error. A crawl found links to YouTube and left them alone, because a video's words are in its caption track and a crawled YouTube page gives a title and nothing else.

**Fix.** Nothing, if you did not want those videos. To index them, add a `youtube` source naming the channel, or put the YouTube address in a `web` source's `seed_url` and the build will read captions from it.

### The build says a listing stopped at its first page

**Cause.** Not an error. YouTube's `robots.txt` disallows `/youtubei/`, the address a page calls for its next batch, and this build honors `robots.txt`. So a listing longer than one page gives its newest 100 videos and stops.

**Fix.** Set `YOUTUBE_API_KEY` to read the whole listing through the documented API. Failing that, `respect_robots_txt: false` pages the way the page itself does, for content you own or have permission to read. See the [configuration reference](configuration.md).

### A video in one of the channel's playlists was left out

**Cause.** Another channel published it. A playlist holds whatever its owner chose, which often includes other people's videos, and indexing those would put another organization's words in your knowledge base under your name. The build counts what it left out.

**Fix.** Nothing, if that is what you wanted. To index them anyway, set `only_channel_videos: false`. To name another organization's channel as one you do index, add it as its own `youtube` source.

### The build says YouTube refused this machine after N videos

**Cause.** Rate limiting. YouTube starts refusing a machine that has asked for a lot of transcripts in a short time. The build keeps what it read and stops asking, rather than throwing the work away.

**Fix.** Wait, then build again: the transcripts already stored are reused and it carries on from there. Repeat until the channel is covered. To make it less likely, raise the source's `delay_seconds` above the one-second floor. Each run is cheaper than the last, because what is stored is never fetched twice.

### YouTube answered 403 for a channel page

**Cause.** A filter refused this machine rather than saying the page is missing. Cloud runners see this most.

**Fix.** Set an API key, which uses a different host altogether. Or set `respect_robots_txt: false`, which allows one retry with a browser identity, the same fallback a challenged web page gets. If neither is possible, build on a machine YouTube answers and commit the cache.

### The Data API answered 403

**Cause.** Usually one of three things: the key is expired, the YouTube Data API v3 is not enabled for the key's project, or the project is over its daily quota.

**Fix.** Check the key in the Google Cloud console. Quota resets daily; a build that only needs stored transcripts is unaffected by it.

### A video is in the channel but not in the knowledge base

**Cause.** Most often it has no captions, or none in the languages asked for. The build counts these and says how many were skipped.

**Fix.** Add the language to `languages` if the captions exist in another one, which is the usual cause: `languages: ["en", "es"]` covers a channel that publishes in both. A video with captions genuinely turned off cannot be indexed, and there is no fallback: reading speech from the audio is [not planned](extractium-spec.md), because sampling a real channel found captions on every video.

### A corrected transcript is not picked up

**Cause.** A stored transcript has no expiry date, by design. A build uses it because it exists, since checking it against YouTube is what a cloud runner cannot do.

**Fix.** Delete that video's file from `<cache_dir>/youtube/videos/` and build again on a machine YouTube answers. To pick up videos newly added to a playlist, delete the playlist's file from `<cache_dir>/youtube/listings/`.

### The cache folder is not in the repository

**Cause.** `cache_dir` is at its default, `.kb_cache`, and that folder is ignored by most projects, this one included.

**Fix.** Set `cache_dir` to a visible folder such as `kb-cache` and commit it. A YouTube build is the one case where the cache is content rather than a convenience.


## Conclusion

Most failures come down to three things: a pattern that is broader or narrower than you meant, a file that did not arrive intact, or a mismatch between the model that built an index and the model searching it. If you hit something that is not here and work out the cause, add it to this page in the same change.


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Running a Build](usage.md) — options, the summary, and what each exit code means.
* [Configuration Reference](configuration.md) — every setting, including the crawl patterns.
* [How to Run a Weekly Build](how-to/run-a-weekly-build.md) — the local and scheduled builds.
* [How to Publish to GitHub Pages](how-to/publish-to-github-pages.md) — publishing settings and checks.
* [How to Search a Compendium](how-to/search-a-compendium.md) — using the index from Python or JavaScript.
* [How to Connect an MCP Client](how-to/connect-an-mcp-client.md) — running the search as a tool an assistant calls.
* [Container Format](container-format.md) — the reader checks the error messages come from.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
