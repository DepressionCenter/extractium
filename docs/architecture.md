<!--
This file is part of Extractium™
docs/architecture.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-04
Summary: How the Extractium codebase is put together today, which parts
are finished, and the design decisions still open, each with a
recommendation and what it would cost to change later.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Architecture and Current State

[← Back to README](../README.md)


## Summary

This page describes the code as it stands, not the finished design. It says which modules work, which are empty placeholders, and which decisions are still open. Read it before you add to the engine, so you do not build on top of a question nobody has answered yet.

The target design is in [the specification](extractium-spec.md). Where this page and the specification disagree, the specification says what is intended and this page says what exists.


## How the pieces fit

Extractium is one Python package with three layers. Source plugins gather documents, one core engine turns them into searchable chunks, and adapter plugins write each output format. Everything runs offline against flat files: no server, no database, no cloud calls.

The rule that shapes the whole design: **one crawl and one embedding pass per build**. Fetching, chunking, and embedding happen once. Every output format is then a cheap serialization of the same result. An adapter that re-fetched or re-embedded would break the design's main promise.


## What exists today

The engine was extracted from a single-file script, which is kept frozen at [tests/reference/build_kb_index_reference.py](../tests/reference/build_kb_index_reference.py) as the yardstick the port is measured against. Each ported module has tests that pin its behavior to that original.

| Part | File | State |
|---|---|---|
| Settings | `extractium/config.py` | Working. Loads and checks `config.yaml`. See the [configuration reference](configuration.md). |
| Fetch and cache | `extractium/core/fetch.py`, `core/cache.py` | Working. Conditional GET, on-disk page cache, URL scope rules. |
| Chunking | `extractium/core/chunk.py` | Working. Content extraction, parent sections, child windows. |
| Scoring | `extractium/core/embed.py`, `dedup.py`, `bm25.py`, `calibration.py` | Working, each on its own. Nothing runs them in order yet. |
| Crawl loop | — | Not ported. Still only in the frozen reference script. |
| Index assembly | — | Not written. See open decision 1. |
| Plugin registry | `extractium/core/registry.py` | Placeholder file. |
| PHI check | `extractium/core/phi_lint.py` | Placeholder file. |
| Source plugins | `extractium/sources/*.py` | Placeholder files. |
| Adapters | `extractium/adapters/*.py` | Placeholder files. |
| Command line | `extractium/cli.py` | Prints a notice. Runs no build. |

A placeholder file holds the license header and a summary of what it will contain, and nothing else. It is not a partly finished module.


## Open design decisions

Three questions are worth settling before the next block of work, because each one is cheap to decide now and expensive to change once code depends on it. Each is also flagged as a `TODO` comment in the file it affects.


### 1. Where the boundary sits between building an index and writing one

The original script's `build_index()` does two jobs in one function: it embeds and scores the chunks, then writes the binary container file.

**Recommendation: split them.** Core should gain one build step that embeds the children, drops near-duplicates, remaps parents, builds the BM25 postings, computes the calibration statistics, and returns `(parents, children, meta)`. The container adapter then only turns that into bytes.

**Why:** four output formats are planned, and all four need the same scored data. If scoring lives inside the container writer, the second adapter either duplicates it or re-runs the embedding model, and the "one embedding pass" rule is lost. The split also makes scoring testable without writing a file.

**Cost of deciding later:** every adapter written before the split has to be reworked.


### 2. How the crawl loop is shaped when it is ported

The original `crawl()` builds its own `requests.Session()` and reports progress with `print()`.

**Recommendation: take the session as a parameter, and report progress through a callback the caller supplies.**

**Why:** a function that builds its own session can only be tested by monkeypatching the `requests` module, which reaches past the code under test and into a third-party library. The test suite already carries a fixture that does exactly this for the frozen script; the port should not need it. Progress reporting has three audiences with different needs: a person watching a double-click run, a CI log, and a library caller who wants no output at all. A callback serves all three; `print()` serves the first only.

**Cost of deciding later:** low for the callback, higher for the session, because every test written against the old shape has to change.


### 3. Whether chunk identifiers become stable now or later

The specification requires identifiers that survive a rebuild: a parent's id is a hash of its URL and heading path, and a child's id comes from its parent's id plus a number. The current code has no identifiers at all. It links a child to its parent by position in a list.

**Recommendation: add stable identifiers with the crawl port, not after it.**

**Why:** positional links are fragile in exactly the situation the tool is built for. Re-crawl a site, have one section disappear, and every parent after it shifts by one. Anything that stored a reference to a chunk (a saved answer, a cached enrichment, a bookmark) now points at the wrong text, silently. Stable identifiers are also what the planned delta builds and enrichment cache need to match old work to new content.

**Cost of deciding later:** the committed test snapshots in [tests/golden/](../tests/golden/) have to be regenerated, and every consumer of a published index has to re-download it. Both get more expensive with every week the format is in use.

Note that this is the one open decision that deliberately breaks equality with the frozen reference script. That is intended, and the specification already calls for it, but it means the characterization tests for chunk building need a documented exception rather than a silent update.


## Conclusion

The core engine works, the settings layer works, and the wiring between them does not exist yet. The next block of work is the crawl loop, the index assembly step, and the plugin registry, in that order. Settle the three decisions above first: each one is a comment today and a rewrite later.


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Extractium™ specification](extractium-spec.md) — the intended design, data model, and roadmap.
* [Configuration reference](configuration.md) — every setting in `config.yaml`.
* [tests/reference/build_kb_index_reference.py](../tests/reference/build_kb_index_reference.py) — the frozen original the port is measured against.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
