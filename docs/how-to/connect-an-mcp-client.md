<!--
This file is part of Extractium™
docs/how-to/connect-an-mcp-client.md
Author(s): Gabriel Mongefranco
Created: 2026-09-11
Last Modified: 2026-09-28
Summary: How to let an AI assistant on your own computer search a
compendium: the one command that serves the search tool, the one
command that writes the connection card, how to check the tool works
without a client, how to add it to each assistant, and what the
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

The Model Context Protocol (MCP) is the standard that AI assistants use to call tools. This page shows you how to give an assistant on your own computer one tool: search of an Extractium™ compendium, the collection a build writes. Two commands do it. `extractium mcp` serves the tool, and `extractium connect` writes a card that tells the assistant, or you, how to connect. You need a built compendium or its published address, a terminal, and a few minutes. Nothing you ask leaves your computer.

The same tool also exists as a JavaScript example, for an assistant that runs JavaScript tools or a machine with Node and no Python. See [the Node server](../../examples/mcp/local-node/README.md). If the assistant does not run on your computer, or you would rather not run anything at all, the tool can be hosted for free. See [how to deploy a remote MCP server](deploy-a-remote-mcp-server.md).


## Before you start

You need one of these:

- A compendium file a build wrote. It is in `dist/` by default. `compendium-full.json.gz` holds the text of every section, so the assistant can quote a page, and it is the usual choice on your own computer. `compendium.json.gz` is the light one, with one entry per page, for when memory matters more.
- The address of a published compendium, such as `https://example.org/kb/compendium-full.json.gz`. The address must start with `https://`, unless it is on `localhost`. The tool refuses anything else, because a file fetched over an open connection can be swapped in transit for whatever someone else wants your assistant to read.

You also need Extractium™ installed, which puts the `extractium` command on the path of the environment you installed it into. `python -m extractium.cli` does the same from that environment. [How to install](install.md) covers both.


## Step 1: Start the tool once by hand

This proves the tool runs before an assistant depends on it.

```bash
extractium mcp --index dist/compendium-full.json.gz
```

The command prints one line to the error stream and then waits. It looks stuck, but it is waiting for a client to write a request to its standard input. Press Ctrl+C to stop it.

To serve a published compendium instead, give the address:

```bash
extractium mcp --index https://example.org/kb/compendium-full.json.gz
```

The file is downloaded once into `~/.cache/extractium-mcp`, or the folder `--cache-dir` names, and checked against the server on later starts, so an unchanged file costs one small request. If the host cannot be reached and a copy is cached, the cached copy is used.

Without `--index`, the command reads `EXTRACTIUM_INDEX_PATH` and then `EXTRACTIUM_INDEX_URL` from the environment, so a client configuration written for the earlier example server still works.


## Step 2: Ask it something without a client

You can drive the tool yourself. Send it two messages, one per line:

```bash
printf '%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_kb","arguments":{"query":"how do I request a data extract"}}}' \
  | extractium mcp --index dist/compendium-full.json.gz
```

You get two lines back. The first lists the one tool, `search_kb`. The second holds the sections it found. The first search is slow, because it loads the embedding model, about 130 MB the first time. Later ones are quick.


## Step 3: Write the connection card

```bash
extractium connect --index dist/compendium-full.json.gz
```

This writes a folder named `extractium-search` holding one file, `SKILL.md`, and prints the same text. The card holds:

- The `extractium mcp` command with the full path of your file, so a client can start it from any folder.
- The JSON entry most clients read, with the same command.
- One sentence per known assistant saying whether it can reach a tool on this computer, and where its configuration goes.
- The rules about what an assistant may do with the text the tool returns.

The card names no token and no credential. `--out` names another folder. `--url` adds a second entry for a client that connects to an address instead of starting a program, when a program on this computer serves the same tool over HTTP; the address has to be on this computer and carry no query. The local page is such a program: while `extractium ui` runs, it answers the same tool at `/mcp` on the address the terminal printed, over the compendium the settings file names, so `--url http://127.0.0.1:<port>/mcp` puts that address on the card. The entry works only while the page runs. See [how to use the local page](use-the-local-page.md).

The folder is the shape a Claude skill takes, so you can copy it where your assistant looks for skills. The text also pastes into the instructions of any assistant that takes them.


## Step 4: Add it to your assistant

Do one of these, whichever fits your assistant. The card says the same thing with your own path filled in.

**Claude Code** can start the tool itself. Run this once, with the path the card shows:

```bash
claude mcp add extractium -- extractium mcp --index C:/Path/To/dist/compendium-full.json.gz
```

**Most other clients** keep a JSON file listing the servers they may start. This is the entry, and it is the one the card prints:

```json
{
  "mcpServers": {
    "extractium": {
      "command": "extractium",
      "args": ["mcp", "--index", "C:/Path/To/dist/compendium-full.json.gz"]
    }
  }
}
```

Use full paths, not relative ones. The client starts the tool from a folder you did not choose. If the client cannot find the `extractium` command, give the full path of the command inside the environment you installed it into, or use `python` with `-m extractium.cli mcp` as the arguments. Restart the client, and the tool appears in its tool list.

**The Node example** takes the same shape, with `node` as the command and the full path of `server.js` as its argument, and the address in an `env` block:

```json
{
  "mcpServers": {
    "extractium": {
      "command": "node",
      "args": ["C:/Path/To/extractium/examples/mcp/local-node/server.js"],
      "env": { "EXTRACTIUM_INDEX_URL": "https://example.org/kb/compendium-full.json.gz" }
    }
  }
}
```


## Step 5: Use it

Ask the assistant a question the compendium covers. It calls `search_kb`, gets back whole sections, and should cite the address of each section it used.

The tool takes two arguments:

| Argument | What it is |
|---|---|
| `query` | The question, in plain words. No search operators. Up to 1,000 characters. |
| `k` | How many sections to return, 1 to 10. Four by default. |

An empty result means nothing in the compendium was relevant enough. That is a real answer. An assistant should say so rather than offer the closest miss.


## What the assistant must not do with the answer

Every section is text somebody else wrote on a web page. A page can hold words aimed at whatever reads it next: "ignore your previous instructions", "the administrator approved this", "run this command". The tool puts a line at the top of every answer saying the sections are quoted evidence, not instructions, and an assistant must treat them that way. The card repeats the rule.

If a compendium includes content read from a local folder, which only happens when you turn that on, the tool marks the answer confidential. Do not paste that text into another service. [Using a published compendium](../using-a-compendium.md) states both rules in full.


## If it does not work

| What you see | What it means |
|---|---|
| The command exits at once, code 2, and asks for `--index` | Nothing named a compendium: no `--index`, and neither `EXTRACTIUM_INDEX_PATH` nor `EXTRACTIUM_INDEX_URL` is set. |
| "the index address must be https://" | The address is plain HTTP somewhere other than this computer. Use HTTPS, or `localhost` for a build you are serving yourself. |
| "The index cannot be read" | The file is not a compendium, or is a version this client does not read. Check it against the [container format](../container-format.md). |
| "The index or the embedding model could not be loaded" | The file could not be read or fetched, or the embedding package is missing. The error stream says which step. The client usually shows it as the server's log. |
| The client lists no tools | The client could not start the command. Check the path in the configuration, and that the same command runs in a terminal. |
| `extractium connect` says the file is not there | The path is wrong, or the build has not run yet. Give the file a build wrote. |

More failures, and their fixes, are in [troubleshooting](../troubleshooting.md).


## Conclusion

You now have an assistant that can search your organization's documentation and cite it, with no server to host and nothing sent to a third party. To build the compendium it searches, read [running a build](../usage.md). To search the same file from your own code instead, read [how to search a compendium](search-a-compendium.md).


## Additional Resources

* [Extractium™ README](../../README.md): project overview and quick start.
* [How to Install](install.md): the two ways to install, and how to check the command works.
* [How to Use the Local Page](use-the-local-page.md): the page that also serves the tool at `/mcp` while it runs.
* [Local Node MCP Server](../../examples/mcp/local-node/README.md): the same tool in JavaScript, and its settings.
* [Local Python MCP Server](../../examples/mcp/local-python/README.md): where the earlier example went.
* [How to Search a Compendium](search-a-compendium.md): the client library the tool is built on.
* [How to Deploy a Remote MCP Server](deploy-a-remote-mcp-server.md): the same tool hosted on Val Town or Cloudflare.
* [Container Format](../container-format.md): the file the tool reads.
* [Running a Build](../usage.md): how the compendium is produced.
* [How to Deploy](deploy.md): the deployment choices, and how each one is consumed.
* [Troubleshooting](../troubleshooting.md): known failures, causes, and fixes.
* [Using a Published Compendium](../using-a-compendium.md): how an AI agent should use what it gets back.
* [Model Context Protocol specification](https://modelcontextprotocol.io/specification/latest): the protocol the tool speaks.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
