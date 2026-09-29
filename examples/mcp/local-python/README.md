<!--
This file is part of Extractium™
examples/mcp/local-python/README.md
Author(s): Gabriel Mongefranco
Created: 2026-09-11
Last Modified: 2026-09-28
Summary: README for the local Python MCP server: it is now the
`extractium mcp` command inside the package, and this page says where
to find it and what changed for anyone who ran the example from here.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Local Python MCP Server

## The search tool is now a command in the package

[← Back to the Extractium README](../../../README.md)


## Summary

The Python server that used to live in this folder is part of the Extractium™ package. `extractium mcp` starts it, and `extractium connect` writes the card that tells an AI assistant how to reach it. This page is here so that a link or a bookmark still lands somewhere useful. The Model Context Protocol (MCP) is the standard that assistants use to call tools, and the tool is the same one as before, `search_kb`, which searches one compendium, the collection a build writes.


## Run it

```bash
extractium mcp --index dist/compendium-full.json.gz
```

Give `--index` a compendium file on this machine or its published `https://` address. Plain `http://` is accepted only on `localhost`. Without `--index`, the command reads `EXTRACTIUM_INDEX_PATH` and then `EXTRACTIUM_INDEX_URL`, so a client configuration written for the file that used to be here keeps working once its command is changed to `extractium mcp`. A downloaded compendium is kept under `~/.cache/extractium-mcp`, or the folder `--cache-dir` or `EXTRACTIUM_CACHE_DIR` names.

`extractium connect --index dist/compendium-full.json.gz` writes the connection card. [How to connect an MCP client](../../../docs/how-to/connect-an-mcp-client.md) walks through both commands, step by step.


## Conclusion

Use the command rather than a copied file. The [Node version](../local-node/README.md) still lives beside this folder for assistants that prefer a JavaScript runtime.


## Additional Resources

* [Extractium™ README](../../../README.md): project overview and quick start.
* [How to Connect an MCP Client](../../../docs/how-to/connect-an-mcp-client.md): the two commands and the client configuration, step by step.
* [Local Node MCP Server](../local-node/README.md): the same tool in JavaScript.
* [Using a Published Compendium](../../../docs/using-a-compendium.md): how an AI agent should use what it gets back.


[← Back to the Extractium README](../../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
