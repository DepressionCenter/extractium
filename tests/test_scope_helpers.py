"""
Summary: Characterization tests pinning the current behavior of
build-kb-index.py's URL scope/normalization helpers: derive_auto_prefix,
compile_patterns, get_origin, is_git_host_url, is_git_blob_text_url,
to_git_raw_url, normalise, and in_scope. These tests exist to prove step 3
of the extraction plan (moving this logic into extractium/core/) is
behavior-preserving -- they assert current behavior, not "correct"
behavior.

This file is part of Extractium™
tests/test_scope_helpers.py

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


# ---------------------------------------------------------------------------
# derive_auto_prefix
# ---------------------------------------------------------------------------

def test_derive_auto_prefix_tdx_url_scopes_to_client_prefix(reference):
    prefix = reference.derive_auto_prefix(
        "https://example.edu/TDClient/210/DepressionCenter/Home/"
    )
    assert prefix == "https://example.edu/TDClient/210/DepressionCenter/"


def test_derive_auto_prefix_non_tdx_url_scopes_to_origin(reference):
    prefix = reference.derive_auto_prefix("https://example.org/docs/setup")
    assert prefix == "https://example.org"


# ---------------------------------------------------------------------------
# compile_patterns / get_origin
# ---------------------------------------------------------------------------

def test_compile_patterns_returns_case_insensitive_compiled_regexes(reference):
    compiled = reference.compile_patterns([r"/kb/", r"\.pdf$"])
    assert len(compiled) == 2
    assert compiled[0].search("/KB/article") is not None  # case-insensitive
    assert compiled[1].search("report.PDF") is not None


def test_get_origin_strips_path_and_query(reference):
    assert reference.get_origin("https://example.org/a/b?c=1") == "https://example.org"


# ---------------------------------------------------------------------------
# is_git_host_url / is_git_blob_text_url / to_git_raw_url
# ---------------------------------------------------------------------------

def test_is_git_host_url_true_for_github(reference):
    assert reference.is_git_host_url("https://github.com/example-org/example-repo") is True


def test_is_git_host_url_false_for_non_git_host(reference):
    assert reference.is_git_host_url("https://example.org/docs") is False


def test_is_git_blob_text_url_true_for_markdown_blob(reference):
    url = "https://github.com/example-org/example-repo/blob/main/docs/setup.md"
    assert reference.is_git_blob_text_url(url) is True


def test_is_git_blob_text_url_false_for_non_text_blob(reference):
    url = "https://github.com/example-org/example-repo/blob/main/src/app.py"
    assert reference.is_git_blob_text_url(url) is False


def test_is_git_blob_text_url_false_for_non_blob_path(reference):
    url = "https://github.com/example-org/example-repo/tree/main/docs"
    assert reference.is_git_blob_text_url(url) is False


def test_to_git_raw_url_rewrites_blob_to_raw_githubusercontent(reference):
    blob_url = "https://github.com/example-org/example-repo/blob/main/docs/setup.md"
    assert (
        reference.to_git_raw_url(blob_url)
        == "https://raw.githubusercontent.com/example-org/example-repo/main/docs/setup.md"
    )


# ---------------------------------------------------------------------------
# normalise
# ---------------------------------------------------------------------------

def test_normalise_strips_fragment_and_trailing_slash(reference):
    assert reference.normalise("https://example.org/docs/#section-1") == "https://example.org/docs"


def test_normalise_leaves_no_trailing_slash_url_unchanged(reference):
    assert reference.normalise("https://example.org/docs") == "https://example.org/docs"


# ---------------------------------------------------------------------------
# in_scope
# ---------------------------------------------------------------------------

def test_in_scope_same_origin_within_auto_prefix_default(reference):
    origin = "https://example.org"
    auto_prefix = "https://example.org/kb/"
    assert reference.in_scope(
        "https://example.org/kb/article-1", auto_prefix, origin, [], []
    ) is True


def test_in_scope_same_origin_outside_auto_prefix_default_excluded(reference):
    origin = "https://example.org"
    auto_prefix = "https://example.org/kb/"
    assert reference.in_scope(
        "https://example.org/other/page", auto_prefix, origin, [], []
    ) is False


def test_in_scope_cross_origin_without_include_pattern_excluded(reference):
    origin = "https://example.org"
    auto_prefix = "https://example.org"
    assert reference.in_scope(
        "https://github.com/example-org/example-repo", auto_prefix, origin, [], []
    ) is False


def test_in_scope_cross_origin_matching_include_pattern_allowed(reference):
    origin = "https://example.org"
    auto_prefix = "https://example.org"
    include_res = reference.compile_patterns([r"github\.com/example-org/"])
    assert reference.in_scope(
        "https://github.com/example-org/example-repo", auto_prefix, origin, include_res, []
    ) is True


def test_in_scope_asset_extension_excluded_even_with_matching_include(reference):
    # ASSET_RE is checked unconditionally, before the include-pattern check.
    origin = "https://example.org"
    auto_prefix = "https://example.org"
    include_res = reference.compile_patterns([r"example\.org/"])
    assert reference.in_scope(
        "https://example.org/report.pdf", auto_prefix, origin, include_res, []
    ) is False


def test_in_scope_exclude_wins_over_matching_include(reference):
    # Comment in the source: "Crawl exclude check (after include, so excludes win)".
    origin = "https://example.org"
    auto_prefix = "https://example.org"
    include_res = reference.compile_patterns([r"example\.org/"])
    crawl_exclude_res = reference.compile_patterns([r"/Login"])
    assert reference.in_scope(
        "https://example.org/Login.aspx", auto_prefix, origin, include_res, crawl_exclude_res
    ) is False


def test_in_scope_explicit_include_patterns_exclude_unmatched_same_origin_url(reference):
    """
    SURPRISING BEHAVIOR, pinned as-is (see AGENTS.md section 4 -- this is
    current behavior, not necessarily intended behavior; not fixed here):
    once INCLUDE_PATTERNS is non-empty, in_scope() no longer falls back to
    "same origin is always allowed" -- a same-origin URL that matches none
    of the explicit include patterns is excluded, even though the same URL
    would have been in-scope with an EMPTY include list.

    TODO: confirm this is intended. A user adding one explicit include
    pattern to reach a second host (e.g. GitHub) may not expect it to also
    narrow same-origin crawling down to just that one pattern.
    """
    origin = "https://example.org"
    auto_prefix = "https://example.org"
    include_res = reference.compile_patterns([r"github\.com/example-org/"])
    assert reference.in_scope(
        "https://example.org/kb/some-other-page", auto_prefix, origin, include_res, []
    ) is False
