"""
Summary: Tests for the YouTube captions source and its client. The Data
API and the caption library are both faked, so the suite needs no key and
no network. The handful of tests that check how the library's own
failures are classified skip when the optional package is absent;
everything else runs either way, which is the promise a build reading
stored transcripts depends on. Covers the timestamp link format, how
captions are grouped into citable stretches, the store that lets a build
YouTube blocks produce the same index anyway, the refusals that keep an
identifier from a response out of a file path, and the promise that an
API key never reaches a message or a log.

This file is part of Extractium™
tests/test_source_youtube.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-11
Last Modified: 2026-09-11
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
__date__ = "2026-09-11"

import json

import pytest
import requests

from extractium.core import cache as cache_module
from extractium.core.models import Source
from extractium.sources import youtube as youtube_source
from extractium.sources import youtube_client as yc
from extractium.sources.youtube import YouTubeSource, YouTubeSourceError

# The synthetic videos, playlist, and channel every test reads. The
# identifiers have the shape YouTube assigns without naming anything real.
VIDEO_A = "VIDEOAAAAAA"
VIDEO_B = "VIDEOBBBBBB"
PLAYLIST = "PLaaaaaaaaaaaaaaaaaaaa"
CHANNEL = "UCaaaaaaaaaaaaaaaaaaaaaa"
UPLOADS = "UUaaaaaaaaaaaaaaaaaaaaaa"

# A key that is obviously not one, so a test asserting it never leaks has
# something distinctive to search for.
FAKE_KEY = "EXAMPLE_API_KEY_NOT_REAL"


@pytest.fixture(autouse=True)
def _youtube_cache_in_a_temporary_folder(isolated_core_cache):
    """
    Keeps every test's stored transcripts and listings in its own
    temporary folder.

    Without this, one test's fetch would satisfy the next test's read,
    and a test asserting that nothing was fetched would pass for the
    wrong reason.
    """


@pytest.fixture(autouse=True)
def _no_api_key_unless_a_test_asks(monkeypatch):
    """
    Runs every test as though no Data API key were set.

    The source reads the key from the environment, so a developer who
    has one exported would otherwise run a different code path from
    everybody else -- and the suite would reach the real API.
    """
    monkeypatch.delenv(yc.API_KEY_ENV, raising=False)


@pytest.fixture
def api_key_set(monkeypatch):
    """Runs one test as though a Data API key were set."""
    monkeypatch.setenv(yc.API_KEY_ENV, FAKE_KEY)


@pytest.fixture
def caption_library():
    """
    Skips a test that needs the optional caption package installed.

    The source catches that package's own exception classes, so a test of
    how a blocked or captionless video is handled cannot substitute its
    own. Every other test here runs without the package, which is the
    point of keeping it optional: a build that reads stored transcripts
    never calls it.
    """
    return pytest.importorskip("youtube_transcript_api")


def quiet(line):
    """A progress sink for tests that do not inspect progress."""


### Fakes ###

class FakeResponse:
    """Stand-in for a requests.Response from the Data API or oEmbed."""

    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


class FakeYouTubeSession:
    """
    Stand-in for requests.Session, scripted per API resource.

    `responses` maps a resource name -- "playlistItems", "videos", or
    "oembed" -- to one FakeResponse or a list popped in call order, so a
    test can script a paged listing. Every call is recorded, which is how
    the tests assert both what was asked for and that no request carried
    a key it should not have.
    """

    def __init__(self, responses=None, raise_for=()):
        self.responses = responses or {}
        self.raise_for = set(raise_for)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None, allow_redirects=True):
        resource = url.rstrip("/").rsplit("/", 1)[-1]
        self.calls.append({
            "url": url,
            "resource": resource,
            "headers": dict(headers or {}),
            "params": dict(params or {}),
            "timeout": timeout,
        })
        if resource in self.raise_for:
            raise requests.ConnectionError(f"cannot reach {url}?key={FAKE_KEY}")
        entry = self.responses[resource]
        if isinstance(entry, list):
            return entry.pop(0)
        return entry


class FakeSnippet:
    """One caption line, shaped like youtube-transcript-api's own snippet."""

    def __init__(self, text, start):
        self.text = text
        self.start = start
        self.duration = 3.0


class FakeFetchedTranscript:
    """
    Stand-in for the library's FetchedTranscript: the attributes this
    project reads, and nothing else.
    """

    def __init__(self, snippets, language_code="en"):
        self.snippets = snippets
        self.language_code = language_code


class FakeReader:
    """
    Stand-in for YouTubeTranscriptApi. `tracks` maps a video id to its
    caption lines; `errors` maps one to an exception to raise instead.
    Every call is recorded, so a test can assert a build fetched nothing.
    """

    def __init__(self, tracks=None, errors=None):
        self.tracks = tracks or {}
        self.errors = errors or {}
        self.calls = []

    def fetch(self, video_id, languages=("en",), preserve_formatting=False):
        self.calls.append({"video_id": video_id, "languages": tuple(languages)})
        if video_id in self.errors:
            raise self.errors[video_id]
        if video_id not in self.tracks:
            raise KeyError(video_id)
        return FakeFetchedTranscript(self.tracks[video_id])


def caption_lines(phrase_count=20, start=0.0, step=5.0):
    """
    A synthetic caption track long enough to become several stretches.

    Each phrase is padded so that phrase_count of them run past the
    grouping target, which is what makes a test of the stretch boundaries
    meaningful rather than accidental.
    """
    return [
        FakeSnippet(
            f"phrase {index} of a synthetic talk about measuring mood with a phone",
            start + index * step,
        )
        for index in range(phrase_count)
    ]


def options(**overrides):
    """The validated options of a youtube source entry, as the configuration produces them."""
    settings = {
        "channel_id": None,
        "playlist_ids": (),
        "video_ids": (),
        "languages": ("en",),
    }
    settings.update(overrides)
    return settings


def source(reader=None, **overrides):
    """A YouTubeSource wired to a fake caption reader."""
    built = YouTubeSource(options(**overrides))
    built.reader = reader if reader is not None else FakeReader()
    return built


def playlist_page(video_ids, next_token=None):
    """One page of a playlistItems response."""
    body = {"items": [{"contentDetails": {"videoId": v}} for v in video_ids]}
    if next_token:
        body["nextPageToken"] = next_token
    return FakeResponse(body=body)


def videos_page(titles):
    """A videos.list response naming each video."""
    return FakeResponse(body={
        "items": [
            {"id": video_id, "snippet": {"title": title, "publishedAt": "2026-01-02T03:04:05Z"}}
            for video_id, title in titles.items()
        ]
    })


### Timestamps ###

@pytest.mark.parametrize("seconds, expected", [
    (0, "0:00"),
    (5, "0:05"),
    (65, "1:05"),
    (134, "2:14"),
    (599, "9:59"),
    (600, "10:00"),
    (3599, "59:59"),
    (3600, "1:00:00"),
    (3725, "1:02:05"),
    (7384, "2:03:04"),
])
def test_a_timestamp_reads_like_the_clock_under_the_player(seconds, expected):
    assert youtube_source.timestamp(seconds) == expected


def test_a_timestamp_rounds_down_to_the_whole_second():
    assert youtube_source.timestamp(134.9) == "2:14"


def test_a_negative_offset_reads_as_the_start():
    """Never seen from a caption track, but an offset reaches a URL, so it is clamped."""
    assert youtube_source.timestamp(-30) == "0:00"


### Deep Links ###

def test_a_watch_address_carries_the_moment_in_whole_seconds():
    assert yc.watch_url(VIDEO_A, 134.7) == f"https://www.youtube.com/watch?v={VIDEO_A}&t=134s"


def test_a_watch_address_without_a_moment_is_the_plain_address():
    assert yc.watch_url(VIDEO_A) == f"https://www.youtube.com/watch?v={VIDEO_A}"
    assert yc.watch_url(VIDEO_A, 0) == f"https://www.youtube.com/watch?v={VIDEO_A}"


@pytest.mark.parametrize("bad", [
    "../../etc/passwd",
    "short",
    "waytoolongforavideoid",
    "has space11",
    "",
    None,
    12345678901,
])
def test_a_video_id_that_is_not_one_is_refused(bad):
    """
    The identifier reaches a request URL and a cache file name, so it is
    matched rather than trusted however it arrived.
    """
    with pytest.raises(yc.YouTubeError):
        yc.checked_video_id(bad)


def test_an_uploads_playlist_is_derived_from_the_channel():
    assert yc.uploads_playlist_id(CHANNEL) == UPLOADS


@pytest.mark.parametrize("bad", ["@handle", "UCshort", "PLaaaaaaaaaaaaaaaaaaaa", "", None])
def test_a_channel_id_that_is_not_one_is_refused_rather_than_guessed_at(bad):
    with pytest.raises(yc.YouTubeError, match="channel id"):
        yc.uploads_playlist_id(bad)


def test_the_refusal_tells_a_reader_a_handle_is_not_a_channel_id():
    with pytest.raises(yc.YouTubeError, match="handle"):
        yc.uploads_playlist_id("@examplechannel")


### Caption Text ###

@pytest.mark.parametrize("raw, expected", [
    ("[Music]", ""),
    ("(applause)", ""),
    ("[MUSIC] hello there", "hello there"),
    ("hello   there", "hello there"),
    ("hello\nthere", "hello there"),
    ("  padded  ", "padded"),
    ("", ""),
    (None, ""),
    ("we measured [inaudible] mood", "we measured mood"),
])
def test_a_caption_line_is_cleaned_of_sound_markers_and_stray_space(raw, expected):
    assert youtube_source.clean_line(raw) == expected


### Grouping Into Stretches ###

def test_captions_are_grouped_into_stretches_that_stay_under_the_target():
    stretches = youtube_source.segments(
        [{"text": line.text, "start": line.start} for line in caption_lines(40)]
    )

    assert len(stretches) > 1
    for stretch in stretches:
        assert len(stretch["text"]) <= youtube_source.SEGMENT_TARGET_CHARS


def test_each_stretch_keeps_the_start_time_of_its_first_line():
    lines = [
        {"text": "first phrase", "start": 0.0},
        {"text": "second phrase", "start": 7.5},
    ]

    # min_chars=0 so the tail-folding rule, tested separately below,
    # does not merge these two back into one.
    stretches = youtube_source.segments(lines, target_chars=20, min_chars=0)

    assert [s["start"] for s in stretches] == [0.0, 7.5]


def test_every_line_of_a_transcript_lands_in_exactly_one_stretch():
    """The stretches are the transcript: nothing dropped, nothing counted twice."""
    lines = [{"text": f"phrase {i}", "start": float(i)} for i in range(30)]

    stretches = youtube_source.segments(lines, target_chars=40)

    joined = " ".join(stretch["text"] for stretch in stretches)
    assert joined.split() == " ".join(line["text"] for line in lines).split()
    assert len(stretches) > 1


def test_a_short_tail_joins_the_stretch_before_it():
    """
    A fragment left at the end of a video would be dropped by the
    chunker's own minimum, so it is folded in rather than lost.
    """
    lines = [{"text": "a" * 300, "start": 0.0}, {"text": "tail", "start": 400.0}]

    stretches = youtube_source.segments(lines, target_chars=310, min_chars=100)

    assert len(stretches) == 1
    assert stretches[0]["text"].endswith("tail")


def test_a_short_transcript_is_still_one_stretch():
    stretches = youtube_source.segments([{"text": "just a few words", "start": 0.0}])

    assert len(stretches) == 1
    assert stretches[0]["text"] == "just a few words"


def test_a_transcript_of_nothing_but_markers_yields_no_stretches():
    assert youtube_source.segments([{"text": "[Music]", "start": 0.0}]) == []


def test_no_captions_at_all_yields_no_stretches():
    assert youtube_source.segments([]) == []


### The Data API Client ###

def test_a_playlist_is_read_page_by_page():
    session = FakeYouTubeSession({"playlistItems": [
        playlist_page([VIDEO_A], next_token="PAGE2"),
        playlist_page([VIDEO_B]),
    ]})
    client = yc.YouTubeClient(session, key=FAKE_KEY)

    assert client.playlist_video_ids(PLAYLIST) == (VIDEO_A, VIDEO_B)
    assert session.calls[1]["params"]["pageToken"] == "PAGE2"


def test_a_playlist_entry_naming_no_readable_video_is_skipped():
    """A deleted or private entry keeps its place in a playlist and names nothing."""
    session = FakeYouTubeSession({"playlistItems": FakeResponse(body={"items": [
        {"contentDetails": {"videoId": VIDEO_A}},
        {"contentDetails": {}},
        {"contentDetails": {"videoId": None}},
        {"snippet": {"title": "no contentDetails at all"}},
        "not even a record",
    ]})})

    assert yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST) == (VIDEO_A,)


def test_a_playlist_entry_whose_video_id_is_not_one_is_skipped():
    """
    The identifier comes out of a response and reaches a file path, so a
    response that tried to steer it somewhere is ignored rather than used.
    """
    session = FakeYouTubeSession({"playlistItems": FakeResponse(body={"items": [
        {"contentDetails": {"videoId": "../../../etc/passwd"}},
        {"contentDetails": {"videoId": VIDEO_A}},
    ]})})

    assert yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST) == (VIDEO_A,)


def test_a_video_listed_twice_is_read_once():
    session = FakeYouTubeSession({"playlistItems": playlist_page([VIDEO_A, VIDEO_A, VIDEO_B])})

    assert yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST) == (VIDEO_A, VIDEO_B)


def test_a_listing_stops_at_the_ceiling(monkeypatch):
    monkeypatch.setattr(yc, "MAX_VIDEOS", 1)
    session = FakeYouTubeSession({"playlistItems": playlist_page([VIDEO_A, VIDEO_B])})

    assert yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST) == (VIDEO_A,)


def test_a_listing_that_never_ends_stops_at_the_page_ceiling(monkeypatch):
    """A nextPageToken on every page must not run a build forever."""
    monkeypatch.setattr(yc, "MAX_PAGES", 3)
    session = FakeYouTubeSession({"playlistItems": playlist_page([VIDEO_A], next_token="ALWAYS")})

    client = yc.YouTubeClient(session, key=FAKE_KEY)
    client.playlist_video_ids(PLAYLIST)

    assert client.request_count == 3


def test_listing_without_a_key_says_which_variable_to_set():
    client = yc.YouTubeClient(FakeYouTubeSession(), key=None)

    with pytest.raises(yc.YouTubeNoApiKey, match="YOUTUBE_API_KEY"):
        client.playlist_video_ids(PLAYLIST)


def test_listing_without_a_key_makes_no_request():
    session = FakeYouTubeSession()

    with pytest.raises(yc.YouTubeNoApiKey):
        yc.YouTubeClient(session, key=None).playlist_video_ids(PLAYLIST)

    assert session.calls == []


def test_a_playlist_that_does_not_exist_is_reported_as_missing():
    session = FakeYouTubeSession({"playlistItems": FakeResponse(status_code=404, body={})})

    with pytest.raises(yc.YouTubeNotFound):
        yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST)


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_key_names_the_variable_and_the_api_to_enable(status):
    session = FakeYouTubeSession({"playlistItems": FakeResponse(status_code=status, body={})})

    with pytest.raises(yc.YouTubeUnavailable, match="YOUTUBE_API_KEY"):
        yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST)


def test_a_server_error_is_reported_as_unavailable():
    session = FakeYouTubeSession({"playlistItems": FakeResponse(status_code=500, body={})})

    with pytest.raises(yc.YouTubeUnavailable, match="500"):
        yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST)


def test_an_answer_that_is_not_data_is_reported_as_unavailable():
    session = FakeYouTubeSession({"playlistItems": FakeResponse(body=None, text="<html>no</html>")})

    with pytest.raises(yc.YouTubeUnavailable, match="other than data"):
        yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST)


def test_an_answer_that_is_a_list_rather_than_a_record_is_reported():
    session = FakeYouTubeSession({"playlistItems": FakeResponse(body=[1, 2, 3])})

    with pytest.raises(yc.YouTubeUnavailable, match="rather than"):
        yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST)


### The Key Is A Credential ###

def test_the_key_travels_as_a_parameter_and_not_in_a_header():
    session = FakeYouTubeSession({"playlistItems": playlist_page([VIDEO_A])})

    yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST)

    assert session.calls[0]["params"]["key"] == FAKE_KEY
    assert FAKE_KEY not in json.dumps(session.calls[0]["headers"])


def test_an_unreachable_host_is_reported_without_quoting_the_key():
    """
    A requests exception carries the whole request URL, and the key is in
    it. Quoting the exception would put a credential in a build log.
    """
    session = FakeYouTubeSession({"playlistItems": playlist_page([VIDEO_A])},
                                 raise_for={"playlistItems"})

    with pytest.raises(yc.YouTubeUnavailable) as caught:
        yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST)

    assert FAKE_KEY not in str(caught.value)
    assert "could not be reached" in str(caught.value)


def test_no_failure_message_from_the_client_quotes_the_key():
    """Every classified answer, checked in one place so a new branch cannot forget."""
    for response in (
        FakeResponse(status_code=404, body={}),
        FakeResponse(status_code=403, body={}),
        FakeResponse(status_code=500, body={}),
        FakeResponse(body=None, text="<html>"),
        FakeResponse(body=[1]),
    ):
        session = FakeYouTubeSession({"playlistItems": response})
        with pytest.raises(yc.YouTubeError) as caught:
            yc.YouTubeClient(session, key=FAKE_KEY).playlist_video_ids(PLAYLIST)
        assert FAKE_KEY not in str(caught.value)


def test_the_key_is_read_from_the_environment_and_never_from_options():
    assert yc.api_key({"YOUTUBE_API_KEY": " abc "}) == "abc"
    assert yc.api_key({"YOUTUBE_API_KEY": "   "}) is None
    assert yc.api_key({}) is None


### Naming Videos ###

def test_video_titles_are_read_in_one_batch():
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "First Talk", VIDEO_B: "Second Talk"})})

    details = yc.YouTubeClient(session, key=FAKE_KEY).video_details([VIDEO_A, VIDEO_B])

    assert details[VIDEO_A]["title"] == "First Talk"
    assert details[VIDEO_B]["published_at"] == "2026-01-02T03:04:05Z"
    assert len(session.calls) == 1
    assert session.calls[0]["params"]["id"] == f"{VIDEO_A},{VIDEO_B}"


def test_video_titles_are_batched_to_the_limit(monkeypatch):
    monkeypatch.setattr(yc, "DETAILS_BATCH", 1)
    session = FakeYouTubeSession({"videos": [
        videos_page({VIDEO_A: "First Talk"}),
        videos_page({VIDEO_B: "Second Talk"}),
    ]})

    details = yc.YouTubeClient(session, key=FAKE_KEY).video_details([VIDEO_A, VIDEO_B])

    assert set(details) == {VIDEO_A, VIDEO_B}


def test_a_video_the_api_will_not_describe_is_simply_absent():
    """One unreadable video must not end a build over a whole channel."""
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "First Talk"})})

    details = yc.YouTubeClient(session, key=FAKE_KEY).video_details([VIDEO_A, VIDEO_B])

    assert set(details) == {VIDEO_A}


def test_a_title_is_read_without_a_key_through_the_public_endpoint():
    session = FakeYouTubeSession({"oembed": FakeResponse(body={"title": "A Public Talk"})})

    details = yc.YouTubeClient(session, key=None).public_video_details([VIDEO_A])

    assert details[VIDEO_A] == {"title": "A Public Talk", "published_at": ""}
    assert session.calls[0]["params"]["url"] == yc.watch_url(VIDEO_A)


def test_a_video_the_public_endpoint_will_not_describe_is_simply_absent():
    session = FakeYouTubeSession({"oembed": FakeResponse(status_code=401, body={})})

    assert yc.YouTubeClient(session, key=None).public_video_details([VIDEO_A]) == {}


### Fetching Captions ###

def test_a_fetched_transcript_becomes_timed_lines():
    reader = FakeReader({VIDEO_A: [FakeSnippet("hello", 0.0), FakeSnippet("there", 4.5)]})

    language, lines = yc.fetch_transcript(VIDEO_A, reader=reader)

    assert language == "en"
    assert lines == ({"text": "hello", "start": 0.0}, {"text": "there", "start": 4.5})


def test_lines_are_put_in_time_order():
    reader = FakeReader({VIDEO_A: [FakeSnippet("second", 9.0), FakeSnippet("first", 1.0)]})

    _, lines = yc.fetch_transcript(VIDEO_A, reader=reader)

    assert [line["start"] for line in lines] == [1.0, 9.0]


def test_the_plain_list_an_older_release_returned_is_read_too():
    """A caller is not tied to one version of the caption package."""
    language, lines = yc.transcript_lines([{"text": "hello", "start": 0.0}])

    assert language == ""
    assert lines == ({"text": "hello", "start": 0.0},)


def test_the_languages_asked_for_are_passed_through():
    reader = FakeReader({VIDEO_A: [FakeSnippet("bonjour", 0.0)]})

    yc.fetch_transcript(VIDEO_A, languages=("fr", "en"), reader=reader)

    assert reader.calls[0]["languages"] == ("fr", "en")


def test_a_block_on_where_the_request_came_from_says_what_to_do(caption_library):
    reader = FakeReader(errors={VIDEO_A: caption_library.RequestBlocked(VIDEO_A)})

    with pytest.raises(yc.YouTubeBlocked, match="commit the cache"):
        yc.fetch_transcript(VIDEO_A, reader=reader)


def test_captions_turned_off_are_reported_as_unavailable_rather_than_broken(caption_library):
    reader = FakeReader(errors={VIDEO_A: caption_library.TranscriptsDisabled(VIDEO_A)})

    with pytest.raises(yc.TranscriptUnavailable):
        yc.fetch_transcript(VIDEO_A, reader=reader)


def test_a_video_that_is_gone_is_reported_as_missing(caption_library):
    reader = FakeReader(errors={VIDEO_A: caption_library.VideoUnavailable(VIDEO_A)})

    with pytest.raises(yc.YouTubeNotFound):
        yc.fetch_transcript(VIDEO_A, reader=reader)


def test_a_network_failure_fetching_captions_is_reported_as_unavailable():
    reader = FakeReader(errors={VIDEO_A: requests.ConnectionError("down")})

    with pytest.raises(yc.YouTubeUnavailable):
        yc.fetch_transcript(VIDEO_A, reader=reader)


def test_a_callers_own_reader_works_with_the_library_absent(monkeypatch):
    """
    The handlers for the library's exception classes have to stay valid
    `except` clauses when those classes cannot be imported, or every
    fetch through a caller's own reader fails with a TypeError from the
    handler rather than reporting what actually went wrong.
    """
    monkeypatch.setitem(__import__("sys").modules, "youtube_transcript_api", None)
    reader = FakeReader({VIDEO_A: [FakeSnippet("hello", 0.0)]})

    language, lines = yc.fetch_transcript(VIDEO_A, reader=reader)

    assert lines == ({"text": "hello", "start": 0.0},)
    assert language == "en"


def test_a_network_failure_is_still_classified_with_the_library_absent(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "youtube_transcript_api", None)
    reader = FakeReader(errors={VIDEO_A: requests.ConnectionError("down")})

    with pytest.raises(yc.YouTubeUnavailable):
        yc.fetch_transcript(VIDEO_A, reader=reader)


def test_the_caption_library_is_only_needed_when_a_transcript_is_fetched(monkeypatch):
    """
    A build that reads only stored transcripts must work with the package
    absent, which is the normal case on a hosted runner.
    """
    monkeypatch.setitem(__import__("sys").modules, "youtube_transcript_api", None)

    with pytest.raises(yc.TranscriptLibraryMissing, match=r"extractium\[youtube\]"):
        yc.transcript_reader()


### The Store ###

def test_a_transcript_is_stored_and_read_back():
    cache_module.save_video(VIDEO_A, "A Talk", "2026-01-02T03:04:05Z", "en",
                            [{"text": "hello", "start": 0.0}])

    stored = cache_module.load_video(VIDEO_A)

    assert stored["title"] == "A Talk"
    assert stored["segments"] == [{"text": "hello", "start": 0.0}]


def test_nothing_stored_reads_as_nothing():
    assert cache_module.load_video(VIDEO_A) is None


def test_an_unreadable_stored_transcript_degrades_to_nothing_rather_than_failing():
    path = cache_module.video_path(VIDEO_A)
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ not json")

    assert cache_module.load_video(VIDEO_A) is None


def test_a_stored_record_without_segments_reads_as_nothing():
    path = cache_module.video_path(VIDEO_A)
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"title": "A Talk"}, f)

    assert cache_module.load_video(VIDEO_A) is None


def test_a_listing_is_stored_and_read_back():
    cache_module.save_listing(PLAYLIST, [VIDEO_A, VIDEO_B])

    assert cache_module.load_listing(PLAYLIST) == (VIDEO_A, VIDEO_B)


@pytest.mark.parametrize("bad", ["../../etc/passwd", "short", "", None])
def test_a_store_path_refuses_an_identifier_that_is_not_a_video_id(bad):
    with pytest.raises(ValueError):
        cache_module.video_path(bad)


@pytest.mark.parametrize("bad", ["../outside", "a/b", "", None, "x" * 65])
def test_a_listing_path_refuses_an_identifier_that_could_leave_the_cache(bad):
    with pytest.raises(ValueError):
        cache_module.listing_path(bad)


def test_a_store_path_stays_inside_the_cache_folder():
    import os
    path = os.path.abspath(cache_module.video_path(VIDEO_A))
    root = os.path.abspath(cache_module.CACHE_YOUTUBE_VIDEOS_DIR)

    assert path.startswith(root + os.sep)


### The Source, End To End ###

def test_the_source_satisfies_the_source_protocol():
    assert isinstance(source(video_ids=(VIDEO_A,)), Source)
    assert YouTubeSource.name == "youtube"


def test_a_video_becomes_one_document_per_stretch_addressed_at_its_moment(api_key_set):
    reader = FakeReader({VIDEO_A: caption_lines(40)})
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "A Talk"})})
    built = source(reader=reader, video_ids=(VIDEO_A,))

    documents = list(built.fetch(session, {}, quiet))

    assert len(documents) > 1
    # The opening stretch begins at zero, so its address is the video's
    # own: a link to the start needs no moment on it.
    assert documents[0].url == f"https://www.youtube.com/watch?v={VIDEO_A}"
    assert documents[0].title == "A Talk -- 0:00"
    assert documents[1].url.endswith("s")
    assert "&t=" in documents[1].url
    for document in documents:
        assert document.source_type == "youtube"
        assert document.content_type == "video_transcript"
        assert f"watch?v={VIDEO_A}" in document.url


def test_every_stretch_after_the_first_carries_its_own_moment(api_key_set):
    reader = FakeReader({VIDEO_A: caption_lines(40)})
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "A Talk"})})

    documents = list(source(reader=reader, video_ids=(VIDEO_A,)).fetch(session, {}, quiet))

    addresses = [document.url for document in documents]
    assert len(set(addresses)) == len(addresses)
    for document in documents[1:]:
        assert "&t=" in document.url


def test_a_heading_carries_the_video_name_and_the_moment(api_key_set):
    reader = FakeReader({VIDEO_A: caption_lines(40)})
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "A Talk"})})

    documents = list(source(reader=reader, video_ids=(VIDEO_A,)).fetch(session, {}, quiet))

    for document in documents:
        page, separator, moment = document.title.partition(" -- ")
        assert page == "A Talk"
        assert separator
        assert ":" in moment


def test_a_fetched_transcript_is_stored_for_the_next_build(api_key_set):
    reader = FakeReader({VIDEO_A: caption_lines(6)})
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "A Talk"})})

    list(source(reader=reader, video_ids=(VIDEO_A,)).fetch(session, {}, quiet))

    stored = cache_module.load_video(VIDEO_A)
    assert stored["title"] == "A Talk"
    assert stored["segments"]


def test_a_second_build_reads_the_store_and_fetches_nothing(api_key_set):
    """
    This is the promise a scheduled build depends on: YouTube blocks
    hosted runners, so the second build must need no caption request and
    no API request at all.
    """
    first_reader = FakeReader({VIDEO_A: caption_lines(6)})
    list(source(reader=first_reader, video_ids=(VIDEO_A,)).fetch(
        FakeYouTubeSession({"videos": videos_page({VIDEO_A: "A Talk"})}), {}, quiet))

    second_reader = FakeReader()
    second_session = FakeYouTubeSession()
    documents = list(source(reader=second_reader, video_ids=(VIDEO_A,)).fetch(
        second_session, {}, quiet))

    assert documents
    assert second_reader.calls == []
    assert second_session.calls == []


def test_the_stored_build_produces_the_same_documents_as_the_first(api_key_set):
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "A Talk"})})
    first = list(source(reader=FakeReader({VIDEO_A: caption_lines(20)}),
                        video_ids=(VIDEO_A,)).fetch(session, {}, quiet))

    second = list(source(reader=FakeReader(), video_ids=(VIDEO_A,)).fetch(
        FakeYouTubeSession(), {}, quiet))

    assert [(d.url, d.title, d.content) for d in first] == \
           [(d.url, d.title, d.content) for d in second]


def test_a_playlist_is_listed_and_every_video_read(api_key_set):
    reader = FakeReader({VIDEO_A: caption_lines(6), VIDEO_B: caption_lines(6)})
    session = FakeYouTubeSession({
        "playlistItems": playlist_page([VIDEO_A, VIDEO_B]),
        "videos": videos_page({VIDEO_A: "First Talk", VIDEO_B: "Second Talk"}),
    })

    documents = list(source(reader=reader, playlist_ids=(PLAYLIST,)).fetch(session, {}, quiet))

    titles = {document.title.split(" -- ")[0] for document in documents}
    assert titles == {"First Talk", "Second Talk"}


def test_a_channel_is_read_through_its_uploads_playlist(api_key_set):
    reader = FakeReader({VIDEO_A: caption_lines(6)})
    session = FakeYouTubeSession({
        "playlistItems": playlist_page([VIDEO_A]),
        "videos": videos_page({VIDEO_A: "A Talk"}),
    })

    list(source(reader=reader, channel_id=CHANNEL).fetch(session, {}, quiet))

    assert session.calls[0]["params"]["playlistId"] == UPLOADS


def test_a_listing_is_stored_so_a_later_build_indexes_the_same_videos(api_key_set):
    session = FakeYouTubeSession({
        "playlistItems": playlist_page([VIDEO_A]),
        "videos": videos_page({VIDEO_A: "A Talk"}),
    })

    list(source(reader=FakeReader({VIDEO_A: caption_lines(6)}),
                playlist_ids=(PLAYLIST,)).fetch(session, {}, quiet))

    assert cache_module.load_listing(PLAYLIST) == (VIDEO_A,)


def test_a_build_with_no_key_falls_back_to_the_stored_listing():
    """The listing was read on an operator's machine; a runner reuses it."""
    cache_module.save_listing(PLAYLIST, [VIDEO_A])
    cache_module.save_video(VIDEO_A, "A Talk", "", "en",
                            [{"text": "a stored phrase about measuring mood", "start": 0.0}])
    lines = []

    documents = list(source(playlist_ids=(PLAYLIST,)).fetch(
        FakeYouTubeSession(), {}, lines.append))

    assert [document.title for document in documents] == ["A Talk -- 0:00"]
    assert any("stored" in line for line in lines)


def test_a_listing_that_cannot_be_read_with_nothing_stored_ends_the_build():
    """Indexing nothing looks exactly like a channel that went empty, so it is refused."""
    built = source(playlist_ids=(PLAYLIST,))

    with pytest.raises(YouTubeSourceError, match="commit the cache folder"):
        list(built.fetch(FakeYouTubeSession(), {}, quiet))


def test_a_blocked_caption_request_with_nothing_stored_ends_the_build(api_key_set, caption_library):
    """The hosted-runner case: say what happened rather than index an empty video."""
    reader = FakeReader(errors={VIDEO_A: caption_library.RequestBlocked(VIDEO_A)})
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "A Talk"})})

    with pytest.raises(YouTubeSourceError, match="cloud-provider"):
        list(source(reader=reader, video_ids=(VIDEO_A,)).fetch(session, {}, quiet))


def test_a_video_without_captions_is_skipped_and_the_build_carries_on(api_key_set, caption_library):
    reader = FakeReader(
        tracks={VIDEO_B: caption_lines(6)},
        errors={VIDEO_A: caption_library.TranscriptsDisabled(VIDEO_A)},
    )
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "Silent", VIDEO_B: "Spoken"})})
    built = source(reader=reader, video_ids=(VIDEO_A, VIDEO_B))

    documents = list(built.fetch(session, {}, quiet))

    assert {document.title.split(" -- ")[0] for document in documents} == {"Spoken"}
    assert built.without_captions == (VIDEO_A,)


def test_explicit_videos_need_no_key_and_are_named_publicly():
    reader = FakeReader({VIDEO_A: caption_lines(6)})
    session = FakeYouTubeSession({"oembed": FakeResponse(body={"title": "A Public Talk"})})

    documents = list(source(reader=reader, video_ids=(VIDEO_A,)).fetch(session, {}, quiet))

    assert documents[0].title.startswith("A Public Talk -- ")
    assert session.calls[0]["resource"] == "oembed"


def test_a_video_that_cannot_be_named_is_still_indexed_under_its_id():
    """A missing title costs a readable heading, not the citation or the text."""
    reader = FakeReader({VIDEO_A: caption_lines(6)})
    session = FakeYouTubeSession({"oembed": FakeResponse(status_code=500, body={})})

    documents = list(source(reader=reader, video_ids=(VIDEO_A,)).fetch(session, {}, quiet))

    assert documents[0].title.startswith(f"{VIDEO_A} -- ")


def test_a_malformed_video_id_in_the_configuration_is_refused_by_name():
    built = source(video_ids=("not-a-video-id-at-all",))

    with pytest.raises(YouTubeSourceError, match="video_ids"):
        list(built.fetch(FakeYouTubeSession(), {}, quiet))


def test_a_malformed_channel_id_in_the_configuration_is_refused_by_name():
    built = source(channel_id="@examplechannel")

    with pytest.raises(YouTubeSourceError, match="channel_id"):
        list(built.fetch(FakeYouTubeSession(), {}, quiet))


def test_a_source_asked_for_nothing_reads_nothing():
    lines = []

    assert list(source().fetch(FakeYouTubeSession(), {}, lines.append)) == []
    assert any("nothing to read" in line for line in lines)


def test_a_video_named_twice_is_read_once(api_key_set):
    reader = FakeReader({VIDEO_A: caption_lines(6)})
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "A Talk"})})
    built = source(reader=reader, video_ids=(VIDEO_A, VIDEO_A))

    list(built.fetch(session, {}, quiet))

    assert len(reader.calls) == 1


### Reporting ###

def test_the_report_says_where_each_transcript_came_from(api_key_set):
    reader = FakeReader({VIDEO_A: caption_lines(6)})
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "A Talk"})})
    built = source(reader=reader, video_ids=(VIDEO_A,))

    list(built.fetch(session, {}, quiet))

    report = "\n".join(built.summary_lines())
    assert "A Talk" in report
    assert "fetched" in report
    assert "1 video(s): 0 from the cache, 1 fetched" in report


def test_the_report_distinguishes_a_stored_transcript_from_a_fetched_one():
    cache_module.save_video(VIDEO_A, "A Talk", "", "en",
                            [{"text": "a stored phrase about measuring mood", "start": 0.0}])
    built = source(video_ids=(VIDEO_A,))

    list(built.fetch(FakeYouTubeSession(), {}, quiet))

    assert "1 from the cache, 0 fetched" in "\n".join(built.summary_lines())


def test_a_source_that_read_nothing_reports_nothing():
    assert source().summary_lines() == []


### A Video In The Outputs ###

def video_compendium(embedder, videos=((VIDEO_A, "A Talk"),)):
    """
    A compendium built from the documents this source produces.

    Built through the real pipeline rather than assembled by hand, so
    what the outputs are asked about is what a build would actually hand
    them.
    """
    from extractium.core import build
    from tests.test_adapter_container import FIXED_BUILT_AT

    documents = []
    for video_id, title in videos:
        # Each video says different things. Identical transcripts would be
        # collapsed as near-duplicates, which is correct behaviour and
        # would hide whatever the test meant to check.
        lines = [
            {
                "text": f"{title} phrase {index} on measuring mood with a phone every day",
                "start": float(index * 5),
            }
            for index in range(40)
        ]
        for stretch in youtube_source.segments(lines):
            documents.append(
                YouTubeSource(options())._document(video_id, title, stretch)
            )
    return build.build_compendium(
        documents, name="Video Library", embedder=embedder, built_at=FIXED_BUILT_AT
    )


def _moment_seconds(heading):
    """A "m:ss" or "h:mm:ss" heading back as a number, for order checks."""
    parts = [int(part) for part in heading.split(":")]
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def test_a_video_becomes_several_sections_in_the_index(fake_embed_chunks_core):
    """The premise of the two tests below: there is more than one section to group."""
    compendium = video_compendium(fake_embed_chunks_core)

    assert len(compendium.parents) > 1


def test_the_index_file_names_a_video_once_however_many_sections_it_has(
    fake_embed_chunks_core,
):
    """
    A forty-minute talk is one page a reader can open, not one page every
    couple of minutes, so the page list names the video and not each
    moment in it.
    """
    from extractium.adapters import llmstxt

    compendium = video_compendium(fake_embed_chunks_core)

    pages = llmstxt.pages_in_order(compendium.parents)

    assert len(pages) == 1
    assert pages[0]["url"] == f"https://www.youtube.com/watch?v={VIDEO_A}"
    assert pages[0]["title"] == "A Talk"


def test_the_index_file_still_tells_two_videos_apart(fake_embed_chunks_core):
    from extractium.adapters import llmstxt

    compendium = video_compendium(
        fake_embed_chunks_core, videos=((VIDEO_A, "First Talk"), (VIDEO_B, "Second Talk")),
    )

    pages = llmstxt.pages_in_order(compendium.parents)

    assert [page["title"] for page in pages] == ["First Talk", "Second Talk"]


def test_a_knowledge_folder_writes_one_file_per_video_with_its_sections_in_order(
    fake_embed_chunks_core,
):
    from extractium.adapters import okf

    compendium = video_compendium(fake_embed_chunks_core)

    pages = okf.pages_with_sections(compendium.parents)

    assert len(pages) == 1
    assert len(pages[0]["sections"]) > 1
    headings = [heading for heading, _ in pages[0]["sections"]]
    assert headings[0] == "0:00"
    # The sections read in the order the words were said, so somebody
    # reading the file by hand follows the talk.
    moments = [_moment_seconds(heading) for heading in headings]
    assert moments == sorted(moments)


def test_the_sections_of_one_video_keep_the_moment_as_their_heading(
    fake_embed_chunks_core,
):
    from extractium.adapters import okf

    compendium = video_compendium(fake_embed_chunks_core)

    pages = okf.pages_with_sections(compendium.parents)

    for heading, _ in pages[0]["sections"]:
        assert ":" in heading


def test_grouping_by_page_leaves_every_other_source_untouched(fixtures_dir, fake_embed_chunks_core):
    """
    The rule that gathers a video's moments applies to videos only. A
    query string anywhere else is part of the address.
    """
    from extractium.adapters.base import page_address
    from extractium.core.models import Parent

    web = Parent(
        id="a" * 16, t="Guide -- Steps", x="x" * 70, u="https://example.org/g?t=9&page=2",
        host="example.org", source_type="web", content_type="page",
    )

    assert page_address(web) == "https://example.org/g?t=9&page=2"
