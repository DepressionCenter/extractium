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
from extractium.sources import youtube_pages as yp
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


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    """
    Stops the politeness delay from actually sleeping.

    The source paces every request to YouTube by at least a second,
    which is right for a build and absurd for a test suite. The tests
    that care about pacing patch this themselves and assert on what was
    asked for.
    """
    for module in (youtube_source, yp, yc):
        monkeypatch.setattr(module.time, "sleep", lambda seconds: None)


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
        return self._answer("get", url, headers, params, timeout)

    def post(self, url, headers=None, params=None, json=None, timeout=None):
        return self._answer("post", url, headers, params, timeout, body=json)

    def _answer(self, method, url, headers, params, timeout, body=None):
        resource = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        self.calls.append({
            "method": method,
            "url": url,
            "resource": resource,
            "headers": dict(headers or {}),
            "params": dict(params or {}),
            "body": body,
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
    session = FakeYouTubeSession({"oembed": FakeResponse(body={
        "title": "A Public Talk",
        "author_url": "https://www.youtube.com/@ExampleChannel",
    })})

    details = yc.YouTubeClient(session, key=None).public_video_details([VIDEO_A])

    assert details[VIDEO_A]["title"] == "A Public Talk"
    assert details[VIDEO_A]["published_at"] == ""
    assert details[VIDEO_A]["author_url"] == "https://www.youtube.com/@ExampleChannel"
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
        "playlists": FakeResponse(body={"items": []}),
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
    """
    The listing was read on an operator's machine; a runner that can
    reach neither the API nor the pages reuses it.
    """
    cache_module.save_listing(PLAYLIST, [VIDEO_A])
    cache_module.save_video(VIDEO_A, "A Talk", "", "en",
                            [{"text": "a stored phrase about measuring mood", "start": 0.0}])
    lines = []
    session = FakeYouTubeSession({"playlist": FakeResponse(status_code=404, body={})})

    documents = list(source(playlist_ids=(PLAYLIST,)).fetch(session, {}, lines.append))

    assert [document.title for document in documents] == ["A Talk -- 0:00"]
    assert any("stored" in line for line in lines)


def test_a_listing_that_cannot_be_read_with_nothing_stored_ends_the_build():
    """Indexing nothing looks exactly like a channel that went empty, so it is refused."""
    built = source(playlist_ids=(PLAYLIST,))
    session = FakeYouTubeSession({"playlist": FakeResponse(status_code=404, body={})})

    with pytest.raises(YouTubeSourceError, match="commit the cache folder"):
        list(built.fetch(session, {}, quiet))


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


def test_a_channel_written_as_someone_elses_address_is_refused_by_name():
    built = source(channel_id="https://vimeo.com/examplechannel")

    with pytest.raises(YouTubeSourceError, match="channel_id"):
        list(built.fetch(FakeYouTubeSession(), {}, quiet))


def test_a_channel_written_as_a_youtube_page_that_is_not_a_channel_is_refused():
    built = source(channel_id="https://www.youtube.com/results?search_query=x")

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


### Naming A Channel Every Way A Browser Shows It ###

@pytest.mark.parametrize("written", [
    CHANNEL,
    f"https://www.youtube.com/channel/{CHANNEL}",
    f"https://www.youtube.com/channel/{CHANNEL}/videos",
    f"http://youtube.com/channel/{CHANNEL}",
    f"https://m.youtube.com/channel/{CHANNEL}/playlists",
])
def test_a_channel_written_as_its_id_needs_no_request(written):
    assert yp.parse_channel_selector(written) == ("id", CHANNEL)


@pytest.mark.parametrize("written, expected", [
    ("@ExampleChannel", "https://www.youtube.com/@ExampleChannel"),
    ("https://www.youtube.com/@ExampleChannel", "https://www.youtube.com/@ExampleChannel"),
    ("https://www.youtube.com/@ExampleChannel/videos", "https://www.youtube.com/@ExampleChannel"),
    ("https://www.youtube.com/@ExampleChannel/playlists", "https://www.youtube.com/@ExampleChannel"),
    ("https://www.youtube.com/examplechannel", "https://www.youtube.com/@examplechannel"),
    ("https://www.youtube.com/c/ExampleChannel", "https://www.youtube.com/@ExampleChannel"),
    ("https://www.youtube.com/user/ExampleChannel", "https://www.youtube.com/@ExampleChannel"),
    ("youtube.com/@ExampleChannel", "https://www.youtube.com/@ExampleChannel"),
    ("ExampleChannel", "https://www.youtube.com/@ExampleChannel"),
])
def test_a_channel_written_any_other_way_becomes_a_page_to_read(written, expected):
    """
    An operator has whichever form the browser showed them. A trailing
    tab is dropped, because the address copied while looking at a
    channel's videos is the address they will paste.
    """
    assert yp.parse_channel_selector(written) == ("page", expected)


@pytest.mark.parametrize("written", [
    "https://vimeo.com/examplechannel",
    "https://example.org/@ExampleChannel",
    "https://www.youtube.com/watch?v=" + VIDEO_A,
    "https://www.youtube.com/results?search_query=depression",
    "https://www.youtube.com/feed/subscriptions",
    "watch",
    "",
    None,
])
def test_something_that_is_not_a_channel_is_refused(written):
    with pytest.raises(yc.YouTubeError):
        yp.parse_channel_selector(written)


@pytest.mark.parametrize("written", [
    VIDEO_A,
    f"https://www.youtube.com/watch?v={VIDEO_A}",
    f"https://www.youtube.com/watch?v={VIDEO_A}&t=90s",
    f"https://youtu.be/{VIDEO_A}",
    f"https://youtu.be/{VIDEO_A}?t=5",
    f"https://www.youtube.com/shorts/{VIDEO_A}",
    f"https://www.youtube.com/live/{VIDEO_A}",
    f"https://www.youtube.com/embed/{VIDEO_A}",
])
def test_a_video_is_read_from_any_address_that_names_one(written):
    assert yp.parse_video_selector(written) == VIDEO_A


@pytest.mark.parametrize("written", [
    "https://example.org/watch?v=" + VIDEO_A,
    "https://www.youtube.com/@ExampleChannel",
    "https://www.youtube.com/playlist?list=" + PLAYLIST,
    "tooshort",
    "far-too-long-to-be-a-video-id",
    "",
])
def test_something_that_is_not_a_video_is_refused(written):
    """
    A bare eleven characters of the base64url alphabet is a video id and
    cannot be told from one, so the values here are wrong in length or in
    shape rather than merely unlikely.
    """
    with pytest.raises(yc.YouTubeError):
        yp.parse_video_selector(written)


def test_a_link_that_is_not_a_video_is_simply_not_one():
    """
    For a link found in crawled content, "not a video" is an ordinary
    answer rather than a mistake worth raising over.
    """
    assert yp.video_id_in("https://example.org/a-page") is None
    assert yp.video_id_in(f"https://youtu.be/{VIDEO_A}") == VIDEO_A


@pytest.mark.parametrize("written, expected", [
    (PLAYLIST, PLAYLIST),
    (f"https://www.youtube.com/playlist?list={PLAYLIST}", PLAYLIST),
    (f"https://www.youtube.com/watch?v={VIDEO_A}&list={PLAYLIST}", PLAYLIST),
])
def test_a_playlist_is_read_from_its_id_or_its_address(written, expected):
    assert yp.parse_playlist_selector(written) == expected


@pytest.mark.parametrize("written", [
    "https://vimeo.com/x?list=PLx",
    "https://www.youtube.com/watch?v=" + VIDEO_A,
    "https://www.youtube.com/@ExampleChannel",
    "",
])
def test_something_that_is_not_a_playlist_is_refused(written):
    """
    As with a video, a bare token is taken to be an id: only an address
    that names no playlist, or one on another host, is refusable.
    """
    with pytest.raises(yc.YouTubeError):
        yp.parse_playlist_selector(written)


### Resolving A Handle Without A Key ###

def channel_page(channel_id=CHANNEL, videos=(), playlists=(), token=None):
    """
    A stand-in for a YouTube page: the canonical link, the parameters the
    page hands out for its own scrolling, and the identifiers on it.
    """
    body = [
        f'<link rel="canonical" href="https://www.youtube.com/channel/{channel_id}">',
        '"INNERTUBE_API_KEY":"EXAMPLE_PAGE_PARAMETER"',
        '"INNERTUBE_CONTEXT_CLIENT_VERSION":"2.20260911.01.00"',
    ]
    body += [f'"videoId":"{v}"' for v in videos]
    body += [f'"playlistId":"{p}"' for p in playlists]
    if token:
        body.append('"continuationCommand":{"token":"' + token + '"}')
    return FakeResponse(text="".join(body), body=None)


def full_page_videos(count=yp.LIKELY_MORE_THRESHOLD):
    """
    Enough synthetic video ids to look like a full first page.

    A listing shorter than LIKELY_MORE_THRESHOLD is treated as complete,
    because a YouTube page carries continuation tokens for shelves that
    have nothing to do with the listing. A test about paging therefore
    has to return a full page, or there is nothing to page.
    """
    return tuple(f"VID{index:08d}" for index in range(count))


def test_a_handle_resolves_to_a_channel_id_in_one_request():
    session = FakeYouTubeSession({"@ExampleChannel": channel_page()})
    pages = yp.YouTubePages(session)

    resolved = pages.resolve_channel(("page", "https://www.youtube.com/@ExampleChannel"))

    assert resolved == CHANNEL
    assert pages.request_count == 1


def test_a_resolved_channel_id_is_stored_so_a_later_build_asks_nothing():
    cache_module.save_channel_id("https://www.youtube.com/@ExampleChannel", CHANNEL)

    assert cache_module.load_channel_id("https://www.youtube.com/@ExampleChannel") == CHANNEL


def test_a_stored_channel_id_is_keyed_by_the_address_and_not_by_its_text():
    """
    A handle is somebody else's text and can hold characters no file
    system accepts, so the address is hashed rather than used as a name.
    """
    path = cache_module.channel_id_path("https://www.youtube.com/@a/../../b")

    assert ".." not in path
    assert path.endswith(".json")


def test_a_page_naming_no_channel_says_the_handle_may_be_wrong():
    session = FakeYouTubeSession({"@Missing": FakeResponse(text="<html>nothing</html>", body=None)})

    with pytest.raises(yc.YouTubeError, match="names no channel id"):
        yp.YouTubePages(session).resolve_channel(("page", "https://www.youtube.com/@Missing"))


def test_the_page_reader_refuses_an_address_off_youtube():
    """
    A canonical link and a configured address both arrive as somebody
    else's text, so neither may send a build's requests off the host.
    """
    session = FakeYouTubeSession({})

    with pytest.raises(yc.YouTubeError, match="refusing to request"):
        yp.YouTubePages(session).resolve_channel(("page", "https://evil.example.org/@x"))
    assert session.calls == []


### Listing Without A Key ###

def test_a_channel_is_listed_from_its_uploads_playlist():
    """
    The uploads playlist holds everything the channel published,
    including its shorts and past streams, and lists more per request
    than the videos tab does.
    """
    session = FakeYouTubeSession({"playlist": channel_page(videos=(VIDEO_A, VIDEO_B))})
    pages = yp.YouTubePages(session)

    assert pages.channel_video_ids(CHANNEL) == (VIDEO_A, VIDEO_B)
    assert session.calls[0]["url"].endswith(f"list={UPLOADS}")


def test_a_listing_stops_at_the_first_page_while_robots_txt_is_respected():
    """
    Reading further means the continuation endpoint, which YouTube's
    robots.txt disallows. The build says what it did not read rather than
    returning a partial list as though it were the whole one.
    """
    lines = []
    first = full_page_videos()
    session = FakeYouTubeSession({"playlist": channel_page(videos=first, token="MORE")})
    pages = yp.YouTubePages(session, progress=lines.append, respect_robots_txt=True)

    found = pages.channel_video_ids(CHANNEL)

    assert found == first
    assert len(pages.capped_listings) == 1
    assert any("robots.txt disallows" in line for line in lines)
    assert all(call["method"] == "get" for call in session.calls)


def test_a_listing_short_enough_to_be_complete_says_nothing_about_robots():
    """
    A four-video playlist is the whole playlist. Warning about it, or
    spending a request to prove it, would both be wrong.
    """
    lines = []
    session = FakeYouTubeSession({"playlist": channel_page(videos=(VIDEO_A, VIDEO_B), token="MORE")})
    pages = yp.YouTubePages(session, progress=lines.append, respect_robots_txt=True)

    assert pages.channel_video_ids(CHANNEL) == (VIDEO_A, VIDEO_B)
    assert pages.capped_listings == ()
    assert not any("robots.txt" in line for line in lines)


def test_the_robots_cap_is_explained_once_and_then_counted():
    """A channel has dozens of playlists; the same paragraph thirty times buries the build."""
    lines = []
    first = full_page_videos()
    session = FakeYouTubeSession({"playlist": channel_page(videos=first, token="MORE")})
    pages = yp.YouTubePages(session, progress=lines.append, respect_robots_txt=True)

    pages.channel_video_ids(CHANNEL)
    pages.playlist_video_ids(PLAYLIST)

    explained = [line for line in lines if "robots.txt disallows" in line]
    assert len(explained) == 1
    assert any("again the first page only" in line for line in lines)
    assert len(pages.capped_listings) == 2


def test_turning_robots_txt_off_pages_past_the_first_page():
    first = full_page_videos()
    session = FakeYouTubeSession({
        "playlist": channel_page(videos=first, token="MORE"),
        "browse": FakeResponse(text='"videoId": "' + VIDEO_B + '"', body=None),
    })
    pages = yp.YouTubePages(session, respect_robots_txt=False)

    found = pages.channel_video_ids(CHANNEL)

    assert found == first + (VIDEO_B,)
    assert pages.capped_listings == ()
    assert [call["method"] for call in session.calls] == ["get", "post"]


def test_a_continuation_hands_back_the_token_it_was_given():
    """The token is never composed here, only returned."""
    session = FakeYouTubeSession({
        "playlist": channel_page(videos=full_page_videos(), token="THE-TOKEN"),
        "browse": FakeResponse(text='"videoId": "' + VIDEO_B + '"', body=None),
    })

    yp.YouTubePages(session, respect_robots_txt=False).channel_video_ids(CHANNEL)

    post = [call for call in session.calls if call["method"] == "post"][0]
    assert post["body"]["continuation"] == "THE-TOKEN"
    assert post["params"]["key"] == "EXAMPLE_PAGE_PARAMETER"


def test_paging_stops_when_a_batch_adds_nothing_new():
    """A token that keeps answering the same batch must not page forever."""
    first = full_page_videos()
    repeated = "".join(f'"videoId": "{v}"' for v in first)
    session = FakeYouTubeSession({
        "playlist": channel_page(videos=first, token="LOOP"),
        "browse": FakeResponse(
            text=repeated + '"continuationCommand": {"token": "LOOP"}', body=None
        ),
    })
    pages = yp.YouTubePages(session, respect_robots_txt=False)

    assert pages.channel_video_ids(CHANNEL) == first
    assert len([c for c in session.calls if c["method"] == "post"]) == 1


def test_a_refused_page_is_retried_once_as_a_browser_only_with_robots_off():
    session = FakeYouTubeSession({"playlist": [
        FakeResponse(status_code=403, body={}),
        channel_page(videos=(VIDEO_A,)),
    ]})
    lines = []
    pages = yp.YouTubePages(session, progress=lines.append, respect_robots_txt=False)

    assert pages.channel_video_ids(CHANNEL) == (VIDEO_A,)
    assert pages.request_count == 2
    assert session.calls[1]["headers"]["User-Agent"].startswith("Mozilla/")
    assert any("retrying once as a browser" in line for line in lines)


def test_a_refused_page_is_not_retried_while_robots_txt_is_respected():
    session = FakeYouTubeSession({"playlist": FakeResponse(status_code=403, body={})})

    with pytest.raises(yc.YouTubeUnavailable, match="respect_robots_txt"):
        yp.YouTubePages(session, respect_robots_txt=True).channel_video_ids(CHANNEL)
    assert len(session.calls) == 1


def test_an_identifier_of_the_wrong_shape_on_a_page_is_dropped():
    """These reach a request and a cache file name, so a page cannot steer them."""
    session = FakeYouTubeSession({"playlist": FakeResponse(
        text='"videoId":"../../etc/pass""videoId":"' + VIDEO_A + '"', body=None)})

    assert yp.YouTubePages(session).playlist_video_ids(PLAYLIST) == (VIDEO_A,)


def test_a_channels_playlists_are_listed_from_its_playlists_tab():
    session = FakeYouTubeSession({"playlists": channel_page(playlists=(PLAYLIST,))})

    assert yp.YouTubePages(session).channel_playlist_ids(CHANNEL) == (PLAYLIST,)


### The Publisher Rule ###

def test_a_channel_with_no_key_is_listed_from_its_pages_and_indexed():
    reader = FakeReader({VIDEO_A: caption_lines(6)})
    session = FakeYouTubeSession({
        "@DepressionCenter": channel_page(),
        "playlist": channel_page(videos=(VIDEO_A,)),
        "playlists": channel_page(playlists=()),
        "oembed": FakeResponse(body={
            "title": "A Talk",
            "author_url": f"https://www.youtube.com/channel/{CHANNEL}",
        }),
    })
    built = source(reader=reader, channel_id="https://www.youtube.com/@DepressionCenter")

    documents = list(built.fetch(session, {}, quiet))

    assert documents
    assert documents[0].title.startswith("A Talk -- ")


def test_a_playlist_video_from_another_channel_is_left_out():
    """
    A channel's playlists routinely hold other people's videos. Indexing
    those would put another organization's words in this knowledge base
    under this organization's name.
    """
    reader = FakeReader({VIDEO_A: caption_lines(6), VIDEO_B: caption_lines(6)})
    other = "UCbbbbbbbbbbbbbbbbbbbbbb"
    session = FakeYouTubeSession({
        "playlist": [
            channel_page(videos=(VIDEO_A,)),          # the channel's uploads
            channel_page(videos=(VIDEO_A, VIDEO_B)),  # a playlist it curated
        ],
        "playlists": channel_page(playlists=(PLAYLIST,)),
        "oembed": [
            FakeResponse(body={"title": "Our Talk",
                               "author_url": f"https://www.youtube.com/channel/{CHANNEL}"}),
            FakeResponse(body={"title": "Someone Else's Talk",
                               "author_url": f"https://www.youtube.com/channel/{other}"}),
        ],
    })
    built = source(reader=reader, channel_id=CHANNEL)

    documents = list(built.fetch(session, {}, quiet))

    titles = {d.title.split(" -- ")[0] for d in documents}
    assert titles == {"Our Talk"}
    assert built.skipped_other_channels == 1
    assert "another channel" in "\n".join(built.summary_lines())


def test_a_playlist_video_from_the_same_channel_is_kept():
    reader = FakeReader({VIDEO_A: caption_lines(6), VIDEO_B: caption_lines(6)})
    session = FakeYouTubeSession({
        "playlist": [
            channel_page(videos=(VIDEO_A,)),
            channel_page(videos=(VIDEO_A, VIDEO_B)),
        ],
        "playlists": channel_page(playlists=(PLAYLIST,)),
        "oembed": FakeResponse(body={
            "title": "Our Talk",
            "author_url": f"https://www.youtube.com/channel/{CHANNEL}",
        }),
    })
    built = source(reader=reader, channel_id=CHANNEL)

    documents = list(built.fetch(session, {}, quiet))

    assert len({d.url.split("&")[0] for d in documents}) == 2
    assert built.skipped_other_channels == 0


def test_the_publisher_rule_can_be_turned_off():
    reader = FakeReader({VIDEO_A: caption_lines(6), VIDEO_B: caption_lines(6)})
    other = "UCbbbbbbbbbbbbbbbbbbbbbb"
    session = FakeYouTubeSession({
        "playlist": [
            channel_page(videos=(VIDEO_A,)),
            channel_page(videos=(VIDEO_A, VIDEO_B)),
        ],
        "playlists": channel_page(playlists=(PLAYLIST,)),
        "oembed": [
            FakeResponse(body={"title": "Our Talk",
                               "author_url": f"https://www.youtube.com/channel/{CHANNEL}"}),
            FakeResponse(body={"title": "Someone Else's Talk",
                               "author_url": f"https://www.youtube.com/channel/{other}"}),
        ],
    })
    built = source(reader=reader, channel_id=CHANNEL, only_channel_videos=False)

    documents = list(built.fetch(session, {}, quiet))

    assert len({d.title.split(" -- ")[0] for d in documents}) == 2
    assert built.skipped_other_channels == 0


def test_a_video_the_operator_named_is_never_held_back_by_the_publisher_rule():
    """Naming a video is the operator's own choice and overrides nothing else."""
    reader = FakeReader({VIDEO_B: caption_lines(6)})
    session = FakeYouTubeSession({
        "playlist": channel_page(videos=()),
        "playlists": channel_page(playlists=()),
        "oembed": FakeResponse(body={
            "title": "Someone Else's Talk",
            "author_url": "https://www.youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbb",
        }),
    })
    built = source(reader=reader, channel_id=CHANNEL, video_ids=(VIDEO_B,))

    documents = list(built.fetch(session, {}, quiet))

    assert documents
    assert built.skipped_other_channels == 0


def test_the_channels_playlists_are_not_queried_when_turned_off():
    reader = FakeReader({VIDEO_A: caption_lines(6)})
    session = FakeYouTubeSession({
        "playlist": channel_page(videos=(VIDEO_A,)),
        "oembed": FakeResponse(body={"title": "A Talk", "author_url": ""}),
    })
    built = source(reader=reader, channel_id=CHANNEL, include_playlists=False)

    list(built.fetch(session, {}, quiet))

    assert not any(call["resource"] == "playlists" for call in session.calls)


def test_a_video_whose_publisher_cannot_be_read_is_still_indexed():
    """
    Holding a video back on a failed lookup would quietly shrink a
    knowledge base, so the benefit of the doubt goes to indexing it.
    """
    reader = FakeReader({VIDEO_A: caption_lines(6), VIDEO_B: caption_lines(6)})
    session = FakeYouTubeSession({
        "playlist": [
            channel_page(videos=(VIDEO_A,)),
            channel_page(videos=(VIDEO_A, VIDEO_B)),
        ],
        "playlists": channel_page(playlists=(PLAYLIST,)),
        "oembed": FakeResponse(body={"title": "A Talk", "author_url": ""}),
    })
    built = source(reader=reader, channel_id=CHANNEL)

    documents = list(built.fetch(session, {}, quiet))

    assert len({d.title.split(" -- ")[0] for d in documents}) >= 1
    assert built.skipped_other_channels == 0


### A Block Partway Through ###

def test_a_block_after_some_videos_keeps_what_was_read(api_key_set, caption_library):
    """
    YouTube starts refusing a machine that has asked a lot of questions.
    A build that indexed most of a channel and then got refused is worth
    having: every later request would be refused too, so none are made,
    and the report says plainly that it is incomplete.
    """
    reader = FakeReader(
        tracks={VIDEO_A: caption_lines(6)},
        errors={VIDEO_B: caption_library.RequestBlocked(VIDEO_B)},
    )
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "First", VIDEO_B: "Second"})})
    built = source(reader=reader, video_ids=(VIDEO_A, VIDEO_B))

    lines = []
    documents = list(built.fetch(session, {}, lines.append))

    assert {d.title.split(" -- ")[0] for d in documents} == {"First"}
    assert built.blocked_after == 1
    assert any("refused this machine after 1 video" in line for line in lines)
    assert "INCOMPLETE" in "\n".join(built.summary_lines())


def test_a_block_before_anything_was_read_still_ends_the_build(api_key_set, caption_library):
    """An index with no video content in it is not a knowledge base worth publishing."""
    reader = FakeReader(errors={VIDEO_A: caption_library.RequestBlocked(VIDEO_A)})
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "First"})})

    with pytest.raises(YouTubeSourceError, match="no video content at all"):
        list(source(reader=reader, video_ids=(VIDEO_A,)).fetch(session, {}, quiet))


def test_no_further_captions_are_requested_after_a_block(api_key_set, caption_library):
    reader = FakeReader(
        tracks={VIDEO_A: caption_lines(6)},
        errors={VIDEO_B: caption_library.RequestBlocked(VIDEO_B)},
    )
    third = "VIDEOCCCCCC"
    session = FakeYouTubeSession({"videos": videos_page(
        {VIDEO_A: "First", VIDEO_B: "Second", third: "Third"})})

    list(source(reader=reader, video_ids=(VIDEO_A, VIDEO_B, third)).fetch(session, {}, quiet))

    assert [call["video_id"] for call in reader.calls] == [VIDEO_A, VIDEO_B]


def test_a_stored_transcript_is_unaffected_by_a_block(api_key_set, caption_library):
    """A build reading its own committed cache never asks YouTube anything."""
    cache_module.save_video(VIDEO_A, "Stored", "", "en",
                            [{"text": "a stored phrase about measuring mood", "start": 0.0}])
    reader = FakeReader(errors={VIDEO_B: caption_library.RequestBlocked(VIDEO_B)})
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_B: "Second"})})
    built = source(reader=reader, video_ids=(VIDEO_A, VIDEO_B))

    documents = list(built.fetch(session, {}, quiet))

    assert {d.title.split(" -- ")[0] for d in documents} == {"Stored"}
    assert built.blocked_after == 1


### Pacing ###

class FakeSettings:
    """The two crawl settings this source reads."""

    def __init__(self, delay_seconds=0.0, respect_robots_txt=True):
        self.delay_seconds = delay_seconds
        self.respect_robots_txt = respect_robots_txt
        self.user_agent = "Extractium/test (+https://example.org)"


def test_youtube_is_paced_no_faster_than_its_own_floor():
    """
    A delay that is polite to a website gets this source refused partway
    through a channel, so the build's own value is a lower bound and not
    the final word.
    """
    built = source(video_ids=(VIDEO_A,))
    built.configure(None, FakeSettings(delay_seconds=0.01))

    assert built._delay_seconds() == youtube_source.MIN_DELAY_SECONDS


def test_a_build_asking_for_a_longer_pause_gets_it():
    built = source(video_ids=(VIDEO_A,))
    built.configure(None, FakeSettings(delay_seconds=5.0))

    assert built._delay_seconds() == 5.0


def test_the_source_can_set_its_own_pause():
    built = YouTubeSource(options(video_ids=(VIDEO_A,), delay_seconds=4.0))
    built.configure(None, FakeSettings(delay_seconds=0.5))

    assert built._delay_seconds() == 4.0


def test_a_caption_request_waits_before_it_is_made(api_key_set, monkeypatch):
    """
    The caption library is called directly rather than through this
    project's client, so it is paced here or not at all. Transcripts are
    by far the most numerous requests a build makes.
    """
    waits = []
    monkeypatch.setattr(youtube_source.time, "sleep", waits.append)
    reader = FakeReader({VIDEO_A: caption_lines(6), VIDEO_B: caption_lines(6)})
    session = FakeYouTubeSession({"videos": videos_page({VIDEO_A: "First", VIDEO_B: "Second"})})
    built = source(reader=reader, video_ids=(VIDEO_A, VIDEO_B))
    built.configure(None, FakeSettings(delay_seconds=0.0))

    list(built.fetch(session, {}, quiet))

    assert len(waits) == 2
    assert all(wait >= youtube_source.MIN_DELAY_SECONDS for wait in waits)


def test_a_stored_transcript_costs_no_pause(api_key_set, monkeypatch):
    """A build working from its committed cache should finish at disk speed."""
    waits = []
    monkeypatch.setattr(youtube_source.time, "sleep", waits.append)
    cache_module.save_video(VIDEO_A, "Stored", "", "en",
                            [{"text": "a stored phrase about measuring mood", "start": 0.0}])
    built = source(video_ids=(VIDEO_A,))
    built.configure(None, FakeSettings())

    list(built.fetch(FakeYouTubeSession(), {}, quiet))

    assert waits == []


### A YouTube Address As The Seed ###

def handler():
    """The site handler, fresh, so one test's counts do not reach another."""
    from extractium.sources.youtube_site import YouTubeHandler
    return YouTubeHandler()


def test_the_handler_satisfies_the_site_handler_protocol():
    from extractium.core.models import SiteHandler
    from extractium.sources.youtube_site import YouTubeHandler

    assert isinstance(handler(), SiteHandler)
    assert YouTubeHandler.name == "youtube"


@pytest.mark.parametrize("seed", [
    "https://www.youtube.com/@DepressionCenter",
    "https://www.youtube.com/@DepressionCenter/videos",
    "https://www.youtube.com/@DepressionCenter/playlists",
    "https://www.youtube.com/depressioncenter",
    f"https://www.youtube.com/channel/{CHANNEL}",
    f"https://www.youtube.com/c/Example",
])
def test_a_channel_address_as_a_seed_reads_that_channel(seed):
    """
    The address stays as written, so the source reads it the same way it
    would from a settings file.
    """
    name, options = handler().offer_source(seed)

    assert name == "youtube"
    assert options == {"channel_id": seed}


@pytest.mark.parametrize("seed", [
    f"https://www.youtube.com/watch?v={VIDEO_A}",
    f"https://youtu.be/{VIDEO_A}",
    f"https://www.youtube.com/shorts/{VIDEO_A}",
    f"https://www.youtube.com/live/{VIDEO_A}",
])
def test_one_video_as_a_seed_reads_that_one_video(seed):
    assert handler().offer_source(seed) == ("youtube", {"video_ids": (VIDEO_A,)})


def test_a_playlist_as_a_seed_reads_that_playlist():
    seed = f"https://www.youtube.com/playlist?list={PLAYLIST}"

    assert handler().offer_source(seed) == ("youtube", {"playlist_ids": (PLAYLIST,)})


def test_a_watch_address_inside_a_playlist_reads_the_video():
    """The video is the more specific request of the two the address names."""
    seed = f"https://www.youtube.com/watch?v={VIDEO_A}&list={PLAYLIST}"

    assert handler().offer_source(seed) == ("youtube", {"video_ids": (VIDEO_A,)})


@pytest.mark.parametrize("seed", [
    "https://example.org/page",
    "https://vimeo.com/12345",
    "https://github.com/DepressionCenter",
])
def test_an_address_somewhere_else_is_not_this_handlers_business(seed):
    assert handler().offer_source(seed) is None
    assert handler().allows(seed) is True


def test_a_youtube_page_is_never_crawled():
    """
    A video's words are in its caption track, so a crawled YouTube page
    yields a title and nothing else.
    """
    built = handler()

    assert built.allows(f"https://www.youtube.com/watch?v={VIDEO_A}") is False
    assert built.allows(f"https://youtu.be/{VIDEO_A}") is False
    assert built.skipped == 2


def test_the_handler_says_once_how_many_links_it_held_back():
    built = handler()
    built.allows(f"https://youtu.be/{VIDEO_A}")
    built.allows(f"https://www.youtube.com/watch?v={VIDEO_B}")

    report = built.skipped_page_report()

    assert "2 YouTube link(s)" in report
    assert "youtube source" in report


def test_a_handler_that_saw_no_links_reports_nothing():
    assert handler().skipped_page_report() == ""


def test_the_handler_extracts_nothing_from_a_page():
    """Reached only if something let a YouTube address through anyway."""
    title, content, categories = handler().extract(None, f"https://www.youtube.com/watch?v={VIDEO_A}")

    assert (title, content, categories) == ("", None, ())
