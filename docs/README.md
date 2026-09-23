<!--
This file is part of Extractium™
docs/README.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-22
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

This folder holds the detailed documentation for Extractium™. The pages are grouped by what you want to do. If you have not run the tool yet, start with the installation guide, then the crawling guide. If you want to know how the tool works inside, or you plan to write a plug-in, start with the architecture page. An overview and user guide is also available in the [EFDC Knowledge Base](https://michmed.org/efdc-kb).


## Getting started

* [How to Install](how-to/install.md): the supported Python versions, the two ways to install, the optional extras, and how to check that the install worked.
* [How to Crawl a Site](how-to/crawl-a-site.md): choosing a source type for each kind of content, running a small trial, tuning the URL patterns, and reading what a build reports.
* [Running a Build](usage.md): the `extractium build` command, its options, the files it writes, and what each exit code means.
* [Configuration Reference](configuration.md): every setting in `config.yaml`, its default, and how the URL patterns work.
* [Troubleshooting](troubleshooting.md): known failures, with the cause and the fix for each.


## Publishing and using a compendium

* [How to Deploy](how-to/deploy.md): where a build can run and where its outputs can live, with what each choice needs and costs.
* [How to Run a Weekly Build](how-to/run-a-weekly-build.md): the one-command build on your own computer or a server, put on a timer, and the scheduled builds on a GitLab runner or on GitHub.
* [How to Publish to GitHub Pages](how-to/publish-to-github-pages.md): turning Pages on, what gets published, and what publishing means.
* [How to Search a Compendium](how-to/search-a-compendium.md): searching a built index from Python or JavaScript.
* [How to Connect an MCP Client](how-to/connect-an-mcp-client.md): letting an AI assistant on your own computer search a published index.
* [How to Deploy a Remote MCP Server](how-to/deploy-a-remote-mcp-server.md): hosting that search on Val Town or Cloudflare so an assistant anywhere can use it.
* [Using a Published Compendium](using-a-compendium.md): how an AI agent should use the published files, cite an answer, and treat retrieved text.


## How the tool works

* [Architecture](architecture.md): the modules, what each one does, and the design decisions behind them.
* [Plug-in Architecture](plugin-architecture.md): the three plug-in kinds, how the tool finds them, and a working example of each.
* [Data Flow](data-flow.md): what happens to content between the site it came from and the files a build writes, and where private content is kept out.
* [Container Format](container-format.md): the search index files every client reads, byte by byte, with a checklist for writing your own reader.
* [The SQLite Database](sqlite-database.md): a diagram of the tables, every column, and sample queries.
* [Compliance and Posture](compliance.md): the security, privacy, and accessibility controls in place, the evidence for each, the dependency licenses, and the known gaps.
* [Specification](extractium-spec.md): the design of the tool: plug-in protocols, data model, output formats, sources, and access tiers.


## Design notes

* [GitHub Repository Indexing](github-repository-indexing.md): how a GitHub organization, user, or repository is read, and how a repository's code is analyzed without copying it.
* [Indexing a DSpace Repository](dspace-repository-indexing.md): how scholarly deposits in a repository such as Deep Blue are read through its own interface.
* [Reading a Site Behind Bot Protection](bot-protection-transport.md): why some sites refuse the crawler, what was measured, and how the build reads them while still identifying itself.


## For maintainers

These pages are about working on the repository rather than using the tool.

* [Branding and Media Pack](branding.md): logos, colors, image files, and accessibility guidance.
* [Implementation Plan](implementation-plan.md): the order in which the tool was built, kept as a project record.
* [Page Template](doc-template.md): the layout new pages in this folder follow.
* [Session Prompt Template](session-prompt-template.md): the fixed opening to paste into a new coding session.
* [Skill Authoring Examples](skill-examples.md): starter recipes for writing a small agent skill under `skills/`.


## Conclusion

Pick the page that matches your task. If you cannot find an answer here, the project README lists how to reach the team.


## Additional Resources

* [Extractium™ README](../README.md): project overview, quick start, and contact details.
* [examples/config.example.yaml](../examples/config.example.yaml): a commented example settings file to copy.
* [examples/config.efdc.yaml](../examples/config.efdc.yaml): a complete settings file that uses every source type.
* [EFDC Knowledge Base](https://michmed.org/efdc-kb): the overview and user guide for this and other EFDC projects.
* [Skills index](../SKILLS.md): the agent skills this repository carries.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
