"""
Summary: Tests for carrying pages forward between builds: the manifest a
build writes and reads back, which never holds local content; the rule
for which unseen pages an incremental rebuild keeps (a web page not
confirmed gone, from a source still configured) and which it drops; a
kept page getting the section identifiers it had; the build step taking
carried-forward pages; the fetch layer telling a page confirmed gone
from one that failed; and a whole incremental build through the command
line against a crawl that lost a page, broke a page, and unlinked a page.

This file is part of Extractium™
tests/test_retain.py

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

import dataclasses
import json
import pathlib
import textwrap

import pytest
from bs4 import BeautifulSoup

from extractium import cli, config
from extractium.core import build, retain
from extractium.core.chunk import chunk_document
from extractium.core.models import Document
from tests.conftest import FakeResponse
from tests.test_adapter_container import mixed_compendium, sample_compendium
from tests.test_cli import read_container


@pytest.fixture
def build_workspace(tmp_path, monkeypatch, fake_embed_chunks_core):
    """A folder the command line can run a whole build in, with the embedding step faked."""
    from extractium.core import embed

    monkeypatch.setattr(embed, "embed_chunks", lambda chunks, progress=None: fake_embed_chunks_core(chunks))
    monkeypatch.chdir(tmp_path)
    return tmp_path

BODY_A = (
    "The team keeps office hours every week, and the notes from each session are "
    "posted the following morning so that anyone who could not attend can follow."
)
BODY_B = (
    "Every release is announced on this page, with the date it went out, what "
    "changed in it, and who to ask when something about it looks wrong to you."
)
BODY_C = (
    "Participants reach the study team through the contact page, which lists the "
    "hours the line is answered and what to do outside them in an emergency."
)
BODY_D = (
    "The onboarding checklist walks a new coordinator through the accounts to "
    "request, the training to complete, and the people to meet in the first week."
)


def quiet(line):
    """A progress sink for tests that do not inspect progress."""


def page(title, body, links=()):
    anchors = "".join(f'<a href="{href}">{href}</a>' for href in links)
    return FakeResponse(status_code=200, headers={"Content-Type": "text/html"},
                        text=f"<html><head><title>{title}</title></head><body><main>"
                             f"<p>{body}</p>{anchors}</main></body></html>")


### The Manifest ###

def test_the_manifest_records_every_published_page_and_no_local_content(
    isolated_core_cache, fixtures_dir, fake_embed_chunks_core,
):
    compendium = mixed_compendium(fixtures_dir, fake_embed_chunks_core)

    path = retain.save_manifest(compendium)
    previous = retain.load_previous()

    assert pathlib.Path(path).name == retain.MANIFEST_FILE
    assert previous["built_at"] == compendium.built_at
    assert set(previous["pages"]) == {retain.page_key(p.u) for p in compendium.parents if not p.local}
    assert "AB123456" not in pathlib.Path(path).read_text(encoding="utf-8")
    for record in previous["pages"].values():
        assert record["last_seen"] == compendium.built_at
        assert record["sections"] and all(len(s) == 2 for s in record["sections"])


def test_a_manifest_that_cannot_be_read_counts_as_absent(isolated_core_cache):
    pathlib.Path(retain.manifest_path()).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(retain.manifest_path()).write_text("{not json", encoding="utf-8")

    assert retain.load_previous() is None


def test_a_carried_forward_page_keeps_the_date_it_was_really_last_seen(
    isolated_core_cache, fixtures_dir, fake_embed_chunks_core,
):
    first = dataclasses.replace(sample_compendium(fixtures_dir, fake_embed_chunks_core), built_at="2026-09-01T00:00:00Z")
    retain.save_manifest(first)
    previous = retain.load_previous()
    key = retain.page_key(first.parents[0].u)

    second = dataclasses.replace(sample_compendium(fixtures_dir, fake_embed_chunks_core), built_at="2026-09-08T00:00:00Z")
    retain.save_manifest(second, previous, retained_keys=[key])
    again = retain.load_previous()

    assert again["pages"][key]["last_seen"] == "2026-09-01T00:00:00Z"
    other = next(k for k in again["pages"] if k != key)
    assert again["pages"][other]["last_seen"] == "2026-09-08T00:00:00Z"


### Which Pages Are Kept ###

@pytest.fixture
def previous_manifest():
    return {
        "version": retain.MANIFEST_VERSION,
        "built_at": "2026-09-01T00:00:00Z",
        "pages": {
            "https://example.org/kept": {
                "url": "https://example.org/kept", "last_seen": "2026-09-01T00:00:00Z",
                "source_type": "web", "content_type": "page", "source_label": "Site",
                "categories": [], "weight": 1.0, "sections": [["Kept", BODY_A]],
            },
            "https://example.org/seen": {
                "url": "https://example.org/seen", "last_seen": "2026-09-01T00:00:00Z",
                "source_type": "web", "content_type": "page", "source_label": "Site",
                "categories": [], "weight": 1.0, "sections": [["Seen", BODY_B]],
            },
            "https://example.org/gone": {
                "url": "https://example.org/gone", "last_seen": "2026-09-01T00:00:00Z",
                "source_type": "web", "content_type": "page", "source_label": "Site",
                "categories": [], "weight": 1.0, "sections": [["Gone", BODY_C]],
            },
            "https://github.com/example-org/repo/blob/main/README.md": {
                "url": "https://github.com/example-org/repo/blob/main/README.md",
                "last_seen": "2026-09-01T00:00:00Z", "source_type": "github",
                "content_type": "readme", "source_label": "Repositories",
                "categories": ["example-org", "repo"], "weight": 1.0, "sections": [["README", BODY_B]],
            },
        },
    }


def test_only_an_unseen_web_page_not_confirmed_gone_is_carried_forward(previous_manifest):
    kept = retain.carry_forward(
        previous_manifest,
        seen_keys=["https://example.org/seen"],
        gone_keys=["https://example.org/gone"],
        retainable_labels=["Site"],
    )

    assert [key for key, _, _, _ in kept] == ["https://example.org/kept"]
    key, parents, children, last_seen = kept[0]
    assert last_seen == "2026-09-01T00:00:00Z"
    assert parents[0]["t"] == "Kept" and parents[0]["source_label"] == "Site"
    assert children[0]["pid"] == 0 and children[0]["x"] == BODY_A


def test_a_page_from_a_source_no_longer_configured_is_dropped(previous_manifest):
    kept = retain.carry_forward(previous_manifest, seen_keys=[], gone_keys=[], retainable_labels=["Other"])

    assert kept == []


def test_a_carried_forward_page_has_the_section_ids_it_had(previous_manifest):
    document = Document(url="https://example.org/kept", title="Kept",
                        content=BeautifulSoup(f"<main><p>{BODY_A}</p></main>", "html.parser"),
                        source_type="web", content_type="page", source_label="Site")
    fresh, _ = chunk_document(document)

    (_, parents, _, _), = retain.carry_forward(
        previous_manifest, ["https://example.org/seen"], ["https://example.org/gone"], ["Site"]
    )

    assert [p["id"] for p in parents] == [p["id"] for p in fresh]
    assert [p["x"] for p in parents] == [p["x"] for p in fresh]


def test_no_manifest_means_nothing_to_carry_forward():
    assert retain.carry_forward(None, [], [], ["Site"]) == []


def test_the_summary_names_what_was_kept_and_what_was_dropped(previous_manifest):
    kept = retain.carry_forward(previous_manifest, [], [], ["Site"])

    lines = retain.summary_lines(kept, gone_count=2)

    assert lines[0].startswith("3 page(s) not seen this build were kept")
    assert "last seen 2026-09-01" in lines[0]
    assert lines[1] == "2 page(s) the server confirmed gone were dropped"
    assert retain.summary_lines([], 0) == []


### The Build Step ###

def test_the_build_step_scores_carried_forward_pages_with_the_rest(previous_manifest, fake_embed_chunks_core):
    kept = retain.carry_forward(previous_manifest, [], [], ["Site"])
    document = Document(url="https://example.org/new", title="New",
                        content=BeautifulSoup(f"<main><p>{BODY_D}</p></main>", "html.parser"),
                        source_type="web", content_type="page", source_label="Site")

    compendium = build.build_compendium([document], embedder=fake_embed_chunks_core, retained=kept)

    urls = [p.u for p in compendium.parents]
    assert urls[0] == "https://example.org/new"
    assert set(urls[1:]) == {"https://example.org/kept", "https://example.org/seen", "https://example.org/gone"}
    assert len(compendium.children) == len(compendium.parents)
    assert max(compendium.children.pid) == len(compendium.parents) - 1


### Confirmed Gone ###

@pytest.mark.parametrize("status, gone", [(404, True), (410, True), (500, False), (403, False), (200, False)])
def test_the_fetch_layer_tells_a_page_confirmed_gone_from_one_that_failed(
    status, gone, isolated_core_cache, fake_session_factory,
):
    from extractium.core import fetch
    url = "https://example.org/page"
    session = fake_session_factory({url: FakeResponse(status_code=status, headers={"Content-Type": "text/html"},
                                                      text="<html><body><main><p>x</p></main></body></html>")})
    seen = []

    fetch.fetch(session, url, {}, progress=quiet, note_gone=lambda: seen.append(True))

    assert bool(seen) is gone


### A Whole Incremental Build ###

SEED = "https://example.org/home"
LOST = "https://example.org/lost"
BROKEN = "https://example.org/broken"
UNLINKED = "https://example.org/unlinked"
ROBOTS = "https://example.org/robots.txt"


def responses_for(first_build):
    """The site as the first build saw it, and as the second one finds it."""
    if first_build:
        return {
            SEED: page("Home", BODY_A, links=[LOST, BROKEN, UNLINKED]),
            LOST: page("Lost", BODY_B), BROKEN: page("Broken", BODY_C), UNLINKED: page("Unlinked", BODY_D),
            ROBOTS: FakeResponse(status_code=404),
        }
    return {
        SEED: page("Home", BODY_A, links=[LOST, BROKEN]),
        LOST: FakeResponse(status_code=404),
        BROKEN: FakeResponse(status_code=500),
        ROBOTS: FakeResponse(status_code=404),
    }


FIRST_RUN = "2026-09-01T06:17:00Z"
SECOND_RUN = "2026-09-08T06:17:00Z"


def run_build(workspace, monkeypatch, fake_session_factory, first_build, rebuild):
    monkeypatch.setattr(build, "utc_now", lambda: FIRST_RUN if first_build else SECOND_RUN)

    def session(*args, **kwargs):
        fake = fake_session_factory(responses_for(first_build))
        fake.close = lambda: None
        return fake
    monkeypatch.setattr(cli, "make_session", session)
    settings = workspace / "config.yaml"
    settings.write_text(textwrap.dedent(f"""
        name: Example Org
        out_dir: dist
        cache_dir: .cache
        rebuild: {rebuild}
        sources:
          - type: web
            label: Site
            seed_url: {SEED}
        outputs:
          - type: container
    """), encoding="utf-8")
    assert cli.main(["build", "--config", str(settings)]) == cli.EXIT_OK
    header = read_container(workspace / "dist" / "compendium.json")
    return sorted({p["u"] for p in header["parents"]})


def test_an_incremental_rebuild_keeps_the_unlinked_and_broken_pages_and_drops_the_lost_one(
    build_workspace, monkeypatch, fake_session_factory, capsys,
):
    assert run_build(build_workspace, monkeypatch, fake_session_factory, True, "incremental") == sorted([SEED, LOST, BROKEN, UNLINKED])

    urls = run_build(build_workspace, monkeypatch, fake_session_factory, False, "incremental")

    assert urls == sorted([SEED, BROKEN, UNLINKED])
    out = capsys.readouterr().out
    assert "2 page(s) not seen this build were kept from earlier builds" in out
    assert "1 page(s) the server confirmed gone were dropped" in out
    manifest = json.loads((build_workspace / ".cache" / retain.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["built_at"] == SECOND_RUN
    assert manifest["pages"][retain.page_key(UNLINKED)]["last_seen"] == FIRST_RUN
    assert manifest["pages"][retain.page_key(BROKEN)]["last_seen"] == FIRST_RUN
    assert manifest["pages"][retain.page_key(SEED)]["last_seen"] == SECOND_RUN


def test_a_full_rebuild_publishes_exactly_what_it_read(build_workspace, monkeypatch, fake_session_factory):
    run_build(build_workspace, monkeypatch, fake_session_factory, True, "incremental")

    assert run_build(build_workspace, monkeypatch, fake_session_factory, False, "full") == [SEED]


def test_the_rebuild_setting_is_full_by_default_and_checked():
    cfg = config.config_from_mapping({"sources": [{"type": "web", "label": "S", "seed_url": SEED}]})
    assert cfg.rebuild == "full"
    assert config.config_from_mapping({"sources": [{"type": "web", "label": "S", "seed_url": SEED}],
                                       "rebuild": "incremental"}).rebuild == "incremental"
    with pytest.raises(config.ConfigError, match="rebuild must be one of"):
        config.config_from_mapping({"sources": [{"type": "web", "label": "S", "seed_url": SEED}], "rebuild": "append"})
