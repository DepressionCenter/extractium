<!--
This file is part of Extractium™
docs/how-to/search-a-compendium.md
Author(s): Gabriel Mongefranco
Created: 2026-09-08
Last Modified: 2026-09-12
Summary: How to search a built compendium with the two client libraries:
loading the container in Python and in JavaScript, supplying a query
embedder, reading the results, and what the search does behind the two
calls.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Search a Compendium

[← Back to README](../../README.md)


## Summary

A build writes one file, `compendium.json`, that holds your text, its vectors, and its keyword statistics. This page shows you how to search that file: once from Python, once from JavaScript. Both clients ship with Extractium, need no server and no database, and give the same answers for the same question. Read it if you are writing a tool, a script, or a web page over a published index.


## What you need

1. A built compendium. The [build page](../usage.md) shows how to make one.
2. A way to turn a question into a vector, using the same embedding model the file was built with. The file names that model in its `embedding.model` field, so you never have to guess.
3. Python 3.10 or newer for the Python client, or Node 18 or newer, a browser, or an edge runtime for the JavaScript client.

The clients deliberately do not embed the query themselves. That keeps them small and lets the same JavaScript file run in a browser with a local model, in a script with a hosted one, or on a server with none at all.


## Search from Python

```python
from extractium.search import load_container

index = load_container("dist/compendium.json")   # a compendium.json.gz reads the same way

hits = index.search("how do I request a data extract", embed_query)

for hit in hits:
    print(hit.parent["t"], hit.parent["u"], round(hit.score, 3))
    print(hit.parent["x"])
```

`embed_query` is any function that takes one string and returns a list of numbers. With the `sentence-transformers` package that Extractium already installs, it looks like this:

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(index.embedding["model"])

def embed_query(text):
    return model.encode([text], normalize_embeddings=True)[0]
```

The client adds the file's query prefix for you before calling your function, so pass the plain question.

### What comes back

`search` returns a list of hits, best first, each with:

| Field | What it holds |
|---|---|
| `parent` | The whole section: its heading (`t`), text (`x`), URL (`u`), categories, and the rest of the fields the [container format](../container-format.md) lists. This is what you show a reader or hand to a language model. |
| `score` | How strong the match was. Useful for ordering and for comparing hits inside one result list. It is not a percentage. |
| `child_index` | Which search window matched. |
| `start`, `end` | Where that window sits inside the section text, in UTF-16 code units. |
| `window_text` | Just the matched window, when you want to highlight it. |

An empty list means nothing was relevant enough. That is a real answer: say so rather than showing the closest miss as if it were a match. If you do want the nearest sections anyway, for a "did you mean" list, pass `no_threshold=True`.

### Refusing the wrong file

Tell the loader which embedder you will use, and it will refuse a file built with another one instead of returning quietly wrong results:

```python
index = load_container("dist/compendium.json", model="BAAI/bge-small-en-v1.5", dims=384)
```


## Search from JavaScript

The client is one file with no dependencies and no build step: `clients/js/extractium-client.js`.

```javascript
import { inflateContainer, loadContainer } from './extractium-client.js';

const response = await fetch('https://example.org/kb/compendium.json');
const index = loadContainer(await inflateContainer(await response.arrayBuffer()));

const hits = await index.search('how do I request a data extract', embedQuery);

for (const hit of hits) {
    console.log(hit.parent.t, hit.parent.u, hit.score.toFixed(3));
}
```

`embedQuery` takes one string and returns an array of numbers, or a promise for one. In a browser, transformers.js can run the same model locally:

```javascript
import { pipeline } from 'https://cdn.jsdelivr.net/npm/@huggingface/transformers';

const embedder = await pipeline('feature-extraction', index.embedding.browserModel);
const embedQuery = async (text) => (await embedder(text, { pooling: 'cls', normalize: true })).data;
```

A hit carries the same fields as in Python, with JavaScript names: `parent`, `score`, `childIndex`, `start`, `end`, and `windowText`. When you already have a query vector, call `index.searchWithVector(query, vector)` and skip the promise.


## What the search actually does

Both clients run the same six steps. You do not have to configure any of them.

1. **Two searches, not one.** Your question is compared with every window by vector similarity, and separately matched word for word against the keyword statistics. A vector search finds text that means the same thing in other words; a keyword search finds an exact product name or error code. Neither alone is enough.
2. **Fusing the two lists.** The two rankings are merged by reciprocal rank fusion, which uses each result's position in its own list and ignores the raw scores. That is what makes two scores on completely different scales comparable.
3. **Deciding what counts as relevant.** A result must clear the strictest of three tests: an absolute floor, the middle of this query's own results plus a margin, and a distance above the average match the build measured for this corpus. The middle test is the one that keeps working when you change sites or models.
4. **Keeping the answers varied.** Near-identical windows are pushed down so that four results say four things rather than one thing four times.
5. **Capping any one section.** At most two windows from the same section survive, so a long article cannot fill the whole answer.
6. **Returning whole sections.** Small windows are searched, whole sections are returned. The match is precise, and the text you get back still has enough around it to answer from.


## Keeping the two clients honest

The repository keeps a small committed compendium in `tests/golden/` and, beside it, a fixed query vector and the ranking both clients must return for it. The Python suite rebuilds that file, checks it has not drifted, checks its own ranking, and then runs the Node suite, which ranks the same file. If a change makes the two clients disagree, those tests fail.

Run them with:

```
python -m pytest tests/test_search.py tests/test_search_contract.py
node --test clients/js
```


## Conclusion

You can now search a published index from either language, with your own embedder, and read the sections that come back. To hand the same search to an AI assistant as a tool instead, read [how to connect an MCP client](connect-an-mcp-client.md). To publish an index on a schedule, read [how to run a weekly build](run-a-weekly-build.md). To understand the file itself, read the [container format](../container-format.md).


## Additional Resources

* [Extractium™ README](../../README.md) — project overview and quick start.
* [Container Format](../container-format.md) — the byte layout both clients read, and the reader checklist they implement.
* [Running a Build](../usage.md) — how the file you are searching is produced.
* [How to Deploy](deploy.md) — where a published index lives and every way it can be consumed.
* [How to Run a Weekly Build](run-a-weekly-build.md) — keeping a published index current.
* [How to Connect an MCP Client](connect-an-mcp-client.md) — the two local servers built on these clients.
* [Using a Published Compendium](../using-a-compendium.md) — how an AI agent uses the published files and these clients.
* [BAAI/bge-small-en-v1.5 model card](https://huggingface.co/BAAI/bge-small-en-v1.5) — the embedding model, including the query prefix the clients apply for you.
* [transformers.js](https://huggingface.co/docs/transformers.js) — running the same model in a browser.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
