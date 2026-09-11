<!--
This file is part of Extractium™
examples/data-repo/kb-cache/README.md
Author(s): Gabriel Mongefranco
Created: 2026-09-11
Last Modified: 2026-09-11
Summary: Explains why this data repository commits its YouTube cache:
YouTube refuses caption requests from cloud runners, so transcripts are
fetched on a person's machine and committed for the scheduled build to
reuse.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Example Org Knowledge Base

## The committed cache

[← Back to the Extractium README](../../../README.md)


## Summary

This folder holds content the weekly build cannot fetch for itself. Almost every cache a build writes is a convenience you can safely delete. This one is not: it is the only copy of the video captions your knowledge base is built from. Commit it, and never delete it without reading this page first.

If your knowledge base indexes no video, this folder does nothing and you can remove it.


## Why it is here and not ignored

YouTube refuses caption requests that come from cloud-provider addresses. GitHub Actions runs on a cloud provider. So the scheduled build cannot read a transcript, however well it is configured.

The way around it has three steps:

1. You build once on your own machine, where YouTube answers.
2. The transcripts land here, one file per video.
3. You commit this folder, and every later build reads it instead of asking YouTube.

That is why `config.yaml` sets `cache_dir: kb-cache` instead of leaving the default. The default, `.kb_cache`, is a hidden folder that most projects ignore, which is the right behavior for a cache you can rebuild and the wrong behavior for this one.


## What is in it

| Path | What it holds |
|---|---|
| `youtube/videos/<video id>.json` | One video's title, publication date, caption language, and timed caption lines. |
| `youtube/listings/<playlist id>.json` | The videos a playlist held the last time it could be listed. |

The two files here now are synthetic examples, so you can see the shape before you have any of your own. Delete them when you add real ones.

A stored transcript has no expiry date. A build uses it because it exists, not because it was checked against YouTube, because checking is the thing a cloud runner cannot do.


## Refreshing a transcript

Captions rarely change, but they can: somebody corrects an automatic transcript, or replaces a video.

1. Delete that video's file from `youtube/videos/`.
2. Build on your own machine, so the transcript is fetched again.
3. Commit the new file.

To pick up videos added to a playlist, delete the playlist's file from `youtube/listings/` and do the same.


## What must never go in here

This folder is published to a public repository along with everything else. Captions of a public video are already public, so they are safe to commit.

Nothing else about YouTube belongs here. In particular, your Data API key is a credential: it lives in the environment, or in a repository secret, and never in a file. No file this build writes holds one.


## Conclusion

Commit this folder, refresh a file when a video changes, and keep credentials out of it. For the settings that fill it, read the [configuration reference](../../../docs/configuration.md); for what to do when a build says it cannot read captions, read [troubleshooting](../../../docs/troubleshooting.md).


## Additional Resources

* [Extractium™ README](../../../README.md) — project overview and quick start.
* [Data repository template](../README.md) — the repository this folder belongs to.
* [Configuration reference](../../../docs/configuration.md) — the `youtube` source and the `cache_dir` setting.
* [How to run a weekly build](../../../docs/how-to/run-a-weekly-build.md) — the local build that fills this folder, and the scheduled one that reads it.
* [Troubleshooting](../../../docs/troubleshooting.md) — what a blocked caption request looks like and what to do.


[← Back to the Extractium README](../../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
