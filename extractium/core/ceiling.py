"""
Summary: The page ceiling every source reads under. A build's `max_pages`
setting is one number, and each source counts what it reads against it in
its own unit: a page for a crawl, a video, a deposit, a file, a concept.
The counter here is what a source asks before reading one more, and what
reports, once, that the ceiling stopped it.

This file is part of Extractium™
extractium/core/ceiling.py

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


class PageCeiling:
    """
    Counts what one source has read against the build's `max_pages`.

    A source asks `allow()` before reading one more item and stops when
    the answer is no. The ceiling is per source, as it is for a crawl: two
    sources may read twice as much between them. A source built without
    settings, as a library caller or a test may do, has no ceiling.

    Args:
        limit (int | None): the most items this source may read; None
            for no ceiling.
        unit (str): what one item is called in the report, singular, such
            as "video" or "file".
    """

    def __init__(self, limit, unit):
        self.limit = limit
        self.unit = unit
        self.read = 0
        self._reported = False

    @classmethod
    def for_settings(cls, settings, unit):
        """
        The ceiling a source reads under, from the build settings it was
        given, or no ceiling when it was given none.

        Args:
            settings: the build's crawl settings, or None.
            unit (str): what one item is called in the report.
        """
        limit = getattr(settings, "max_pages", None) if settings is not None else None
        return cls(limit, unit)

    @property
    def reached(self):
        """Whether the ceiling has been reached, so nothing more may be read."""
        return self.limit is not None and self.read >= self.limit

    def allow(self):
        """
        Whether one more item may be read. Counts it when so.

        Returns:
            bool: True and one more counted, or False with nothing counted.
        """
        if self.reached:
            return False
        self.read += 1
        return True

    def report(self, progress):
        """
        Says, once, that this source reached the ceiling, when it did. A
        source stops at the ceiling without looking past it, so the line
        does not claim to know how much was left.

        Args:
            progress (Callable[[str], None]): receives the one line.
        """
        if self.reached and not self._reported:
            self._reported = True
            progress(
                f"  max_pages: the ceiling of {self.limit} {self.unit}(s) was reached; "
                "anything past it was not read"
            )
