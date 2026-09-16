"""
Summary: Tests for the project's one-page site, index.html. The page
carries a Content Security Policy that allows its inline stylesheet and
scripts by hash, so any edit to one of those blocks that does not
update the policy leaves a browser rendering the page with no styles
at all. These tests hold the policy to the page.

This file is part of Extractium™
tests/test_site.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-16
Last Modified: 2026-09-16
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
__date__ = "2026-09-16"

import base64
import hashlib
import pathlib
import re

import pytest

SITE = pathlib.Path(__file__).resolve().parent.parent / "index.html"

# The analytics loader at the end of the page is deliberately not in the
# policy. Allowing it by hash would change nothing on its own, because
# the policy names no tag-manager host in script-src or connect-src
# either; turning analytics on is a decision to make in the page, in
# all three places at once, not one this test should make by accident.
ANALYTICS_MARKER = "googletagmanager.com"


def _hash(text):
    """The value a CSP hash source carries for one inline block."""
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()


@pytest.fixture(scope="module")
def page():
    return SITE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def policy(page):
    """The policy's directives, each mapped to the hashes it names."""
    content = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)"', page).group(1)
    directives = {}
    for directive in content.split(";"):
        name, _, sources = directive.strip().partition(" ")
        directives[name] = re.findall(r"'sha256-([^']+)'", sources)
    return directives


def test_the_policy_allows_the_pages_stylesheet(page, policy):
    """A stale style hash leaves the page unstyled in every browser."""
    styles = re.findall(r"<style[^>]*>(.*?)</style>", page, re.S)

    assert len(styles) == 1
    assert policy["style-src"] == [_hash(styles[0])]


def test_the_policy_allows_every_script_the_page_needs(page, policy):
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", page, re.S)
    needed = [script for script in scripts if ANALYTICS_MARKER not in script]

    assert len(needed) == 2, "the structured-data block and the page's own script"
    assert sorted(policy["script-src"]) == sorted(_hash(script) for script in needed)


def test_the_policy_names_no_hash_that_matches_nothing_on_the_page(page, policy):
    """A leftover hash is a sign an edit was made without this check."""
    blocks = re.findall(r"<style[^>]*>(.*?)</style>", page, re.S)
    blocks += re.findall(r"<script[^>]*>(.*?)</script>", page, re.S)
    present = {_hash(block) for block in blocks}

    for directive in ("style-src", "script-src"):
        assert set(policy[directive]) <= present, directive
