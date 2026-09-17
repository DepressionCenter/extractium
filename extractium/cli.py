"""
Summary: Command-line entry point for the Extractium build tool (console
script `extractium`, per pyproject.toml [project.scripts]). Reads a
configuration file, resolves the source, site-handler, and adapter plugins
through the registry, runs every source once, hands the documents to the
core build step, and lets each adapter write its own output format. Along
the way it scans what the sources produced for likely protected health
information and writes the review reports.
Progress goes to standard error; the summary goes to standard output.
The `init` subcommand, in extractium/init.py, writes a first settings
file so a person can start without editing YAML.

This file is part of Extractium™
extractium/cli.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-17
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
__date__ = "2026-09-17"

import argparse
import dataclasses
import os
import sys
import threading
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait

from extractium import __version__
from extractium import init as init_command
from extractium.config import ConfigError, load_config, source_descriptors
from extractium.core import cache as caching
from extractium.core import keywords as keywording
from extractium.core import phi_lint
from extractium.core import retain
from extractium.core.build import page_key_of
from extractium.core.build import build_compendium
from extractium.core.registry import RegistryError, build_registry
from extractium.core.transport import make_session
from extractium.sources.github import accounts_named_by
from extractium.sources.github_api import GitHubSourceError
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

# Sources report from their own threads, so each line is written whole
# under a lock rather than as text and newline in two writes.
_WRITE_LOCK = threading.Lock()


def write_line(message, stream):
    """
    Writes one line to a stream, whatever characters it holds.

    Page titles and file names come from sites nobody here controls, and a
    console whose encoding cannot represent one of their characters raises
    rather than printing. Losing a finished build to that, after the whole
    crawl and every vector, would be absurd, so an unrepresentable
    character is replaced and the line still goes out.
    """
    encoding = getattr(stream, "encoding", None) or "utf-8"
    safe = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
    with _WRITE_LOCK:
        stream.write(safe + "\n")
        stream.flush()


def progress_to_stderr(message):
    """
    Prints one progress line to standard error.

    Progress goes to standard error so that standard output holds only the
    summary, which means a caller can redirect the summary to a file while
    still watching the run.
    """
    write_line(message, sys.stderr)


def fail(message, code):
    """Prints one actionable line to standard error and returns the exit code."""
    write_line(f"extractium: {message}", sys.stderr)
    return code


### Sources ###

def run_sources(config, registry, session, cache, progress):
    """
    Runs every configured source and collects its documents, in file order.

    Up to `parallel_sources` of them run at the same time, each in its own
    thread, over the one session, which paces requests per host so no
    site is asked faster than `delay_seconds` allows. Their documents are
    still returned in file order, so the rule that the first source to
    reach a page keeps it does not depend on which thread finished first.

    Args:
        config (extractium.config.Config): the validated configuration.
        registry (extractium.core.registry.Registry): the resolved plugins.
        session: the HTTP session every source requests through.
        cache (dict): fetch cache metadata, read and updated in place.
        progress (Callable[[str], None]): receives one line per event.

    Returns:
        tuple[list, list[str], set[str]]: every document produced, in
        source order; the notes the sources want the reader to see at the
        end -- how completely each repository was read, and which accounts
        were left out, because a note nobody reads is a gap that will be
        mistaken for an answer; and the keys of the pages the sources
        reported as confirmed gone.

    Raises:
        extractium.core.registry.RegistryError: if a source type is not
            installed, or names a site handler that is not.
    """
    settings = CrawlSettings(
        max_pages=config.max_pages,
        delay_seconds=config.delay_seconds,
        user_agent=config.user_agent,
        respect_robots_txt=config.respect_robots_txt,
        parallel_pages=getattr(config, "parallel_pages", 1),
        # Deny by default: a GitHub account is read only when this build
        # asked for it, either in a source or in the github_owners
        # setting. Otherwise one link in one README could pull thousands
        # of other people's repositories into the index.
        github_owners=tuple(sorted(
            accounts_named_by(config.sources) | {o.lower() for o in config.github_owners}
        )),
    )
    ran = []
    for entry in config.sources:
        source = registry.get_source(entry.type)(entry.options)
        # Optional protocol hook: a source that takes part in a crawl
        # learns the enabled site handlers and the global crawl settings
        # here, because neither belongs to its own configuration entry.
        if hasattr(source, "configure"):
            source.configure(registry, settings)
        ran.append((entry, source))
    documents = fetch_sources(ran, session, cache, progress, getattr(config, "parallel_sources", 1))
    # Links a crawl found and held back, such as videos linked from a
    # page, are offered to every source that reads such links, once every
    # source has run, so the order of the sources list does not decide
    # whether a link is seen. Each source applies its own rule to them.
    links = found_links(source for _, source in ran)
    if links:
        for entry, source in ran:
            if hasattr(source, "read_found_links"):
                progress(f"Source: {entry.type} (links found while crawling)")
                documents.extend(
                    dataclasses.replace(document, source_label=entry.label)
                    for document in source.read_found_links(session, cache, progress, links)
                )
    gone = set()
    for _, source in ran:
        if hasattr(source, "gone_pages"):
            gone.update(retain.page_key(url) for url in source.gone_pages())
    return documents, collect_notes(source for _, source in ran), gone


def fetch_sources(ran, session, cache, progress, workers=1):
    """
    Runs the sources' fetch methods and returns every document, in the
    order the sources were listed.

    With one worker, or one source, each source runs to the end before
    the next starts, and the log is exactly one source's lines after
    another's. With more, up to `workers` sources run at once in threads,
    and every progress line is prefixed with its source's label so the
    interleaved log still reads.

    A failure in one source stops the build as it always has: the other
    sources are told to stop at their next progress line, and the failed
    source's own error is raised once they have. Ctrl+C is handled the
    same way, so the wait for the running sources ends within a page
    rather than at the end of a crawl.

    Args:
        ran (Sequence[tuple]): (entry, source) pairs, in file order, with
            each source already constructed and configured.
        session: the HTTP session every source requests through.
        cache (dict): fetch cache metadata, read and updated in place.
        progress (Callable[[str], None]): receives one line per event.
        workers (int): how many sources may run at once; 1 or more.

    Returns:
        list: every document produced, labelled with its source's label,
        in source order.
    """
    if workers <= 1 or len(ran) <= 1:
        documents = []
        for entry, source in ran:
            documents.extend(_fetch_documents(entry, source, session, cache, progress))
        return documents

    stop = threading.Event()
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_fetch_documents, entry, source, session, cache,
                        _labelled_progress(progress, entry.label, stop))
            for entry, source in ran
        ]
        try:
            done, _ = wait(futures, return_when=FIRST_EXCEPTION)
            failed = next((f for f in futures if f in done and f.exception() is not None), None)
            if failed is not None:
                stop.set()
                pool.shutdown(wait=True, cancel_futures=True)
                failed.result()
            results = [future.result() for future in futures]
        except BaseException:
            # Ctrl+C lands here, in the thread that waits; the sources
            # learn of it at their next progress line.
            stop.set()
            pool.shutdown(wait=True, cancel_futures=True)
            raise
    return [document for documents in results for document in documents]


def _fetch_documents(entry, source, session, cache, progress):
    """One source's documents, each carrying the label its configuration entry gives it."""
    progress(f"Source: {entry.type}")
    # The configuration owns the display name, not the source: only the
    # person who wrote the file knows which web source is the main site
    # and which is a program microsite. Applying it here means no
    # source, built-in or plugin, has to carry the setting itself.
    return [
        dataclasses.replace(document, source_label=entry.label)
        for document in source.fetch(session, cache, progress)
    ]


def _labelled_progress(progress, label, stop):
    """
    A progress callback for one source running beside others: it prefixes
    every line with the source's label, and it ends the source once the
    build has been told to stop.

    Every source reports at least once per page, so raising here unwinds a
    source within a page of the stop being asked for. That is what lets a
    Ctrl+C, or another source's failure, end the build promptly instead of
    after the longest crawl.
    """
    def report(line):
        if stop.is_set():
            raise KeyboardInterrupt
        progress(f"{label} | {line}")
    return report


def carry_forward_pages(config, documents, gone, progress):
    """
    The pages an incremental rebuild keeps without having read them.

    Args:
        config (extractium.config.Config): the validated configuration.
        documents (list): every document the sources produced.
        gone (set[str]): the keys of the pages confirmed gone.
        progress (Callable[[str], None]): receives one line per event.

    Returns:
        tuple[dict | None, list]: the manifest the last build wrote, and
        what extractium.core.retain.carry_forward chose from it. Both are
        empty on a full rebuild, which reads no manifest at all.
    """
    if config.rebuild != retain.REBUILD_INCREMENTAL:
        return None, []
    previous = retain.load_previous()
    if previous is None:
        progress("No earlier build to carry pages forward from.")
        return None, []
    # Only a crawl can miss a page that is still there; every other
    # source lists its content through an interface, so a page absent
    # from its listing is gone.
    labels = {entry.label for entry in config.sources if entry.type == "web"}
    kept = retain.carry_forward(previous, (page_key_of(d) for d in documents), gone, labels)
    for key, parents, _, last_seen in kept:
        progress(f"  kept from an earlier build (last seen {last_seen[:10]}): {parents[0]['u']}")
    return previous, kept


def found_links(sources):
    """
    The addresses the site handlers held back during the crawls, in the
    order found and without repeats.

    Args:
        sources (Iterable): the source instances that have already run.

    Returns:
        tuple[str, ...]: every link a handler collected through its
        optional `found_links` method.
    """
    links = {}
    for source in sources:
        for handler in getattr(source, "handlers", ()):
            if hasattr(handler, "found_links"):
                for link in handler.found_links():
                    links.setdefault(link, None)
    return tuple(links)


def collect_notes(sources):
    """
    The lines the sources want reported at the end of a build.

    Args:
        sources (Iterable): the source instances that have already run.

    Returns:
        list[str]: coverage lines from each source that offers them, then
        one line per source naming the accounts its handlers held back.
    """
    sources = list(sources)
    notes = []
    for source in sources:
        if hasattr(source, "summary_lines"):
            notes.extend(source.summary_lines())
    for source in sources:
        for handler in getattr(source, "handlers", ()):
            # A handler may hold content back for its own reason, and each
            # says so once for the whole build rather than once per link.
            for method in ("skipped_account_report", "skipped_page_report"):
                report = getattr(handler, method)() if hasattr(handler, method) else ""
                if report and report not in notes:
                    notes.append(report)
    return notes


### Protected Health Information ###

def run_phi_lint(config, documents, progress):
    """
    Scans what the sources produced for likely identifiers and writes the
    two review reports.

    The reports go to the working directory, never to the output folder,
    because everything in that folder is written in order to be published.
    The scan runs before the build so that its result survives a later
    failure: a person who pointed the tool at the wrong folder should learn
    that whether or not the embedding step then works.

    Args:
        config (extractium.config.Config): the validated configuration.
        documents (list): every document the sources produced.
        progress (Callable[[str], None]): receives the one summary line.

    Returns:
        extractium.core.phi_lint.Report: what was scanned and what fired.

    Raises:
        OSError: if a report file cannot be written.
    """
    report = phi_lint.scan(documents, mode=config.phi_lint)
    paths = () if config.phi_lint == phi_lint.MODE_OFF else phi_lint.write_reports(report)
    progress(phi_lint.summary_line(report, paths))
    return report


### Outputs ###

# The most files one output may name individually in the build summary.
# Past this it is named as a folder with a count, because an output that
# writes one document per page writes hundreds of them.
PATHS_NAMED = 8


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
        options = dict(entry.options, include_local=entry.include_local,
                       sources=source_descriptors(config))
        written.append((entry, adapter.write(compendium, config.out_dir, options)))
        # An output that keeps a folder in step with the compendium says
        # what it removed, so a deletion is never silent.
        for path in getattr(adapter, "pruned", ()):
            progress(f"  removed, no longer in the compendium: {path}")
    return written


def wrote_lines(paths, limit=PATHS_NAMED):
    """
    What one output wrote, as summary lines.

    An output that wrote a handful of files names each one. An output that
    wrote a folder of them -- one document per page, which is hundreds --
    names the folder, how many files are in it, and their total size, so
    the summary stays readable.

    Args:
        paths (Sequence[pathlib.Path]): the files that output wrote.
        limit (int): the most files to name one by one.

    Returns:
        list[str]: one line per named file, or a single folder line, or
        both when a few files sit beside one folder holding the rest.

    Raises:
        OSError: if a written file can no longer be read.
    """
    def named(path):
        return f"{path} ({path.stat().st_size / 1024 / 1024:.2f} MB)"

    def counted(group):
        total_mb = sum(path.stat().st_size for path in group) / 1024 / 1024
        folder = os.path.commonpath([str(path) for path in group])
        return f"{folder} ({len(group)} files, {total_mb:.2f} MB)"

    if len(paths) <= limit:
        return [named(path) for path in paths]
    # An index file with a folder of files beside it reads better as the
    # file and then the folder than as one count for the folder above both.
    top = os.path.commonpath([str(path) for path in paths])
    beside = [path for path in paths if str(path.parent) == top]
    below = [path for path in paths if str(path.parent) != top]
    if beside and below and len(beside) <= limit and os.path.commonpath([str(p) for p in below]) != top:
        return [named(path) for path in beside] + [counted(below)]
    return [counted(paths)]


def print_summary(compendium, written, notes=()):
    """
    Prints what the build produced, on standard output.

    Names every file and its size, reports how completely each source was
    read, and calls out any output that contains content read from a local
    folder, so nobody publishes such a file without having been told.
    """
    write_line(f"Built {compendium.name!r} at {compendium.built_at}", sys.stdout)
    write_line(f"  sections : {len(compendium.parents)}", sys.stdout)
    write_line(f"  windows  : {len(compendium.children)}", sys.stdout)
    write_line(f"  sources  : {compendium.source_count}", sys.stdout)
    for entry, paths in written:
        for line in wrote_lines(paths):
            write_line(f"  wrote    : {line}", sys.stdout)
        if entry.include_local and compendium.local_parents():
            write_line(
                f"  NOTICE   : output {entry.type!r} includes local content; check before publishing.",
                sys.stdout,
            )
    for note in notes:
        write_line(f"  coverage : {note}", sys.stdout)


### Keywords ###

def keyword_pass_for(config, progress):
    """
    The keyword step this build runs, or None.

    None when the settings switch keywords off, and also when the
    extractor library is not installed: the build then says what is
    missing and how to add it, and goes on, because a compendium
    without keywords is still a compendium.

    Args:
        config (extractium.config.Config): the validated settings.
        progress (Callable[[str], None]): receives the line about a
            missing library.

    Returns:
        extractium.core.keywords.KeywordPass | None
    """
    if not config.keywords:
        return None
    if not keywording.keyword_library_available():
        progress(
            "Keywords: the keywords extra is not installed, so no section is named with "
            "keywords and no page with tags. Install it with: pip install \"extractium[keywords]\""
        )
        return None
    return keywording.KeywordPass(load=caching.load_keywords, save=caching.save_keywords)


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
    session = make_session(config.transport, progress=progress_to_stderr,
                           delay_seconds=config.delay_seconds)

    try:
        documents, notes, gone = run_sources(config, registry, session, cache, progress_to_stderr)
        # Which hosts needed the browser handshake, on record at the end
        # as well as in the log.
        if hasattr(session, "summary_lines"):
            notes.extend(session.summary_lines())
    except RegistryError as e:
        return fail(str(e), EXIT_CONFIG)
    except GitHubSourceError as e:
        # The operator asked for something that is not there. Falling back
        # would turn a misspelled account name into a strange, empty
        # result, so the build stops and says what was wrong.
        return fail(str(e), EXIT_CONFIG)
    finally:
        # Saved whatever happened, so a run interrupted halfway still
        # leaves the pages it did fetch usable by the next run.
        caching.save_cache_meta(cache)
        session.close()

    try:
        run_phi_lint(config, documents, progress_to_stderr)
    except OSError as e:
        return fail(f"the review report could not be written: {e}", EXIT_OUTPUT)

    previous, kept = carry_forward_pages(config, documents, gone, progress_to_stderr)
    notes.extend(retain.summary_lines(kept, len(gone)))

    compendium = build_compendium(
        documents,
        name=config.name,
        float32_vecs=args.float32_vecs,
        progress=progress_to_stderr,
        retained=kept,
        keywords=keyword_pass_for(config, progress_to_stderr),
    )
    if compendium is None:
        return fail(
            "the sources produced no indexable content, so no output was written. "
            "Check the seed URL and the include and exclude patterns.",
            EXIT_NO_CONTENT,
        )
    try:
        retain.save_manifest(compendium, previous, [key for key, _, _, _ in kept])
    except OSError as e:
        progress_to_stderr(f"  the build manifest could not be written ({e}); the next build cannot carry pages forward")

    try:
        written = run_outputs(config, registry, compendium, progress_to_stderr)
    except RegistryError as e:
        return fail(str(e), EXIT_CONFIG)
    except OSError as e:
        return fail(f"an output could not be written: {e}", EXIT_OUTPUT)

    print_summary(compendium, written, notes)
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

    init = subcommands.add_parser("init", help="Write a first settings file, asking for what a flag does not give.")
    init.add_argument("--name", metavar="TEXT",
                      help="Display name of the compendium.")
    init.add_argument("--slug", metavar="TEXT",
                      help="Short name the output files are named after. Derived from the name when omitted.")
    init.add_argument("--seed-url", metavar="URL",
                      help="The website to start crawling from.")
    init.add_argument("--output", default=init_command.DEFAULT_OUTPUT, metavar="FILE",
                      help="Where to write the settings file. Defaults to config.yaml in the current folder.")
    init.add_argument("--force", action="store_true",
                      help="Replace the file if it already exists.")
    init.set_defaults(handler=init_command.run_init)
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
