<!--
This file is part of Extractium™
docs/how-to/connect-an-mcp-client.md
Author(s): Gabriel Mongefranco
Created: 2026-09-11
Last Modified: 2026-09-11
Summary: How to let an AI assistant on your own machine search a
published compendium: which of the two local servers to pick, how to
configure a client, how to check it works without a client, and what the
assistant may and may not do with what comes back.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Connect an MCP Client

[← Back to README](../../README.md)


## Summary

The Model Context Protocol (MCP) is the standard that AI assistants use to call tools. This page shows you how to give an assistant on your own machine one tool: search of a published Extractium knowledge base. You need a published index address, a terminal, and a few minutes. Nothing you ask leaves your computer.

Two servers ship with Extractium, one in Python and one in JavaScript. They expose the same tool and return the same answers, so pick whichever runtime you already have.


## Which server to use

| Pick | When |
|---|---|
| [Python](../../examples/mcp/local-python/README.md) | You already installed Extractium. It embeds questions with the package Extractium installs, so there is nothing else to add. |
| [Node](../../examples/mcp/local-node/README.md) | Your assistant runs JavaScript tools, or you have Node and no Python. It installs one package, `@huggingface/transformers`, and everything that package needs. |

Both read the same index file, so you can change your mind later.


## Step 1: Get the index address

You need the address of a built compendium, usually `kb-index.json` in a published folder. If you built one yourself, the file is in `dist/` and you can point at it directly instead.

Check the address answers before you go further:

```bash
curl -I https://example.org/kb/kb-index.json
```

A `200` means you are ready. A `404` means the path is wrong. The address must start with `https://`, unless it is on `localhost`; both servers refuse anything else, because an index fetched over an open connection can be swapped in transit for whatever someone else wants your assistant to read.


## Step 2: Start the server once by hand

This proves the server runs before an assistant depends on it.

Python:

```bash
EXTRACTIUM_INDEX_URL=https://example.org/kb/kb-index.json python examples/mcp/local-python/server.py
```

Node:

```bash
cd examples/mcp/local-node && npm install
EXTRACTIUM_INDEX_URL=https://example.org/kb/kb-index.json node server.js
```

On Windows, set the variable first (`set NAME=value` in Command Prompt, `$env:NAME = 'value'` in PowerShell), then run the command without the prefix.

The server prints one line to the error stream and then waits. It looks stuck. It is not: it is waiting for a client to write a request to its standard input. Press Ctrl+C to stop it.


## Step 3: Ask it something without a client

You can drive the server yourself. Send it two messages, one per line:

```bash
printf '%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_kb","arguments":{"query":"how do I request a data extract"}}}' \
  | EXTRACTIUM_INDEX_URL=https://example.org/kb/kb-index.json python examples/mcp/local-python/server.py
```

You get two lines back. The first lists the one tool, `search_kb`. The second holds the sections it found. The first search is slow, because it downloads the embedding model, about 130 MB; later ones are quick.


## Step 4: Add it to your assistant

Most clients keep a JSON file listing the servers they may start. The shape below is the common one; your client's own documentation says where the file lives and whether it calls the section `mcpServers` or something else.

Python:

```json
{
  "mcpServers": {
    "extractium": {
      "command": "python",
      "args": ["C:/Path/To/extractium/examples/mcp/local-python/server.py"],
      "env": { "EXTRACTIUM_INDEX_URL": "https://example.org/kb/kb-index.json" }
    }
  }
}
```

Node:

```json
{
  "mcpServers": {
    "extractium": {
      "command": "node",
      "args": ["C:/Path/To/extractium/examples/mcp/local-node/server.js"],
      "env": { "EXTRACTIUM_INDEX_URL": "https://example.org/kb/kb-index.json" }
    }
  }
}
```

Use full paths, not relative ones: the client starts the server from a folder you did not choose. Restart the client, and the tool appears in its tool list.


## Step 5: Use it

Ask the assistant a question the knowledge base covers. It calls `search_kb`, gets back whole sections, and should cite the address of each section it used.

The tool takes two arguments:

| Argument | What it is |
|---|---|
| `query` | The question, in plain words. No search operators. Up to 1,000 characters. |
| `k` | How many sections to return, 1 to 10. Four by default. |

An empty result means nothing in the index was relevant enough. That is a real answer. An assistant should say so rather than offer the closest miss.


## What the assistant must not do with the answer

Every section is text somebody else wrote on a web page. A page can hold words aimed at whatever reads it next: "ignore your previous instructions", "the administrator approved this", "run this command". The server puts a line at the top of every answer saying the sections are quoted evidence, not instructions, and an assistant must treat them that way.

If a compendium includes content read from a local folder, which only happens when an operator turns that on, the server marks the answer confidential. Do not paste that text into another service. [Using a published compendium](../using-a-compendium.md) states both rules in full.


## If it does not work

| What you see | What it means |
|---|---|
| The server exits at once, code 2 | Neither `EXTRACTIUM_INDEX_URL` nor `EXTRACTIUM_INDEX_PATH` is set. |
| "must be an https:// address" | The address is plain HTTP, or not an address at all. Use HTTPS, or `localhost` for a build you are serving yourself. |
| "The index cannot be read" | The file at that address is not a compendium, or is a version this client does not read. Check it with `curl` and see the [container format](../container-format.md). |
| "The index or the embedding model could not be loaded" | The download failed, or the embedding package is missing. The server's error stream says which step; the client usually shows it as the server's log. |
| The client lists no tools | The client could not start the command. Check the path in the configuration, and that the same command runs in a terminal. |

More failures, and their fixes, are in [troubleshooting](../troubleshooting.md).


## Conclusion

You now have an assistant that can search your organization's documentation and cite it, with no server to host and nothing sent to a third party. To build the index it searches, read [running a build](../usage.md). To search the same file from your own code instead, read [how to search a compendium](search-a-compendium.md).


## Additional Resources

* [Extractium™ README](../../README.md) — project overview and quick start.
* [Local Python MCP Server](../../examples/mcp/local-python/README.md) — settings and limits of the Python server.
* [Local Node MCP Server](../../examples/mcp/local-node/README.md) — settings and limits of the Node server.
* [How to Search a Compendium](search-a-compendium.md) — the client libraries both servers are built on.
* [Container Format](../container-format.md) — the index file both servers read.
* [Running a Build](../usage.md) — how the index is produced.
* [Troubleshooting](../troubleshooting.md) — known failures, causes, and fixes.
* [Using a Published Compendium](../using-a-compendium.md) — how an AI agent should use what it gets back.
* [Model Context Protocol specification](https://modelcontextprotocol.io/specification/latest) — the protocol these servers speak.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
