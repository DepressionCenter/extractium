<!--
This file is part of Extractium™
docs/container-format.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-04
Summary: Specification of the Extractium™ binary container (version 3):
byte layout, header fields, parent and child records, vector bytes, BM25
statistics, calibration, identifiers, versioning rule, and a checklist
for anyone writing a client that reads the file.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Container Format (version 3)

[← Back to README](../README.md)


## Summary

The container is the one file every Extractium client reads: a search index with the text, the vectors, and the keyword statistics for a whole knowledge base, packed so a browser, a script, or a small server can load it with no database. This page defines the file byte by byte. It is written for people building a client in any language, and for anyone who has to check what a published index contains.


## Status of this format

**Draft.** This page describes the target format. The adapter that writes it, and the clients that read it, are scheduled in the [implementation plan](implementation-plan.md) (Phase 3 and Phase 4). Nothing in the repository writes this file yet.

Version 3 replaces the version 2 layout that Field Station AI's `build-kb-index.py` writes. Field Station AI keeps its own version 2 file and is not affected by anything on this page. The differences are listed near the end, under "Changes from version 2".


## Why one binary file

A knowledge index has two kinds of data: text and metadata, which JSON handles well, and thousands of numeric vectors, which JSON handles badly. Encoding vectors as JSON arrays or base64 costs about a third more bytes and a slow parse. The container keeps the JSON for what JSON is good at and stores the vectors as raw bytes right after it.

The file keeps a `.json` extension so static hosts such as GitHub Pages serve it with a plain content type and no special configuration.


## Byte layout

| Offset | Length | Content |
|---|---|---|
| 0 | 4 bytes | Header length `N`, unsigned 32-bit integer, little-endian |
| 4 | `N` bytes | Header: one JSON object, UTF-8, minified |
| 4 + `N` | to end of file | Vector bytes (see "Vector bytes") |

A reader copies the vector bytes into a fresh buffer before viewing them as a typed array. `4 + N` is not guaranteed to be a multiple of four, and many runtimes refuse to create a 32-bit typed array at an unaligned offset.


## Header fields

| Field | Type | Meaning |
|---|---|---|
| `_license` | text | The license notice for the file. Present because the file is a JSON document with no other place for a notice. |
| `format` | text | Always `extractium-compendium`. A reader refuses any other value. |
| `v` | whole number | Layout version. This page describes `3`. |
| `extractium` | text | Version of the tool that wrote the file, for example `0.1.0`. |
| `builtAt` | text | Build time in UTC, ISO 8601 with a `Z` suffix, for example `2026-09-04T12:00:00Z`. |
| `site` | text | Display name of the knowledge base. Defaults to the title of the first page crawled. |
| `sourceCount` | whole number | Number of distinct source URLs that contributed at least one parent. Pages visited but not indexed do not count. |
| `embedding` | object | How the vectors were made. See the next table. |
| `offsetUnit` | text | Unit of the child `start` and `end` columns. Always `utf16` in version 3. |
| `parents` | list | One record per section of text. See "Parents". |
| `children` | object | Column arrays, one entry per search window. See "Children". |
| `bm25` | object | Keyword statistics. See "BM25 statistics". |
| `calibration` | object | Corpus-relative score statistics. See "Calibration". |

Unknown top-level fields must be ignored by readers. That is what lets the format grow without a version bump.

### The `embedding` object

| Field | Type | Meaning |
|---|---|---|
| `model` | text | Hugging Face model id used at build time, for example `BAAI/bge-small-en-v1.5`. |
| `browserModel` | text | Id of the same model packaged for transformers.js, for example `Xenova/bge-small-en-v1.5`. |
| `dims` | whole number | Vector length, for example `384`. |
| `normalized` | true or false | `true` when every vector has unit length, so cosine similarity is a plain dot product. |
| `queryPrefix` | text | Text placed in front of a search query before embedding it. For the default model it is `Represent this sentence for searching relevant passages: `, with the trailing space. Indexed passages never get this prefix. |
| `passagePrefix` | text | Text placed in front of each passage before embedding. Empty for the default model. |
| `dtype` | text | Storage type of each vector component: `int8` or `float32`. |
| `scale` | number | Present when `dtype` is `int8`. A reader divides each stored value by `scale` to recover the float, for example `127`. |

A reader must compare `model` and `dims` with the embedder it has available. A model id check alone is not enough: the query prefix is part of the contract, which is why the file carries it.


## Parents

A parent is one section of a page: the text a language model is shown when a search hits it. Parents are the unit of citation.

| Field | Type | Meaning |
|---|---|---|
| `id` | text | Stable identifier, 16 lowercase hexadecimal characters. See "Identifiers". |
| `t` | text | Heading, in the form `Page title -- Section heading`, or just the page title for text before the first heading. |
| `x` | text | The section text. At most `CHUNK_MAX_CHARS` characters; longer sections are split into several parents with the same heading. |
| `u` | text | Source URL. For local files, `local:` followed by the path relative to the source folder. |
| `host` | text | Host name of `u`, lowercase. Empty for local files. |
| `source_type` | text | Which kind of source the parent came from. One of: `kb` (TeamDynamix portal), `github`, `web`, `youtube`, `local`. |
| `content_type` | text | What the page is. One of: `article`, `readme`, `wiki`, `release_notes`, `page`, `text`, `video_transcript`. |
| `categories` | list of text | Hierarchy taken from the source, outermost first: TeamDynamix breadcrumbs, repository paths. Empty when the source has none. |
| `local` | true or false | `true` when the parent came from a local-filesystem source. |
| `weight` | number | Per-document multiplier applied after rank fusion. `1.0` unless a source or plugin sets otherwise. |

Field names `t`, `x`, and `u` are short on purpose: with thousands of parents, key names are a measurable share of the file.


## Children

A child is a small window of a parent: the unit that is embedded and searched. Searching small windows and returning the whole parent ("small to big" retrieval) gives precise matches with enough context to answer from.

In version 3 a child carries no text of its own. `children` is an object of parallel arrays, all the same length:

| Column | Type | Required | Meaning |
|---|---|---|---|
| `pid` | list of whole numbers | yes | Index into `parents` for each child. |
| `start` | list of whole numbers | no | Start of the child's window inside `parents[pid].x`, in `offsetUnit`. |
| `end` | list of whole numbers | no | End of the window, exclusive, in `offsetUnit`. |

Child `i` refers to `parents[children.pid[i]]`, and its vector is row `i` of the vector bytes. Its text, when a client wants to show the matched window rather than the whole parent, is `parents[pid].x` sliced from `start` to `end`.

### Offsets are counted in UTF-16 code units

Browsers are the first consumer of this file, and JavaScript strings index by UTF-16 code unit. So the writer counts offsets that way. A Python writer or reader converts with:

```python
def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2
```

Most text has no characters outside the Basic Multilingual Plane, in which case the two counts are equal. Emoji and some symbols are the exception, and the rule above keeps every language honest.

### What a child's text was at build time

Two build steps see a child's text, and any client that re-implements them must use the same text:

- **Embedding input**: the parent heading, a newline, then the window text.
- **BM25 tokens**: the parent heading, a space, then the window text, lowercased, split on the token rule in "BM25 statistics".


## Vector bytes

The vector bytes hold `len(children.pid) × embedding.dims` values of type `embedding.dtype`, row-major, in child order, little-endian for `float32`. A reader checks that the byte length equals that count times the byte width of `dtype` (1 for `int8`, 4 for `float32`) and refuses the file if it does not.

For `int8`, each stored value `q` becomes `q / scale`. Vectors are unit length before quantization, so every component lies in roughly `[-1, 1]` and one shared scale is enough.


## BM25 statistics

`bm25` holds what a client cannot compute from one query on its own. The client computes the score.

| Field | Type | Meaning |
|---|---|---|
| `k` | number | Term-frequency saturation, `1.2`. |
| `b` | number | Length normalization, `0.75`. |
| `d` | number | Lower bound added to the term score so a single sparse match never scores zero, `0.5`. |
| `avgDocLen` | number | Mean token count over all children. |
| `docLen` | list of whole numbers | Token count of each child, in child order. |
| `df` | object | Term to the number of children containing it. |
| `postings` | object | Term to a list of `[childIndex, termFrequency]` pairs. |

**Token rule.** Lowercase the text and take every run of three or more ASCII letters or digits: the regular expression `[a-z0-9]{3,}`. A query must be tokenized the same way or nothing will match.

**Score.** For a query with terms `T`, over `N` children, the score of child `i` is the sum over `t` in `T` found in `postings`:

```
idf(t)  = ln(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
tf      = term frequency of t in child i
denom   = tf + k * (1 - b + b * docLen[i] / avgDocLen)
score  += idf(t) * (d + tf * (k + 1)) / denom
```

**Safety note for JavaScript readers.** `df` and `postings` are keyed by words taken from crawled pages. Load them into `Map` objects, never plain objects, so a page containing the word `__proto__` cannot pollute a prototype.


## Calibration

`calibration` gives a corpus-relative sense of what a "good" similarity score is, so a client can set a relevance threshold without hand-tuning it per knowledge base.

| Field | Type | Meaning |
|---|---|---|
| `mean` | number | Mean, over a sample of children, of each child's best cosine similarity to any other child. |
| `std` | number | Standard deviation of the same values. |
| `sampleSize` | whole number | Number of children sampled, at most 500. `0` when the corpus has fewer than two children, in which case `mean` and `std` are `0`. |

A client that treats scores below `mean + margin × std` as "not relevant" adapts to each corpus. The sample is drawn with a fixed seed, so rebuilding an unchanged corpus reproduces the same numbers.


## Identifiers

A parent's `id` is the first 16 hexadecimal characters of the SHA-1 of three parts joined by a NUL byte: the normalized source URL, the parent heading, and the parent's ordinal among parents on the same page with the same heading, starting at 0.

The ordinal matters because a long section is split into several parents that share a heading. Without it those parents would share an id.

Children have no stored id. When a client or a cache needs one, it is the parent id, a hyphen, and the child's ordinal within its parent, for example `9f1c2ab3d4e5f607-2`.

Ids survive a rebuild as long as the page URL and heading are unchanged. A changed heading changes the id; that is intended, because the section is then a different section.


## Changes from version 2

Version 2 is the layout Field Station AI's `build-kb-index.py` writes. Readers of that format will notice:

- `format`, `extractium`, `embedding`, and `offsetUnit` are new. `model`, `dims`, `vecsQ`, and `vecsScale` moved inside `embedding` as `browserModel`, `dims`, `dtype`, and `scale`; `embedding.model` is the Hugging Face id.
- The `chunks` list is gone. Children are the `children` column arrays and carry no text, heading, URL, host, kind, or weight; all of that is read from the parent.
- Parents gained `id`, `source_type`, `content_type`, `categories`, and `local`. The `kind` field is replaced by `source_type`.
- The query prefix convention is stated in the file instead of assumed.

Measured on the Field Station AI index built on 2026-08-14 (2,464 parents, 5,910 children, 418 sources), the version 2 file is 10.0 MB, of which the children list alone is 3.3 MB. The same corpus in version 3 is expected to be about 6.9 MB: parents 2.4 MB, children under 0.1 MB, BM25 statistics 2.1 MB, vectors 2.3 MB.


## Versioning rule

`v` changes only when the layout changes in a way a reader cannot ignore: a moved or removed field, a new meaning for an old field, a different vector encoding. Adding an optional field does not bump `v`. Readers ignore fields they do not know.


## Checklist for a reader

1. Read the first four bytes as a little-endian unsigned 32-bit integer; call it `N`.
2. Decode bytes `4` to `4 + N` as UTF-8 and parse the JSON object.
3. Refuse the file unless `format` is `extractium-compendium` and `v` is `3`.
4. Refuse the file unless `embedding.model` and `embedding.dims` match the embedder you will use for queries.
5. Copy the remaining bytes into a fresh buffer and check the length against `len(children.pid) × embedding.dims × width(dtype)`.
6. Load `bm25.df` and `bm25.postings` into map structures, not plain objects.
7. Treat `calibration` as optional: if `sampleSize` is `0`, fall back to a fixed threshold.
8. Prefix every query with `embedding.queryPrefix` before embedding it. Never prefix a passage.


## Conclusion

You can now read or write an Extractium container in any language: four bytes of length, a JSON header, and raw vectors. Keep the token rule, the query prefix, and the offset unit exactly as stated, and your client will rank the same way the reference clients do. For how the file is produced, read the [specification](extractium-spec.md); for when the writer and the clients land, read the [implementation plan](implementation-plan.md).


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Extractium™ specification](extractium-spec.md) — architecture, data model, outputs, and sources.
* [Implementation plan](implementation-plan.md) — the phase in which this format is written and read.
* [tests/reference/build_kb_index_reference.py](../tests/reference/build_kb_index_reference.py) — the frozen version 2 writer this format replaces.
* [BAAI bge-small-en-v1.5 model card](https://huggingface.co/BAAI/bge-small-en-v1.5) — the default embedding model and its query instruction.
* [Okapi BM25 on Wikipedia](https://en.wikipedia.org/wiki/Okapi_BM25) — background on the keyword score.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
