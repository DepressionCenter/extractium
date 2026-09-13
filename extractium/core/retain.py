"""
Summary: Carrying pages forward between builds. After every build the
sections of every published page are recorded in a manifest beside the
cache, with the date each page was last seen. An incremental build reads
that manifest back and keeps the pages this build did not see, unless
the server confirmed them gone or their source is no longer configured,
so a site that was down for an hour does not empty a quarter of the
index while a page taken down on purpose still leaves it.

This file is part of Extractium™
extractium/core/retain.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-12
Last Modified: 2026-09-12
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
__date__ = "2026-09-12"

import json
import os
from urllib.parse import urlparse

from extractium.core import cache
from extractium.core.chunk import _children_for, assign_parent_ids
from extractium.core.fetch import normalise

### Constants ###

# The manifest lives beside the cache, so a scheduled build restores it
# with the rest of the cache. It holds the text of every published
# section, and never a section read from a local folder: the cache folder
# is committed by a data repository that indexes video, and local content
# must not travel in it.
MANIFEST_FILE = "previous-build.json"
MANIFEST_VERSION = 1

# The two rebuild modes. A full rebuild publishes exactly what this build
# read. An incremental one also keeps the pages it did not see, apart
# from those the server confirmed gone.
REBUILD_FULL = "full"
REBUILD_INCREMENTAL = "incremental"
REBUILD_MODES = (REBUILD_FULL, REBUILD_INCREMENTAL)

# The fields a section carries besides its heading and text, recorded so
# a carried-forward section is the record it was.
SECTION_FIELDS = ("source_type", "content_type", "source_label", "categories", "weight")


### Manifest ###

def manifest_path():
    """The manifest's path under the cache folder in use."""
    return os.path.join(cache.CACHE_DIR, MANIFEST_FILE)


def page_key(url):
    """The key one page is filed under: its normalised address."""
    return normalise(url)


def load_previous():
    """
    The manifest the last build wrote, or None when there is none or it
    cannot be read. A manifest that cannot be read is treated as absent,
    because a build must not fail on a file it only uses to keep more.

    Returns:
        dict | None: the manifest, with `built_at` and `pages`.
    """
    try:
        with open(manifest_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
        return None
    pages = data.get("pages")
    if not isinstance(pages, dict):
        return None
    return data


def pages_of(compendium, previous=None, retained_keys=()):
    """
    The manifest's page records for one compendium.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        previous (dict | None): the manifest read before this build, so a
            carried-forward page keeps the date it was really last seen.
        retained_keys (Iterable[str]): the keys of the pages carried
            forward rather than read this build.

    Returns:
        dict[str, dict]: page key to record. Local sections are left out.
    """
    retained = set(retained_keys)
    old_pages = (previous or {}).get("pages", {})
    pages = {}
    for parent in compendium.parents:
        if parent.local:
            continue
        key = page_key(parent.u)
        record = pages.get(key)
        if record is None:
            if key in retained and key in old_pages:
                last_seen = old_pages[key].get("last_seen", compendium.built_at)
            else:
                last_seen = compendium.built_at
            record = pages[key] = {
                "url": parent.u,
                "last_seen": last_seen,
                "sections": [],
                **{field: _plain(getattr(parent, field)) for field in SECTION_FIELDS},
            }
        record["sections"].append([parent.t, parent.x])
    return pages


def save_manifest(compendium, previous=None, retained_keys=()):
    """
    Writes the manifest for one finished build, replacing the last one.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        previous (dict | None): the manifest read before this build.
        retained_keys (Iterable[str]): the keys of the pages carried forward.

    Returns:
        str: the path written.

    Raises:
        OSError: if the file cannot be written.
    """
    path = manifest_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "version": MANIFEST_VERSION,
        "built_at": compendium.built_at,
        "pages": pages_of(compendium, previous, retained_keys),
    }
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_path, path)
    return path


### Carrying Forward ###

def carry_forward(previous, seen_keys, gone_keys, retainable_labels):
    """
    The pages from the last build that this build keeps without having
    read them.

    A page is carried forward when this build produced nothing for its
    address, no server confirmed it gone, and it came from a source that
    can miss a live page: a web crawl, which reaches pages by following
    links and may not reach one that is still there. A source that lists
    its content through an interface is authoritative, so a page absent
    from its listing is gone, and a source no longer in the settings file
    takes its pages with it.

    Args:
        previous (dict | None): the manifest the last build wrote.
        seen_keys (Iterable[str]): the keys of every page this build
            produced a document for.
        gone_keys (Iterable[str]): the keys the sources reported as
            confirmed gone.
        retainable_labels (Iterable[str]): the labels of the configured
            sources whose pages may be carried forward.

    Returns:
        list[tuple[str, list[dict], list[dict], str]]: one entry per page
        kept: its key, its parents, its children with page-local pids,
        and the date it was last seen.
    """
    if not previous:
        return []
    seen = set(seen_keys)
    gone = set(gone_keys)
    labels = set(retainable_labels)
    kept = []
    for key, record in previous["pages"].items():
        if key in seen or key in gone or record.get("source_label") not in labels:
            continue
        parents = _parents_from(record)
        if not parents:
            continue
        kept.append((key, parents, _children_for(parents), record.get("last_seen", "")))
    return kept


def _parents_from(record):
    """One page's parent dicts, rebuilt from its manifest record with the ids they had."""
    url = record.get("url")
    sections = record.get("sections")
    if not isinstance(url, str) or not isinstance(sections, list):
        return []
    host = urlparse(url).netloc.lower()
    parents = []
    for section in sections:
        if not (isinstance(section, list) and len(section) == 2 and all(isinstance(s, str) for s in section)):
            continue
        heading, text = section
        parents.append({
            "t": heading,
            "x": text,
            "u": url,
            "host": host,
            "source_type": record.get("source_type", "web"),
            "content_type": record.get("content_type", "page"),
            "source_label": record.get("source_label", ""),
            "categories": tuple(record.get("categories") or ()),
            "local": False,
            "weight": record.get("weight", 1.0),
        })
    return assign_parent_ids(parents)


def _plain(value):
    """A manifest-safe copy of one field value."""
    return list(value) if isinstance(value, tuple) else value


def summary_lines(kept, gone_count):
    """
    What the build summary says about pages carried forward and dropped.

    Args:
        kept (Sequence): what carry_forward returned.
        gone_count (int): how many pages the sources confirmed gone.

    Returns:
        list[str]: zero, one, or two lines.
    """
    lines = []
    if kept:
        oldest = min(last_seen for _, _, _, last_seen in kept if last_seen) if any(k[3] for k in kept) else ""
        when = f"; the oldest was last seen {oldest[:10]}" if oldest else ""
        lines.append(
            f"{len(kept)} page(s) not seen this build were kept from earlier builds{when}"
        )
    if gone_count:
        lines.append(f"{gone_count} page(s) the server confirmed gone were dropped")
    return lines
