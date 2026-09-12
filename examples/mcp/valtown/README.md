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

1. A Val Town account. The free plan is enough.
2. Python 3.10 or newer, which you already have if you built the index. Nothing else is installed.
3. A published index address, starting with `https://`.

A val holds only its own files, so the JavaScript client and the shared protocol modules this example imports from elsewhere in the repository have to be copied beside the entry point, with their import lines rewritten. `push.py` does that. There are two ways to get the result onto Val Town: through the browser with no key at all, or through the platform's API with a token.


## Way 1: the browser, no key

```bash
cd examples/mcp/valtown
python push.py
```

That writes six files under `val/`, which git ignores. Then, signed in to Val Town in your browser:

1. Create a new val and name it.
2. Add each of the six files by name, pasting its contents. Make `main.http.ts` an HTTP file; the others are plain files.
3. Under the val's environment variables, add `EXTRACTIUM_INDEX_URL` with your published index address.
4. Open the address the platform shows for `main.http.ts`. You see one line naming the endpoint, and the MCP endpoint is `/mcp` under it.

Repeat step 2 for any file that changes. No token is made and nothing about your account leaves the browser.


## Way 2: the API, with a token

Make a token at [val.town/settings/api](https://www.val.town/settings/api) with read and write on vals. Write on vals is off by default when a token is made; turn it on for this one. Then:

```bash
cd examples/mcp/valtown
VALTOWN_API_TOKEN=EXAMPLE_TOKEN python push.py --push --name my-compendium \
  --set EXTRACTIUM_INDEX_URL=https://example.org/kb/kb-index.json
```

On Windows, set the variable first (`$env:VALTOWN_API_TOKEN = 'EXAMPLE_TOKEN'` in PowerShell), then run the command without the prefix.

The first run creates the val under your account, writes the six files with `main.http.ts` as an HTTP file, sets the variables you gave with `--set`, and prints the endpoint. Later runs find the val by name and update the files in place. Run it again whenever a source file changes. The token is read from the environment, sent in one header, and printed nowhere.

| Option | What it does |
|---|---|
| `--name` | The val's name. Defaults to `extractium-kb-mcp`. |
| `--org` | Create the val under an organization you belong to, by its handle. |
| `--val-id` | Update a val you already know the id of, skipping the lookup by name. |
| `--privacy` | `public` (the default), `unlisted`, or `private` for the source. The free plan caps the number of unlisted and private vals, and refuses a new one past the cap. |
| `--set KEY=VALUE` | An environment variable to set on the val. Repeat for each. |

Val Town also documents [syncing a val with a GitHub repository](https://docs.val.town/guides/github-sync/), which keeps a val mirrored from a repository on every push. Point it at a repository holding the staged folder.

`push.py` is tested against a fake of the API, call by call, and was run against the live platform on 2026-09-12: the first run created the val, the second found it and updated every file, and the endpoint answered the golden compendium's contract query with the sections the clients rank as relevant.


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

They run the search in Node against the small compendium committed in `tests/golden/`, with a blob store and a fetch in memory. The staging and the push are covered by the Python suite, `tests/test_mcp_remote_servers.py`, which checks that the staged folder's imports all resolve and drives `push.py` against a fake of the API: the calls it makes, the file types it sends, and that the token reaches one header and nothing else. Neither needs a network, an install, or a Val Town account.


## Conclusion

You now have a search endpoint any MCP-capable assistant can reach, hosted for free and reading a static file you already publish. [How to deploy a remote MCP server](../../../docs/how-to/deploy-a-remote-mcp-server.md) walks through the same steps with the client configuration, and compares this example with the [Cloudflare one](../cloudflare/README.md).


## Additional Resources

* [Extractium™ README](../../../README.md) — project overview and quick start.
* [How to Deploy a Remote MCP Server](../../../docs/how-to/deploy-a-remote-mcp-server.md) — both hosted examples, step by step, and how to connect a client.
* [Cloudflare MCP Server](../cloudflare/README.md) — the other hosted example, which searches from a database instead of a file in memory.
* [Local Node MCP Server](../local-node/README.md) — the same tool on your own machine.
* [Using a Published Compendium](../../../docs/using-a-compendium.md) — how an AI agent should use what it gets back.
* [Val Town documentation](https://docs.val.town/) — the platform, its blob store, and its environment variables.
* [Val Town REST API](https://docs.val.town/reference/api/) — the calls `push.py` makes, and the token scopes.
* [Syncing vals with GitHub](https://docs.val.town/guides/github-sync/) — keeping a val mirrored from a repository.
* [Val Town limits](https://www.val.town/limits) — the plan limits the numbers above come from.
* [Model Context Protocol specification](https://modelcontextprotocol.io/specification/latest) — the protocol this server speaks.


[← Back to the Extractium README](../../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
