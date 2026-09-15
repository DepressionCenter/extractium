"""
Summary: Tests for the page ceiling every source counts against: it allows
up to the limit and no more, reports once when it stopped a source, and
is no ceiling at all for a source built without settings.

This file is part of Extractium™
tests/test_core_ceiling.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-15
Last Modified: 2026-09-15
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

from extractium.core.ceiling import PageCeiling
from extractium.sources.web import CrawlSettings


def test_the_ceiling_allows_up_to_the_limit_and_no_more():
    ceiling = PageCeiling(2, "video")

    assert [ceiling.allow() for _ in range(4)] == [True, True, False, False]
    assert ceiling.read == 2
    assert ceiling.reached


def test_the_ceiling_reports_once_and_only_when_it_was_reached():
    lines = []
    ceiling = PageCeiling(2, "deposit")
    ceiling.allow()
    ceiling.report(lines.append)
    assert lines == []

    ceiling.allow()
    ceiling.report(lines.append)
    ceiling.report(lines.append)
    assert lines == [
        "  max_pages: the ceiling of 2 deposit(s) was reached; anything past it was not read"
    ]


def test_a_source_without_settings_has_no_ceiling():
    ceiling = PageCeiling.for_settings(None, "file")

    assert all(ceiling.allow() for _ in range(1000))
    assert not ceiling.reached


def test_the_ceiling_is_read_from_the_build_settings():
    ceiling = PageCeiling.for_settings(CrawlSettings(max_pages=3), "file")

    assert ceiling.limit == 3
