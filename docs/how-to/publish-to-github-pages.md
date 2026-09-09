<!--
This file is part of Extractium™
docs/how-to/publish-to-github-pages.md
Author(s): Gabriel Mongefranco
Created: 2026-09-08
Last Modified: 2026-09-08
Summary: How to publish a built index to GitHub Pages: turning Pages on,
what the workflow uploads, the permissions it asks for and why, how to
check the published files, and what to do before publishing anything that
might not be public.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Publish to GitHub Pages

[← Back to README](../../README.md)


## Summary

The files a build writes are static: no server, no database, nothing to run. That makes GitHub Pages a good home for them. This page shows you how to turn Pages on, what the workflow publishes, and how to check the result. It also says plainly what publishing means, because a published file is public to anyone who has the link.


## Before you start

You need a repository with the workflow in it. [examples/data-repo/](../../examples/data-repo/README.md) is the template to copy. You also need permission to change the repository's settings.


## Turn on Pages

1. Open the repository on GitHub.
2. Go to **Settings → Pages**.
3. Under **Build and deployment**, set **Source** to **GitHub Actions**.

That is the whole setup. Do not pick a branch: the workflow publishes the build output directly, so no branch holds the site.

Your address is `https://<owner>.github.io/<repository>/`, shown on the same settings page once the first run finishes.


## Run it once

Open the **Actions** tab, choose **Build compendium**, and press **Run workflow**. When the run finishes, the workflow shows the published address on the `publish` job.

Check three files:

| Address | What you should see |
|---|---|
| `.../llms.txt` | A list of the pages that were indexed, one line each, with the build time near the top. |
| `.../llms-full.txt` | The whole indexed text. |
| `.../kb-index.json` | A download rather than readable text. It is partly binary; that is expected. |

If `llms.txt` lists pages you did not mean to index, fix the patterns in `config.yaml` and run again. Publishing is the last step of the build, so what you see is exactly what the crawl found.


## What the workflow is allowed to do

The workflow asks for as little as it can, and the permissions are worth understanding before you approve them.

| Permission | Where | Why |
|---|---|---|
| `contents: read` | The whole workflow | To check out the repository. Nothing is written back to it. |
| `pages: write` | The publishing job only | To deploy the built site. |
| `id-token: write` | The publishing job only | GitHub's own Pages action proves the run's identity with a short-lived token instead of a stored secret. |

Publishing goes through GitHub's official actions (`actions/configure-pages`, `actions/upload-pages-artifact`, `actions/deploy-pages`) and no others. That is deliberate: a third-party publishing action would need a token of its own, and the token is the thing worth protecting.

Only one publish runs at a time, and a run that is already publishing is never cancelled. A half-uploaded site is worse than a late one.


## Publishing means public

A Pages site on a public repository is readable by anyone with the address, and search engines will find it. Nothing in Extractium makes a published file private.

Two habits keep that safe:

- **Read the page list before the first publish.** `llms.txt` is short and shows exactly what was indexed.
- **Leave local content out.** Content read from a local folder stays out of every output unless that output opts in, and the build's summary names any output that includes it. Do not turn that option on for a published file. The [compliance page](../compliance.md) says more.

If your content is not for the public, publish to a private host instead. The build output is a folder of ordinary files; anything that serves static files will do.


## Using a custom address

Pages supports a custom domain under **Settings → Pages → Custom domain**. Extractium does not care what the address is: the clients are given a URL and fetch it. If you move the site, update whatever points at the old address, including any assistant configuration that names the index file.


## Conclusion

Set the Pages source to GitHub Actions, run the workflow once, and check the three published files. After that every weekly run republishes on its own. To change what gets built, read the [configuration reference](../configuration.md); to use the published index, read [how to search a compendium](search-a-compendium.md).


## Additional Resources

* [Extractium™ README](../../README.md) — project overview and quick start.
* [How to Run a Weekly Build](run-a-weekly-build.md) — the scheduled build and the local one.
* [How to Search a Compendium](search-a-compendium.md) — reading the published index from Python or JavaScript.
* [Compliance](../compliance.md) — the security and privacy posture of a published build.
* [Data repository template](../../examples/data-repo/README.md) — the workflow and settings file to copy.
* [GitHub Pages documentation](https://docs.github.com/pages) — Pages settings, custom domains, and limits.
* [Publishing with GitHub Actions](https://docs.github.com/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site#publishing-with-a-custom-github-actions-workflow) — the source setting this workflow needs.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
