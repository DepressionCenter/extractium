<!--
This file is part of Extractium™
docs/README.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-08
Summary: Index of the Extractium documentation folder; one line per page.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Documentation Index

[← Back to README](../README.md)


## Summary

This folder holds the written documentation for Extractium™. Each page below covers one topic. Start with Running a Build if you want to produce an index, the configuration reference if you are setting one up, or the specification if you want to know how the tool is put together.


## Pages

* [Architecture and Current State](architecture.md) — what is built, what is a placeholder,
  and the design decisions still open.
* [Configuration Reference](configuration.md) — every setting in `config.yaml`, its default, and how the URL patterns work.
* [Container Format](container-format.md) — the binary index file every client reads: byte layout, header fields, and the checklist for writing a reader.
* [Data Flow](data-flow.md) — what happens to content between the site it is read from and the files a build writes, and where private content is kept out.
* [Extractium™ Specification](extractium-spec.md) — the intended design: architecture, plugin kinds, data model, output formats, sources, and access tiers.
* [Implementation Plan](implementation-plan.md) — the phased order of work, about one week per phase, with a done-when rule for each.
* [Running a Build](usage.md) — the `extractium build` command, its options, what it writes, and what each exit code means.
* [How to Search a Compendium](how-to/search-a-compendium.md) — searching a built index from Python and from JavaScript, and what the search does behind the call.
* [How to Run a Weekly Build](how-to/run-a-weekly-build.md) — the one-command local build and the scheduled build on GitHub.
* [How to Publish to GitHub Pages](how-to/publish-to-github-pages.md) — turning Pages on, what is published, and what publishing means.
* [Compliance and Posture](compliance.md) — the controls that exist, the evidence for each, and the known gaps.
* [Troubleshooting](troubleshooting.md) — failures seen so far: symptom, cause, fix.
* [Page Template](doc-template.md) — the layout new pages in this folder follow.
* [Session Prompt Template](session-prompt-template.md) — the fixed opening to paste into any new coding session, phase or not; your request goes on the last line.

Pages are added as the tool grows. The specification lists what is planned but not yet built.


## Conclusion

Pick the page that matches your task. If you cannot find an answer here, the project README lists how to reach the team.


## Additional Resources

* [Extractium™ README](../README.md) — project overview, quick start, and contact details.
* [examples/config.example.yaml](../examples/config.example.yaml) — commented example configuration file.
* [EFDC Knowledge Base](https://michmed.org/efdc-kb) — the wider documentation site for this group's projects.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
