"""
Summary: Tests pinning extractium.core.fetch's URL scope/normalization
helpers: derive_auto_prefix, compile_patterns, get_origin, is_git_host_url,
is_git_blob_text_url, to_git_raw_url, normalise, and in_scope. Mirrors
tests/test_scope_helpers.py (which pins the same behavior on the frozen
reference script) against the real, ported implementation, proving the
port is behavior-identical.

This file is part of Extractium™
tests/test_core_scope.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-08-17
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

from extractium.core import fetch


# ---------------------------------------------------------------------------
# derive_auto_prefix
# ---------------------------------------------------------------------------

def test_derive_auto_prefix_tdx_url_scopes_to_client_prefix():
    prefix = fetch.derive_auto_prefix(
        "https://example.edu/TDClient/210/DepressionCenter/Home/"
    )
    assert prefix == "https://example.edu/TDClient/210/DepressionCenter/"


def test_derive_auto_prefix_non_tdx_url_scopes_to_origin():
    prefix = fetch.derive_auto_prefix("https://example.org/docs/setup")
    assert prefix == "https://example.org"


# ---------------------------------------------------------------------------
# compile_patterns / get_origin
# ---------------------------------------------------------------------------

def test_compile_patterns_returns_case_insensitive_compiled_regexes():
    compiled = fetch.compile_patterns([r"/kb/", r"\.pdf$"])
    assert len(compiled) == 2
    assert compiled[0].search("/KB/article") is not None  # case-insensitive
    assert compiled[1].search("report.PDF") is not None


def test_get_origin_strips_path_and_query():
    assert fetch.get_origin("https://example.org/a/b?c=1") == "https://example.org"


# ---------------------------------------------------------------------------
# is_git_host_url / is_git_blob_text_url / to_git_raw_url
# ---------------------------------------------------------------------------

def test_is_git_host_url_true_for_github():
    assert fetch.is_git_host_url("https://github.com/example-org/example-repo") is True


def test_is_git_host_url_false_for_non_git_host():
    assert fetch.is_git_host_url("https://example.org/docs") is False


def test_is_git_blob_text_url_true_for_markdown_blob():
    url = "https://github.com/example-org/example-repo/blob/main/docs/setup.md"
    assert fetch.is_git_blob_text_url(url) is True


def test_is_git_blob_text_url_false_for_non_text_blob():
    url = "https://github.com/example-org/example-repo/blob/main/src/app.py"
    assert fetch.is_git_blob_text_url(url) is False


def test_is_git_blob_text_url_false_for_non_blob_path():
    url = "https://github.com/example-org/example-repo/tree/main/docs"
    assert fetch.is_git_blob_text_url(url) is False


def test_to_git_raw_url_rewrites_blob_to_raw_githubusercontent():
    blob_url = "https://github.com/example-org/example-repo/blob/main/docs/setup.md"
    assert (
        fetch.to_git_raw_url(blob_url)
        == "https://raw.githubusercontent.com/example-org/example-repo/main/docs/setup.md"
    )


# ---------------------------------------------------------------------------
# normalise
# ---------------------------------------------------------------------------

def test_normalise_strips_fragment_and_trailing_slash():
    assert fetch.normalise("https://example.org/docs/#section-1") == "https://example.org/docs"


def test_normalise_leaves_no_trailing_slash_url_unchanged():
    assert fetch.normalise("https://example.org/docs") == "https://example.org/docs"


# ---------------------------------------------------------------------------
# in_scope
# ---------------------------------------------------------------------------

def test_in_scope_same_origin_within_auto_prefix_default():
    origin = "https://example.org"
    auto_prefix = "https://example.org/kb/"
    assert fetch.in_scope(
        "https://example.org/kb/article-1", auto_prefix, origin, [], []
    ) is True


def test_in_scope_same_origin_outside_auto_prefix_default_excluded():
    origin = "https://example.org"
    auto_prefix = "https://example.org/kb/"
    assert fetch.in_scope(
        "https://example.org/other/page", auto_prefix, origin, [], []
    ) is False


def test_in_scope_cross_origin_without_include_pattern_excluded():
    origin = "https://example.org"
    auto_prefix = "https://example.org"
    assert fetch.in_scope(
        "https://github.com/example-org/example-repo", auto_prefix, origin, [], []
    ) is False


def test_in_scope_cross_origin_matching_include_pattern_allowed():
    origin = "https://example.org"
    auto_prefix = "https://example.org"
    include_res = fetch.compile_patterns([r"github\.com/example-org/"])
    assert fetch.in_scope(
        "https://github.com/example-org/example-repo", auto_prefix, origin, include_res, []
    ) is True


def test_in_scope_asset_extension_excluded_even_with_matching_include():
    # ASSET_RE is checked unconditionally, before the include-pattern check.
    origin = "https://example.org"
    auto_prefix = "https://example.org"
    include_res = fetch.compile_patterns([r"example\.org/"])
    assert fetch.in_scope(
        "https://example.org/report.pdf", auto_prefix, origin, include_res, []
    ) is False


def test_in_scope_exclude_wins_over_matching_include():
    # Comment in the source: "Crawl exclude check (after include, so excludes win)".
    origin = "https://example.org"
    auto_prefix = "https://example.org"
    include_res = fetch.compile_patterns([r"example\.org/"])
    crawl_exclude_res = fetch.compile_patterns([r"/Login"])
    assert fetch.in_scope(
        "https://example.org/Login.aspx", auto_prefix, origin, include_res, crawl_exclude_res
    ) is False


def test_in_scope_explicit_include_patterns_exclude_unmatched_same_origin_url():
    """
    SURPRISING BEHAVIOR, pinned as-is (see AGENTS.md section 4 -- this is
    current behavior, not necessarily intended behavior; not fixed here):
    once an include pattern list is non-empty, in_scope() no longer falls
    back to "same origin is always allowed" -- a same-origin URL that
    matches none of the explicit include patterns is excluded, even though
    the same URL would have been in-scope with an EMPTY include list. This
    is unchanged from the reference script's behavior; whether to change
    it is a separate design decision, not part of this port.
    """
    origin = "https://example.org"
    auto_prefix = "https://example.org"
    include_res = fetch.compile_patterns([r"github\.com/example-org/"])
    assert fetch.in_scope(
        "https://example.org/kb/some-other-page", auto_prefix, origin, include_res, []
    ) is False
