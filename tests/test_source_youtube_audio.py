"""
Summary: Tests for the audio fallback of the YouTube source: what the
downloader's record becomes, how Whisper's segments become caption
lines, how a configured language reaches the model, and that the
packages are never required by a build that does not use them.

This file is part of Extractium™
tests/test_source_youtube_audio.py

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

import sys
from types import SimpleNamespace

import pytest

from extractium.sources import youtube_audio as audio


def test_metadata_from_info_keeps_only_the_fields_the_store_carries():
    metadata = audio.metadata_from_info({
        "title": "  A Talk ", "description": "What it covers.", "tags": ["mood", 7, "phone"],
        "upload_date": "20260102", "channel_id": " UCaaaaaaaaaaaaaaaaaaaaaa ", "view_count": 5,
    })

    assert metadata == {
        "title": "A Talk", "description": "What it covers.", "tags": ("mood", "phone"),
        "published_at": "2026-01-02T00:00:00Z", "channel_id": "UCaaaaaaaaaaaaaaaaaaaaaa",
    }


@pytest.mark.parametrize("info", [None, {}, {"tags": "not a list", "upload_date": "2026-1-2"}, {"tags": [1, 2], "title": None}])
def test_metadata_from_info_degrades_to_blanks_on_anything_unexpected(info):
    metadata = audio.metadata_from_info(info)

    assert metadata["title"] == "" and metadata["tags"] == () and metadata["published_at"] == ""


def test_transcript_lines_collapse_whitespace_and_skip_empty_segments():
    segments = [
        SimpleNamespace(start=0.0, text="  First\n line "),
        SimpleNamespace(start=3.5, text="   "),
        SimpleNamespace(start=7.25, text="Second."),
    ]

    assert audio.transcript_lines(segments) == [
        {"text": "First line", "start": 0.0}, {"text": "Second.", "start": 7.25},
    ]


@pytest.mark.parametrize("configured, expected", [("en", "en"), ("en-US", "en"), ("EN", "en"), ("", None), ("1", None)])
def test_whisper_language_is_the_two_letter_code_or_nothing(configured, expected):
    assert audio.whisper_language(configured) == expected


def test_downloaded_path_reads_what_the_downloader_reports():
    assert audio._downloaded_path({"requested_downloads": [{"filepath": "C:/tmp/x.m4a"}]}) == "C:/tmp/x.m4a"
    assert audio._downloaded_path({"requested_downloads": [{}]}) == ""
    assert audio._downloaded_path("nonsense") == ""


def test_the_audio_path_is_unavailable_without_its_packages(monkeypatch):
    """A build that never needs the packages must not fail for lacking them."""
    monkeypatch.setitem(sys.modules, "yt_dlp", None)
    monkeypatch.setitem(sys.modules, "faster_whisper", None)

    assert audio.audio_transcription_available() is False
    with pytest.raises(audio.AudioTranscriptionUnavailable, match=r"extractium\[whisper\]"):
        audio.download_audio("VIDEOAAAAAA", ".")


def test_transcribe_audio_uses_the_model_it_is_given():
    class FakeModel:
        def __init__(self):
            self.calls = []

        def transcribe(self, path, language=None, beam_size=None, vad_filter=None):
            self.calls.append({"path": path, "language": language, "beam_size": beam_size})
            return iter([SimpleNamespace(start=1.0, text="spoken words")]), SimpleNamespace(language="en")

    model = FakeModel()
    language, lines = audio.transcribe_audio("talk.m4a", language="en-GB", model=model)

    assert (language, lines) == ("en", [{"text": "spoken words", "start": 1.0}])
    assert model.calls == [{"path": "talk.m4a", "language": "en", "beam_size": audio.WHISPER_BEAM_SIZE}]


def test_a_video_identifier_is_checked_before_anything_is_downloaded():
    with pytest.raises(audio.YouTubeError):
        audio.download_audio("../not-a-video", ".")
