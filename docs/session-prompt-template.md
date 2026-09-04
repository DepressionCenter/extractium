<!--
This file is part of Extractium™
docs/session-prompt-template.md
Author(s): Gabriel Mongefranco
Created: 2026-09-04
Last Modified: 2026-09-04
Summary: A fixed, copy-and-paste opening for any AI coding session on
this repository: what the project is, which files to read before
changing anything, the branch and pull request workflow, and the
standing constraints. The request itself goes at the end.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Session Prompt Template

[← Back to README](../README.md)


## Summary

Every AI coding session on this repository starts the same way: the agent must know what the project is, read the settled design before touching code, work on a branch, and finish with a pull request. This page holds that opening as one block you copy without editing. Your own request, whether a plan phase, an enhancement, or a bug fix, goes on the last line. It is written for the maintainer who runs the sessions.


## How to use it

1. Copy the block below into a new chat, unchanged.
2. Replace the last line with what you want done. One or two sentences is enough: "Execute Phase 2 of the implementation plan", or "The loader accepts a negative delay_seconds when written as a string; fix it".
3. Review the breakdown the agent shows before it writes code. Correct it there; that is the cheapest moment.
4. When the pull request arrives, review it and merge it yourself.


## The prompt

```text
This is Extractium (c:\git\extractium), a knowledge-base compiler extracted from
FieldStationAI. It crawls an organization's public documentation and builds one
static file holding text, vectors, and keyword statistics that a browser, a
script, or a small server can search with no database and no API. Follow
AGENTS.md; it overrides your defaults. The design and the order of work were
settled on 2026-09-04 and are recorded in the repository; do not re-open them.

Read, in this order, before changing anything:
1. AGENTS.md (the rules for every change: engineering style, file headers,
   comments, security, accessibility, documentation, response format)
2. docs/implementation-plan.md (the phases, their done-when rules, and the
   "finished" notes that say which phases are complete)
3. docs/architecture.md (what exists today, what is a placeholder, and the
   eight settled design decisions with the specification section for each)
4. docs/configuration.md and examples/config.example.yaml (the settings file)
5. docs/extractium-spec.md, the sections the plan or the architecture page
   point at for the work in hand
6. extractium/core/models.py and extractium/core/registry.py (the records and
   protocols every plugin and build step is built on), then the modules the
   task touches; a placeholder module's TODO comment describes the capability
   it must hold
7. tests/conftest.py and the test files nearest the task (patterns and
   fixtures to reuse); the frozen original the port is measured against is
   tests/reference/build_kb_index_reference.py

Branch and pull request workflow:
- Start from an up-to-date main: git switch main, then git pull. Never commit
  to main.
- Create one branch for the task and do all work there. Name it
  phase-<number>-<short-name> for a plan phase, fix-<short-name> for a bug,
  or feat-<short-name> for an enhancement.
- Commit each coherent piece as it is finished. Commit messages describe the
  capability added or the defect removed, never a plan step.
- When the work is done and the full test suite passes, push the branch and
  open a pull request against main with gh. The title names the phase or the
  change; the body lists what changed, the verification you ran, and anything
  the reviewer should check by hand. Do not merge; I merge after review.
- If the task has to be split, open the pull request for the finished part
  and say exactly what was left out and why.

Constraints: keep to the task as asked; a plan phase is about one week of
work, so split rather than grow. The full test suite must pass at the end.
Update the affected /docs pages in the same change set. Comments describe
capabilities, never plan steps or this conversation. Do not touch
FieldStationAI. Never merge, force-push, rebase, or delete branches. Start by
running git status and pytest, then show me your breakdown before writing
code.

My request:
```


## Conclusion

You can now start any session with one paste and one sentence, and get back a branch, a breakdown to approve, and a pull request to review. Keep this page in step with the repository: when the reading order, the workflow, or the constraints change, change them here first.


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [AGENTS.md](../AGENTS.md) — the rules every session follows.
* [Implementation plan](implementation-plan.md) — the phases and their done-when rules.
* [Architecture and Current State](architecture.md) — what exists, the settled decisions, and the current test count.
* [Configuration reference](configuration.md) — the settings file.
* [Extractium™ specification](extractium-spec.md) — the design each phase builds toward.
* [GitHub CLI manual](https://cli.github.com/manual/) — the `gh pr create` command the workflow uses.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
