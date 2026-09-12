<!--
This file is part of Extractium™
docs/how-to/install.md
Author(s): Gabriel Mongefranco
Created: 2026-09-12
Last Modified: 2026-09-12
Summary: How to install Extractium: the supported Python versions, the
one-command scripts against a developer install, the three optional
extras and what each is for, what the lock file pins, what the first
build downloads, and how to check that an install works.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Install

[← Back to README](../../README.md)


## Summary

This page gets Extractium onto your machine. There are two ways in: a script that installs and builds in one step, for a person who wants a knowledge base, and an ordinary editable install, for a developer who will change the code. It also explains the three optional extras, what the lock file pins, and how to tell that the install worked. Read it once, before your first build.


## What you need

- **Python 3.10 or newer.** The scheduled build on GitHub uses 3.12, and the test suite runs on newer releases as well. Check with `python --version`.
- **Git**, to clone the repository.
- **About one gigabyte of disk** for the dependencies. The embedding model is another 130 MB, downloaded on the first build.
- **Node.js**, only if you will run the JavaScript client's tests or one of the Node search servers. A build needs no Node.

Nothing else is installed system-wide. Everything goes into a virtual environment inside the clone.


## Way 1: the one-command script

This is the way for a person who wants to build a knowledge base and does not plan to change the code.

1. Clone the repository:

   ```
   git clone https://github.com/DepressionCenter/extractium.git
   cd extractium
   ```

2. Put a settings file named `config.yaml` in that folder. Copy [examples/config.example.yaml](../../examples/config.example.yaml) and change the seed URL to your own site.
3. Run the script for your system:

   ```
   ./run.sh                  # macOS and Linux
   run.bat                   # Windows
   ```

The script creates a virtual environment in `.venv`, installs the exact package versions the lock file records, installs Extractium into it, runs the build, and prints what to commit. Running it again reuses the environment and only rebuilds. [How to run a weekly build](run-a-weekly-build.md) covers what the script accepts and how to change what it builds.

The script installs the runtime dependencies only. A build made this way indexes documentation, records a repository's source files by name, and reads video captions a person already stored, but it does not analyze code and does not fetch new captions. For either of those, use way 2, or regenerate the lock file with the extra included as described below.


## Way 2: the developer install

This is the way for anyone who will run the tests, change the code, or write a plugin.

1. Clone the repository and open a terminal in it.
2. Create and activate a virtual environment:

   ```
   python -m venv .venv
   source .venv/bin/activate      # macOS and Linux
   .venv\Scripts\activate         # Windows
   ```

3. Install Extractium in editable mode, with the extras you need:

   ```
   pip install -e ".[dev,code,youtube]"
   ```

Install from inside the clone, not from an empty folder: `pip install -e .` reads the `pyproject.toml` in the folder you are in. Editable mode means a change to the code takes effect the next time you run the tool, with no reinstall.


## The three extras

The core install reads websites, GitHub documentation, DSpace repositories, and local folders. Three optional extras add what a smaller number of builds need. Name them inside the square brackets, separated by commas.

| Extra | What it adds | When you need it |
|---|---|---|
| `dev` | `pytest` and `pytest-cov`, the test tools. | To run the test suite. |
| `code` | The Tree-sitter parser and thirteen language grammars. | To index the structure of a repository's code: what each file defines, imports, and calls. Without it, every source file is still recorded by name, language, and length. |
| `youtube` | The caption library. | To fetch captions from YouTube. Without it, a build still reads transcripts already stored under `cache_dir`. |

Universal Ctags is a fourth, optional piece that is not a Python package. When it is installed on the machine, the code analysis uses it for languages no grammar covers, such as R. Install it with your system's package manager, or leave it out; a build says which files it could not analyze and why.

Two environment variables are optional too. `GITHUB_TOKEN` raises the request limit when reading GitHub, and `YOUTUBE_API_KEY` lets a build list a whole channel rather than the newest hundred videos of each listing. Neither is ever read from a settings file. See [how to crawl a site](crawl-a-site.md) for when each is worth setting.


## What the lock file pins

`requirements-lock.txt` at the repository root records the exact version and the hash of every runtime dependency. The run scripts and the scheduled workflow install from it with `--require-hashes`, so a package whose contents do not match what was locked is refused rather than installed. The developer install does not use it: `pip install -e .` resolves versions from the ranges in `pyproject.toml`.

The file is generated for every platform at once, so it lists packages that install on Linux only. Those are the CUDA libraries the embedding stack can use on a machine with a graphics card. A Linux install downloads them, which is several gigabytes more than a Windows or macOS install; the build does not need them and runs on the processor either way.

To regenerate the file after changing a dependency, run the command recorded in its header. It needs the `uv` tool:

```bash
uv pip compile pyproject.toml --universal --python-version 3.11 --generate-hashes -o requirements-lock.txt
```

Add `--extra code` to include the parser set, or `--extra youtube` for the caption library, when a scheduled build needs one of them. Keep the header at the top of the file when you do; the command that produced the list is recorded on the line below it.


## What the first build downloads

The first build downloads the embedding model, `BAAI/bge-small-en-v1.5`, about 130 MB, into the Hugging Face cache folder in your home directory. Later builds reuse it and run offline. Nothing else is fetched at build time except the pages, repositories, and captions your settings file names.


## Check that it worked

Print the version:

```
python -m extractium.cli --version
```

The short form, `extractium --version`, works once Python's scripts folder is on your `PATH`, which it often is not after a user install. The module form always works.

With the `dev` extra installed, run the test suite. No test contacts a live site; every response comes from committed fixtures:

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


## Conclusion

You can now install Extractium either way, choose the extras a build needs, and confirm the install with the version flag and the test suite. Next, read [how to crawl a site](crawl-a-site.md) to set up your first build, or [running a build](../usage.md) for the command reference.


## Additional Resources

* [Extractium™ README](../../README.md) — project overview and quick start.
* [How to Crawl a Site](crawl-a-site.md) — setting up and reading your first build.
* [How to Run a Weekly Build](run-a-weekly-build.md) — what the one-command scripts accept, and the scheduled build.
* [Running a Build](../usage.md) — every command-line option and exit code.
* [Troubleshooting](../troubleshooting.md) — known failures, including the `PATH` fix for the short command form.
* [Compliance](../compliance.md) — why the dependencies are pinned and hash-checked.
* [uv documentation](https://docs.astral.sh/uv/) — the tool that regenerates the lock file.
* [Universal Ctags](https://ctags.io/) — the optional second parser for languages no grammar covers.
* [BAAI/bge-small-en-v1.5 model card](https://huggingface.co/BAAI/bge-small-en-v1.5) — the embedding model the first build downloads.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
