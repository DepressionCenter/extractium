"""
Summary: Characterization tests pinning the current end-to-end behavior of
build-kb-index.py's crawl(): the pid-offset arithmetic as pages accumulate
into the shared parent/child lists, and the fact that the seed URL is
queued unconditionally and never passed through in_scope(). Uses
FakeSession (no real network) and the synthetic HTML fixtures in
tests/fixtures/.

This file is part of Extractium™
tests/test_crawl_integration.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
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

from tests.conftest import FakeResponse


def test_crawl_two_pages_pid_offset_arithmetic(
    reference, isolated_cache, fake_session_factory, patch_crawl_session, fixtures_dir
):
    page_a_html = (fixtures_dir / "page_boilerplate_a.html").read_text(encoding="utf-8")
    page_b_html = (fixtures_dir / "page_boilerplate_b.html").read_text(encoding="utf-8")

    seed = "https://example.org/team"
    page_b_url = "https://example.org/project"

    session = fake_session_factory(
        {
            seed: FakeResponse(status_code=200, headers={"Content-Type": "text/html"}, text=page_a_html),
            page_b_url: FakeResponse(status_code=200, headers={"Content-Type": "text/html"}, text=page_b_html),
        }
    )
    patch_crawl_session(session)

    parents, children, site_name = reference.crawl(
        seed, max_pages=10, delay=0, include_res=[], crawl_exclude_res=[], index_exclude_res=[]
    )

    assert site_name == "Team Directory"  # from the seed page's <title>
    assert {c["url"] for c in session.calls} == {seed, page_b_url}

    # Page A contributes 2 sections ("Members", "Standard Disclaimer");
    # page B contributes 2 more ("Overview", "Standard Disclaimer"). crawl()
    # itself never deduplicates -- that is build_index's job -- so all 4
    # parents are present here, each page's locally 0-based child pids
    # offset by how many parents had already accumulated when that page
    # was processed.
    assert len(parents) == 4
    page_a_children = [c for c in children if c["u"] == seed]
    page_b_children = [c for c in children if c["u"] == page_b_url]
    assert sorted(c["pid"] for c in page_a_children) == [0, 1]
    assert sorted(c["pid"] for c in page_b_children) == [2, 3]  # offset by len(all_parents)==2 at that point


def test_crawl_visits_seed_url_even_if_it_matches_crawl_exclude_patterns(
    reference, isolated_cache, fake_session_factory, patch_crawl_session
):
    """
    SURPRISING BEHAVIOR, pinned as-is (see AGENTS.md section 4): crawl()
    queues the seed URL unconditionally and never runs it through
    in_scope(), so a seed matching CRAWL_EXCLUDE_PATTERNS is still fetched
    and indexed -- the exclude list only ever governs which *discovered*
    links get followed.

    TODO: confirm this is intended. A seed URL that happens to match an
    exclude pattern (e.g. one ending in a login page) is silently still
    crawled, which may surprise an operator who assumes the exclude list
    is an absolute filter.
    """
    seed = "https://example.org/Login.aspx"
    html = (
        "<html><head><title>Login</title></head><body><main>"
        "<p>No headings here, just enough placeholder text to clear the "
        "sixty character minimum chunk size threshold used by the "
        "reference script's chunker.</p>"
        "</main></body></html>"
    )
    session = fake_session_factory(
        {seed: FakeResponse(status_code=200, headers={"Content-Type": "text/html"}, text=html)}
    )
    patch_crawl_session(session)
    crawl_exclude_res = reference.compile_patterns([r"/Login\.aspx"])

    parents, children, site_name = reference.crawl(
        seed, max_pages=10, delay=0, include_res=[], crawl_exclude_res=crawl_exclude_res, index_exclude_res=[]
    )

    assert session.calls[0]["url"] == seed  # the seed was fetched despite matching the exclude pattern
    assert site_name == "Login"
    assert len(parents) == 1


def test_crawl_respects_max_pages_ceiling(
    reference, isolated_cache, fake_session_factory, patch_crawl_session
):
    seed = "https://example.org/a"
    other = "https://example.org/b"
    html_a = (
        '<html><head><title>Page A</title></head><body><nav><a href="/b">next</a></nav>'
        "<main><p>Placeholder content long enough to clear the sixty character minimum "
        "chunk size threshold used by the reference script's chunker here.</p></main>"
        "</body></html>"
    )
    html_b = (
        "<html><head><title>Page B</title></head><body>"
        "<main><p>More placeholder content, also long enough to clear the sixty "
        "character minimum chunk size threshold used by the chunker.</p></main>"
        "</body></html>"
    )
    session = fake_session_factory(
        {
            seed: FakeResponse(status_code=200, headers={"Content-Type": "text/html"}, text=html_a),
            other: FakeResponse(status_code=200, headers={"Content-Type": "text/html"}, text=html_b),
        }
    )
    patch_crawl_session(session)

    parents, children, site_name = reference.crawl(
        seed, max_pages=1, delay=0, include_res=[], crawl_exclude_res=[], index_exclude_res=[]
    )

    assert len(session.calls) == 1  # the ceiling stopped the second page from ever being fetched
