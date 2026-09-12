<!--
This file is part of Extractium™
examples/mcp/cloudflare/README.md
Author(s): Gabriel Mongefranco
Created: 2026-09-12
Last Modified: 2026-09-12
Summary: README for the Cloudflare Worker example: what it does, how to
load a build into D1 and deploy, the settings it reads, what search it
runs with and without Workers AI, and its limits.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Cloudflare MCP Server

## Search a published compendium from a database at the edge

[← Back to the Extractium README](../../../README.md)


## Summary

This folder holds a hosted search server that runs as a [Cloudflare Worker](https://developers.cloudflare.com/workers/) and reads the knowledge base from [D1](https://developers.cloudflare.com/d1/), Cloudflare's hosted SQLite. Once deployed, it answers Model Context Protocol (MCP) requests at `https://<your-worker>.workers.dev/mcp`. It exposes the same one tool, `search_kb`, as the [local servers](../local-node/README.md), with the same arguments and the same answers.

A Worker on the free plan has ten milliseconds of CPU per request, which is not enough to parse a multi-megabyte index. So this example never reads the container at all. A build's SQLite output is loaded into D1 once, keyword ranking runs inside the database, and the Worker only shapes the answer. With the Workers AI binding turned on, the keyword candidates are also ranked by vector similarity and fused as the clients do.


## What you need

1. A Cloudflare account. The free plan is enough.
2. Node 22.5 or newer, which brings `npx wrangler`, Cloudflare's command-line tool. Run `npm install` in this folder once to pin it.
3. A build with a `sqlite` output. Add this to the `outputs:` list of your settings file if it is not there:

   ```yaml
   outputs:
     - type: sqlite
   ```

   The build writes `dist/compendium.sqlite`.


## Load the index into D1

D1 is filled with SQL statements, not by copying a file. The export script turns the SQLite output into those statements:

```bash
cd examples/mcp/cloudflare
python export_d1.py ../../../dist/compendium.sqlite compendium.d1.sql
```

Then create the database, put its id into `wrangler.jsonc`, and load the statements:

```bash
npx wrangler d1 create extractium-kb
npx wrangler d1 execute extractium-kb --remote --file compendium.d1.sql
```

`d1 create` prints a `database_id`; replace the zeros in `wrangler.jsonc` with it. The export begins by dropping the tables, so loading a newer build replaces the older one rather than adding to it. Repeat the two `export` and `execute` steps after every build you want the server to answer from.

The export is text. On a real knowledge base it runs to tens of megabytes, because it carries every vector as hexadecimal; that is expected.


## Try it on your machine first

Everything above works locally, with no account, against a database wrangler keeps under `.wrangler/`:

```bash
npx wrangler d1 execute extractium-kb --local --file compendium.d1.sql
npx wrangler dev
```

`wrangler dev` prints an address, usually `http://localhost:8787`. Open it in a browser and you see one line naming the endpoint. Ask it something:

```bash
curl -X POST http://localhost:8787/mcp \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_kb","arguments":{"query":"how do I request a data extract"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'
```

You get one JSON object back holding the sections it found. This is the check the Worker was built against: the golden compendium in `tests/golden/` loaded the same way, queried the same way.


## Deploy

```bash
npx wrangler deploy
```

Wrangler prints the address. To require a token on every request, set it as a secret, never in `wrangler.jsonc`:

```bash
npx wrangler secret put EXTRACTIUM_BEARER_TOKEN
```


## Settings

| Setting | Where | What it does |
|---|---|---|
| `DB` binding | `wrangler.jsonc`, `d1_databases` | The database holding the build. Required. |
| `AI` binding | `wrangler.jsonc`, `ai` (commented out) | Turns on hybrid search through Workers AI. Optional; see below. |
| `EXTRACTIUM_BEARER_TOKEN` | `wrangler secret put` | When set, every request to `/mcp` must carry it as a bearer token. Without it the endpoint is open to anyone who finds the address. |
| `EXTRACTIUM_ALLOWED_ORIGINS` | `wrangler.jsonc`, `vars` | Comma-separated browser origins allowed to call the endpoint from a web page. A request with no `Origin` header is not from a web page and always passes. |


## What search it runs

Keyword search runs as one SQL statement over the postings table: the inverse document frequency of each query term is computed in the Worker from the term's document count, and the database does the rest of the BM25 arithmetic, using the constants the build recorded in the `meta` table. The fifty best windows come back, their sections are read, and the clients' diversity selection picks the answer. Every term is bound as a parameter; nothing from the question is ever spliced into the statement.

With the `AI` binding, the Worker embeds the question through Workers AI's `@cf/baai/bge-small-en-v1.5`, which is the model Extractium builds with, and ranks those same fifty windows by cosine similarity against their stored vectors. The two rankings are fused by reciprocal rank, thresholded, and diversified exactly as the clients do. The binding is used only when the `meta` table says the index was built with that model; otherwise the Worker logs why and answers from keywords alone.

The difference from the clients is the candidate pool. A client scores every window by vector; the Worker scores only the fifty that keyword search found, because reading every vector from the database on every question would not fit the CPU budget. A section that shares no term with the question therefore cannot appear, hybrid or not.


## Limits

- D1 binds at most a hundred parameters to one statement, so a question is cut to its first thirty-two distinct terms.
- During `wrangler dev`, the `AI` binding calls the remote model, so hybrid search needs a logged-in account even for a local run. Keyword search needs no account at all.
- The Worker is stateless. Nothing is cached between requests except the `meta` table, read once per isolate.
- One tool, no writes: the Worker runs `SELECT` statements and nothing else.


## Run the tests

```bash
node --test examples/mcp/cloudflare
```

They load the golden compendium's D1 export into an in-process SQLite database that stands in for the binding, and check keyword search against the client's own scores, hybrid search against the clients' recorded ranking, and the HTTP round trip through the Worker's handler. They need Node 22.5 or newer for the built-in SQLite module, and no account. The Python suite checks the export script and runs this suite.


## Conclusion

You now have a search endpoint at the edge that answers from a database, costs nothing at rest, and does not parse your index on every question. [How to deploy a remote MCP server](../../../docs/how-to/deploy-a-remote-mcp-server.md) walks through the same steps with the client configuration, and compares this example with the [Val Town one](../valtown/README.md).


## Additional Resources

* [Extractium™ README](../../../README.md) — project overview and quick start.
* [How to Deploy a Remote MCP Server](../../../docs/how-to/deploy-a-remote-mcp-server.md) — both hosted examples, step by step, and how to connect a client.
* [Val Town MCP Server](../valtown/README.md) — the other hosted example, which holds the whole container in memory.
* [Local Node MCP Server](../local-node/README.md) — the same tool on your own machine.
* [Configuration Reference](../../../docs/configuration.md) — the `sqlite` output this example reads.
* [Using a Published Compendium](../../../docs/using-a-compendium.md) — how an AI agent should use what it gets back.
* [Cloudflare D1 documentation](https://developers.cloudflare.com/d1/) — the database, its binding, and the `wrangler d1` commands.
* [Workers AI text embeddings](https://developers.cloudflare.com/workers-ai/models/bge-small-en-v1.5/) — the model the optional binding serves.
* [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits/) — the CPU budget this design works within.
* [Model Context Protocol specification](https://modelcontextprotocol.io/specification/latest) — the protocol this server speaks.


[← Back to the Extractium README](../../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
