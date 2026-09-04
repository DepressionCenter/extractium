<!--
This file is part of Extractium™
docs/architecture.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-04
Summary: How the Extractium codebase is put together today, which parts
are finished, and the design decisions that have been settled, each with
the reason and a pointer to where it is specified.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Architecture and Current State

[← Back to README](../README.md)


## Summary

This page describes the code as it stands, not the finished design. It says which modules work, which are empty placeholders, and which design decisions are settled so that nobody builds on a question that has already been answered a different way. Read it before you add to the engine.

The target design is in [the specification](extractium-spec.md) and the order of work is in the [implementation plan](implementation-plan.md). Where this page and the specification disagree, the specification says what is intended and this page says what exists.


## How the pieces fit

Extractium is one Python package with three layers. Source plugins gather documents, one core engine turns them into searchable chunks, and adapter plugins write each output format. The web source, which is the core crawler, asks small site-handler plugins how to read each kind of page it visits. Everything runs offline against flat files: no server, no database, no cloud calls.

The rule that shapes the whole design: **one crawl and one embedding pass per build**. Fetching, chunking, and embedding happen once. Every output format is then a cheap serialization of the same result. An adapter that re-fetched or re-embedded would break the design's main promise.


## What exists today

The engine was extracted from a single-file script, which is kept frozen at [tests/reference/build_kb_index_reference.py](../tests/reference/build_kb_index_reference.py) as the yardstick the port is measured against. Each ported module has tests that pin its behavior to that original.

| Part | File | State |
|---|---|---|
| Settings | `extractium/config.py` | Working, for the single-seed form. Loads and checks `config.yaml`. See the [configuration reference](configuration.md). |
| Fetch and cache | `extractium/core/fetch.py`, `core/cache.py` | Working. Conditional GET, on-disk page cache, URL scope rules. |
| Chunking | `extractium/core/chunk.py` | Working. Content extraction, parent sections, child windows. Host-specific branches still live here. |
| Scoring | `extractium/core/embed.py`, `dedup.py`, `bm25.py`, `calibration.py` | Working, each on its own. Nothing runs them in order yet. |
| Crawl loop | — | Not ported. Still only in the frozen reference script. |
| Build step | — | Not written. |
| Plugin registry | `extractium/core/registry.py` | Placeholder file. |
| PHI check | `extractium/core/phi_lint.py` | Placeholder file. |
| Sources and site handlers | `extractium/sources/*.py` | Placeholder files. |
| Adapters | `extractium/adapters/*.py` | Placeholder files. |
| Clients | — | Not started. The retrieval code to extract still lives in Field Station AI's `index.html`. |
| Command line | `extractium/cli.py` | Prints a notice. Runs no build. |

A placeholder file holds the license header, a summary of what it will contain, and a `TODO` comment describing the capability, and nothing else. It is not a partly finished module.

The test suite passes: 176 tests as of 2026-09-04.


## Settled design decisions

Each decision below was open at some point and is now fixed. Each one is cheap to follow now and expensive to reverse once code depends on it. The specification section given is the authority; this list is the short version.


### 1. Building an index and writing one are separate steps

The original script's `build_index()` embeds and scores the chunks, then writes the container in the same function.

**Decision:** core gains one build step that embeds the children, drops near-duplicates, remaps parents, builds the BM25 postings, computes the calibration statistics, and returns one `Compendium` record. Adapters only turn that record into files.

**Why:** several output formats need the same scored data. If scoring lived inside the container writer, every other adapter would duplicate it or re-run the model, and the one-embedding-pass rule would be lost. The split also makes scoring testable without writing a file.

Specification: section 2, key invariants.


### 2. The crawl loop takes its session and reports through a callback

The original `crawl()` builds its own `requests.Session()` and reports progress with `print()`.

**Decision:** the loop takes the session as a parameter and reports progress through a callback the caller supplies.

**Why:** a function that builds its own session can only be tested by monkeypatching the `requests` module, which reaches past the code under test. Progress has three audiences with different needs: a person watching a double-click run, a CI log, and a library caller who wants silence. A callback serves all three.

Specification: section 2.1, the source protocol.


### 3. Chunk identifiers are stable, and they include an ordinal

The current code has no identifiers. It links a child to its parent by position in a list, which shifts whenever a section disappears on re-crawl.

**Decision:** a parent's id is a hash of its URL, its heading, and its ordinal among parents on the same page with the same heading. A child's id is derived from its parent's id and its own ordinal. Ids are added with the crawl port, not after it.

**Why:** the ordinal is needed because a long section is cut into several parents that share a heading; without it they would share an id. Stable ids are what saved answers, cached enrichment, and future delta builds use to match old work to new content.

This decision deliberately breaks equality with the frozen reference script for the id fields only. The characterization tests for chunk building carry a documented exception rather than a silent update.

Specification: section 3.3.


### 4. One web crawler, pluggable site handlers, three plugin kinds

The v0.1 specification listed `web`, `tdx`, and `github` as three source plugins. The code is one crawler with host-specific branches, and the crawl is one graph: a knowledge-base article links to a repository README and the same queue must follow it.

**Decision:** the generic crawler is core. TeamDynamix and GitHub handling become site handlers: plugins the crawler consults per URL, shipped enabled, switchable off in configuration. Sources, site handlers, and adapters are the three plugin kinds, all resolved by one registry in the order local `plugins/` folder, installed entry points, built-ins.

**Why:** the split keeps one loop and one link graph while moving every host-specific line out of core, which is what makes the tool usable by an organization that has no TeamDynamix portal and no GitHub.

Specification: sections 2.1 to 2.3.


### 5. The configuration file lists sources and outputs

Today's loader accepts one `seed_url` and a handful of crawl settings.

**Decision:** the file becomes a `sources:` list and an `outputs:` list plus global settings, before any code beyond the loader depends on the old shape.

**Why:** a second source type or a second output cannot be expressed in the flat form. Changing it now costs one module and its tests; changing it later costs every caller.

Specification: section 12.


### 6. The container is version 3 from the first release

Field Station AI's version 2 file duplicates every child's text, heading, URL, and facets. Measured on the real index, that is a third of a 10 MB file, and no search step reads it.

**Decision:** Extractium writes version 3 only: children are column arrays of parent index and character offsets, and everything else is read from the parent. Field Station AI keeps its own version 2 file and is unaffected; moving it to the Extractium client is a later task in that repository.

**Why:** there is no compatibility obligation to carry the waste, and doing it now avoids a migration later.

Specification: section 4 and the [container format](container-format.md) page.


### 7. Local content stays out of every output unless the output opts in

The v0.1 rule excluded local content from web-facing formats but let the container and SQLite include it. The container is exactly the file that gets published.

**Decision:** every adapter drops local parents by default. An output opts in with `include_local: true`, and the command line names each output that contains local content.

**Why:** publishing is the normal use of every output. The safe default is the one that cannot leak by omission.

Specification: section 7.


### 8. The crawler identifies itself and honors `robots.txt`

The reference script sends a browser User-Agent and never reads `robots.txt`.

**Decision:** the default User-Agent names the tool and its repository; `robots.txt` is honored unless switched off; both are settings. Whether the TeamDynamix portal serves article HTML to the truthful agent is checked before the crawler ships.

**Why:** a tool distributed to other organizations should not spoof a browser by default. The check exists because some portals do serve different pages to non-browser agents, and the answer belongs in the documentation, not in a surprise.

Specification: section 6.


## Conclusion

The core modules work, the settings layer works for one source, and the wiring between them does not exist yet. The next block of work is the configuration schema, the registry, and the data models, then the crawl loop and site handlers, then the build step and the first two adapters. That order, with a done-when rule for each step, is the [implementation plan](implementation-plan.md).


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Extractium™ specification](extractium-spec.md) — the intended design, data model, and plugin protocols.
* [Implementation plan](implementation-plan.md) — the phased order of work.
* [Container format](container-format.md) — the flagship output, byte by byte.
* [Configuration reference](configuration.md) — every setting in `config.yaml` as it exists now.
* [tests/reference/build_kb_index_reference.py](../tests/reference/build_kb_index_reference.py) — the frozen original the port is measured against.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
