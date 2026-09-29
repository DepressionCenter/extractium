"""
Summary: Packs the portable Extractium folder, with the run and install
scripts beside it, into the zip a release attaches, and writes the zip's
SHA-256 beside it. When the zip with the model cache inside would pass
the size limit a release file may have, the cache goes into a second
zip instead, so both stay attachable. The release workflow runs this on
a Windows runner after the installer has built the folder.

This file is part of Extractium™
tools/pack_portable.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-30
Last Modified: 2026-09-30
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
__date__ = "2026-09-30"

import argparse
import hashlib
import pathlib
import sys
import zipfile

### Constants ###

# GitHub refuses a release file past two gibibytes.
SIZE_LIMIT_BYTES = 2 * 1024 * 1024 * 1024

# The folder the installer builds, and the cache inside it that the
# models live in, which is what moves to a second zip when needed.
FOLDER_NAME = "Extractium"
CACHE_NAME = "cache"

# The scripts packed beside the folder.
SCRIPTS = ("run.bat", "install.bat")


### Packing ###

def files_under(root, base, skip=()):
    """
    Every file under a folder, as (path, name inside the zip) pairs, in
    a fixed order so the same folder packs the same way twice.

    Args:
        root (pathlib.Path): the folder to walk.
        base (pathlib.Path): the folder the names inside the zip are
            relative to, so a second zip unpacks into the same place.
        skip (Sequence[pathlib.Path]): folders left out.

    Returns:
        list[tuple[pathlib.Path, str]]
    """
    root = pathlib.Path(root)
    base = pathlib.Path(base)
    skip = [pathlib.Path(folder) for folder in skip]
    pairs = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(folder == path or folder in path.parents for folder in skip):
            continue
        pairs.append((path, path.relative_to(base).as_posix()))
    return pairs


def write_zip(target, entries):
    """
    Writes one zip, deflated, and returns its size in bytes.

    Args:
        target (pathlib.Path): the zip to write.
        entries (Sequence[tuple[pathlib.Path, str]]): files and their
            names inside the zip.

    Returns:
        int: the zip's size.
    """
    target = pathlib.Path(target)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path, name in entries:
            archive.write(path, name)
    return target.stat().st_size


def sha256_of(path):
    """The SHA-256 of a file, as lowercase hex."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_hash(target):
    """Writes `<file>.sha256` beside a file in the two-column form `sha256sum` prints, and returns the hash."""
    target = pathlib.Path(target)
    digest = sha256_of(target)
    target.with_name(target.name + ".sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return digest


def pack(where, out_dir, stem, limit=SIZE_LIMIT_BYTES):
    """
    Packs the folder and the scripts beside it.

    The first zip holds everything. When it would be larger than the
    limit, it is written again without the cache, and the cache goes
    into a second zip, so a person unzips both into the same place.

    Args:
        where (pathlib.Path): the folder holding `Extractium`, `run.bat`,
            and `install.bat`.
        out_dir (pathlib.Path): where the zips go.
        stem (str): the zips' name without the ending, such as
            `extractium-v0.5-windows-portable`.
        limit (int): the most bytes one zip may have.

    Returns:
        list[tuple[pathlib.Path, str, int]]: each zip written, with its
        SHA-256 and its size.

    Raises:
        FileNotFoundError: if the folder or a script is missing.
    """
    where = pathlib.Path(where)
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    folder = where / FOLDER_NAME
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder} is not a folder.")
    scripts = []
    for name in SCRIPTS:
        script = where / name
        if not script.is_file():
            raise FileNotFoundError(f"{script} is missing.")
        scripts.append((script, name))

    main_zip = out_dir / f"{stem}.zip"
    size = write_zip(main_zip, scripts + files_under(folder, where))
    written = []
    if size > limit:
        cache = folder / CACHE_NAME
        size = write_zip(main_zip, scripts + files_under(folder, where, skip=[cache]))
        models_zip = out_dir / f"{stem}-models.zip"
        models_size = write_zip(models_zip, files_under(cache, where) if cache.is_dir() else [])
        written.append((models_zip, write_hash(models_zip), models_size))
    written.insert(0, (main_zip, write_hash(main_zip), size))
    return written


### Entry Point ###

def main(argv=None):
    """Packs and prints one line per zip: its name, its SHA-256, and its size."""
    parser = argparse.ArgumentParser(description="Pack the portable Extractium folder into a release zip.")
    parser.add_argument("--where", default=".", help="The folder holding Extractium, run.bat, and install.bat.")
    parser.add_argument("--out", default=".", help="Where the zips go.")
    parser.add_argument("--stem", required=True, help="The zip name without .zip, such as extractium-v0.5-windows-portable.")
    parser.add_argument("--limit", type=int, default=SIZE_LIMIT_BYTES, help="The most bytes one zip may have.")
    args = parser.parse_args(argv)
    try:
        written = pack(args.where, args.out, args.stem, args.limit)
    except FileNotFoundError as error:
        print(f"pack_portable: {error}", file=sys.stderr)
        return 1
    for path, digest, size in written:
        print(f"{path.name}  {digest}  {size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
