<!--
This file is part of Extractium™
docs/ui-implementation-plan.md
Author(s): Gabriel Mongefranco
Created: 2026-09-23
Last Modified: 2026-09-30
Summary: The staged plan for the local page: a small web page, served by
the tool itself, for setting up, building, scheduling, searching, and
installing plug-ins without a terminal, the installer that puts the tool
on a computer with no admin rights, and the way an AI assistant
connects to a compendium on the same computer. Records the decisions the
plan relies on, the stages of about one week each, and the done-when rule
for each.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## User Interface Implementation Plan

[← Back to README](../README.md)


## Summary

This page is the plan for giving Extractium™ a local web page, so a person can install it, set it up, run a build, put it on a weekly timer, search the result, and add plug-ins without opening a terminal. It also plans how an AI assistant on the same computer connects to a compendium, the collection a build writes. It is written for whoever builds it, in stages of about one week each, with what each stage delivers, the tests that prove it, the documentation it must change, and a rule for when it is done. Read it before starting a stage, and update it when a stage finishes or the scope changes. What exists right now is in [Architecture and Current State](architecture.md), and the plan for the engine itself is the [implementation plan](implementation-plan.md).


## What this builds

One page, in the person's own browser, served by the tool on the same computer. Nothing listens beyond that computer. The page has these parts, plus the installer that brings it to a computer, and each stage below adds one or two of them:

- A welcome screen for a first run, asking the same three questions the terminal asks, with the terminal command shown beside every button and a link to the documentation.
- A settings form for the file `config.yaml`, with an advanced view of the file itself.
- A build button, for a trial of 25 pages or a full build, with the log as it happens, and a history of past runs with what each one found.
- A weekly schedule switch, and a way back to the page from the Start menu or its equivalent.
- A search box that answers as you type, with no model loaded, and understands `#tag`.
- An "Ask with AI" button that opens [Field Station AI](https://github.com/DepressionCenter/FieldStationAI) over the local file, and a "Connect your assistant" panel for Claude, Codex, and the other clients that speak the Model Context Protocol (MCP), the standard AI assistants use to call tools.
- A plug-ins page that installs a plug-in from a file or a repository address after checking it, lists what is installed, and removes it again.
- An installer and a portable zip that put the tool on a computer with one download and no admin rights, as a folder beside the person's data or under their own account, and a menu entry that opens the page.

For a new person on Windows the path is: download the release zip, unzip it into a folder, double-click `run.bat`, answer "browser", answer four questions on the welcome screen, press "Trial build", read the results, press "Build weekly". A person who wants the command on PATH and Extractium in the Start menu runs `install.bat` from that folder, and on a Mac or Linux downloads and runs `install.sh`; either way Extractium then opens from the menu. For a person who already builds today nothing changes. Plain `run.bat` builds as before and never opens a browser, so a scheduled run keeps working; `run.bat ui` opens the page.


## What already exists and is reused

The plan is smaller than it looks, because most of the pieces are already in the repository or next door.

- The light container, `compendium.json.gz`, already carries every page's title, description, keywords, categories, and tags, and the posting lists the keyword half of the hybrid search uses: for every word, which entries hold it and how often. That is a ready-made instant index. It is about 1 MB for the Depression Center's corpus and grows by a few hundred bytes per page. See the [container format](container-format.md).
- The [JavaScript client](../clients/js/extractium-client.js) and the [Python client](../extractium/search.py) both read that file and already export the keyword ranking. Only a keyword-only entry point is missing.
- The `init` module writes a settings file through the YAML library from the commented example, and refuses to replace an existing file. The welcome screen and the settings form are a layer over it, which is what [issue #42](https://github.com/DepressionCenter/extractium/issues/42) asks for.
- The [local Python MCP server](../extractium/mcp/server.py) already answers the protocol over standard input and output, and the [shared JavaScript](../examples/mcp/shared/mcp-http.js) already has the one-request-per-POST binding of Streamable HTTP. Stage 2 moved the first into the package, from `examples/mcp/local-python/`, and wrote the second in Python beside it.
- The two prompts under [examples/wrappers/](../examples/wrappers/README.md) already tell an assistant how to use the search tool once connected. The connection card grows from them.
- Field Station AI is one dependency-free HTML file that chats with a model in the browser or with Ollama when it finds one, searches a compendium, and loads any compendium named by `?compendium-url=`. It is the "Ask with AI" client, unchanged.
- The installer puts the tool on a computer with no admin rights, and the build scripts are thin entry points that find it or install it and run it. The page is one more thing they can start.


## Decisions this plan relies on

Decisions 1 to 14 were settled on 2026-09-23 with the maintainer, and 15 to 17 on 2026-09-29. They are listed so a reader of this page alone knows what is fixed, and why, so nobody proposes the same thing again from first principles.

1. **Python, in this repository, not a Go binary.** Everything the page does that matters is Python: run a build, embed a question, write settings through the YAML library, read the cache, load plug-ins. A separate binary would shell out to the virtual environment for all of it or reimplement search and embedding a third time, and it would need code signing on macOS and Windows or show a warning on first open. The page is a command in the package, `extractium ui`, and installs with everything else.
2. **Standard library only for the server, plain HTML for the page.** The server is Python's own HTTP server. The page is HTML forms and the JavaScript client the project already ships, with no framework. A plain page is easier to keep accessible and easier to keep for years.
3. **Loopback only, with a token.** The server binds to 127.0.0.1 on a free port, the address it opens carries a random session token, every request that writes must carry it, and the server checks the `Host` and `Origin` headers so a web page from elsewhere cannot reach it through a name that points at the local machine. Nothing is reachable from another computer.
4. **The page and the search tool share one process, and the tool also stands alone.** While the page runs, the same process answers MCP at `/mcp` for clients that connect to an address. An `extractium mcp` command answers over standard input and output for clients that start a program themselves, which is most of them, so the tool works with the page closed.
5. **Field Station AI is reused as it is, and never changed from this repository.** The server serves a pinned copy of its single file, downloaded once and checked against a recorded hash, with the local compendium's address in the link. Its promise that nothing leaves the browser stays intact. An endpoint that would have let it call Claude Code or Codex on the person's machine was considered and dropped for that reason.
6. **Assistants connect through MCP, guided by a card, not by files the page writes into other applications.** No prompt can make a client connect; the connection is a setting in the client. So the page produces one Markdown card holding the local address, the file path, the standard config snippet, and plain instructions, offered as a Claude skill folder, as text for a custom GPT's or a Gem's instructions, and as text for any chat. An assistant that can run commands adds the server itself; one that cannot walks the person through its own settings screen; one that cannot reach a local server says so and points to the hosted server pages. Install links and bundle files were considered and set aside, because every desktop client would need an account to test them. The Cursor and VS Code install links are documented and free to test, so they stay as an extra.
7. **Instant search uses the light file's own posting lists and no search library.** A JavaScript search library would rebuild at page load an index the file already carries, and would add the client's first dependency. Typo tolerance is the one thing such a library adds; if it is wanted later, it goes over titles and tags only. The page never loads the full file, which can pass 300 MB; it searches the light file and opens a page's own Markdown from the Open Knowledge Format (OKF) folder to show its text.
8. **Search by meaning on the page uses the model the tool already installed.** The server embeds the question with the same model the build used, loaded once, so the browser downloads nothing. The keyword results appear at once and the meaning results are added when they arrive.
9. **The OKF and gzip outputs are on by default when the page writes the settings file.** The search page shows a result's text from its OKF file, and Field Station AI wants the gzip file. The terminal `init` keeps its own defaults.
10. **Local models first.** Field Station AI already prefers Ollama when it finds it and a browser model otherwise. A third-party assistant reaches the compendium only through the search tool, and the connect panel says in one line that what it retrieves goes wherever that assistant sends it. A corpus may hold protected health information.
11. **Plug-ins install through the tiers the registry already has.** A single file goes into `plugins/`, a package installs through pip, and a repository address installs through pip pinned to a commit or tag, which is the decision recorded on 2026-09-12. Every plug-in is checked in a child process, against the protocols in `extractium/core/models.py`, before it is placed where a build would load it. Importing a plug-in runs its code, and the page says so.
12. **Scheduled builds never open a page.** The scripts start the page only when asked with `ui`, or on a first run when the person chooses the browser. A schedule calls the script with no arguments.
13. **Menu entries are per user and removable.** A shortcut under the user's own Start Menu folder on Windows, a `.desktop` file under `~/.local/share/applications` on Linux, and a small `.app` folder under `~/Applications` on macOS, which opens without a signing warning because it was made on the machine. No administrator rights, and a matching "Remove" button.
14. **ZippyServe stays out.** It serves files and cannot run builds or write settings. It remains the right tool for serving a published output folder.
15. **Installed by a script that tries uv first and the machine's Python second.** uv is one static binary per platform that installs per user with no admin rights, brings its own Python at the version a release pins, and installs the hash-pinned lock, so the Python version and the packages are the project's to choose and a person never meets them. The installer downloads it at a pinned version, checks its hash, and never pipes an install script into a shell. When uv cannot run, because a policy refuses every downloaded executable, a standard Python 3.10 or newer already on the machine is used with pip from the same lock, and when neither works the installer stops and says what to ask IT for. Rootless containers and a packaged application were considered and set aside: a container runtime needs admin rights on Windows and macOS, where users have none, and a packaged application would ship two gigabytes per system and face the same signing gates a Go binary does. A container image stays a candidate for servers and runners.
16. **One folder, in two places, and git for developers only.** The tool, its Python, its packages, and the `extractium` command live in one folder that works wherever it sits: beside the person's data as the portable install, or under the profile as the per-user install, with the command on PATH and a menu entry. A compendium folder holds only what a build writes. A user gets the folder in the release zip, or the installer builds it; a developer clones and runs the installer inside the checkout. The build scripts stay as thin entry points, for double-clicking and for the copies people already saved.
17. **The portable zip is built by a release workflow, not by the person.** A release attaches a zip holding the folder, built on a Windows runner from the lock by the same installer, with its hash in the release notes, so the portable path downloads nothing but the zip. Windows first: a zip a browser downloads on macOS is quarantined, and Gatekeeper refuses the unsigned Python inside it, so the Mac path stays the installer, which downloads with `curl` and sets no flag.


## How stages are sized

Each stage has a goal, deliverables, the tests that prove them, the documentation that must change in the same stage, and a "done when" rule. A stage is about one week for one developer, the same rule as the [implementation plan](implementation-plan.md). A stage that grows past that is split, not stretched. The repository must pass its test suite at the end of every stage, and every stage lands as its own pull request against `main`.

The first two stages change the engine and the clients and are useful on their own, with no page. The page begins in Stage 3. Stage 4 changes how the tool reaches a computer, and the page's own work continues in Stage 5.


## Stages

### Stage 1: Search without a model, and a record of every run

**Goal.** Give both clients an instant search that needs no model, and make every build leave a record the page can list later.

**Deliverables.**

- `search_keywords(query, k)` in the Python client and `searchKeywords(query, options)` in the JavaScript client: the keyword half of the hybrid search alone, over the posting lists the file carries, returning the same hit shape as `search` with the cosine left empty. A `#word` token in the query keeps only pages whose tags, keywords, or categories hold that word, compared without regard to case, and the remaining words rank them. Both clients keep the per-source cap so one site cannot fill the list.
- `suggest(prefix, limit)` in both clients: the words of the posting-list vocabulary, the page titles, and the tags that start with the typed prefix, tags returned with their `#`. It is a prefix filter over lists already in memory, so it answers between keystrokes.
- A run record. Every build writes `runs/<start time in UTC>.json` beside the settings file, on success and on failure, holding what the summary already prints: start and end time in UTC, how long it took, the tool version, the settings file's hash, the exit status, the counts of pages, sections, and windows per source, every file written with its size, and the notes and errors. The folder is `runs_dir` in the settings file, `runs` by default. The record holds no content read from a local folder and no token. The data-repo template ignores the folder in git.

**Tests.** The cross-language test that already puts one corpus through both clients also puts a keyword query and a `#tag` query through both and checks that they rank alike; a `#tag` no page carries returns nothing; `suggest` matches a word, a title, and a tag and honors the limit; a build that succeeds and a build that fails each leave one record with the expected fields; a record written from a build with a local folder holds no local text.

**Documentation.** [How to search a compendium](how-to/search-a-compendium.md), the [configuration reference](configuration.md) for `runs_dir`, the [data flow](data-flow.md) page for the record, and the [data repository template README](../examples/data-repo/README.md).

**Done when** the same question typed against the center's light file returns the same keyword results from both clients with no model loaded, `#depression` narrows them, and a build that stops with an error still leaves a run record saying so.

*Finished 2026-09-28 on branch `phase-ui-1-keyword-search-and-run-records`. Built as written, with four choices the text left open. The keyword search returns each section once, at its best window, because a list of results is a list of pages in the light file and one page shown twice is a defect there, a rule the hybrid search has since adopted as well; no cap per site was added, since one site often holds every right answer. A `#word` matches a whole tag, keyword, or category entry or any one word of it, so a suggested multi-word tag still narrows when typed back. The record lists an output's files the way the summary does, naming a folder with a count past eight files, because the history page shows figures and a weekly record of every Open Knowledge Format path would be hundreds of kilobytes of names. And a record is written even when the settings file cannot be read, into the default `runs` folder, so a mistyped file shows up in the history like any other failed run. Two things the text did not foresee: the record's file name replaces the colons of the start time with hyphens, because Windows refuses them, and the record carries the compendium's name only when the settings file gave one, because the fallback is the first page's title, which may have been read from a local folder. The check against the center's light file is owed; no built file was in the checkout.*

### Stage 2: The search tool as a command, and the connection card

**Goal.** Make the local MCP server part of the package, able to read a compendium from a file on disk, and write the card that tells an assistant how to connect.

**Deliverables.**

- `extractium mcp --index <path or https address>`: the local Python server moved into the package under `extractium/mcp/`, with the same one tool, `search_kb`, over standard input and output. It reads a local file directly, and keeps the rule that an address must be HTTPS unless it is on the loopback address. The example under `examples/mcp/local-python/` becomes a short README that points to the command, so the how-to page keeps working.
- The Streamable HTTP binding in Python: one function that takes one request body and returns one response, stateless, mirroring the shared JavaScript, ready for the page's server to mount at `/mcp` in Stage 3. It has no session and no event stream, the same choice the hosted examples made.
- `extractium connect --index <path> [--out <folder>]`: writes the card. One function produces the text; the command writes it as a folder holding `SKILL.md`, the shape a Claude skill takes, and prints the same text for pasting. The card holds the `extractium mcp` command with the real path, the standard JSON snippet most clients read, the HTTP address when the page runs, the rules from the wrappers about what an assistant must not do with retrieved text, and one plain sentence per known client about whether it can reach a local server. The card names no token and no credential.

**Tests.** The tool answers a search over standard input and output from a local file; a plain-HTTP address off the loopback is refused; the HTTP binding answers one JSON-RPC request per POST, refuses other methods, and answers the same as the standard-input path for the same query; the card holds the given path, the snippet parses as JSON, the skill front matter is valid, and no line holds an environment variable's value.

**Documentation.** [How to connect an MCP client](how-to/connect-an-mcp-client.md) leads with the command and the card, [using a published compendium](using-a-compendium.md), the [architecture page](architecture.md), and the two example READMEs under `examples/mcp/`.

**Done when** Claude Code lists the tool after the one command the card gives, and answers a question from the center's local file with the page closed.

*Finished 2026-09-28 on branch `phase-ui-2-mcp-command-and-connection-card`. Built as written, with four choices the text left open. The environment variables the example server read stay as the fallback when `--index` is absent, so a client configuration written for the example keeps working once its command changes; `--index` wins over them. The command refuses a plain `http://` address off the loopback address before it waits for a client, so a mistyped configuration fails in the client's log at once rather than at the first search. The card's HTTP entry appears only when an address is given, since nothing in the package serves the binding yet, and that address is accepted only on the loopback address with no user name, password, or query, which is where a token would otherwise land; the card itself reads nothing from the environment. `extractium connect` refuses a file that is not there, because a card naming a missing file produces a tool that fails at its first search. The sentence per client is kept to where each client reads its configuration, and a hosted chat product is told it cannot reach a local tool. The Node example stays an example. The check that Claude Code lists the tool after the card's command is owed; it changes a client's own settings, which the branch does not do.*

### Stage 3: The local page, the first-run choice, and the settings form

**Goal.** Start the page from the build scripts, and let a person write or change the settings file from it.

**Deliverables.**

- `extractium ui [--port N] [--no-browser]`: a threaded server from the standard library, bound to 127.0.0.1 on a free port, opening the browser at an address that carries a random session token. The page keeps the token and sends it with every request that writes. The server refuses a request whose `Host` header is not its own address, refuses a write whose `Origin` is not its own, serves static files only from an allowlist inside the package, and quits when no page has checked in for ten minutes, when the page's "Quit" button is pressed, or on Ctrl+C. It mounts the `/mcp` binding from Stage 2 and serves the output folder under `/dist/` for the search page and Field Station AI later.
- The welcome screen, shown when the folder has no settings file: the three questions of `init`, a note that the terminal does the same with the command shown, and a link to the documentation. It writes the file through the `init` module with the `okf` and `gzip` outputs on.
- The settings form, shown when the file exists: the name and short name, each source with the fields its type takes, the outputs, `rebuild`, `max_pages`, and the other settings the [configuration reference](configuration.md) lists, with a field's help text beside it. An advanced view shows the file's text. Both save through the settings loader, so a value the loader would refuse is refused with the same message, and the previous file is kept beside it with a date stamp. Comments a person added by hand are not kept, and the page says so before the first save. Every credential stays in the environment, and the form never shows one.
- The build scripts: `run.bat ui` and `run.sh ui` start the page instead of a build. On a first run with no settings file they ask one question, set up in the browser or in the terminal, and the browser is the default. Any other argument still goes to `extractium build`.

**Tests.** The server binds only to the loopback address; a write without the token, with the wrong `Host`, or with a foreign `Origin` is refused; a path with `..` in it is refused; a file outside the allowlist is not served; the welcome screen writes a file the loader accepts with both outputs on and refuses to replace an existing one; a hostile name is written as a quoted string and read back unchanged; a saved form round-trips every setting; the idle timer quits the server; the scripts route `ui` to the page and a build argument to the build.

**Documentation.** A new page, `docs/how-to/use-the-local-page.md`, on using the page, the [installation guide](how-to/install.md), [running a build](usage.md), the [architecture](architecture.md) and [compliance](compliance.md) pages, and [troubleshooting](troubleshooting.md).

**Done when** a lone `run.bat` on a clean Windows machine, answered with "browser", ends with the page open and a settings file written, closing the tab stops the server within ten minutes, and issue #42 can close.

*Finished 2026-09-28 on branch `phase-ui-3-local-page-and-settings-form`. Built as written, with these choices where the text left room. The server binds `127.0.0.1` and answers its `Host` and `Origin` checks under that name and `localhost`, since a person types either and neither reaches beyond the machine. Every call to the page's own API needs the session token, not only a write, since the settings text is the one thing worth reading and the page always has the token; a write needs the page's own origin as well, and a request with no origin is refused rather than passed. The `/mcp` and `/dist/` addresses carry no token, because an assistant and Field Station AI cannot send one, and `/mcp` is gated on origin the way the binding gates a hosted endpoint. The form writes the file afresh holding only what differs from the defaults, and the advanced view writes the text exactly as typed, so comments survive that path; the previous file is kept as `config.yaml.<UTC time>.bak`. The welcome screen's file is the commented example with an outputs list added at its end, so the terminal `init` and the page share one writer. A `--config` flag was added beside the two the text names. `run.sh` asks the browser-or-terminal question only when a terminal is attached and otherwise sets up in the terminal, so a scheduled run with no settings file fails fast rather than waiting for a browser; `run.bat` cannot tell and always asks, with the browser as the default on Enter. The browser path ends when the page quits and the next run builds, since the page has no build button until Stage 5. The search tool mounted at `/mcp` loads the compendium once and does not yet reload it after a build. The check on a clean Windows machine is owed; the page was checked by hand on this machine, as the compliance page records.*

### Stage 4: The installer, the portable zip, and the menu entry

**Goal.** Put the tool on a computer with one download and no admin rights, so a person never meets pip, a virtual environment, or a Python version, and give them a menu entry that opens the page.

**Deliverables.**

- One layout, in one folder named `Extractium`: uv, a managed Python with the packages installed into it, the release, a `bin` folder with the `extractium` shim, a `cache` folder for the models, the log a server started from the menu writes to, the last compendium folder the page used, and a copy of the installer. There is no virtual environment, because one records the absolute path of its base interpreter and breaks when the folder moves, and the release is installed as a plain copy rather than editable for the same reason. The shim starts the tool as `python -I -m extractium.cli` from a path relative to itself, never through the wrapper executables pip writes, which embed an absolute path and are unsigned; `-I` also keeps the working folder off the import path. The shim points the model cache at the folder's own `cache`, so the embedding model, the reranker, and the Whisper model travel with the folder. A portable install is this folder beside the person's data. A per-user install is the same folder under the profile, `%LOCALAPPDATA%\Extractium` on Windows and `~/.local/share/extractium` elsewhere, plus the shim on PATH and a menu entry.
- The portable zip, attached to every release for Windows: `run.bat`, `install.bat`, and the `Extractium` folder, built by a release workflow on a Windows runner that runs this same installer from the lock and zips the result, with the zip's SHA-256 in the release notes. The workflow warms the cache with the default embedding model and the reranker, and with Whisper `base.en` when the whole zip stays under GitHub's two-gigabyte limit on a release file; otherwise the models are a second zip. A person unzips it into the folder where the compendium should live and double-clicks `run.bat`. Nothing downloads, and a build then needs the network for the crawl alone. The workflow follows the rules the other workflows follow: every action pinned to a commit digest, read access by default.
- `install.bat` and `install.sh`, at the repository root, inside the zip, and attached to every release. The installer installs and exits: it asks no setup question and runs no build, and when it was double-clicked it pauses before its window closes. It tells three situations apart. With an `Extractium` folder beside it, as in the zip, it copies that folder under the profile, adds the shim to PATH, and makes the menu entry, with no download. Inside a checkout, it installs that checkout editable under the profile, which is the developer path. On its own, it resolves "latest" to the newest release tag through the releases redirect, as the build scripts do today, downloads that release's archive, and builds the same folder from scratch through the four steps below; git is no longer used to fetch the tool. It takes `--update`, which reinstalls in place from the pinned release's lock and downloads only what changed; `--uninstall`, which deletes the folder and the PATH entry; `--version TAG`; and `--portable`, which builds the folder beside the script instead of under the profile and is what the release workflow runs.
- The four steps of decision 15, each tried rather than predicted. First, uv is downloaded at a pinned version, checked against the SHA-256 written in the script, unpacked, and asked for its version. Second, uv fetches its managed Python at the version the release pins, installs the lock into it with hashes enforced, and installs the tool without dependencies, with `UV_NATIVE_TLS=1` set so a corporate proxy's certificate is trusted; when the managed Python download is refused, uv is pointed at a suitable Python already on the machine. Third, when uv cannot run, a standard Python 3.10 or newer on the machine whose `venv` works is used, with pip installing from the same lock, and the shim starts the tool through that interpreter; such an install is not portable, and the installer says so. Fourth, the installer stops, names the step that failed and why, and says what to ask IT for. It never runs `sudo` or an admin step itself: where a packager could supply what is missing, such as `python3-venv` through `apt-get`, or Python through `dnf`, `brew`, or `winget`, it prints the command and asks before running it.
- PATH and the menu entry, for a per-user install. The installer asks once before adding `bin` to the person's PATH: on Windows through the per-user registry key, never `setx`, which truncates; on macOS and Linux the shim goes in `~/.local/bin`, and when that is not on PATH the installer prints the line to add to the shell profile rather than editing the profile. It says that a new terminal is needed. The menu entry is the per-user entry of decision 13, named "Extractium", which opens the page. On Windows the shortcut runs the shim with `ui` minimized, so the server's window exists but stays out of the way; the `.app` and `.desktop` entries start it with no terminal, so the server writes its lines to the log in the folder and stops from the page's Quit button or the idle timer. The entry opens the last compendium folder the page used, or the welcome screen when there is none.
- The welcome screen's fourth question, "Where should the compendium live?", with `Extractium` under the home folder as the default rather than under Documents, which corporate images often sync to OneDrive. The server takes a folder at start-up, `--folder`, beside `--config`, and the page's header names the folder it works in.
- `extractium` with no arguments does what the build scripts do today: with no settings file it asks whether to set up in the browser or the terminal, otherwise it builds. `run.bat` and `run.sh` shrink to a few lines: they use an `Extractium` folder beside them, else the per-user shim by its full path, so they work before a new terminal is opened and when PATH could not be changed, and otherwise fetch the installer and run it. A copy of today's `run.bat` that someone saved keeps working: it downloads the release and calls the thin script inside it, which runs the installer beside itself, so the person ends up installed under the profile with the downloaded checkout left beside their data, and the installation guide says it may be deleted. The GitLab runner file in the data repository template checks the tool out at a pinned version and installs the lock itself, so it does not change.

**Tests.** The installer scripts are checked the way the operations tests check the build scripts today, by their text and, for the shell script, its syntax: the three situations are told apart; each flag is routed; the uv version and hash are pinned; nothing pipes a download into a shell; no `sudo` or `setx` appears; the shim quotes its path for a folder with spaces and starts the tool through the interpreter with `-I`. The pieces written in Python are tested against fakes: the release tag from a fake redirect; a uv archive whose hash differs is refused; the fallback is taken when a fake uv fails to start; the copy from a folder beside the installer lands under the profile with nothing downloaded; the PATH entry is added once and removed on uninstall; the folder holds no absolute path of the machine it was made on; the shortcut, the `.desktop` file, and the `.app` property list are written and removed; the welcome screen writes the file in the folder it was given and refuses a folder it cannot write; `extractium` with no arguments routes to the question and to the build. The release workflow passes the checks the workflow tests already make, every action pinned to a commit digest and read access by default. Nothing in the suite downloads uv, a Python, a release, or a model.

**Documentation.** The [installation guide](how-to/install.md) rewritten around the zip, the installer, and the developer checkout; the [README](../README.md) quick start; [running a build](usage.md); [how to use the local page](how-to/use-the-local-page.md) for the menu entry and the folder question; [how to run a weekly build](how-to/run-a-weekly-build.md) for the shim's path; [troubleshooting](troubleshooting.md) for the download mark Explorer's unzip copies onto the extracted files, a blocked uv, a proxy certificate, and a command not found before a new terminal; the [architecture](architecture.md) and [compliance](compliance.md) pages.

**Done when** on a Michigan Medicine imaged Windows machine with no admin rights, the release zip unzipped into a folder runs `run.bat` to the page with no download; `install.bat` from that folder ends with `extractium --version` answering in a new terminal and "Extractium" in the Start menu opening the page, again with no download; a lone `install.sh` does the same on a Mac and on a Fedora or Debian machine; and a `run.bat` saved before this stage still builds.

*Finished 2026-09-30 on branch `phase-ui-4-installer-and-portable-zip`. Built as written, with these choices where the text left room. The scripts do only what must happen before a Python exists, telling the situation apart, downloading uv and checking its hash, obtaining an interpreter, and downloading the release; everything after that runs in `extractium/install.py`, which imports only the standard library so it runs as a file from the release checkout before the package is installed and as a module afterwards. The release-tag lookup and the uv hash check therefore live in the scripts, text-tested as the run scripts were, plus one real run of `install.sh` against a fake `curl` for the wrong-hash refusal. A checkout installs as a plain copy unless `--editable` is passed, because a saved old `run.bat` downloads a checkout beside the person's data and the guide promises that download may be deleted afterwards. `extractium` with no arguments is a real subcommand, `start`, so it has `--config` and a help line, and the thin scripts keep honouring `CONFIG` through it. The page finds its folder in this order: `--folder`, a settings file in the working folder, the folder remembered under the home the shim names in `EXTRACTIUM_HOME`, and otherwise the welcome screen's fourth question; the Start menu shortcut's working directory is the Extractium folder itself, which never holds a settings file, so a menu launch goes to the memory. The managed Python is 3.12.12 and uv is 0.12.20, with the six archive hashes copied into the scripts. A folder built on a Python already on the machine carries a `not-portable.txt` mark, and the installer refuses to copy such a folder. The shim runs `python -I -X utf8 -m extractium.cli`: isolated mode keeps the working folder off the import path, which is what makes the module form safe here, and the utf8 switch stands in for the variable isolated mode would ignore. The release workflow attaches the four scripts beside the zip, so a lone `run.bat` can fetch the installer from the newest release, and falls back to the repository's copy while no release carries one. Two things the first real run on this machine taught: a locked-down Windows image can lack PowerShell's `Get-FileHash`, so the hash goes through `certutil` and the unzip through `tar`, with the cmdlets as the second try; and on a disk that ignores case a folder named `Extractium` inside a checkout is the package folder `extractium` itself, so a portable build inside a checkout needs `--home DIR`, which the workflow passes with a folder under the runner's temporary space. The checks owed are the three in the table below and the done-when runs on the three systems; on this machine the tests pass and the scripts were exercised by hand against a fake shim.*

### Stage 5: Builds, history, the schedule, and a way back

**Goal.** Run and watch a build from the page, see what past builds found, put the build on a weekly timer, and get back to the page without a terminal.

**Deliverables.**

- "Trial build" and "Full build" buttons. The server starts `extractium build` as a child process on the interpreter the page runs on, one at a time, with the arguments as an array and never a built string. The page shows the log as it grows, by asking for the tail of the log file every second, and a "Stop" button ends the child process. When the build ends, its run record appears in the history.
- The history page: one row per record in `runs_dir` with the start time, how long it took, how many pages, and the outcome, opening to the full figures and the log.
- The schedule switch: on by default for Monday at 06:17 local time, with the day and time editable. Turning it on shows the exact crontab line or `schtasks` command from [how to run a weekly build](how-to/run-a-weekly-build.md), with the real path, and writes it only after a confirming press. Turning it off removes exactly that entry. The page reads the system's own list to show whether one exists. macOS uses cron too, so there is one code path, with a note in the documentation about launchd and Full Disk Access.
- "Add to Start menu": a per-user entry of the kind decision 13 describes, named after this compendium and pointing at its folder, for a person with more than one. It is shown before it is written, with a "Remove" button. On Windows the shortcut is made through PowerShell, which every supported Windows has. The installer of Stage 4 makes the general "Extractium" entry.

**Tests.** The build runner, against a fake command: one build at a time, the log tail, the stop, the record after the end, and no shell string anywhere; the history from a folder of fixture records; the crontab line and the `schtasks` command for a path with spaces; the `.desktop` file and the `.app` folder's property list; the remove of each; nothing in the test suite runs a real scheduler or a real build.

**Documentation.** The new page on using the local page, [how to run a weekly build](how-to/run-a-weekly-build.md), and [troubleshooting](troubleshooting.md).

**Done when** pressing "Build weekly" on each of the three systems creates an entry the system's own tool lists, removing it leaves none, and the menu entry opens the page.

### Stage 6: The search page

**Goal.** Search the built compendium from the page, instantly and without a model, then by meaning.

**Deliverables.**

- The search box. As the person types, the JavaScript client, loaded from the package and reading the light file from `/dist/`, offers suggestions from Stage 1 and lists keyword results. A `#tag` in the box narrows them, and pressing a tag on a result adds it to the box. Pressing Enter also asks the server for meaning results through `/api/search`, which embeds the question with the installed model, loaded once, and runs the Python client's hybrid search; those results join the list, marked as meaning matches.
- A result shows the title, source, description, tags, and a link to the original address. "Open" shows the page's OKF concept file as text when the `okf` output exists, and the description alone when it does not. The full file is never loaded by the page.
- Every string from a compendium is encoded for the page before it is shown. Titles and descriptions come from crawled sites and are untrusted.
- The suggestion list follows the combobox pattern: arrow keys move through it, Enter picks, Escape closes, and a screen reader hears how many suggestions there are.

**Tests.** `/api/search` returns hits from a fixture file with a fake embedder and loads the model once across requests; the page loads the light file and the client from the server; a title holding markup is shown as text; an automated accessibility scan of the page reports nothing; the keyboard path through the suggestions in a browser test.

**Documentation.** The new page on using the local page, [how to search a compendium](how-to/search-a-compendium.md), and the [compliance](compliance.md) page with the scan result and the manual checks made.

**Done when** typing in the box over the center's light file shows suggestions and results with no model loaded, `#tag` narrows them, Enter adds meaning results, and the whole page works with the keyboard alone.

### Stage 7: Ask with AI, and connecting an assistant

**Goal.** Put Field Station AI one press away over the local file, and give every assistant the card and the address it needs.

**Deliverables.**

- "Ask with AI". On first press the server downloads Field Station AI's single file from a pinned release address, checks it against the hash recorded in the package, keeps it beside the tool, and serves it under `/fieldstation/`. The link carries `compendium-url` pointing at the local full file under `/dist/`, or the light file when there is no full one. Field Station AI finds Ollama on its own and otherwise runs a model in the browser; it works offline after the first download.
- The "Connect your assistant" panel: the `/mcp` address while the page runs, the `extractium mcp` command, the JSON snippet, copy buttons, "Download the card" as the skill folder in a zip and as plain text, the Cursor and VS Code install links, one plain sentence per client about reach, and the one-line notice from decision 10.

**Tests.** A downloaded file whose hash differs is refused and not served; the link's compendium address is relative to the page's own origin; `/mcp` answers a search through the page's server; the zip holds `SKILL.md` and nothing else; the links encode the address; the panel shows no token.

**Documentation.** The new page on using the local page, [how to connect an MCP client](how-to/connect-an-mcp-client.md), and the [compliance](compliance.md) page.

**Done when** "Ask with AI" opens Field Station AI over the center's local file and answers, offline after the first download, and a Claude Code session connected from the card answers from the same file.

### Stage 8: Plug-ins from the page

**Goal.** Install a plug-in from a file or a repository address after checking it, see what is installed, and remove it.

**Deliverables.**

- The plug-ins page: every plug-in the registry resolves, with its name, kind, tier, and where it came from. The registry gains a `describe()` that returns that list.
- Install from a file: a `.py` file, a `.zip` holding `.py` files at its top level, or a folder path. A single file or the files of a zip are staged, checked, and moved into `plugins/`. A zip or folder holding a `pyproject.toml` is installed through pip from that path into the virtual environment, in a child process, with the log shown. A zip entry whose name would leave the staging folder is refused.
- Install from a repository address: an HTTPS address with a commit or tag, never a floating branch, installed through pip in a child process with the log shown. This is the form the [plug-in architecture](plugin-architecture.md) page already documents.
- The check, run in a child process with a time limit before anything is placed: the file parses; it has a `register` function; each class it registers passes its kind's protocol check; a name that would shadow a built-in or an installed plug-in is listed and needs a confirming press. A plug-in may declare `EXTRACTIUM_REQUIRES = ">=0.3,<1"` at module level; when present it is compared with the installed version, and when absent the page says the plug-in declares no version. The result shows what the plug-in would register before the person confirms, next to the file's hash and a sentence that installing runs its code.
- Remove: a file is deleted from `plugins/`; a package is uninstalled through pip; a built-in cannot be removed, only shadowed.

**Tests.** A good plug-in of each kind passes and is placed; a file with no `register` fails with the reason; a class missing a method fails with the method named; a shadowing name is reported; an import that hangs is stopped by the time limit; a zip with a traversal entry is refused; a plain-HTTP or unpinned address is refused; a version outside `EXTRACTIUM_REQUIRES` is reported; removal of a file and of a package, with pip faked; a built-in is not removable; `describe()` lists all three tiers.

**Documentation.** [Plug-in architecture](plugin-architecture.md) for installing from the page and for `EXTRACTIUM_REQUIRES`, the new page on using the local page, and the [compliance](compliance.md) page.

**Done when** the three example plug-ins from the plug-in architecture page install from a file and from a repository address, show in the list, act in a build, and remove cleanly, and issue #98 can close.


## After Stage 8

Not scheduled, kept here so the shape is known:

- **A plug-in catalog.** A file `plugins.json` in this repository listing published plug-ins, each with a name, a kind, a one-line description, its repository address, the pinned commit or tag, and the hash of that commit's archive. The plug-ins page reads it and shows an "Install" button per entry that goes through the same check as Stage 8. The catalog is a listing, not an endorsement, and the page says so.
- **A static search page in the output folder.** The Stage 6 page written into `dist/` by the build, with the meaning search done in the browser, so a published compendium can be searched on GitHub Pages or GitLab Pages with no server. It needs the browser embedding library and a model download, which is why the local page uses the server instead.
- **Typo tolerance in suggestions**, over titles and tags only, if people ask for it.
- **Portable archives for macOS and Linux**, built the same way as the Windows zip, once there is an answer for the quarantine flag a browser download carries on macOS.
- **A container image for servers and runners.** Everything in a build runs inside a container, and an image would make the GitLab runner file one line. Not for desktops, where the container runtime itself needs admin rights.
- **A tray icon or a window**, if the server's idle quit turns out to annoy people. pywebview can wrap the same page without changing anything else.


## Checks made outside the code

Facts about other software that decide parts of this plan. Each is checked in the stage named and recorded here.

| Check | When | What it decides |
|---|---|---|
| Does Field Station AI accept a `compendium-url` that is a path from the page's own origin, such as `/dist/compendium-full.json.gz`? | Stage 7 | Whether the link can be relative, or must be the full local address with the port. |
| Does Ollama accept requests from a page served at `http://127.0.0.1:<port>`? | Stage 7 | Whether "Ask with AI" finds Ollama with no setting, or the page must tell the person to set `OLLAMA_ORIGINS`. |
| Does Claude Desktop accept a plain-HTTP address on the loopback as a connector? | Stage 7 | Whether the card offers it the `/mcp` address or only the standard-input command. |
| Do the Cursor and VS Code install links open with the snippet filled in? | Stage 7 | Whether those two buttons stay on the panel. |
| Does cron on macOS run the script from the person's folder without Full Disk Access? | Stage 5 | Whether the documentation must send macOS users to System Settings first, or to launchd. |
| Does uv start from a folder under the person's profile on a Michigan Medicine imaged Windows machine with no admin rights? | Stage 4 | Whether uv is the main path for the center's users, or the machine's Python is. |
| Can uv install from the hash-pinned lock file with every hash enforced? | Stage 4 | Whether uv makes the environment itself, or only supplies the Python while pip installs from the lock. |
| Does the portable zip with the packages and the three models stay under two gigabytes? | Stage 4 | Whether the models ship inside the zip, or as a second one. |


## Assumptions and risks

- The settings file is read and written with `yaml.safe_load` and its counterpart, which keep no comments. The form warns before the first save and keeps the previous file. Keeping comments would need a different YAML library, which is a dependency decision for later.
- Field Station AI loads the whole full file in the browser. On a small machine, or with a full file of hundreds of megabytes, that can fail. The button falls back to the light file, and the documentation says which to expect.
- The meaning search on the page loads the embedding model into the server, which takes a few seconds the first time and a few hundred megabytes of memory while the page runs. That is the same cost a build pays.
- Windows may show a firewall prompt the first time the server listens, although it listens on the loopback address only. If it does, the documentation shows the prompt and says that allowing it opens nothing to the network.
- uv is a third-party program downloaded at install time. The installer pins its version and checks its hash, and moving the pin is where its release notes are read. A machine whose policy refuses every downloaded executable from a user folder cannot run uv, a packaged binary, or pip's wrapper executable; only a Python that IT installed works there, which is why the fallback starts the tool through the interpreter.
- The embedding and transcription packages are about two gigabytes installed. The release zip carries them compressed and must stay under GitHub's two-gigabyte limit on a release file; if the models push it over, they become a second zip. Explorer's own unzip copies the download mark onto every extracted file, so the first double-click on `run.bat` may show the "Windows protected your PC" prompt once; unblocking the zip before unzipping avoids it, and the installation guide shows how.
- A plug-in is checked, not sandboxed. The check catches a plug-in that does not fit; it cannot catch one written to do harm. The page says so where it matters.


## Keeping this page current

When a stage finishes, add a one-line note under its heading with the date and the branch. When scope changes, edit the stage here, and the matching pages under `docs/` in the same change. A plan that disagrees with the code is a defect, the same as any other stale page.


## Conclusion

You now know what the local page is for, what it reuses, the decisions behind it, and the eight stages that build it. Start with Stage 1, which changes the clients and the build and needs no page, and update this page when you finish.


## Additional Resources

* [Extractium™ README](../README.md): project overview and quick start.
* [Implementation plan](implementation-plan.md): the plan for the engine, and the record of what was decided against.
* [Architecture and Current State](architecture.md): what exists in the repository today.
* [Container format](container-format.md): the light and full files the search page reads.
* [Plug-in architecture](plugin-architecture.md): the three kinds, the tiers, and the pinned pip install the plug-ins page uses.
* [How to connect an MCP client](how-to/connect-an-mcp-client.md): the servers and the config snippet the card grows from.
* [How to run a weekly build](how-to/run-a-weekly-build.md): the cron and Task Scheduler lines the schedule switch writes.
* [Installation guide](how-to/install.md): the zip, the installer, and the folder it builds, as Stage 4 delivered them.
* [uv](https://docs.astral.sh/uv/): the program the installer uses to bring its own Python and install the lock.
* [Field Station AI](https://github.com/DepressionCenter/FieldStationAI): the in-browser client "Ask with AI" opens, and its `compendium-url` parameter.
* [Issue #98, front-end needed](https://github.com/DepressionCenter/extractium/issues/98): the request this plan answers.
* [Issue #42, guided setup](https://github.com/DepressionCenter/extractium/issues/42): the setup the welcome screen and settings form deliver.
* [Model Context Protocol](https://modelcontextprotocol.io/): the standard the search tool speaks.


[← Back to README](../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
