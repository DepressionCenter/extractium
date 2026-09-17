<!--
This file is part of Extractium™
docs/how-to/deploy.md
Author(s): Gabriel Mongefranco
Created: 2026-09-12
Last Modified: 2026-09-17
Summary: The deployment choices side by side: build on your own computer
and publish nowhere, build on GitHub and publish to Pages, publish the
output folder to any static host, and keep a separate data repository.
For each, what it needs, what it costs, and what it cannot reach, then
every way the published outputs can be used.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Deploy

[← Back to README](../../README.md)


## Summary

This page helps you choose where a build runs and where its outputs live. There are four arrangements, and most organizations end up using two of them. For each one, the page says what you need, what it costs, and what it cannot reach. It then lists every way the published files can be used, so you can see which arrangement supports the use you have in mind.


## The four arrangements

| Arrangement | Builds where | Publishes to | Best for |
|---|---|---|---|
| Local, private | Your own computer | Nowhere. The output folder stays on disk. | A trial run, a folder of local files, or an index only your own scripts read. |
| GitHub, weekly | A GitHub Actions runner | GitHub Pages | Public documentation that should stay current without anyone remembering to rebuild. This is the usual choice. |
| Any static host | Your own computer or a runner | A web server, a storage bucket, or a shared drive that serves files | An organization that already has hosting, or one that cannot use Pages. |
| Data repository | Either of the above | Either of the above | Any of the others, once your settings and outputs deserve a home apart from the tool. |

The data repository is not a fourth place to build. It is the shape the other three take once you separate your content from the tool, and it is the recommended shape for anything that runs on a schedule.


## Local, private

Build on your own computer and publish nowhere.

- What you need: Python 3.10 or newer and a clone of the repository. See [how to install](install.md).
- What it costs: nothing. The first build downloads the embedding model, about 130 MB, and later builds reuse it.
- What it can reach: everything. A local folder, YouTube captions, a site behind bot protection, and every public source. This is the only arrangement that can read a `local` source or fetch a caption, so it is also the first step of any build that needs either.
- What it cannot do: serve the index to anyone else. A browser page that searches the index needs the file on a web server. An index that stays on disk is searched by scripts, by the Python client, or by a local search server pointed at a file served from the loopback address.

The commands:

```
./run.sh --max-pages 25 --out-dir trial     # run.bat on Windows
./run.sh                                     # the full build
```

Keep `.kb_cache` between runs so a rebuild downloads only what changed. Read the two reports from the check for protected health information before you let any output leave your computer.


## GitHub, weekly

Build on a GitHub Actions runner every Monday morning and publish the output folder to GitHub Pages.

- What you need: a GitHub repository holding your settings file and a copy of the workflow. The [data repository template](../../examples/data-repo/README.md) is that repository, ready to copy. Pages must be turned on with GitHub Actions as its source. [How to publish to GitHub Pages](publish-to-github-pages.md) walks through it.
- What it costs: nothing on a public repository. GitHub's free plan includes the runner minutes a weekly build uses and the Pages hosting. A private repository spends its monthly minutes allowance instead.
- Secrets: none are required. The workflow asks for `contents: read` on the repository and, for the publishing job alone, permission to write to Pages. It passes no `GITHUB_TOKEN` to the build, so a GitHub source reads at the public request limit, which is enough for a few repositories. A build that needs more adds a token as a repository secret and passes it to the build step as an environment variable. The tool never reads one from a file.
- The crawl cache: the runner restores `.kb_cache` from the previous run, keyed on your settings file, so a weekly rebuild fetches only what changed. Change the settings file and the next run starts from an empty cache.
- What it cannot reach: a folder on your computer, and YouTube captions, which YouTube refuses to serve to cloud-provider addresses. For video, build once locally and commit the store under `cache_dir`. The runner then reads it without asking YouTube for anything. See [how to run a weekly build](run-a-weekly-build.md) for that sequence.
- What publishing means: everything in the output folder becomes readable by anyone with the address. There is no unlisted tier. Local content never reaches an output unless that output opted in, and a scheduled build cannot read local content at all, so this arrangement publishes public sources only.


## Any static host

Build wherever you like and copy the output folder to a web server, a storage bucket, or a shared drive that serves files over HTTPS.

- What you need: a host that serves static files and that you can copy to. The output folder needs no server-side code, no database, and no special headers, with one exception: the index file must be served with its bytes untouched. A host that compresses `.json` files on the fly is fine. One that reformats them is not.
- What it costs: whatever the host charges. The files are small: a few megabytes for the index of a few hundred pages.
- What it can reach: whatever the computer that builds can reach. A local build copied to a host can include YouTube captions and a site behind bot protection. A build on a runner cannot.
- How to copy: the output folder is ordinary files, so any copy tool works. A build on GitHub can publish here instead of Pages by replacing the two Pages steps in the workflow with an upload to your host, using whatever credential that host needs, stored as a repository secret.
- What to check: open `llms.txt` at its published address and confirm the build time near the top is the one you just made. Then open the index address in the Python or JavaScript client. [How to search a compendium](search-a-compendium.md) shows how.


## Data repository

Keep your settings file, your committed caption store, and the workflow in a small repository of your own, apart from the tool.

- What you need: a copy of [examples/data-repo/](../../examples/data-repo/README.md) in a new repository. Two lines change: the seed URL and the name.
- Why it is separate: the tool repository changes when the tool does, and your content repository changes when your documentation does. Keeping them apart means you can update either one without disturbing the other, the tool version you build with is a line you can pin, and your repository stays small because the published files come from the build artifact rather than from a commit.
- What it costs: one more repository.
- What lives there: `config.yaml`, the workflow, and, if you index video, `kb-cache/youtube/`. Nothing else. The output folder is not committed. It is published from the build.


## How the outputs can be used

Every arrangement above produces the same files, and the same consumers read them. What differs is whether the files are on a web server, which some consumers need.

| Consumer | Reads | Needs the files served over HTTPS |
|---|---|---|
| A script, in Python or JavaScript | The index, through one of the two clients | No. A local path works in Python, and a file served from the loopback address works for both. |
| A browser search page | The index, through the JavaScript client | Yes. The page and the index are served together, and the page embeds the query in the browser. |
| An AI assistant on your own computer | The index, through a local MCP server | Yes, except from the loopback address. The server downloads the index once and caches it. |
| An AI assistant anywhere | A hosted MCP server on Val Town or Cloudflare | Yes. The hosted server reads the published index or a database loaded from the SQLite output. |
| A platform that browses but cannot call tools | `llms.txt` and the index files it links to, from a system prompt | Yes. The prompt names the address. |
| A person | The Open Knowledge Format folder, in any Markdown viewer | No. |
| A SQL consumer | The SQLite output | No. |

The pages for each consumer:

- [How to search a compendium](search-a-compendium.md) for a script or a browser page.
- [How to connect an MCP client](connect-an-mcp-client.md) for an assistant on your own computer.
- [How to deploy a remote MCP server](deploy-a-remote-mcp-server.md) for an assistant anywhere.
- [Hosted assistant prompts](../../examples/wrappers/README.md) for a platform that browses.
- [Using a published compendium](../using-a-compendium.md) for what any AI agent must and must not do with what it reads.


## Choosing

Start local and private, with a page limit, until the page lists under `llms/` look right. Then, for public documentation, move the settings file into a data repository and let GitHub build it weekly. Add a local build to that only when a source needs it: a local folder, or a channel's captions. Use another static host only when Pages is not available to you.


## Conclusion

You can now pick the arrangement that matches your sources and your consumers, and you know what each one needs, costs, and cannot reach. Next, read [how to run a weekly build](run-a-weekly-build.md) for the two build commands in detail, or [how to publish to GitHub Pages](publish-to-github-pages.md) to turn publishing on.


## Additional Resources

* [Extractium™ README](../../README.md): project overview and quick start.
* [How to Install](install.md): the two ways to install, and the optional extras.
* [How to Run a Weekly Build](run-a-weekly-build.md): the local script and the scheduled workflow, step by step.
* [How to Publish to GitHub Pages](publish-to-github-pages.md): turning Pages on and what the workflow is allowed to do.
* [How to Search a Compendium](search-a-compendium.md): the two clients.
* [How to Connect an MCP Client](connect-an-mcp-client.md): the two local search servers.
* [How to Deploy a Remote MCP Server](deploy-a-remote-mcp-server.md): the two hosted examples.
* [Hosted Assistant Prompts](../../examples/wrappers/README.md): the two system prompts.
* [Using a Published Compendium](../using-a-compendium.md): the rules for an AI agent reading the outputs.
* [Data repository template](../../examples/data-repo/README.md): the repository to copy.
* [Compliance](../compliance.md): what publishing means for private content, and the workflow's permissions.
* [GitHub Actions billing](https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions): the minutes allowance a private repository spends.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
