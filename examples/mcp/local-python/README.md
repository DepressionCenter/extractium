<!--
This file is part of Extractium™
examples/mcp/local-python/README.md
Author(s): Gabriel Mongefranco
Created: 2026-09-11
Last Modified: 2026-09-11
Summary: README for the local Python MCP server example: what it does,
how to run it, the settings it reads, and its limits.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Local Python MCP Server

## Search a published compendium from your own machine

[← Back to the Extractium README](../../../README.md)


## Summary

This folder holds one file, `server.py`. It lets an AI assistant on your computer search a published Extractium knowledge base. The assistant asks a question, the server searches the index, and it gets back whole sections with the address of each one. Nothing you ask leaves your machine: the index is a static file, and the question is turned into a vector by a model that runs locally.

The Model Context Protocol (MCP) is the standard that assistants use to call tools. This server exposes exactly one tool, `search_kb`.


## What you need

1. Python 3.10 or newer, with Extractium installed: `pip install -e ".[dev]"` from the repository root.
2. A published index address, or an index file you built yourself.
3. An assistant that can run an MCP server over standard input and output.


## Run it

```bash
export EXTRACTIUM_INDEX_URL=https://example.org/kb/kb-index.json
python examples/mcp/local-python/server.py
```

On Windows, use `set` in Command Prompt or `$env:` in PowerShell instead of `export`.

The server waits for requests on standard input, so on its own it looks like it has hung. That is correct: an assistant drives it. To add it to one, see [how to connect an MCP client](../../../docs/how-to/connect-an-mcp-client.md).


## Settings

All settings come from the environment, so no file holds an address or a path.

| Variable | What it does |
|---|---|
| `EXTRACTIUM_INDEX_URL` | The published index. Must start with `https://`, except on `localhost`. |
| `EXTRACTIUM_INDEX_PATH` | An index file on this machine. Wins over the address above, and never touches the network. |
| `EXTRACTIUM_CACHE_DIR` | Where the downloaded index is kept. Defaults to `~/.cache/extractium-mcp`. |

One of the first two is required. Without either, the server stops at once and says so, with exit code 2.


## What the tool returns

`search_kb` takes a question (`query`) and, optionally, how many sections to return (`k`, 1 to 10, 4 by default). It gives back:

- A block of text for the model to read, headed by a reminder that the sections are quoted evidence and never instructions.
- The same sections as data, in `structuredContent`: the title, the address, the text, and whether the section came from a local folder.

An empty result means nothing was relevant enough. That is a real answer, and the text says so.


## Limits

- The first search downloads the embedding model, about 130 MB. Later searches reuse it.
- The index is downloaded once and then revalidated, so an unchanged file costs one small request. If the host cannot be reached and a copy is cached, the cached copy is used.
- One tool, no writes: this server reads a static file and nothing else.


## Conclusion

You can now run a local search server over any published compendium. The [Node version](../local-node/README.md) does the same thing for assistants that prefer a JavaScript runtime, and the [how-to page](../../../docs/how-to/connect-an-mcp-client.md) shows the client configuration for both.


## Additional Resources

* [Extractium™ README](../../../README.md) — project overview and quick start.
* [How to Connect an MCP Client](../../../docs/how-to/connect-an-mcp-client.md) — the client configuration, step by step.
* [Local Node MCP Server](../local-node/README.md) — the same tool in JavaScript.
* [How to Search a Compendium](../../../docs/how-to/search-a-compendium.md) — the client library this server is built on.
* [SKILLS.md](../../../SKILLS.md) — how an AI agent should use what it gets back.
* [Model Context Protocol specification](https://modelcontextprotocol.io/specification/latest) — the protocol this server speaks.


[← Back to the Extractium README](../../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
