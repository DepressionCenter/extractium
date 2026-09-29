<!--
This file is part of Extractium™
docs/how-to/install.md
Author(s): Gabriel Mongefranco
Created: 2026-09-12
Last Modified: 2026-09-30
Summary: How to install Extractium: the release zip for Windows, the
installer for every system, and the developer checkout; what the
installer does and what it asks IT for when it cannot; the folder it
builds and the two places it lives; the command and the menu entry;
updating and removing; the optional extras, the lock file, and how to
check that the install worked.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Install

[← Back to README](../../README.md)


## Summary

This page shows you how to put Extractium™ on your computer. You do not need admin rights, and you do not need Python: the tool brings its own. On Windows, the quickest way is the release zip, which you unzip and run. On any system, the installer downloads what it needs and installs the tool for your own account, with an `extractium` command and an entry in the Start menu or its equivalent. Developers who will change the code install from a checkout instead. The page also explains what the installer does when something on your computer stops it, how to update and remove the tool, the optional extras, and what the lock file pins.


## What you need

- A computer running Windows, macOS, Fedora, or Debian, or another Linux the same tools run on. No admin rights.
- About three gigabytes of free disk space. The packages are about two gigabytes installed, and the three models a build and a search use are a few hundred megabytes more.
- Network access to GitHub, for the download, and to PyPI, for the packages, unless you use the Windows zip, which downloads nothing.
- Node.js, only if you will run the JavaScript client's tests or one of the Node search servers. A build does not need Node.

Nothing is installed system-wide. Everything goes into one folder named `Extractium`, either beside your data or under your own profile.


## Option 1: the release zip, on Windows

Use this option on a Windows computer where you cannot install software. The zip is built by a workflow for every release. It holds the `Extractium` folder ready to run, with a Python, every package from the lock file, the tool, and the three models already in the cache, plus `run.bat` and `install.bat`. Nothing is downloaded when you run it. Its exact size is listed on the releases page beside the file, and it is large, so download it over a good connection.

1. Open the [releases page](https://github.com/DepressionCenter/extractium/releases) and download `extractium-<version>-windows-portable.zip` from the newest release. If the release also lists a `-models.zip`, download that too; it holds the models when they did not fit in the first file.
2. Before you unzip, right-click the zip, choose Properties, tick "Unblock" at the bottom of the General tab, and press OK. Windows marks a downloaded file, and Explorer copies that mark onto every file it unzips, which would make the first double-click show a "Windows protected your PC" prompt. Unblocking the zip first avoids it. If you see the prompt anyway, press "More info" and then "Run anyway"; it appears once.
3. Unzip it into the folder where your compendium should live, for example `C:\Users\you\Extractium`. Unzip the models zip, if there is one, into the same folder, so its `Extractium\cache` lands inside the same `Extractium` folder.
4. Double-click `run.bat`. It asks whether to set up in the browser or in the terminal. Press Enter for the browser, and the local page opens with four questions on it. [How to use the local page](use-the-local-page.md) walks through them.

That is a portable install: everything is in the `Extractium` folder beside `run.bat`, nothing else on the computer changes, and you can move or copy the whole folder. The releases page lists the SHA-256 of each zip. To check a download, open PowerShell in the folder and compare the result of `Get-FileHash -Algorithm SHA256 <the zip>` with the value listed.

To also have the `extractium` command in every terminal and Extractium in the Start menu, double-click `install.bat` from the same folder. It copies the `Extractium` folder under your profile, to `%LOCALAPPDATA%\Extractium`, adds its `bin` folder to your own PATH, and makes the Start menu entry, again with no download. The copy beside your data keeps working and can be deleted.


## Option 2: the installer

Use this option on macOS and Linux, and on Windows when you would rather not download the zip.

1. Download the installer for your system into any folder: [install.bat](https://raw.githubusercontent.com/DepressionCenter/extractium/main/install.bat) for Windows, or [install.sh](https://raw.githubusercontent.com/DepressionCenter/extractium/main/install.sh) for macOS and Linux. Each release attaches the same two files.
2. Run it:

   ```
   bash install.sh           # macOS and Linux
   install.bat               # Windows, or double-click it
   ```

3. Read what it prints at the end. It names the folder it installed into, says that a new terminal is needed for the `extractium` command, and on macOS and Linux tells you when `~/.local/bin` is not on your PATH and which line to add to your shell profile.
4. Open a new terminal and run `extractium --version`. Then run `extractium` in the folder where your compendium should live, or open Extractium from the Start menu, Launchpad, or the applications menu.

The installer installs and exits. It asks no setup question and runs no build; the first run of `extractium` does that.

### What the installer does

The installer tells three situations apart by what sits beside it. With an `Extractium` folder beside it, as in the zip, it copies that folder under your profile and downloads nothing. Inside a checkout of the repository, it installs the checkout. On its own, it looks up the newest release, downloads that release's archive, and builds the folder from scratch through four steps, each tried rather than assumed:

1. It downloads uv, a small program that installs Python and packages, at the version written in the script, and checks the download against the SHA-256 written beside it. A download that does not match is refused. It then asks uv for its version, which is how it learns whether your computer lets a downloaded program run from your profile.
2. uv downloads a standard Python 3.12 into the folder, installs every package from the lock file with every hash checked, and installs the tool without dependencies. Every uv call trusts the certificates your computer trusts, so a proxy that inspects traffic does not stop it. When the managed Python cannot be downloaded, uv looks for a suitable Python already on the computer and makes a virtual environment inside the folder on it.
3. When uv cannot run at all, the installer looks for a standard Python 3.10 or newer already on the computer, makes a virtual environment inside the folder with it, and installs from the same lock file with pip. On Debian and Ubuntu, where Python ships without the `venv` module, it prints the `apt-get` command that adds it and asks before running it. Where no Python is found, it prints the `dnf`, `brew`, or `winget` command that would install one and asks the same way. It never runs a command with admin rights on its own.
4. When none of that works, it stops, names the step that failed, and says what to ask IT for: permission to run programs from your profile folder, or a standard Python installed for you.

An install made on a Python already on the computer, in steps 2 and 3, works the same but cannot be moved, because a virtual environment records where it was made. The installer says so, and a file named `not-portable.txt` in the folder records it.

### The Extractium folder

Whichever way it was made, the folder holds the same things:

| Inside the folder | What it is |
|---|---|
| `uv` or `uv.exe` | The program that installed the Python and the packages, kept for updates. Absent after step 3. |
| `python\` | The Python uv installed, with every package inside it. |
| `venv\` | A virtual environment instead, after step 3 or when the managed Python could not be downloaded. |
| `bin\extractium.cmd`, or `bin/extractium` | The command. It starts the tool through the folder's own Python, by a path relative to itself, so the folder works wherever it is. On macOS and Linux, `bin/extractium-page` beside it opens the page from the menu with no terminal. |
| `cache\` | The models: the embedding model, the reranker, and the Whisper model. They travel with the folder, so a copy of the folder never downloads them again. |
| `extractium-ui.log` | The lines the page prints when it was started from the menu, with no terminal to show them. |
| `last-folder.txt` | The compendium folder the page used last, so the menu entry reopens it. |
| `installed-version.txt` | The release installed. |
| `install.bat` or `install.sh` | A copy of the installer, for updating and removing. |

The folder lives in one of two places. Beside your data, as the zip unpacks it or as `--portable` builds it, it is the portable install: nothing else on the computer changes. Under your profile, at `%LOCALAPPDATA%\Extractium` on Windows or `~/.local/share/extractium` on macOS and Linux, it is the per-user install, with the command on your PATH and the menu entry.

### The command and the menu entry

For a per-user install, the installer asks once before it changes your PATH. On Windows it adds the folder's `bin` to your own PATH through the per-user registry key, which needs no admin rights, and says that a new terminal is needed before `extractium` is found. On macOS and Linux it writes a two-line script at `~/.local/bin/extractium` that runs the folder's command. When `~/.local/bin` is not on your PATH, it prints the line to add to your shell profile rather than editing the profile itself.

The menu entry is named "Extractium" and opens the page. On Windows it is a Start menu shortcut that runs the command with `ui` in a minimized window, so the window exists for Ctrl+C but stays out of the way. On macOS it is `Extractium.app` under `~/Applications`, and on Linux a `.desktop` file under `~/.local/share/applications`; both start the page with no terminal, and the page's lines go to `extractium-ui.log` in the folder. The page opens the compendium folder it used last, or the welcome screen when there is none.

### Updating and removing

Run the installer copy inside the folder, or a fresh download of it, with a flag:

| Command | What it does |
|---|---|
| `install.bat --update`, `bash install.sh --update` | Moves the install to the newest release, into the same folder, downloading only what changed. |
| `install.bat --version v0.5`, `bash install.sh --version v0.5` | Installs, or updates to, that release rather than the newest. |
| `install.bat --uninstall`, `bash install.sh --uninstall` | Asks, then removes the PATH entry, the command, the menu entry, and the folder. |
| `install.bat --portable`, `bash install.sh --portable` | Builds the folder beside the script instead of under your profile, and changes nothing else. This is what the release workflow runs. |

Set `EXTRACTIUM_REPO` in the environment to install from a fork.


## Option 3: the developer checkout

Use this option if you will run the tests, change the code, or write a plug-in.

1. Clone the repository and open a terminal in it.
2. Either run the installer with `--editable`, which builds the folder under your profile as above but points it at the checkout, so a change to the code takes effect the next time you run the tool:

   ```
   bash install.sh --editable     # macOS and Linux
   install.bat --editable         # Windows
   ```

   Or make a virtual environment yourself and install with the extras you need:

   ```
   python -m venv .venv
   source .venv/bin/activate      # macOS and Linux
   .venv\Scripts\activate         # Windows
   pip install -e ".[dev,code,youtube,pdf,keywords]"
   ```

Run the pip install from inside the cloned folder, not from an empty one, because `pip install -e .` reads the `pyproject.toml` in the folder you are in. In your own environment the command is `python -m extractium.cli`; the rest of this documentation writes it that way. `python -m extractium.cli init` writes a first settings file from the terminal, and `python -m extractium.cli ui` asks the same questions on the local page.


## The optional extras

The core install reads websites, GitHub documentation, DSpace repositories, knowledge bundles, and local folders. Six optional extras add what some builds need. The installer and the zip include every one of them from the lock file; a developer install with pip names them inside the square brackets, separated by commas.

| Extra | What it adds | When you need it |
|---|---|---|
| `dev` | `pytest` and `pytest-cov`, the test tools. | To run the test suite. |
| `code` | The Tree-sitter parser and its language grammars. | To index the structure of a repository's code: what each file defines, imports, and calls. Without it, every source file is still recorded by name, language, and length. |
| `youtube` | The caption library. | To fetch captions from YouTube. Without it, a build still reads transcripts already stored under `cache_dir`. |
| `whisper` | `yt-dlp` and `faster-whisper`, the audio transcription packages. | To transcribe a video from its audio when YouTube refuses its captions, which it does to most machines that build on a schedule and to many on shared networks. Without it, a refused build keeps what it read and reports the video content as incomplete. About 200 MB of packages, and a 75 MB model. |
| `pdf` | `pypdf`, the PDF reader. | To read PDF files when a source sets `read_documents: true`. Without it, every PDF is skipped with a line saying so, and Word, OpenDocument, and RTF files are still read. |
| `keywords` | `yake`, the keyword extractor. | To name every section with keywords and every page with tags, which the build does by default. Without it, the build says so once and every output leaves the keyword fields empty. |

Universal Ctags is one more optional piece, and it is not a Python package. When it is installed on your computer, the code analysis uses it for languages that have no Tree-sitter grammar, such as R. Install it with your system's package manager, or leave it out. A build tells you which files it could not analyze and why.

Two environment variables are optional as well. `GITHUB_TOKEN` raises the request limit when reading GitHub, and `YOUTUBE_API_KEY` lets a build list a whole channel rather than the newest hundred videos of each listing. Neither is ever read from a settings file. See [how to crawl a site](crawl-a-site.md) for when each one is worth setting.


## What the lock file pins

`requirements-lock.txt` at the repository root records the exact version and the hash of every runtime dependency, of the code parsers, of the caption library, of the audio transcription packages, of the PDF reader, and of the keyword extractor. The installer, the release workflow, and the scheduled workflow install from it with every hash checked, so a package whose contents do not match what was locked is refused rather than installed. The pip development install does not use the lock file: `pip install -e .` resolves versions from the ranges in `pyproject.toml`.

The lock file is generated for every platform at once, so it lists packages that install on Linux only. Those are the CUDA libraries the embedding stack can use on a machine with a graphics card. A Linux install downloads them, which adds several gigabytes compared to a Windows or macOS install. The build does not need them and runs on the processor either way.

To regenerate the file after changing a dependency, run the command recorded in its header. It needs the `uv` tool:

```bash
uv pip compile pyproject.toml --universal --python-version 3.11 --generate-hashes --extra code --extra youtube --extra pdf --extra keywords --extra whisper -o requirements-lock.txt
```

Keep all five extras: tests check that every parser named in `pyproject.toml`, the caption library, the audio transcription packages, the PDF reader, and the keyword extractor are pinned in the lock, because the installer installs from the lock alone and a package missing from it is a package no scripted build has. Keep the license header at the top of the file when you do.

The installer pins two more things in its own text: the uv version and the SHA-256 of each uv archive, and the Python version uv installs. Move them together, after reading uv's release notes, and copy the hashes from the files uv publishes beside each archive.


## What the first build downloads

The Windows zip carries the three models, so a build made from it downloads nothing but the pages it crawls. Every other install downloads the embedding model, `BAAI/bge-small-en-v1.5`, about 130 MB, on the first build, and the reranker and the Whisper model the first time a search or an audio transcription needs them. They go into the `cache` folder inside the Extractium folder, so they move with it, and later builds run offline. A pip development install keeps them in the Hugging Face cache folder in your home directory instead.


## Check that it worked

Open a new terminal and print the version:

```
extractium --version
```

If the command is not found, the terminal is one that was open before the install, or on macOS and Linux `~/.local/bin` is not on your PATH; [troubleshooting](../troubleshooting.md) covers both, and the command works by its full path in the meantime: `%LOCALAPPDATA%\Extractium\bin\extractium.cmd` on Windows, `~/.local/share/extractium/bin/extractium` elsewhere. In a pip development environment the command is `python -m extractium.cli --version`.

With the `dev` extra installed, run the test suite. No test contacts a live site. Every response comes from committed fixtures:

```
python -m pytest -q
```

To check the JavaScript client and the Node search servers as well, with Node.js installed:

```
node --test clients/js
node --test examples/mcp/local-node
node --test examples/mcp/shared
```

The Val Town and Cloudflare examples each carry their own test command in their READMEs.


## A free-threaded Python

Python 3.13 and 3.14 come in two builds, and the python.org installer offers the free-threaded one (`3.13t`, `3.14t`) as an optional part. The code parsers ship compiled wheels the free-threaded build cannot use. The Python uv installs is a standard build, so this only matters when the installer falls back to a Python already on the computer: there it looks for a standard build and skips a free-threaded one. Set `PYTHON_EXE` to the path of a standard build to have it tried first. A developer who installs with pip on a free-threaded Python can leave the parsers out with `tools/lock_without_parsers.py`, which writes a copy of the lock without them; [troubleshooting](../troubleshooting.md) has the pip message this shows up as.


## Conclusion

You can now install Extractium™ from the zip, with the installer, or from a checkout, know what the installer does when your computer stops it, update or remove the install, and confirm it with the version flag and the test suite. Next, read [how to use the local page](use-the-local-page.md) to set up your first build in the browser, or [how to crawl a site](crawl-a-site.md) and [running a build](../usage.md) for the terminal.


## Additional Resources

* [Extractium™ README](../../README.md): project overview and quick start.
* [Releases](https://github.com/DepressionCenter/extractium/releases): the zip, the installers, and the hash of each file.
* [How to Use the Local Page](use-the-local-page.md): the page the menu entry opens, and its four questions.
* [How to Crawl a Site](crawl-a-site.md): setting up and reading your first build.
* [How to Run a Weekly Build](run-a-weekly-build.md): the run scripts, the command, and the scheduled build.
* [Running a Build](../usage.md): every command-line option and exit code.
* [Troubleshooting](../troubleshooting.md): known failures, including a command not found and a download Windows blocks.
* [Compliance](../compliance.md): why uv, the release, and every package are pinned and hash-checked, and what the installer never does.
* [uv documentation](https://docs.astral.sh/uv/): the program the installer uses to bring its own Python and install the lock.
* [Universal Ctags](https://ctags.io/): the optional second parser for languages with no grammar.
* [BAAI/bge-small-en-v1.5 model card](https://huggingface.co/BAAI/bge-small-en-v1.5): the embedding model every build uses.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
