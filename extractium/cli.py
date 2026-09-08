"""
Summary: Command-line entry point for the Extractium build tool (console
script `extractium`, per pyproject.toml [project.scripts]). Reads a
configuration file, resolves the source, site-handler, and adapter plugins
through the registry, runs every source once, hands the documents to the
core build step, and lets each adapter write its own output format.
Progress goes to standard error; the summary goes to standard output.

This file is part of Extractium™
extractium/cli.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-08
Notes: See README file for documentation and full license information.
"""

# Copyright © 2026 The Regents of the University of Michigan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>.

__author__ = "Gabriel Mongefranco, University of Michigan."
__copyright__ = "Copyright (C) 2026 The Regents of the University of Michigan"
__license__ = "GPLv3 or later"
__date__ = "2026-08-17"

import argparse
import sys

import requests

from extractium import __version__
from extractium.config import ConfigError, load_config
from extractium.core import cache as caching
from extractium.core.build import build_compendium
from extractium.core.registry import RegistryError, build_registry
from extractium.sources.web import CrawlSettings

### Exit Codes ###

# Distinct codes so a scheduled build can tell an operator mistake from an
# empty crawl from a disk problem, without anyone reading the log.
EXIT_OK = 0
EXIT_FAILED = 1            # anything unexpected
EXIT_CONFIG = 2            # the configuration file is missing or invalid
EXIT_NO_CONTENT = 3        # the sources produced nothing indexable
EXIT_OUTPUT = 4            # an output could not be written


### Progress And Messages ###

def progress_to_stderr(message):
    """
    Prints one progress line to standard error.

    Progress goes to standard error so that standard output holds only the
    summary, which means a caller can redirect the summary to a file while
    still watching the run.
    """
    print(message, file=sys.stderr, flush=True)


def fail(message, code):
    """Prints one actionable line to standard error and returns the exit code."""
    print(f"extractium: {message}", file=sys.stderr)
    return code


### Sources ###

def run_sources(config, registry, session, cache, progress):
    """
    Runs every configured source in file order and collects its documents.

    Args:
        config (extractium.config.Config): the validated configuration.
        registry (extractium.core.registry.Registry): the resolved plugins.
        session: the HTTP session every source requests through.
        cache (dict): fetch cache metadata, read and updated in place.
        progress (Callable[[str], None]): receives one line per event.

    Returns:
        list[extractium.core.models.Document]: every document produced, in
        source order.

    Raises:
        extractium.core.registry.RegistryError: if a source type is not
            installed, or names a site handler that is not.
    """
    settings = CrawlSettings(
        max_pages=config.max_pages,
        delay_seconds=config.delay_seconds,
        user_agent=config.user_agent,
        respect_robots_txt=config.respect_robots_txt,
    )
    documents = []
    for entry in config.sources:
        progress(f"Source: {entry.type}")
        source = registry.get_source(entry.type)(entry.options)
        # Optional protocol hook: a source that takes part in a crawl
        # learns the enabled site handlers and the global crawl settings
        # here, because neither belongs to its own configuration entry.
        if hasattr(source, "configure"):
            source.configure(registry, settings)
        documents.extend(source.fetch(session, cache, progress))
    return documents


### Outputs ###

def run_outputs(config, registry, compendium, progress):
    """
    Writes every configured output and returns what each one wrote.

    Args:
        config (extractium.config.Config): the validated configuration.
        registry (extractium.core.registry.Registry): the resolved plugins.
        compendium (extractium.core.models.Compendium): the build result.
        progress (Callable[[str], None]): receives one line per output.

    Returns:
        list[tuple]: one (output type, paths written) pair per output.

    Raises:
        OSError: if a file cannot be written.
        extractium.core.registry.RegistryError: if an output type is not installed.
    """
    written = []
    for entry in config.outputs:
        progress(f"Output: {entry.type}")
        adapter = registry.get_adapter(entry.type)()
        options = dict(entry.options, include_local=entry.include_local)
        written.append((entry, adapter.write(compendium, config.out_dir, options)))
    return written


def print_summary(compendium, written):
    """
    Prints what the build produced, on standard output.

    Names every file and its size, and calls out any output that contains
    content read from a local folder, so nobody publishes such a file
    without having been told.
    """
    print(f"Built {compendium.name!r} at {compendium.built_at}")
    print(f"  sections : {len(compendium.parents)}")
    print(f"  windows  : {len(compendium.children)}")
    print(f"  sources  : {compendium.source_count}")
    for entry, paths in written:
        for path in paths:
            size_mb = path.stat().st_size / 1024 / 1024
            print(f"  wrote    : {path} ({size_mb:.2f} MB)")
        if entry.include_local and compendium.local_parents():
            print(f"  NOTICE   : output {entry.type!r} includes local content; check before publishing.")


### Build Command ###

def run_build(args):
    """
    Runs one build from a configuration file.

    Args:
        args (argparse.Namespace): the parsed `build` arguments.

    Returns:
        int: one of the EXIT_ constants.
    """
    overrides = {
        "out_dir": args.out_dir,
        "max_pages": args.max_pages,
    }
    try:
        config = load_config(args.config, overrides=overrides)
    except ConfigError as e:
        return fail(str(e), EXIT_CONFIG)

    try:
        registry = build_registry()
    except RegistryError as e:
        return fail(f"plugins could not be loaded: {e}", EXIT_CONFIG)

    caching.use_cache_dir(config.cache_dir)
    cache = caching.load_cache_meta()
    session = requests.Session()

    try:
        documents = run_sources(config, registry, session, cache, progress_to_stderr)
    except RegistryError as e:
        return fail(str(e), EXIT_CONFIG)
    finally:
        # Saved whatever happened, so a run interrupted halfway still
        # leaves the pages it did fetch usable by the next run.
        caching.save_cache_meta(cache)
        session.close()

    compendium = build_compendium(
        documents,
        name=config.name,
        float32_vecs=args.float32_vecs,
        progress=progress_to_stderr,
    )
    if compendium is None:
        return fail(
            "the sources produced no indexable content, so no output was written. "
            "Check the seed URL and the include and exclude patterns.",
            EXIT_NO_CONTENT,
        )

    try:
        written = run_outputs(config, registry, compendium, progress_to_stderr)
    except RegistryError as e:
        return fail(str(e), EXIT_CONFIG)
    except OSError as e:
        return fail(f"an output could not be written: {e}", EXIT_OUTPUT)

    print_summary(compendium, written)
    return EXIT_OK


### Entry Point ###

def build_parser():
    """The argument parser for the `extractium` console script."""
    parser = argparse.ArgumentParser(
        prog="extractium",
        description="Compile an organization's public documentation into one searchable static file.",
    )
    parser.add_argument("--version", action="version", version=f"extractium {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    build = subcommands.add_parser("build", help="Build every configured output from a configuration file.")
    build.add_argument("--config", required=True, metavar="FILE",
                       help="Path to the YAML configuration file.")
    build.add_argument("--out-dir", metavar="DIR",
                       help="Write outputs here instead of the folder the configuration file names.")
    build.add_argument("--max-pages", type=int, metavar="N",
                       help="Visit at most N pages, overriding the configuration file. Useful for a trial run.")
    build.add_argument("--float32-vecs", action="store_true",
                       help="Store vectors as float32 instead of the default int8, at four times the size.")
    build.set_defaults(handler=run_build)
    return parser


def main(argv=None):
    """
    Entry point for the `extractium` console script.

    Args:
        argv (Sequence[str] | None): arguments to parse. None reads
            sys.argv, which is what the console script does.

    Returns:
        int: the process exit code.
    """
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        return fail("stopped at your request.", EXIT_FAILED)
    except Exception as e:
        # The message reaches the user; the type and traceback do not,
        # because an internal path is not something a user can act on.
        return fail(f"the build failed: {type(e).__name__}: {e}", EXIT_FAILED)


if __name__ == "__main__":
    sys.exit(main())
