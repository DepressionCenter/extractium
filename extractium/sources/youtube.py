"""
Summary: Will hold the YouTube captions source plugin. Accepts explicit
video ids, playlist ids, and a channel id; lists playlists and channels
through the YouTube Data API v3 with a key read from the YOUTUBE_API_KEY
environment variable, never from config.yaml; fetches captions with
youtube-transcript-api; caches each transcript under the cache directory;
yields one Document per video whose parents deep-link to a timestamp. See
docs/extractium-spec.md section 5.

This file is part of Extractium™
extractium/sources/youtube.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-04
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

# TODO: implement the source protocol (see extractium.core.registry).
# Constraints that shape it:
#   - youtube-transcript-api cannot list a channel or playlist; only the
#     Data API can, and it needs an API key. Explicit video_ids need none.
#   - YouTube blocks requests from cloud-provider IP ranges, so transcript
#     fetching runs on an operator's machine. A CI run must reuse the
#     transcript cache (cache_dir/youtube/<video_id>.json) and never fetch.
#   - Parents are cut at CHUNK_MAX_CHARS with heading "<title> -- mm:ss"
#     and URL https://www.youtube.com/watch?v=<id>&t=<seconds>s, so a
#     citation opens the video at the right moment. source_type is
#     "youtube" and content_type is "video_transcript".
