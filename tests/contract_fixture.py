"""
Summary: Builds the small compendium the two clients are held to. One
deterministic build over the HTML fixtures produces tests/golden/
contract-container.json, and one fixed query vector plus the ranking both
clients must return produces tests/golden/contract-query.json. The Python
contract test regenerates both and compares; the Node test reads them.

This file is part of Extractium™
tests/contract_fixture.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-08
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
__date__ = "2026-09-08"

import json
import pathlib

import numpy as np

from extractium.adapters.container import ContainerAdapter
from extractium.core import build
from extractium.search import CANDIDATE_POOL, TOP_K, load_container
from tests.test_build import document_from_fixture

### Constants ###

# Build time fixed in the past, so the committed files do not change
# every time the tests run.
CONTRACT_BUILT_AT = "2026-01-02T03:04:05Z"

# Display name of the synthetic knowledge base the clients search.
CONTRACT_SITE_NAME = "Example Org"

# The synthetic pages that make up the corpus, each under its own URL so
# the per-section cap and the source counts have something to work with.
CONTRACT_PAGES = (
    ("page_boilerplate_a.html", "https://example.org/team", "web", "page"),
    ("page_boilerplate_b.html", "https://example.org/project", "web", "page"),
    ("page_long_section.html", "https://example.org/handbook", "web", "page"),
    ("generic_page_with_main.html", "https://example.org/about", "web", "page"),
)

# The query both clients run. Its words appear in the corpus, so the
# keyword half of the search contributes and the fusion path is exercised.
CONTRACT_QUERY = "standard disclaimer for the fictional test site"

# The window whose vector stands in for an embedded query. Using a real
# vector from the file keeps the fixture honest -- the ranking it produces
# is the ranking a query landing on that window would produce -- and needs
# no embedding model to generate.
CONTRACT_QUERY_CHILD = 1

# How many candidates the committed ranking records. Small enough to read
# in a diff, long enough to catch a client that fuses or sorts differently.
CONTRACT_POOL_RECORDED = 10

# Names of the two committed files.
CONTAINER_FILE = "contract-container.json"
QUERY_FILE = "contract-query.json"


### Building ###

def build_contract_compendium(fixtures_dir, embedder):
    """
    Builds the contract corpus.

    Args:
        fixtures_dir (pathlib.Path): the tests/fixtures folder.
        embedder (Callable): the deterministic test embedder.

    Returns:
        extractium.core.models.Compendium: the build result.
    """
    documents = [
        document_from_fixture(fixtures_dir, name, url, source_type=source_type,
                              content_type=content_type)
        for name, url, source_type, content_type in CONTRACT_PAGES
    ]
    return build.build_compendium(
        documents,
        name=CONTRACT_SITE_NAME,
        embedder=embedder,
        built_at=CONTRACT_BUILT_AT,
    )


def write_contract_container(compendium, out_dir):
    """
    Writes the container both clients read.

    Args:
        compendium (extractium.core.models.Compendium): the build result.
        out_dir (str | pathlib.Path): folder to write into.

    Returns:
        pathlib.Path: the file written.
    """
    (path,) = ContainerAdapter().write(compendium, out_dir, {"file": CONTAINER_FILE})
    return path


def contract_expectations(container_path):
    """
    The query and the ranking every client must reproduce for it.

    Args:
        container_path (str | pathlib.Path): the container just written.

    Returns:
        dict: the contents of the query file, ready to serialize.
    """
    index = load_container(container_path)
    query_vector = index.vectors[CONTRACT_QUERY_CHILD]
    query_vector = query_vector / np.linalg.norm(query_vector)

    pool = index.candidates(CONTRACT_QUERY, query_vector)
    closest = index.search(
        CONTRACT_QUERY, lambda _text: query_vector, k=TOP_K, no_threshold=True
    )
    relevant = index.search(CONTRACT_QUERY, lambda _text: query_vector, k=TOP_K)

    return {
        "_comment": (
            "Generated by tests/contract_fixture.py. The Python and JavaScript clients "
            "must produce these rankings from contract-container.json and this query vector."
        ),
        "query": CONTRACT_QUERY,
        "queryPrefix": index.query_prefix,
        "queryVector": [float(value) for value in query_vector],
        "poolSize": CANDIDATE_POOL,
        "k": TOP_K,
        "candidateChildren": [entry["i"] for entry in pool[:CONTRACT_POOL_RECORDED]],
        "closestParentIds": [hit.parent["id"] for hit in closest],
        "relevantParentIds": [hit.parent["id"] for hit in relevant],
    }


def write_contract_files(fixtures_dir, embedder, out_dir):
    """
    Writes both committed contract files.

    Args:
        fixtures_dir (pathlib.Path): the tests/fixtures folder.
        embedder (Callable): the deterministic test embedder.
        out_dir (str | pathlib.Path): folder to write into.

    Returns:
        tuple[pathlib.Path, pathlib.Path]: the container and the query file.
    """
    out_dir = pathlib.Path(out_dir)
    container_path = write_contract_container(
        build_contract_compendium(fixtures_dir, embedder), out_dir
    )
    query_path = out_dir / QUERY_FILE
    query_path.write_text(
        json.dumps(contract_expectations(container_path), indent=2) + "\n", encoding="utf-8"
    )
    return container_path, query_path
