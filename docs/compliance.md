<!--
This file is part of Extractium™
docs/compliance.md
Author(s): Gabriel Mongefranco
Created: 2026-09-08
Last Modified: 2026-09-11
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
| A GitHub access token stays in the request headers | `extractium/sources/github_client.py` | The token is read from `GITHUB_TOKEN` only, travels in one header, and reaches no URL, log line, error message, or cache file. `tests/test_github_client.py` checks the header, the absence of the token from the request address, and the contents of every file the blob cache writes. |
| A build reads only the GitHub accounts it was told to read | `extractium/sources/github.py`, `allows`; `extractium/cli.py` | Deny by default: the allowed set is built from the build's own sources plus the `github_owners` setting, and covers `github.com`, `raw.githubusercontent.com`, and `<account>.github.io`. `tests/test_github_account_scope.py` covers a linked account being kept out of an actual crawl, and `tests/test_config.py` covers the refusal of a pattern in the allowlist. |
| A private repository is never indexed, even when the token could read it | `extractium/sources/github_api.py`, `_wanted` | A token raises the request budget; it does not widen what may be published. Pinned in `tests/test_source_github_api.py`. |
| Names and identifiers from an API response are checked before they are used | `extractium/sources/github_client.py`, `_checked`, `_checked_ref`; `extractium/core/cache.py`, `github_blob_path` | An account name, repository name, branch, or blob SHA that could change which endpoint is reached, or name a path outside the cache, is refused. Covered by parametrised tests in `tests/test_github_client.py`. |
| A repository archive is read in memory and never extracted to disk | `extractium/sources/github_client.py`, `_files_from_archive` | This is the normal way a repository is read, so it carries the checks accordingly. Only regular files are read, archive paths are compared and never joined onto a real directory, and a path that climbs out matches nothing. Reading uses the standard library, with no external `tar` program and no shell, and creates no symbolic link, so the behaviour is the same on Windows, macOS, and Linux. `tests/test_github_client.py` covers a symbolic link, a traversal path, an oversized archive, and content that is not text; the suite runs on Windows. |
| Source files, lock files, and anything holding a credential are never downloaded from a repository | `extractium/sources/github_files.py` | `.env`, private keys, certificates, binaries, and generated folders are filtered from the inventory before any request. `.env.example` is the deliberate exception. Covered in `tests/test_source_github_api.py`. |
| Nothing a repository holds is executed to read it | `extractium/code/` | Tree-sitter and Universal Ctags parse bytes. No script is run, no module imported, no build file executed, no dependency installed, and no container started. A file being indexed may also carry text aimed at an AI agent; it is recorded as content and acted on never. `tests/test_code_analysis.py` pins the second half of that. |
| Universal Ctags is run with an argument array, no shell, and no configuration file | `extractium/code/ctags.py`, `_run` | The command is a list handed to the operating system, so nothing in a file name is ever read as a command, and `--options=NONE` keeps a configuration file -- in the repository or on the machine -- from defining a parser this code knows nothing about. A program that is not Universal Ctags, or that speaks no JSON, is not used at all. `tests/test_code_analysis.py` runs a fake program and checks the arguments it received. |
| A repository path never names a file this project writes | `extractium/code/ctags.py`, `_write_temporary` | A file handed to Ctags gets a generated name in the system temporary folder, carrying only the extension. A path holding a traversal sequence, a shell character, a newline, or a space changes nothing about where the file goes, and the record still names the real path. Covered by parametrised tests in `tests/test_code_analysis.py`. |
| Another program's output is checked before any of it is used | `extractium/code/ctags.py`, `_symbols_from` | Each line must be one JSON object of the type Ctags uses for a tag, carrying a name and a kind this code recognizes. Anything else is dropped rather than guessed at, and a nonsensical line number becomes the first line. Covered in `tests/test_code_analysis.py`. |
| A notebook's saved outputs are never read | `extractium/code/embedded.py`, `read_notebook` | Outputs can hold printed rows of real participant data. Only Markdown cells and code cells are read. `tests/test_code_analysis.py` checks that a marked string in a fixture's outputs reaches neither the prose, the parsed code, nor the rendered record. |
| No source body reaches an index | `extractium/code/tree_sitter.py`, `_signature`; `extractium/code/render.py` | A signature is read as the definition up to its body, which is what guarantees a body is never recorded, and a long constant value becomes an ellipsis. A record links to its lines on GitHub instead of copying them. Covered in `tests/test_code_analysis.py`. |
| A file summary is a quotation or a count, never a description nobody wrote | `extractium/code/render.py`, `summary_for` | Four sources in order: the file's own documentation, the `Summary:` line in its header, the README in its folder, and a sentence counted off the parse. Each is pinned in `tests/test_code_analysis.py`. |
| A guessed relationship is labelled as one | `extractium/code/relationships.py` | A call is `resolved` only inside the file that defines it, `probable` through an import that file declares, and `unresolved` otherwise -- and an unresolved call carries no file at all. Ctags results carry no imports and no calls, because Ctags produces none. Covered in `tests/test_code_analysis.py`. |
| The parser dependencies are optional, pinned, and license-checked | `pyproject.toml`, `code` extra | Fourteen packages, every one MIT-licensed and compatible with GPL v3 or later, each pinned to a version range, each shipping wheels for Windows, macOS, and Linux with no compiler and no run-time download. A bundle offering 371 languages was rejected for fetching compiled grammars from the network on first use. The check was run on 2026-09-10 and is recorded in [GitHub repository indexing](github-repository-indexing.md). |
| A build reads only the repository collections it was told to read | `extractium/config.py`, `_read_dspace_source`; `extractium/sources/dspace.py`, `_collection` | Collections are listed, never discovered, and each is confirmed to exist before anything is searched. This matters more than it looks: a search scope a DSpace interface does not recognize is answered with every deposit in the repository rather than refused, so confirming first is what keeps a mistyped identifier from indexing a whole university's holdings. `tests/test_source_dspace.py` pins the order of the two requests and the refusal of an identifier that is not a UUID. |
| Identifiers and addresses from a repository response are checked before they are used | `extractium/sources/dspace_client.py`, `_checked_uuid`, `_content_path`, `_collection_uuid_from`; `extractium/core/cache.py`, `deposit_text_path` | A deposit or collection identifier that is not a UUID never reaches a request path or a cache file name. A file address is downloaded only when it is a deposited file's contents on the configured interface, so a response cannot send a build's requests to another host, and a handle lookup that points off that interface is refused rather than followed. Covered in `tests/test_source_dspace.py`. |
| Nothing is parsed or unpacked to read a deposit's contents | `extractium/sources/dspace.py`, `_text_for` | Only the plain text the repository extracted when the file was deposited is read. There is no PDF, Word, or archive reader in the build, so there is no malformed-document handling to get wrong, and no new dependency. |
| A repository is read without credentials, so only published material is reached | `extractium/sources/dspace_client.py`, `_headers` | No token, cookie, or other credential is sent, and none is accepted in the settings file. A deposit under embargo is not returned and none is requested. `tests/test_source_dspace.py` checks the headers of every request. |
| Dependencies are pinned and hash-checked | `requirements-lock.txt` | Generated with `uv pip compile --universal --generate-hashes`. Both run scripts and both workflows install with `--require-hashes`, so a package whose contents do not match what was locked is refused. `tests/test_operations.py` checks that every pinned package carries a hash. |
| The scheduled build asks for the least access it can | `.github/workflows/build-compendium.yml` | `contents: read` for the workflow; `pages: write` and `id-token: write` for the publishing job alone. Publishing goes through GitHub's own Pages actions only. `tests/test_operations.py` pins all of this. |
| An AI agent is told to treat indexed text as evidence, never as instructions | `SKILLS.md` | The rule is stated in the file an agent is pointed at. |
| Every answer a local search server gives an assistant repeats that rule | `examples/mcp/local-python/server.py`, `examples/mcp/local-node/server.js`, `UNTRUSTED_NOTE` | The note is the first line of every tool result, where the model reads it next to the text it describes. `tests/test_mcp_local_servers.py` and `examples/mcp/local-node/server.test.js` check it is there. |
| A local search server marks content read from a folder as confidential | The same two files, `LOCAL_NOTE` | An answer holding a section whose `local` flag is set carries the warning; one that does not, does not. Covered in both suites. |
| A published index is fetched only over a secure connection | The same two files, `checked_url` / `checkedUrl` | HTTPS is required, with plain HTTP allowed only on the loopback address, where a developer serving a build has no certificate. Every other scheme, including `file:`, is refused. Parametrised tests cover each case. |
| A downloaded index cannot decide where it is written | The same two files, `cache_paths` / `cachePaths` | The cached file is named by a SHA-256 digest of its address, so a URL carrying path separators or a parent-directory step lands in the cache folder like any other. Pinned in both suites. |
| A search server answers questions and writes nothing | The same two files | One tool, `search_kb`, which reads one static file. There is no tool that writes, deletes, or runs anything, and no path by which a model's output becomes a command. |
| A failure tells the model what to do without exposing the machine | The same two files, `_search` / `search` | An index that cannot be loaded returns a tool error naming the step; the underlying message, which can hold a path from the operator's disk, goes to the error stream only. Both suites check that a path in the failure does not reach the answer. |
| Every output records how it was made | Container header, `llms.txt` preamble | Model, dimensions, query prefix, build time, and tool version, so a stale or mismatched file is detectable rather than silently wrong. |
| A client refuses a file it cannot read correctly | `extractium/search.py`, `clients/js/extractium-client.js` | Both implement every check in the [container format](container-format.md) reader checklist. `tests/test_search.py` and `clients/js/extractium-client.test.js` cover each refusal. |


## Known gaps

These are real and current. None is hidden behind a setting.

- **The check for protected health information reads shapes, not meaning.** It finds an identifier that looks like one: a number with a check digit, or a value sitting next to a word such as "Patient" or "Serial number". It does not recognise a person's name or a place name written in ordinary prose, with no label nearby. A clean result is not evidence of anything.
- **Adding that recognition would mean adding a language model.** The libraries that do it well need a model of several hundred megabytes, and the one that reads addresses needs a C library with no simple install on Windows. That is a large, fragile dependency for a check that only ever flags something for a person to read, so the project does without it and states the gap here instead. Revisit the trade if a build is ever pointed at clinical free text rather than documentation.
- **The check does not read images, PDFs, or spreadsheets.** Neither does the build, so nothing from them reaches an output; but a folder holding them is not covered by the report.
- **Text a repository extracted from a deposited document is not scanned by default.** The default `phi_lint: local` setting covers content that was never published, and a deposit in a public repository was published deliberately. But extracted text from a research poster is exactly where a stray identifier is most likely to sit, so set `phi_lint: 'all'` on any build with a `dspace` source. The setting exists; choosing it is the operator's.
- **Code records are not scanned by default either, for the same reason.** A repository's source files are published material, so `phi_lint: local` leaves them out. Set `phi_lint: 'all'` on any build that reads code. Run that way against this project's own repository on 2026-09-10, the check reported 90 pattern matches in 34 of 1,945 documents — author names in file headers, synthetic examples, and hash digits in a lock file that look like identifiers. That is the check asking questions, which is what it is for.
- **The Node search server's one package brings unfixed advisories.** `@huggingface/transformers`, which runs the embedding model, depends on `sharp` and `adm-zip`; `npm audit` reported four high-severity advisories against those two on 2026-09-11, none with a fix available. The affected paths are image decoding and unpacking the machine-learning runtime at install time, neither of which this server uses, but the package is still installed on the machine. The Python server needs no extra package at all and is the safer choice where either will do.
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

Extractium keeps nothing of its own beyond three folders, all under your control:

| What | Where | How long |
|---|---|---|
| Fetched pages | `.kb_cache`, next to your settings file unless you change it | Until you delete it. Deleting it costs time on the next build and nothing else. |
| Build output | `dist` unless you change it | Until you delete or overwrite it. Each build rewrites the folder. |
| An index a local search server downloaded | `~/.cache/extractium-mcp`, unless `EXTRACTIUM_CACHE_DIR` names another folder | Until you delete it. It holds one copy of each published index you searched, which is public material. |

Neither folder should be committed. Both are in the `.gitignore` files that ship here.


## Review status

| Item | Status |
|---|---|
| Test suite | 1,128 Python tests passing as of 2026-09-11, plus 36 Node tests for the JavaScript client and 24 for the local Node MCP server. |
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
