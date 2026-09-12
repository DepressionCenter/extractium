<!--
This file is part of Extractium™
docs/how-to/deploy-a-remote-mcp-server.md
Author(s): Gabriel Mongefranco
Created: 2026-09-12
Last Modified: 2026-09-12
Summary: How to give an assistant anywhere a search tool over a published
compendium, with no server of your own: which of the two hosted examples
to pick, how to deploy each, how to protect the endpoint, how to connect
a client, and what a hosted search can and cannot do.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Deploy a Remote MCP Server

[← Back to README](../../README.md)


## Summary

The Model Context Protocol (MCP) is the standard that AI assistants use to call tools. [How to connect an MCP client](connect-an-mcp-client.md) gives an assistant on your own machine a search tool. This page gives the same tool to an assistant that runs anywhere, by hosting the search on a free platform instead of on your computer. You need a published index, an account on one of the two platforms, and about half an hour.

Two hosted examples ship with Extractium. Both expose one tool, `search_kb`, with the same arguments and the same answers as the local servers, and neither needs a machine of yours to stay on.


## Which example to use

| Pick | When | How it searches |
|---|---|---|
| [Val Town](../../examples/mcp/valtown/README.md) | You want the shortest path: one folder pushed with one command. | Holds the whole index file in memory. Keyword search out of the box; the full hybrid search if you point it at an embedding service. |
| [Cloudflare](../../examples/mcp/cloudflare/README.md) | You already use Cloudflare, or you want hybrid search without a third service. | Reads a database you load the build into. Keyword search out of the box; hybrid search with Workers AI turned on, over the keyword candidates. |

Both are free at the scale a documentation search runs at. The Val Town free plan stores 10 MB of blobs, so an index larger than that is downloaded on every cold start there; Cloudflare's free plan has no such limit on a database, but its Worker never sees the index file at all.


## Step 1: Publish the index

You need a published `kb-index.json` for Val Town, or a `compendium.sqlite` for Cloudflare. [How to publish to GitHub Pages](publish-to-github-pages.md) covers the first; for the second, add a `sqlite` output to your settings file and run a build:

```yaml
outputs:
  - type: container
  - type: sqlite
```


## Step 2: Deploy

Follow the README of the example you picked. In short:

Val Town:

```bash
cd examples/mcp/valtown
node stage.js
vt create extractium-kb-mcp && cp val/* extractium-kb-mcp/ && cd extractium-kb-mcp && vt push
```

Then set `EXTRACTIUM_INDEX_URL` in the val's environment variables.

Cloudflare:

```bash
cd examples/mcp/cloudflare
python export_d1.py ../../../dist/compendium.sqlite compendium.d1.sql
npx wrangler d1 create extractium-kb          # put the printed id into wrangler.jsonc
npx wrangler d1 execute extractium-kb --remote --file compendium.d1.sql
npx wrangler deploy
```

Each command prints the address of the endpoint. The Cloudflare example can be run on your own machine first, with no account, through `wrangler dev`; its README shows how.


## Step 3: Check it answers

Ask the endpoint one question from a terminal, replacing the address:

```bash
curl -X POST https://example-kb.val.run/mcp \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_kb","arguments":{"query":"how do I request a data extract"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'
```

You get one JSON object back. Its `result.content[0].text` is what an assistant reads, headed by the line saying the sections are quoted evidence; `result.structuredContent.results` is the same answer as data. An empty `results` list means nothing was relevant enough, which is a real answer.

Opening the endpoint's root address in a browser shows one line naming the endpoint, so you can tell a live deployment from a wrong address.


## Step 4: Decide who may call it

A hosted endpoint is public unless you say otherwise. The index it searches is public too, so an open endpoint gives away nothing that the published files do not; what it can cost you is the platform's request quota. Two settings, the same on both platforms, narrow who may call it:

| Setting | Effect |
|---|---|
| `EXTRACTIUM_BEARER_TOKEN` | Every request must carry `Authorization: Bearer <token>`. Set it as a secret on the platform, never in a file. Most MCP clients can send a fixed header; see Step 5. |
| `EXTRACTIUM_ALLOWED_ORIGINS` | A web page may call the endpoint only from one of these origins. A request with no `Origin` header is not from a web page and always passes, so this protects a visitor's browser, not the endpoint. |

If a compendium includes content read from a local folder, which only happens when an operator turns that on, set the token. The server marks such answers confidential, but the mark is advice to the assistant, not a lock on the endpoint.


## Step 5: Connect a client

Clients that speak MCP over HTTP take the endpoint address, and most take a fixed header. The common shape:

```json
{
  "mcpServers": {
    "extractium": {
      "url": "https://example-kb.val.run/mcp",
      "headers": { "Authorization": "Bearer EXAMPLE_TOKEN" }
    }
  }
}
```

Leave out `headers` when no token is set. Your client's own documentation says where the file lives and what it calls the section. Restart the client, and the tool appears in its tool list.

Both servers answer the current revision of the protocol and the older ones that open with an `initialize` handshake, so a client written against either works. Neither offers a server-sent event stream or a session: every request is one POST and one JSON answer.


## What a hosted search does and does not do

- **Keyword search by default.** Neither platform runs an embedding model on its own, so out of the box a question is matched by its words. A section that shares no word with the question cannot appear. That is a narrower search than the local servers run; it is also fast, free, and good enough for most documentation questions, which use the documentation's own words.
- **Hybrid search when you add a model.** Val Town gets there through any HTTP embedding service that serves the index's model; Cloudflare through its own Workers AI, which serves that model. On Val Town the result is then identical to the local servers'; on Cloudflare the vector ranking runs over the keyword candidates only, so the keyword floor stays.
- **Read-only.** Both servers have one tool and it reads. There is no path by which a model's output runs anything.
- **Stateless.** Nothing is kept between requests except the index itself. Each request is judged on its own.


## If it does not work

| What you see | What it means |
|---|---|
| `401` with `WWW-Authenticate: Bearer` | A token is set and the request did not carry it, or carried another. |
| `403` naming the origin | The request came from a web page whose origin is not in `EXTRACTIUM_ALLOWED_ORIGINS`. |
| `405` on a GET | Correct: the endpoint takes POST only. Open the root address instead to see the server is up. |
| `404` with a JSON-RPC error inside | The method name is one this server does not have. The tool is `search_kb`, called through `tools/call`. |
| `400` with `"Unsupported protocol version"` | The client named a revision neither server speaks. The error lists the ones they do. |
| `400` with `"Header mismatch"` | An `MCP-Protocol-Version`, `Mcp-Method`, or `Mcp-Name` header disagrees with the body. A gateway in front of the server may have rewritten one. |
| A tool error saying the server is not configured | On Val Town, `EXTRACTIUM_INDEX_URL` is missing or not `https://`. |
| A tool error saying the index or model could not be loaded | The published address did not answer, or the database is not an Extractium compendium. The platform's log names the step. |

More failures, and their fixes, are in [troubleshooting](../troubleshooting.md).


## Conclusion

You now have a search tool any MCP-capable assistant can call, hosted for free, over an index you already publish. For an assistant that cannot call tools at all, the [hosted-assistant prompts](../../examples/wrappers/README.md) point it at the static files instead. To run the same tool on your own machine, read [how to connect an MCP client](connect-an-mcp-client.md).


## Additional Resources

* [Extractium™ README](../../README.md) — project overview and quick start.
* [Val Town MCP Server](../../examples/mcp/valtown/README.md) — settings, staging, and limits of the Val Town example.
* [Cloudflare MCP Server](../../examples/mcp/cloudflare/README.md) — loading D1, local runs, and limits of the Cloudflare example.
* [How to Connect an MCP Client](connect-an-mcp-client.md) — the local servers and the client configuration in full.
* [How to Publish to GitHub Pages](publish-to-github-pages.md) — where the published index comes from.
* [Hosted Assistant Prompts](../../examples/wrappers/README.md) — for platforms that browse but cannot call tools.
* [Using a Published Compendium](../using-a-compendium.md) — how an AI agent should use what it gets back.
* [Configuration Reference](../configuration.md) — the `sqlite` output.
* [Troubleshooting](../troubleshooting.md) — known failures, causes, and fixes.
* [Model Context Protocol specification](https://modelcontextprotocol.io/specification/latest) — the protocol, including its HTTP transport.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
