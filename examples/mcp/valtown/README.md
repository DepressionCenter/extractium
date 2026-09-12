<!--
This file is part of Extractium™
examples/mcp/valtown/README.md
Author(s): Gabriel Mongefranco
Created: 2026-09-12
Last Modified: 2026-09-12
Summary: README for the Val Town example: what it does, the three ways
to push it, the settings it reads, what search it runs with and without an
embedding service, and its limits.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Val Town MCP Server

## Search a published compendium from a hosted endpoint

[← Back to the Extractium README](../../../README.md)


## Summary

This folder holds a hosted search server that runs on [Val Town](https://www.val.town/), a platform that runs small TypeScript programs at a public address. Once pushed, it answers Model Context Protocol (MCP) requests at `https://<your-val>.val.run/mcp`, so an assistant anywhere can search your published knowledge base without you running a machine. It exposes the same one tool, `search_kb`, as the [local servers](../local-node/README.md), with the same arguments and the same answers.

The val fetches the published container once, keeps a copy in its blob store so a cold start does not download it again, and holds it in memory while the val stays warm. Out of the box it answers with keyword search. Point it at an embedding service and it runs the full hybrid search the clients run.


## What you need

1. A Val Town account, and an API token from [val.town/settings/api](https://www.val.town/settings/api) with read and write on vals. Write on vals is off by default when a token is made; turn it on for this one.
2. Node 18 or newer on your machine.
3. A published index address, starting with `https://`.


## Push it

A val holds only its own files, so the JavaScript client and the shared protocol modules this example imports from elsewhere in the repository have to be copied beside it. `stage.js` does that and rewrites the import lines; `push.js` runs it and then sends the six files through Val Town's REST API, with nothing to install:

```bash
cd examples/mcp/valtown
VALTOWN_API_TOKEN=EXAMPLE_TOKEN node push.js
```

On Windows, set the variable first (`$env:VALTOWN_API_TOKEN = 'EXAMPLE_TOKEN'` in PowerShell), then run `node push.js`.

The first run creates a val named `extractium-kb-mcp` under your account, with its source unlisted; give another name as the first argument, or `--privacy public` to list it. Later runs find the val by name and update the files. `main.http.ts` is sent as an `http` file, which is what gives the val an endpoint; the script prints that endpoint, and the MCP endpoint is `/mcp` under it. Run it again whenever a source file changes.

Two other ways to get the same six files into a val, both from Val Town's own documentation:

- `node stage.js` alone writes the files under `val/`, ignored by git, for you to paste into the web editor or push with the [`vt` command-line tool](https://docs.val.town/guides/prompting/cli/), which needs Deno.
- [Syncing vals with GitHub](https://docs.val.town/guides/github-sync/) keeps a val mirrored from a repository on every push, through a GitHub Actions workflow or a sync val. Point it at a repository holding the staged folder.

`push.js` is tested against a fake of the API, call by call; it was not run against the live platform from this machine.


## Settings

Set these in the val's environment variables on Val Town, in the web editor or through the API's environment-variable endpoints. No file holds an address or a token.

| Variable | Required | What it does |
|---|---|---|
| `EXTRACTIUM_INDEX_URL` | Yes | The published index. Must start with `https://`. |
| `EXTRACTIUM_EMBED_URL` | No | An HTTP service that turns text into a vector with the same model the index was built with. When set, searches are hybrid; when not, keyword only. |
| `EXTRACTIUM_EMBED_TOKEN` | No | Bearer token for that service. Sent in the `Authorization` header and nowhere else. |
| `EXTRACTIUM_BEARER_TOKEN` | No | When set, every request to `/mcp` must carry it as a bearer token. Without it the endpoint is open to anyone who finds the address. |
| `EXTRACTIUM_ALLOWED_ORIGINS` | No | Comma-separated browser origins allowed to call the endpoint from a web page. A request with no `Origin` header is not from a web page and always passes. |

The embedding service is asked with a JSON body of `{"inputs": "<text>"}` and must answer with a vector of numbers, either bare, wrapped in an outer array, or under a `data` field. That is the shape the Hugging Face inference endpoints use for feature extraction; other services with the same shape work too. The text sent already carries the query prefix the index names, and the vector must have the width the index names, or the search fails and says so. No embedding service was exercised from this repository; the shape is tested against a fake one.


## What search it runs

Without an embedding service, the query terms are ranked by BM25 against the index's keyword statistics, weighted per section as the clients weight them, and passed through the clients' diversity selection so near-copies of one paragraph cannot fill the answer. A section that shares no term with the question cannot appear; having matched at least one term is the relevance floor.

With one, the val runs exactly the search the [JavaScript client](../../../docs/how-to/search-a-compendium.md) runs: vectors and keywords fused, thresholded, and diversified.


## Limits

- The Val Town free plan allows 10 MB of blob storage in total. A larger container is still served, but cannot be kept in the store, so every cold start downloads it again; the val's log says so. The Pro plan allows 1 GB.
- A val has one minute of wall-clock time per request and four gigabytes of memory, which is far more than one search needs; the first request after a cold start also pays for the download.
- While the val stays warm, the index is revalidated against the published address at most every ten minutes, so a new build appears within that time without a push.
- One tool, no writes: the val reads one static file and, when configured, calls one embedding service.


## Run the tests

```bash
node --test examples/mcp/valtown
```

They run the search in Node against the small compendium committed in `tests/golden/`, with a blob store and a fetch in memory; check that `stage.js` produces a folder whose imports all resolve; and drive `push.js` against a fake of the API to check the calls it makes, the file types it sends, and that the token reaches one header and nothing else. They need no network, no install, and no Val Town account.


## Conclusion

You now have a search endpoint any MCP-capable assistant can reach, hosted for free and reading a static file you already publish. [How to deploy a remote MCP server](../../../docs/how-to/deploy-a-remote-mcp-server.md) walks through the same steps with the client configuration, and compares this example with the [Cloudflare one](../cloudflare/README.md).


## Additional Resources

* [Extractium™ README](../../../README.md) — project overview and quick start.
* [How to Deploy a Remote MCP Server](../../../docs/how-to/deploy-a-remote-mcp-server.md) — both hosted examples, step by step, and how to connect a client.
* [Cloudflare MCP Server](../cloudflare/README.md) — the other hosted example, which searches from a database instead of a file in memory.
* [Local Node MCP Server](../local-node/README.md) — the same tool on your own machine.
* [Using a Published Compendium](../../../docs/using-a-compendium.md) — how an AI agent should use what it gets back.
* [Val Town documentation](https://docs.val.town/) — the platform, its blob store, and its environment variables.
* [Val Town REST API](https://docs.val.town/reference/api/) — the calls `push.js` makes, and the token scopes.
* [Syncing vals with GitHub](https://docs.val.town/guides/github-sync/) — keeping a val mirrored from a repository.
* [Val Town limits](https://www.val.town/limits) — the plan limits the numbers above come from.
* [Model Context Protocol specification](https://modelcontextprotocol.io/specification/latest) — the protocol this server speaks.


[← Back to the Extractium README](../../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
