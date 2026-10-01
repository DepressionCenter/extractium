"""
Summary: Downloads the three models a build and a search use into the
model cache, so a portable folder carries them and a person who unzips
it needs no download before the first build: the embedding model, the
reranker, and the Whisper model the audio fallback runs. Each is loaded
by name through the same library call the tool makes, so what lands in
the cache is exactly what the tool asks for. Run with HF_HOME pointing
at the folder's cache, as the release workflow does.

This file is part of Extractium™
tools/warm_model_cache.py

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
import os
import pathlib
import sys

### The Models ###

def model_names():
    """
    The three model names, read from the modules that load them, so a
    change there changes what is cached.

    Returns:
        dict[str, str]: `embedding`, `reranker`, `whisper`.
    """
    from extractium.core.embed import EMBED_MODEL
    from extractium.search import DEFAULT_RERANK_MODEL
    from extractium.sources.youtube_audio import WHISPER_MODEL

    return {"embedding": EMBED_MODEL, "reranker": DEFAULT_RERANK_MODEL, "whisper": WHISPER_MODEL}


def loaders():
    """
    One loader per model, each making the library call the tool makes.
    Loading a model downloads it into the cache when it is not there.
    """
    def embedding(name):
        from sentence_transformers import SentenceTransformer
        SentenceTransformer(name)

    def reranker(name):
        from sentence_transformers import CrossEncoder
        CrossEncoder(name)

    def whisper(name):
        from faster_whisper import WhisperModel
        WhisperModel(name, device="cpu", compute_type="int8")

    return {"embedding": embedding, "reranker": reranker, "whisper": whisper}


def folder_size(folder):
    """The bytes under a folder."""
    return sum(path.stat().st_size for path in pathlib.Path(folder).rglob("*") if path.is_file())


def warm(names=None, load=None, say=print):
    """
    Loads each model once, which downloads it, and reports the cache size.

    Args:
        names (Mapping[str, str] | None): the models; the tool's own when None.
        load (Mapping[str, Callable] | None): the loaders; the real ones when None.
        say (Callable[[str], None]): prints one line.
    """
    names = model_names() if names is None else names
    load = loaders() if load is None else load
    for kind, name in names.items():
        say(f"Loading the {kind} model, {name} ...")
        load[kind](name)
    cache = os.environ.get("HF_HOME")
    if cache and pathlib.Path(cache).is_dir():
        say(f"The model cache at {cache} holds {folder_size(cache) / 1024 / 1024:.0f} MB.")


### Entry Point ###

def main(argv=None):
    parser = argparse.ArgumentParser(description="Download the models into the cache HF_HOME names.")
    parser.add_argument("--dry-run", action="store_true", help="Print the model names and download nothing.")
    args = parser.parse_args(argv)
    if args.dry_run:
        for kind, name in model_names().items():
            print(f"{kind}: {name}")
        return 0
    warm()
    return 0


if __name__ == "__main__":
    sys.exit(main())
