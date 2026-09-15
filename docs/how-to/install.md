<!--
This file is part of Extractium™
docs/how-to/install.md
Author(s): Gabriel Mongefranco
Created: 2026-09-12
Last Modified: 2026-09-15
Summary: How to install Extractium: the supported Python versions, the
build script and the developer install, the optional extras and what
each is for, what the lock file pins, what the first build downloads,
and how to check that the install worked.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Install

[← Back to README](../../README.md)


## Summary

This page shows you how to install Extractium™ on your computer. Extractium™ can be installed two different ways: with the build script, which installs and builds in one step, or in a Python development environment, which you will want if you plan to run the tests, change the code, or write a plug-in. The page also explains the optional extras, what the lock file pins, and how to check that the install worked.


## What you need

- Python 3.10 or newer. Check your version with `python --version`.
- Git, to clone the repository.
- About one gigabyte of disk space for the dependencies. The embedding model takes another 130 MB and is downloaded on the first build.
- Node.js, only if you will run the JavaScript client's tests or one of the Node search servers. A build does not need Node.

Nothing is installed system-wide. Everything goes into a virtual environment inside the cloned folder.


## Option 1: the build script

Use this option if you want to build a knowledge base and do not plan to change the code. You do not need git.

1. Make an empty folder for your knowledge base and save the script for your operating system into it: [run.sh](https://raw.githubusercontent.com/DepressionCenter/extractium/main/run.sh) for macOS and Linux, or [run.bat](https://raw.githubusercontent.com/DepressionCenter/extractium/main/run.bat) for Windows. If you have git, you can clone the repository instead and run the script from inside the clone.
2. Run the script:

   ```
   ./run.sh                  # macOS and Linux
   run.bat                   # Windows
   ```

3. Answer its three questions: the name of your knowledge base, a short name for its files (press Enter to accept the one it suggests), and the website to start crawling from.

When the script is on its own, it first downloads the latest release of Extractium™ into a folder called `extractium-src` beside itself. The folder is named that way, and not `extractium`, because Python would otherwise mistake it for the installed package when you run a build from the folder above it. It uses git when git is installed. Otherwise it downloads the release archive, through `curl` or `wget` on macOS and Linux, through PowerShell on Windows, or through Python itself when none of those is present. To pin a release, set `EXTRACTIUM_REF` to its tag before running the script.

The script then creates a virtual environment in `.venv`, installs the exact package versions recorded in the lock file, installs Extractium™ into it, writes `config.yaml` from your answers, runs a first build limited to 25 pages, and prints what to do next. Running it again reuses the environment, skips the questions, and builds the whole site. See [how to run a weekly build](run-a-weekly-build.md) for the options the script accepts.

The script installs the runtime dependencies, the code parsers, and the caption library, so a build made this way indexes documentation, the structure of a repository's code, and what is said in a video. Fetching captions still has to happen on your own computer, because YouTube refuses caption requests from cloud-provider addresses; the `youtube` section of the [configuration reference](../configuration.md) explains what to commit so a scheduled build reads the stored copies.


## Option 2: the Python development environment

Use this option if you will run the tests, change the code, or write a plug-in.

1. Clone the repository and open a terminal in it.
2. Create and activate a virtual environment:

   ```
   python -m venv .venv
   source .venv/bin/activate      # macOS and Linux
   .venv\Scripts\activate         # Windows
   ```

3. Install Extractium™ in editable mode, with the extras you need:

   ```
   pip install -e ".[dev,code,youtube]"
   ```

Run the install from inside the cloned folder, not from an empty one, because `pip install -e .` reads the `pyproject.toml` in the folder you are in. Editable mode means a change to the code takes effect the next time you run the tool, with no reinstall.

To write a first settings file, run `python -m extractium.cli init`. It asks the same three questions the build script asks and writes `config.yaml`. [Running a build](../usage.md) describes the command and its flags.


## The optional extras

The core install reads websites, GitHub documentation, DSpace repositories, knowledge bundles, and local folders. Four optional extras add what some builds need. Name them inside the square brackets, separated by commas.

| Extra | What it adds | When you need it |
|---|---|---|
| `dev` | `pytest` and `pytest-cov`, the test tools. | To run the test suite. |
| `code` | The Tree-sitter parser and its language grammars. | To index the structure of a repository's code: what each file defines, imports, and calls. The build script installs it from the lock file already; a developer install has to name it. Without it, every source file is still recorded by name, language, and length. |
| `youtube` | The caption library. | To fetch captions from YouTube. Without it, a build still reads transcripts already stored under `cache_dir`. |
| `pdf` | `pypdf`, the PDF reader. | To read PDF files when a source sets `read_documents: true`. The build script installs it from the lock file already; a developer install has to name it. Without it, every PDF is skipped with a line saying so, and Word, OpenDocument, and RTF files are still read. |

Universal Ctags is a fourth optional piece, and it is not a Python package. When it is installed on your computer, the code analysis uses it for languages that have no Tree-sitter grammar, such as R. Install it with your system's package manager, or leave it out. A build tells you which files it could not analyze and why.

Two environment variables are optional as well. `GITHUB_TOKEN` raises the request limit when reading GitHub, and `YOUTUBE_API_KEY` lets a build list a whole channel rather than the newest hundred videos of each listing. Neither is ever read from a settings file. See [how to crawl a site](crawl-a-site.md) for when each one is worth setting.


## What the lock file pins

`requirements-lock.txt` at the repository root records the exact version and the hash of every runtime dependency, of the code parsers, of the caption library, and of the PDF reader. The build scripts and the scheduled workflow install from it with `--require-hashes`, so a package whose contents do not match what was locked is refused rather than installed. The development install does not use the lock file: `pip install -e .` resolves versions from the ranges in `pyproject.toml`.

The lock file is generated for every platform at once, so it lists packages that install on Linux only. Those are the CUDA libraries the embedding stack can use on a machine with a graphics card. A Linux install downloads them, which adds several gigabytes compared to a Windows or macOS install. The build does not need them and runs on the processor either way.

To regenerate the file after changing a dependency, run the command recorded in its header. It needs the `uv` tool:

```bash
uv pip compile pyproject.toml --universal --python-version 3.11 --generate-hashes --extra code --extra youtube --extra pdf -o requirements-lock.txt
```

Keep all three extras: tests check that every parser named in `pyproject.toml`, the caption library, and the PDF reader are pinned in the lock, because the build scripts install from the lock alone and a package missing from it is a package no scripted build has. Keep the license header at the top of the file when you do.


## What the first build downloads

The first build downloads the embedding model, `BAAI/bge-small-en-v1.5`, about 130 MB, into the Hugging Face cache folder in your home directory. Later builds reuse it and run offline. Nothing else is fetched at build time except the pages, repositories, and captions your settings file names.


## Check that it worked

Print the version:

```
python -m extractium.cli --version
```

The short form, `extractium --version`, works once Python's scripts folder is on your `PATH`. After a user install it often is not, so the module form is the reliable one.

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

Python 3.13 and 3.14 come in two builds, and the python.org installer offers the free-threaded one (`3.13t`, `3.14t`) as an optional part. The build script prefers a standard build, because the code parsers ship compiled wheels the free-threaded build cannot use. On a machine that has only the free-threaded build, the script installs everything except the parsers and says so: code files are still recorded by name, language, and length, but what they define is not read. Install a standard build, or set `PYTHON` to the path of one, to get the parsers. [Troubleshooting](../troubleshooting.md) has the pip message this shows up as.


## Conclusion

You can now install Extractium™ either way, choose the extras a build needs, and confirm the install with the version flag and the test suite. Next, read [how to crawl a site](crawl-a-site.md) to set up your first build, or [running a build](../usage.md) for the command reference.


## Additional Resources

* [Extractium™ README](../../README.md): project overview and quick start.
* [How to Crawl a Site](crawl-a-site.md): setting up and reading your first build.
* [How to Run a Weekly Build](run-a-weekly-build.md): what the build scripts accept, and the scheduled build.
* [Running a Build](../usage.md): every command-line option and exit code.
* [Troubleshooting](../troubleshooting.md): known failures, including the `PATH` fix for the short command form.
* [Compliance](../compliance.md): why the dependencies are pinned and hash-checked.
* [uv documentation](https://docs.astral.sh/uv/): the tool that regenerates the lock file.
* [Universal Ctags](https://ctags.io/): the optional second parser for languages with no grammar.
* [BAAI/bge-small-en-v1.5 model card](https://huggingface.co/BAAI/bge-small-en-v1.5): the embedding model the first build downloads.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
