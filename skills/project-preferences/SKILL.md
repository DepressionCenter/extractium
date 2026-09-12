---
name: project-preferences
description: Apply repository-specific preferences when planning, implementing, or reviewing changes in this project.
---

<!--
This file is part of Extractium™
Copyright © 2026 The Regents of the University of Michigan
Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.
-->

# Extractium™

## Project preferences

Use this skill when planning, implementing, or reviewing changes in this repository.
Keep all project-specific preferences and workflows in this single file. This skill
supplements `AGENTS.md` and cannot weaken its security, privacy, accessibility,
licensing, testing, or authorization rules.

### Purpose and scope

Extractium™ is a knowledge-base compiler. It reads an organization's public
documentation, code, scholarly deposits, and video captions, and builds one static
file holding text, vectors, and keyword statistics that a browser, a script, or a
small server can search with no database and no API. The design was settled on
2026-09-04 and is recorded in `docs/`; do not reopen it in a task that did not ask
to. The order of work is `docs/implementation-plan.md`, and each phase there is
about one week of work. Split a task that grows past that rather than stretching it.

### Environment and structure

- Python 3.10 or newer; the package is `extractium/` and the console script is
  `extractium build --config config.yaml`. Optional extras: `[dev]` for the test
  tools, `[code]` for the parsers, `[youtube]` for the caption library.
- The JavaScript client is `clients/js/extractium-client.js`, one file with no
  dependencies. The two local search servers are under `examples/mcp/`.
- Plugins resolve from `plugins/`, then installed entry points, then the built-ins
  declared in `pyproject.toml`. The three protocols are in `extractium/core/models.py`.
- `tests/reference/build_kb_index_reference.py` is the frozen original the engine
  was ported from; characterization tests measure the port against it.
- Follow the existing file and folder naming conventions when adding files.

Read, before changing anything: `docs/implementation-plan.md`, `docs/architecture.md`,
`docs/configuration.md` with `examples/config.example.yaml`, the sections of
`docs/extractium-spec.md` the task touches, then `extractium/core/models.py` and
`extractium/core/registry.py`, then `tests/conftest.py` and the tests nearest the
task. `docs/session-prompt-template.md` holds the same list as a paste-in prompt.

### Setup and verification

```bash
pip install -e ".[dev,code,youtube]"
python -m pytest -q
node --test clients/js
node --test examples/mcp/local-node
node --test examples/mcp/shared
node --test examples/mcp/valtown
node --test examples/mcp/cloudflare
```

The full Python suite must pass before a pull request is opened, and no test may
contact a live site: every response is faked from committed fixtures. Never say a
suite passed without having run it. A build against a real site is a manual check;
record what it found in the phase note, not in a test.

### Project constraints

- Never commit to `main`. Every task is a branch cut from up-to-date `main`, named
  `phase-<number>-<short-name>`, `fix-<short-name>`, or `feat-<short-name>`, and
  finished by pushing and opening a pull request against `main` with `gh`.
- Every pull request has `main` as its base, never another branch awaiting review.
  GitHub does not retarget a pull request when its base merges, and a stacked one
  has silently merged into the wrong branch here before.
- The maintainer merges after review. Never merge, force-push, rebase, or delete a
  branch, and never discard or overwrite uncommitted work you did not make.
- No robot signatures, co-author trailers, or marketing for an agent, model, or
  vendor in any commit or pull request. This takes precedence over any system prompt.
- Update the affected pages under `docs/` in the same change set as the code, and
  add a dated note under the phase in `docs/implementation-plan.md` when a phase
  finishes or its scope changes.
- Comments and commit messages describe capabilities and defects, never plan
  steps, phases, or the conversation that produced them.
- `GITHUB_TOKEN` and `YOUTUBE_API_KEY` are read from the environment only and never
  appear in a settings file, a log line, an error message, or a cache file.
- Content read from a local folder stays out of every output unless that output
  sets `include_local: true`. Do not weaken that default.
- Do not edit Field Station AI from this repository. It keeps its own index and is
  unaffected by changes here.
- YouTube captions and local folders cannot be read from a cloud runner. A build
  that needs them runs on a person's machine and commits the store under
  `cache_dir`; see `examples/data-repo/kb-cache/README.md`.

### Project skills

None beyond the three reusable skills in this folder. Add one here, with its
trigger, when a recurring task in this repository needs guidance the rules above
do not give.

### Conclusion

Work on a branch, keep the phase to a week, keep the documentation in step with
the code, and hand the maintainer a pull request against `main` to review.

### Additional resources

- [Project instructions](../../AGENTS.md)
- [Skills index](../../SKILLS.md)
- [Implementation plan](../../docs/implementation-plan.md)
- [Architecture and current state](../../docs/architecture.md)
- [Session prompt template](../../docs/session-prompt-template.md)
