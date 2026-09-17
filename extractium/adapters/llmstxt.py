"""
Summary: The llms.txt adapter. Writes the plain-Markdown index a
web-browsing language model looks for, as a tree short enough to read
whole: llms.txt lists the sources, llms/<source>.txt lists one source's
pages with a description of each, and a source too long for one file
gets a folder of them. No file lists code records or carries vectors;
they are for a model that reads pages rather than searching an index.
See https://llmstxt.org/ and docs/extractium-spec.md section 4.

This file is part of Extractium™
extractium/adapters/llmstxt.py

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

import re
from urllib.parse import unquote, urlsplit

from extractium.adapters.base import (
    count_of,
    describe,
    excerpt,
    link,
    output_compendium,
    page_records,
    prepare_out_dir,
    prose_parents,
    DESCRIPTION_CHARS,
)

### Constants ###

INDEX_FILE = "llms.txt"

# The folder the per-source index files are written under, beside INDEX_FILE.
INDEX_DIR = "llms"

# No longer written. The name is kept because a folder built by an earlier
# version may still hold the file, and write() removes a copy this tool wrote.
FULL_FILE = "llms-full.txt"

# The most entries one index file lists. A browsing model keeps the first
# part of a fetched page and drops the rest, so a file is held to a length
# it can read whole. A source past this is split into one file per group.
MAX_ENTRIES_PER_FILE = 500

# Named in every file so a reader knows what produced it and under what
# terms. The indexed text keeps whatever license its own site carries.
# write() also reads it as the mark of a file this tool wrote, which is
# what makes removing a stale file safe.
LICENSE_LINE = (
    "Compiled by Extractium (https://github.com/DepressionCenter/extractium), "
    "copyright (c) 2026 The Regents of the University of Michigan, licensed under "
    "the GNU General Public License v3.0 or later. The indexed content remains "
    "under the license of the site it was read from."
)

# Sites named in the summary before the rest are counted rather than
# listed, so the opening line stays one readable sentence.
HOSTS_SHOWN = 3

# The source type the GitHub source gives its records. Those pages are
# listed by repository, because a repository is what a reader looks for.
GITHUB_SOURCE_TYPE = "github"

# Top-level folders that hold a repository's documentation, compared in
# lower case. Their files are listed after the root files and before the rest.
DOC_FOLDERS = frozenset({"docs", "doc", "guide", "guides"})

# The group a page lands in when it has neither a category nor a folder in
# its address to group by.
TOP_LEVEL_GROUP = "top-level pages"

# What each file says about itself, for a reader arriving with no context.
# The llms.txt convention puts the free-form explanation between the
# summary and the link sections, and allows no headings there, so these
# are plain paragraphs (https://llmstxt.org/).
RELATIVE_NOTE = "Links to other index files are relative to this file's address."

CODE_NOTE = (
    "Source code is not listed here. These files are meant to be read inside a "
    "language model's context window, so they hold documentation only."
)

ROOT_ORIENTATION = (
    "This file is an index of the sources this compendium was built from, not the "
    "content itself. Each entry below names one source, links to where it starts, "
    "says what it holds, and links to that source's own index file, which lists "
    "its pages with a description of each. Pick the source that matches your "
    "question, fetch its index file, then fetch the page you need.",
)

SOURCE_ORIENTATION = (
    "This file lists the pages of one source. Each entry names one page, links to "
    "it, and describes it: with the page's own description where it has one, "
    "otherwise with the keywords it is about or the opening of its text."
)

SPLIT_ORIENTATION = (
    "This source has more pages than one file holds, so its pages are listed in "
    "the files linked below, one per section of the source."
)

GITHUB_ORIENTATION = (
    "Each repository is listed with the description it gives itself, then its "
    "documentation files: the files at the repository's root first, then its docs "
    "and guide folders, then the rest."
)


### Names For Files ###

def slug_of(text, fallback):
    """
    A file-name-safe form of a label: lower-case letters, digits, and hyphens.

    A label comes from a settings file and a category from a crawled page,
    so neither is trusted as a path. Everything outside the allowlist
    becomes a hyphen, which is what keeps a name from reaching outside the
    output folder.

    Args:
        text (str): the label or category.
        fallback (str): the name used when nothing usable remains.

    Returns:
        str: at most 64 characters of [a-z0-9-], never empty.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:64].strip("-")
    return slug or fallback


def _unique(slug, used):
    """The slug, or the slug with the first free number after it; recorded in `used`."""
    candidate, number = slug, 1
    while candidate in used:
        number += 1
        candidate = f"{slug}-{number}"
    used.add(candidate)
    return candidate


def _free_name(slug, folder_used, used, source_slug):
    """
    A file name under one source's folder that no group and no
    continuation file of an earlier group has taken; recorded in both sets.
    """
    candidate, number = slug, 1
    while candidate in folder_used or f"{INDEX_DIR}/{source_slug}/{candidate}.txt" in used:
        number += 1
        candidate = f"{slug}-{number}"
    folder_used.add(candidate)
    used.add(f"{INDEX_DIR}/{source_slug}/{candidate}.txt")
    return candidate


def source_slugs(labels):
    """
    The file name each source's index goes by.

    Args:
        labels (Sequence[str]): distinct source labels, in listing order.

    Returns:
        dict[str, str]: label to slug. Two labels that reduce to one slug
        get "-2", "-3" in listing order, and a label with no usable
        character is named by its position.
    """
    used = set()
    return {
        label: _unique(slug_of(label, f"source-{position}"), used)
        for position, label in enumerate(labels, start=1)
    }


### Grouping ###

def shared_depth(pages):
    """
    How many leading categories every categorized page of a source shares.

    A portal files every article under "Knowledge Base", which tells a
    reader nothing, so grouping starts at the first category that differs.

    Returns:
        int: the length of the common prefix, 0 when no page has categories.
    """
    categorized = [page["categories"] for page in pages if page["categories"]]
    if not categorized:
        return 0
    depth = 0
    for level in zip(*categorized):
        if len(set(level)) > 1:
            break
        depth += 1
    # A prefix as long as the shortest list would leave that page nothing
    # to group by, so the last shared category stays available.
    return min(depth, min(len(categories) for categories in categorized) - 1)


def group_key(page, depth):
    """
    The group one page is listed under when its source is split.

    The first category below the ones every page shares; for a page with
    none, the first folder of its address; else TOP_LEVEL_GROUP.

    Args:
        page (dict): one record from page_records.
        depth (int): what shared_depth returned for the page's source.

    Returns:
        str: the group's display name.
    """
    if len(page["categories"]) > depth:
        return page["categories"][depth]
    segments = [unquote(part) for part in urlsplit(page["url"]).path.split("/") if part]
    if len(segments) >= 2:
        return segments[0]
    return TOP_LEVEL_GROUP


def repository_of(page):
    """The (owner, repository) a GitHub page belongs to, or None when it names neither."""
    if page["source_type"] != GITHUB_SOURCE_TYPE or len(page["categories"]) < 2:
        return None
    return page["categories"][0], page["categories"][1]


def github_band(page):
    """
    Where a repository's file sorts: 0 at the repository root, 1 in a
    documentation folder, 2 anywhere else. A reader that stops partway
    through a list has then seen the files most likely to matter.
    """
    folders = page["categories"][2:]
    if not folders:
        return 0
    return 1 if folders[0].lower() in DOC_FOLDERS else 2


def _file_order(page):
    """Sort key within a repository: band, the root README ahead of its neighbors, then address."""
    band = github_band(page)
    is_root_readme = band == 0 and page["content_type"] == "readme"
    return band, not is_root_readme, page["url"].lower()


def repository_sections(pages):
    """
    A source's GitHub pages, gathered by repository.

    Grain: one record per repository, in first-appearance order.

    Args:
        pages (Iterable[dict]): page records that repository_of accepts.

    Returns:
        list[dict]: `owner`, `repository`, `description` (what the
        repository says about itself, or a note that it says nothing),
        and `files`, its pages in listing order.
    """
    gathered = {}
    for page in pages:
        gathered.setdefault(repository_of(page), []).append(page)
    sections = []
    for (owner, repository), files in gathered.items():
        files = sorted(files, key=_file_order)
        # The GitHub source gives every page the repository's own
        # description as its summary, so any page can supply it; the root
        # README is asked first because it sorts first.
        given = next((page["given_summary"] for page in files if page["given_summary"]), "")
        sections.append({
            "owner": owner,
            "repository": repository,
            "description": excerpt(given, DESCRIPTION_CHARS) if given else "No description.",
            "files": files,
        })
    return sections


### Entries ###

def _sentence(text):
    """The text ending in a full stop, so a sentence can follow it on the same line."""
    text = text.strip()
    return text if text.endswith((".", "!", "?", "...")) else f"{text}."


def page_entry(page, title=None):
    """One list item for one page: its link and its description."""
    return f"- {link(title or page['title'], page['url'])}: {describe(page)}"


def file_entry(page, owner, repository):
    """
    One list item for a repository's file. The source titles a file
    "owner/repository: path"; under the repository's own heading the
    prefix repeats on every line, so only the path is kept.
    """
    prefix = f"{owner}/{repository}: "
    title = page["title"]
    return page_entry(page, title[len(prefix):] if title.startswith(prefix) else title)


def repository_entry(section, index_path=None):
    """
    The list item that introduces a repository: its link, what it says
    about itself, and, when its files are listed elsewhere, where.
    """
    name = f"{section['owner']}/{section['repository']}"
    entry = f"- {link(name, f'https://github.com/{name}')}: {_sentence(section['description'])}"
    if index_path:
        entry += f" Index of its files: {link(index_path, index_path)}."
    return entry


def split_entries(entries, cap):
    """The entries in runs of at most `cap`, in order; one empty run when there are none."""
    return [entries[start:start + cap] for start in range(0, len(entries), cap)] or [[]]


### File Bodies ###

def source_hosts(parents):
    """
    The sites the content came from, in the order they first appear.

    Args:
        parents (Iterable[extractium.core.models.Parent]): the parents this
            output may write.

    Returns:
        tuple[str, ...]: distinct host names. Local files have no host and
        contribute none.
    """
    hosts = {}
    for parent in parents:
        if parent.host:
            hosts.setdefault(parent.host, None)
    return tuple(hosts)


def name_sites(hosts, limit=HOSTS_SHOWN):
    """
    The hosts as a readable phrase, counting the ones past the limit rather
    than listing them: "a.edu, b.org and 4 other sites".

    Returns:
        str: the phrase, or an empty string when there are no hosts, which
        is the case for an output of purely local content.
    """
    if not hosts:
        return ""
    shown, extra = list(hosts[:limit]), len(hosts) - limit
    if extra > 0:
        shown.append(f"{extra} other site{'s' if extra > 1 else ''}")
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def summary(compendium, page_count, parents=None):
    """
    The blockquote line: what this compendium is, where it came from,
    and when it was built. The llms.txt convention puts the information a
    reader needs in order to understand the rest of the file here, and the
    heading above it already carries the name.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        page_count (int): pages the files list.
        parents (Sequence | None): the sections the files describe; the
            compendium's own when not given.
    """
    parents = compendium.parents if parents is None else parents
    sites = name_sites(source_hosts(parents))
    pages = count_of(page_count, "page") if sites else count_of(page_count, "file")
    drawn_from = f" drawn from {pages} on {sites}" if sites else f" drawn from {pages}"
    return (
        f"> A compendium of {count_of(len(parents), 'section')}"
        f"{drawn_from}, compiled on {compendium.built_at}."
    )


def _render_file(heading, blockquote, orientation, sections, continued=None):
    """
    One index file's complete text.

    Args:
        heading (str): the H1.
        blockquote (str): the summary line, already starting with "> ".
        orientation (Sequence[str]): plain paragraphs saying what the file is.
        sections (Sequence[tuple[str, Sequence[str]]]): each H2 and its list items.
        continued (str | None): the file name this one continues in.

    Returns:
        str: the text, ending in one newline.
    """
    lines = [f"# {heading}", "", blockquote, ""]
    for paragraph in orientation:
        lines.extend([paragraph, ""])
    lines.extend([LICENSE_LINE, ""])
    for position, (title, entries) in enumerate(sections):
        lines.extend([f"## {title}", ""])
        lines.extend(entries)
        if continued and position == len(sections) - 1:
            lines.append(f"- {link(f'Continued in {continued}', continued)}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _paginate(sections, cap):
    """
    Sections dealt into files of at most `cap` entries each, in order. A
    section too long for what is left of a file continues in the next
    under the same heading.

    Returns:
        list[list[tuple[str, list[str]]]]: one list of sections per file;
        always at least one file.
    """
    files, current, room = [], [], cap
    for title, entries in sections:
        entries = list(entries)
        while True:
            taken, entries = entries[:room], entries[room:]
            if taken or not entries:
                current.append((title, taken))
                room -= len(taken)
            if not entries:
                break
            files.append(current)
            current, room = [], cap
    files.append(current)
    return [file for file in files if file] or [[]]


def _numbered(path, number):
    """`a/b.txt` for the first file of a run, `a/b-2.txt` for the second, and so on."""
    if number == 1:
        return path
    stem, _, extension = path.rpartition(".")
    return f"{stem}-{number}.{extension}"


def _write_run(tree, path, used, heading, blockquote, orientation, sections):
    """
    Renders one logical index into `tree`, as one file or as a numbered
    run of them when it holds more entries than a file may.

    Args:
        tree (dict[str, str]): the files rendered so far; added to.
        path (str): the first file's path, relative to the output folder.
            The caller has already recorded it in `used`.
        used (set[str]): every path taken so far, so a continuation file
            never lands on a group that happens to carry its name.
    """
    files = _paginate(sections, MAX_ENTRIES_PER_FILE)
    paths, number = [path], 1
    for _ in files[1:]:
        number += 1
        while _numbered(path, number) in used:
            number += 1
        used.add(_numbered(path, number))
        paths.append(_numbered(path, number))
    for position, file_sections in enumerate(files):
        following = paths[position + 1].rsplit("/", 1)[-1] if position + 1 < len(paths) else None
        tree[paths[position]] = _render_file(heading, blockquote, orientation, file_sections, following)


def _source_description(source, pages):
    """
    What the root file says a source is: the description its settings
    give, else the description of the page it starts at, else a count.
    """
    if source.get("description"):
        return source["description"]
    home = (source.get("home_url") or "").rstrip("/").lower()
    if home:
        for page in pages:
            if page["url"].rstrip("/").lower() == home and page["given_summary"]:
                return excerpt(page["given_summary"], DESCRIPTION_CHARS)
    hosts = {}
    for page in pages:
        host = urlsplit(page["url"]).netloc
        if host:
            hosts.setdefault(host, None)
    noun = "page" if hosts else "file"
    counted = f"{len(pages):,} {noun}{'' if len(pages) == 1 else 's'}"
    return f"{counted} from {name_sites(tuple(hosts))}" if hosts else counted


def render_root(compendium, parents, sources, pages_by_label, slugs):
    """
    The llms.txt body: a heading, a summary, and one entry per source.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        parents (Sequence): the prose sections the tree describes.
        sources (Sequence[dict]): one descriptor per source that has a
            page, in listing order.
        pages_by_label (dict[str, list[dict]]): each source's page records.
        slugs (dict[str, str]): each source's file name.

    Returns:
        str: the file's complete text.
    """
    entries = []
    for source in sources:
        label = source["label"]
        index_path = f"{INDEX_DIR}/{slugs[label]}.txt"
        description = _sentence(_source_description(source, pages_by_label[label]))
        if source.get("home_url"):
            entries.append(
                f"- {link(label, source['home_url'])}: {description} "
                f"Index of its pages: {link(index_path, index_path)}."
            )
        else:
            entries.append(f"- {link(label, index_path)}: {description}")
    page_count = sum(len(pages) for pages in pages_by_label.values())
    return _render_file(
        compendium.name,
        summary(compendium, page_count, parents),
        ROOT_ORIENTATION + (RELATIVE_NOTE, CODE_NOTE),
        [("Sources", entries)],
    )


def render_source(compendium, label, pages, slug, used=None):
    """
    One source's index files.

    A source that fits in one file lists its pages there, and its
    repositories each under a heading of their own. A source that does
    not fit lists its groups and repositories, and each of those gets a
    file under a folder named after the source.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        label (str): the source's label.
        pages (Sequence[dict]): its page records.
        slug (str): its file name, without extension.
        used (set[str] | None): paths taken so far across the tree.

    Returns:
        dict[str, str]: path relative to the output folder, to file text.
        The source's own file first.
    """
    used = set() if used is None else used
    path = f"{INDEX_DIR}/{slug}.txt"
    used.add(path)
    heading = f"{compendium.name}: {label}"
    blockquote = (
        f"> {count_of(len(pages), 'page')} from {label}, one source of the "
        f"{compendium.name} compendium, compiled on {compendium.built_at}."
    )
    up = f"The index of every source is {link(INDEX_FILE, '../' + INDEX_FILE)}."

    plain = [page for page in pages if repository_of(page) is None]
    repositories = repository_sections([page for page in pages if repository_of(page)])
    orientation = [SOURCE_ORIENTATION]
    if repositories:
        orientation.append(GITHUB_ORIENTATION)

    if len(pages) + len(repositories) <= MAX_ENTRIES_PER_FILE:
        sections = [(label, [page_entry(page) for page in plain])] if plain else []
        for section in repositories:
            entries = [repository_entry(section)]
            entries += [file_entry(page, section["owner"], section["repository"]) for page in section["files"]]
            sections.append((f"{section['owner']}/{section['repository']}", entries))
        return {path: _render_file(heading, blockquote, orientation + [up, RELATIVE_NOTE, CODE_NOTE], sections)}

    # Too long for one file: the source's file becomes a list of its
    # groups and repositories, and each of those gets a file of its own.
    below = {}
    folder_used = set()
    deeper_up = (
        f"The index of this source is {link(f'{slug}.txt', f'../{slug}.txt')}, and the index of "
        f"every source is {link(INDEX_FILE, '../../' + INDEX_FILE)}."
    )
    sections = []

    depth = shared_depth(plain)
    groups = {}
    for page in plain:
        groups.setdefault(group_key(page, depth), []).append(page)

    # Every group and repository takes its file name before anything is
    # rendered, so a long group's continuation file ("news-2.txt") never
    # lands on the name a later group ("news 2") was going to get.
    group_files = {name: _free_name(slug_of(name, "group"), folder_used, used, slug) for name in groups}
    repository_files = [
        _free_name(slug_of(section["repository"], "repository"), folder_used, used, slug)
        for section in repositories
    ]

    group_entries = []
    for name, members in groups.items():
        file_name = f"{group_files[name]}.txt"
        group_entries.append(f"- {link(name, f'{slug}/{file_name}')}: {count_of(len(members), 'page')}.")
        _write_run(
            below, f"{INDEX_DIR}/{slug}/{file_name}", used, f"{heading}: {name}",
            f"> {count_of(len(members), 'page')} under {name} in {label}, one source of the "
            f"{compendium.name} compendium, compiled on {compendium.built_at}.",
            [SOURCE_ORIENTATION, deeper_up, RELATIVE_NOTE, CODE_NOTE],
            [(name, [page_entry(page) for page in members])],
        )
    if group_entries:
        sections.append((label, group_entries))

    repository_entries = []
    for section, file_slug in zip(repositories, repository_files):
        name = f"{section['owner']}/{section['repository']}"
        file_name = f"{file_slug}.txt"
        repository_entries.append(repository_entry(section, f"{slug}/{file_name}"))
        files = [file_entry(page, section["owner"], section["repository"]) for page in section["files"]]
        _write_run(
            below, f"{INDEX_DIR}/{slug}/{file_name}", used, f"{heading}: {name}",
            f"> {count_of(len(section['files']), 'file')} from the {name} repository in {label}, one "
            f"source of the {compendium.name} compendium, compiled on {compendium.built_at}.",
            [SOURCE_ORIENTATION, GITHUB_ORIENTATION, deeper_up, RELATIVE_NOTE, CODE_NOTE],
            [(name, [repository_entry(section)] + files)],
        )
    if repository_entries:
        sections.append((f"{label}: repositories" if group_entries else label, repository_entries))

    tree = {}
    _write_run(tree, path, used, heading, blockquote,
               [SPLIT_ORIENTATION] + orientation[1:] + [up, RELATIVE_NOTE, CODE_NOTE], sections)
    tree.update(below)
    return tree


def render_tree(compendium, sources=()):
    """
    Every index file, as text.

    llms.txt lists the sources. Each source has a file under INDEX_DIR
    listing its pages, and a source too long for one file has a folder of
    them. Code records are listed nowhere: these files are read inside a
    language model's context window, and a repository's code analysis
    would crowd out its documentation.

    Args:
        compendium (extractium.core.models.Compendium): the build result,
            already filtered to what this output may write. Only `name`,
            `built_at`, and `parents` are read.
        sources (Sequence[dict]): what the settings file says about each
            source: `label`, `home_url`, and `description`. A label found
            on a page and not described here is listed after the rest,
            with no home address.

    Returns:
        dict[str, str]: path relative to the output folder, to that file's
        complete text. INDEX_FILE first, then each source's file followed
        by its group files.
    """
    parents = prose_parents(compendium.parents)
    pages_by_label = {}
    for page in page_records(parents):
        pages_by_label.setdefault(page["source_label"], []).append(page)

    described = {}
    for source in sources:
        described.setdefault(source["label"], source)
    listed = [source for label, source in described.items() if label in pages_by_label]
    listed += [{"label": label, "home_url": "", "description": ""}
               for label in pages_by_label if label not in described]

    slugs = source_slugs([source["label"] for source in listed])
    tree = {INDEX_FILE: render_root(compendium, parents, listed, pages_by_label, slugs)}
    # Every source's own file is taken before any is rendered, so one
    # source's continuation file never lands on another source's name.
    used = {INDEX_FILE} | {f"{INDEX_DIR}/{slug}.txt" for slug in slugs.values()}
    for source in listed:
        label = source["label"]
        tree.update(render_source(compendium, label, pages_by_label[label], slugs[label], used))
    return tree


### Adapter ###

class LlmsTxtAdapter:
    """
    Writes llms.txt and the llms/ folder of per-source index files.

    Every file is plain Markdown with real headings and real lists, so it
    reads correctly in a browser, in a screen reader, and to a language
    model. This adapter never fetches a URL and never runs the embedding
    model.

    Attributes:
        pruned (tuple[pathlib.Path, ...]): the files the last write()
            removed, which the command line names so that a deletion is
            never silent.
    """

    name = "llmstxt"

    def __init__(self):
        self.pruned = ()

    def write(self, compendium, out_dir, options):
        """
        Writes the index tree and removes what it replaces.

        A file is removed only when this tool wrote it, which is read from
        LICENSE_LINE in its text: llms-full.txt from a build made before
        that file was dropped, and an index file under llms/ that this
        write did not produce, such as one for a source that has left the
        settings file. A file without that line is somebody else's and is
        never touched. A folder under llms/ that the removal leaves empty
        is removed with it.

        Args:
            compendium (extractium.core.models.Compendium): the build result.
            out_dir (str | pathlib.Path): folder to write under; created
                when it does not exist.
            options (Mapping): the output's options. `include_local` is
                read by the local-content guardrail, and `sources`, the
                descriptors the command line supplies, names and
                describes the sources. A caller that supplies none gets
                each source listed by its label alone.

        Returns:
            tuple[pathlib.Path, ...]: llms.txt, then every file under llms/.

        Raises:
            OSError: if a file cannot be written or a stale one removed.
        """
        compendium = output_compendium(compendium, options)
        folder = prepare_out_dir(out_dir)
        written = []
        for relative, text in render_tree(compendium, options.get("sources") or ()).items():
            path = folder.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            written.append(path)
        self.pruned = _prune(folder, written)
        return tuple(written)


def _wrote_it(path):
    """Whether this tool wrote the file, judged by the license line every file of its carries."""
    try:
        return LICENSE_LINE in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def _prune(folder, written):
    """
    Removes the files an earlier write left that this one did not produce.

    Args:
        folder (pathlib.Path): the output folder.
        written (Sequence[pathlib.Path]): the files this write produced.

    Returns:
        tuple[pathlib.Path, ...]: the files removed, in path order.
    """
    keep = {path.resolve() for path in written}
    index_dir = folder / INDEX_DIR
    candidates = [folder / FULL_FILE]
    if index_dir.is_dir():
        candidates += sorted(index_dir.rglob("*.txt"))
    removed = []
    for path in candidates:
        if path.is_file() and not path.is_symlink() and path.resolve() not in keep and _wrote_it(path):
            path.unlink()
            removed.append(path)
    if index_dir.is_dir():
        # Deepest first, so a folder emptied by removing its subfolder goes too.
        for directory in sorted((p for p in index_dir.rglob("*") if p.is_dir()), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
    return tuple(removed)
