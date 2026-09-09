<!--
This file is part of Extractium™
docs/compliance.md
Author(s): Gabriel Mongefranco
Created: 2026-09-08
Last Modified: 2026-09-09
Summary: The security, privacy, and accessibility posture of Extractium as
it stands today: the controls that exist and where they live in the code,
the evidence for each, the known gaps, and what still needs institutional
review.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Compliance and Posture

[← Back to README](../README.md)


## Summary

This page states what Extractium does today to keep content, credentials, and readers safe, and where each control lives so a reviewer can check it. It also states what is not built yet and what no code review can settle. It claims nothing beyond what the repository shows. Read it before you publish anything, and again before you point the tool at content that is not already public.

**Extractium makes no compliance claim.** It is a tool for building an index of documents you already have the right to read and publish. Whether a particular use meets HIPAA, an IRB protocol, or a data use agreement is a decision for your privacy office, not for this page.


## What the tool is for

Extractium reads public documentation, turns it into a searchable file, and publishes that file. The normal case involves no personal information at all. The care below exists because the tool can also read a local folder, and because a crawler that misbehaves is a problem even when the content is public.


## Controls in place

| Control | Where | Evidence |
|---|---|---|
| Content from a local folder is left out of every output unless that output opts in | `extractium/adapters/base.py`, `output_compendium` | `tests/test_adapter_container.py` checks that a local section is absent by default, that its text does not appear anywhere in the header, and that keyword statistics and vectors are rebuilt to match. |
| The build says so when an output does include local content | `extractium/cli.py` | Covered by the command-line tests in `tests/test_cli.py`. |
| A local source cannot reach outside the folder it was pointed at | `extractium/sources/local.py`, `matching_files` | A file whose real location is outside the folder is skipped and the reason is printed. `tests/test_source_local.py` covers a symbolic link out of the tree. |
| No absolute path from the operator's disk reaches an output | `extractium/sources/local.py`, `relative_url` | Every local document's URL is `local:` plus a path relative to the source folder. Pinned in `tests/test_source_local.py`. |
| Content is checked for likely identifiers before anything is published | `extractium/core/phi_lint.py` | 26 rules covering the HIPAA Safe Harbor identifiers a pattern can reach. `tests/test_phi_lint.py` exercises every rule and checks that ordinary documentation is not flagged. |
| The check's reports never copy what they found, and never leave the working folder | `extractium/core/phi_lint.py`, `write_reports` | `tests/test_phi_lint.py` checks, for every rule, that the matched text appears in neither report, and that both are written where the build was run rather than under `out_dir`. |
| The check never states an absence of protected health information | `extractium/core/phi_lint.py`, `ZERO_MATCH_SENTENCE` | A clean scan reports "0 pattern matches (this does not confirm absence of PHI)". `tests/test_phi_lint.py` pins the sentence and checks the forbidden phrasing against the module source as well as its output. |
| The crawler identifies itself truthfully | `extractium/core/fetch.py`, `DEFAULT_USER_AGENT` | The default names the tool and its repository. It is a setting, not a hard-coded string. |
| `robots.txt` is honored, and a site whose rules cannot be read is skipped entirely | `extractium/core/fetch.py`, `RobotsPolicy` | `tests/test_core_fetch.py` covers a disallow, a missing file, and an unreadable one. Failing closed is deliberate. |
| The crawl waits between requests | `delay_seconds` setting, default 0.5 seconds | Documented in the [configuration reference](configuration.md). |
| A crawl cannot wander off the site it was pointed at | `extractium/core/fetch.py` scope rules, plus include and exclude patterns | `tests/test_core_scope.py`. |
| No credentials in the repository or in a settings file | Settings schema | The configuration loader has no field for a token. Sources that need one read it from the environment. |
| Dependencies are pinned and hash-checked | `requirements-lock.txt` | Generated with `uv pip compile --universal --generate-hashes`. Both run scripts and both workflows install with `--require-hashes`, so a package whose contents do not match what was locked is refused. `tests/test_operations.py` checks that every pinned package carries a hash. |
| The scheduled build asks for the least access it can | `.github/workflows/build-compendium.yml` | `contents: read` for the workflow; `pages: write` and `id-token: write` for the publishing job alone. Publishing goes through GitHub's own Pages actions only. `tests/test_operations.py` pins all of this. |
| An AI agent is told to treat indexed text as evidence, never as instructions | `SKILLS.md` | The rule is stated in the file an agent is pointed at. |
| Every output records how it was made | Container header, `llms.txt` preamble | Model, dimensions, query prefix, build time, and tool version, so a stale or mismatched file is detectable rather than silently wrong. |
| A client refuses a file it cannot read correctly | `extractium/search.py`, `clients/js/extractium-client.js` | Both implement every check in the [container format](container-format.md) reader checklist. `tests/test_search.py` and `clients/js/extractium-client.test.js` cover each refusal. |


## Known gaps

These are real and current. None is hidden behind a setting.

- **The check for protected health information reads shapes, not meaning.** It finds an identifier that looks like one: a number with a check digit, or a value sitting next to a word such as "Patient" or "Serial number". It does not recognise a person's name or a place name written in ordinary prose, with no label nearby. A clean result is not evidence of anything.
- **Adding that recognition would mean adding a language model.** The libraries that do it well need a model of several hundred megabytes, and the one that reads addresses needs a C library with no simple install on Windows. That is a large, fragile dependency for a check that only ever flags something for a person to read, so the project does without it and states the gap here instead. Revisit the trade if a build is ever pointed at clinical free text rather than documentation.
- **The check does not read images, PDFs, or spreadsheets.** Neither does the build, so nothing from them reaches an output; but a folder holding them is not covered by the report.
- **No security scanning runs in continuous integration.** There is no dependency-audit or code-scanning workflow in this repository yet.
- **The scheduled workflow has not been observed running.** It is written and its shape is tested, but as of 2026-09-08 no run has completed on GitHub. Treat the first run as a check to perform, not a result to rely on.
- **Actions are pinned to a major version, not to a commit.** `actions/checkout@v4` follows that major line. Pinning to a commit digest is stricter and is worth doing if your organization requires it.
- **Accessibility has been reviewed by hand only.** See below.


## Handling research and health data

Assume any content you point the tool at may hold protected health information unless you know it does not.

- Source data is never modified. Extractium reads and writes copies.
- Identifiers do not belong in a published index. The safest position, and the default, is that local content is never published.
- Nothing in this repository has been reviewed by an IRB, a privacy office, or Information Assurance. If your use involves participant data, that review is a prerequisite, not a formality.
- Publishing to GitHub Pages makes a file readable by anyone with the address. There is no "unlisted" tier.


## Accessibility

The tool has no graphical interface. What a person reads is the command-line output and this documentation.

**Target:** WCAG 2.1 AA for the documentation, with the reading-level goal in the project's writing guidance.

What has been done:

- Documentation uses real headings in order, real lists, and pipe tables with header rows. No structure is conveyed by bold text alone.
- Command-line output carries no color and no symbol as its only meaning: every state is words.
- Progress goes to the error stream and results to the output stream, so a screen reader user can capture one without the other.
- Exit codes distinguish each failure, so a build can be checked without reading a log.

What has not been done:

- No automated accessibility scan has been run against the rendered documentation. There is no rendered site for this repository yet; the pages are read on GitHub, which supplies its own markup.
- Contrast and zoom behavior are properties of whatever renders these files, not of the files themselves.

Anyone publishing an interface over a compendium, a search page for instance, owns its accessibility. The clients impose nothing.


## Data retention

Extractium keeps nothing of its own beyond two folders, both under your control:

| What | Where | How long |
|---|---|---|
| Fetched pages | `.kb_cache`, next to your settings file unless you change it | Until you delete it. Deleting it costs time on the next build and nothing else. |
| Build output | `dist` unless you change it | Until you delete or overwrite it. Each build rewrites the folder. |

Neither folder should be committed. Both are in the `.gitignore` files that ship here.


## Review status

| Item | Status |
|---|---|
| Test suite | 564 Python tests and 36 Node tests passing as of 2026-09-08. |
| Security review by a second person | Not done. |
| Privacy, IRB, or Information Assurance review | Not done, and needed before any use involving participant data. |
| Accessibility audit with an automated tool | Not done. |
| Penetration testing | Not applicable: the tool is a local program with no service of its own. |


## Conclusion

Today's posture is: publish public content, keep local content out by default, install only what was locked, and ask for the least access a scheduled build needs. The gaps above are named rather than papered over. Update this page in the same change set as any work that alters one of them.


## Additional Resources

* [Extractium™ README](../README.md) — project overview and quick start.
* [Data Flow](data-flow.md) — where content enters, how it changes, and where private content is kept out.
* [How to Publish to GitHub Pages](how-to/publish-to-github-pages.md) — what publishing means and the permissions involved.
* [Configuration Reference](configuration.md) — every setting, including the crawler etiquette settings.
* [Implementation Plan](implementation-plan.md) — when the missing pieces above are scheduled.
* [OWASP Application Security Verification Standard](https://owasp.org/www-project-application-security-verification-standard/) — the checklist used for anything handling untrusted input.
* [Web Content Accessibility Guidelines 2.1](https://www.w3.org/TR/WCAG21/) — the accessibility target named above.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
