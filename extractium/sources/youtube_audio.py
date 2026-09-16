"""
Summary: The last resort for a video's transcript. When YouTube refuses
the caption request, which it does for cloud-provider addresses, shared
addresses such as a mobile carrier's, and any address that has asked too
often, the video's audio is downloaded with yt-dlp and transcribed with
faster-whisper, the CTranslate2 build of Whisper, on the CPU. The audio
servers are not gated the way the caption endpoint is, so this works
from a machine the caption library cannot use. Both packages are the
optional `extractium[whisper]` install; a build without them reports the
refusal as before.

This file is part of Extractium™
extractium/sources/youtube_audio.py

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

import functools
import os
import re
import tempfile

from extractium.core import cache as cache_module
from extractium.sources.youtube_client import YouTubeError, checked_video_id, watch_url

### Constants ###

# The one Whisper model every build uses. Fixed rather than chosen per
# machine, so two operators transcribing the same video store the same
# words. The English-only base model is the smallest that reads a talk
# well enough to search: about 75 MB of weights, and on a plain laptop
# CPU it transcribes an hour of speech in roughly ten minutes. It is
# downloaded once, into the same cache the embedding model uses.
WHISPER_MODEL = "base.en"

# Whisper runs on the CPU with 8-bit weights, everywhere. A GPU would be
# faster on the machines that have one, but it needs a matching CUDA
# install that most operator laptops lack, and a fallback that only
# sometimes works is not a fallback.
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

# Greedy decoding. A wider beam reads a little better and costs several
# times the CPU; for a search index the words matter more than the
# punctuation, and the caption library's automatic captions are no
# better than this.
WHISPER_BEAM_SIZE = 1

# Whisper's own language codes are two letters; a configured "en-US"
# means the same track.
LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2}")

# The smallest audio-only rendition yt-dlp can find, in a container the
# decoder reads without a separate ffmpeg install: an m4a first, then
# whatever audio-only format the video has.
AUDIO_FORMAT = "ba[ext=m4a]/ba"

# Longest audio download accepted, in bytes. A six-hour recording at
# 128 kbit/s is about 350 MB; anything past this is not a talk.
MAX_AUDIO_BYTES = 500_000_000

# Where the audio lands while it is being transcribed: a folder under
# the YouTube cache, on the same disk as the transcript it becomes, and
# removed as soon as the transcript is stored.
AUDIO_WORK_DIR_NAME = "audio"


### Errors ###

class AudioTranscriptionUnavailable(YouTubeError):
    """Raised when the packages the audio path needs are not installed."""


class AudioTranscriptionFailed(YouTubeError):
    """Raised when the audio could not be downloaded or transcribed."""


### Availability ###

def audio_transcription_available():
    """
    Whether the audio path can run on this machine: both yt-dlp and
    faster-whisper import. Neither is imported at module scope, because
    a build that reads stored transcripts, or is never refused, must not
    pay for either.

    Returns:
        bool: True when both packages are installed.
    """
    try:
        import faster_whisper  # noqa: F401
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


### Downloading ###

class _SilentLogger:
    """
    Swallows yt-dlp's own log lines. What matters is reported through
    the build's progress callback in this project's words, and an error
    reaches the caller as an exception.
    """

    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


def download_audio(video_id, folder):
    """
    Downloads one video's audio track into a folder.

    Args:
        video_id (str): the video's identifier.
        folder (str): where to write the file.

    Returns:
        tuple[str, dict]: the path of the audio file, and what yt-dlp
        learned about the video: `title`, `description`, `tags`,
        `published_at` (ISO 8601 at midnight UTC, or blank), and
        `channel_id`.

    Raises:
        YouTubeError: if video_id is not a video identifier.
        AudioTranscriptionUnavailable: if yt-dlp is not installed.
        AudioTranscriptionFailed: if the download fails or the file
            is over the size ceiling.
    """
    checked_video_id(video_id)
    try:
        import yt_dlp
    except ImportError as e:
        raise AudioTranscriptionUnavailable(
            "transcribing audio needs yt-dlp and faster-whisper, which are not "
            "installed. Install them with: pip install \"extractium[whisper]\"."
        ) from e

    options = {
        "format": AUDIO_FORMAT,
        "outtmpl": os.path.join(folder, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "max_filesize": MAX_AUDIO_BYTES,
        "retries": 2,
        "quiet": True,
        "no_warnings": True,
        "logger": _SilentLogger(),
        # Nothing yt-dlp finds on the page is run: no JavaScript runtime
        # is configured, and no post-processor is asked for.
        "postprocessors": [],
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(watch_url(video_id), download=True)
    except yt_dlp.utils.DownloadError as e:
        raise AudioTranscriptionFailed(
            f"the audio of {video_id} could not be downloaded ({_first_line(e)})."
        ) from e
    except Exception as e:  # the downloader raises its own kinds for a bad page
        raise AudioTranscriptionFailed(
            f"the audio of {video_id} could not be downloaded ({type(e).__name__})."
        ) from e

    path = _downloaded_path(info)
    if not path or not os.path.isfile(path):
        raise AudioTranscriptionFailed(
            f"the audio of {video_id} was not downloaded: no audio-only rendition "
            f"under {MAX_AUDIO_BYTES} bytes, or the download was refused."
        )
    return path, metadata_from_info(info)


def _downloaded_path(info):
    """The file a download wrote, as yt-dlp reports it."""
    if not isinstance(info, dict):
        return ""
    for download in info.get("requested_downloads") or ():
        if isinstance(download, dict) and download.get("filepath"):
            return str(download["filepath"])
    return ""


def _first_line(error):
    """The first line of an exception's message, without yt-dlp's prefix."""
    text = str(error).splitlines()[0] if str(error) else type(error).__name__
    return text.replace("ERROR: ", "", 1)


def metadata_from_info(info):
    """
    What yt-dlp learned about a video, in the fields the transcript
    store carries.

    Args:
        info (Mapping): yt-dlp's information record for one video.
            Untrusted, like any response: only values of the expected
            type are used.

    Returns:
        dict: `title`, `description`, `tags` (tuple of str),
        `published_at` (ISO 8601 at midnight UTC, or blank when the
        upload date is missing or malformed), and `channel_id`.
    """
    info = info if isinstance(info, dict) else {}
    tags = info.get("tags")
    upload_date = str(info.get("upload_date") or "")
    published_at = ""
    if re.match(r"^\d{8}$", upload_date):
        published_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}T00:00:00Z"
    return {
        "title": str(info.get("title") or "").strip(),
        "description": str(info.get("description") or ""),
        "tags": tuple(tag for tag in tags if isinstance(tag, str)) if isinstance(tags, list) else (),
        "published_at": published_at,
        "channel_id": str(info.get("channel_id") or "").strip(),
    }


### Transcribing ###

@functools.lru_cache(maxsize=1)
def _model():
    """The Whisper model, loaded once per process."""
    from faster_whisper import WhisperModel

    return WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)


def whisper_language(language):
    """
    The two-letter code Whisper takes for a configured caption language.

    Args:
        language (str): a caption language as configured, such as
            "en" or "en-US".

    Returns:
        str | None: the two-letter code, or None when the value does not
        start with one, which lets the model detect the language itself.
    """
    match = LANGUAGE_CODE_RE.match((language or "").strip().lower())
    return match.group(0) if match else None


def transcript_lines(segments):
    """
    Timed lines from Whisper's segments, in the shape a caption track
    gives: `text` and `start` in seconds.

    Args:
        segments (Iterable): objects with `start` and `text`.

    Returns:
        list[dict]: one record per segment with any words in it.
    """
    lines = []
    for segment in segments:
        text = " ".join(str(getattr(segment, "text", "") or "").split())
        if text:
            lines.append({"text": text, "start": float(getattr(segment, "start", 0.0) or 0.0)})
    return lines


def transcribe_audio(path, language="en", model=None):
    """
    Transcribes one audio file.

    Args:
        path (str): the audio file.
        language (str): the caption language configured first; Whisper
            is told it rather than left to guess, which is faster and
            avoids a wrong guess on a short clip.
        model: a loaded WhisperModel, or None to load the fixed one.

    Returns:
        tuple[str, list[dict]]: the language code the model worked in,
        and the timed lines.

    Raises:
        AudioTranscriptionUnavailable: if faster-whisper is not installed.
        AudioTranscriptionFailed: if the file cannot be read or decoded.
    """
    if model is None:
        try:
            model = _model()
        except ImportError as e:
            raise AudioTranscriptionUnavailable(
                "transcribing audio needs faster-whisper, which is not installed. "
                "Install it with: pip install \"extractium[whisper]\"."
            ) from e
    try:
        segments, info = model.transcribe(
            path, language=whisper_language(language), beam_size=WHISPER_BEAM_SIZE, vad_filter=True,
        )
        lines = transcript_lines(segments)
    except Exception as e:  # the decoder raises its own kinds for a bad file
        raise AudioTranscriptionFailed(
            f"the audio could not be transcribed ({type(e).__name__})."
        ) from e
    return str(getattr(info, "language", "") or whisper_language(language) or ""), lines


### The Fallback ###

class AudioTranscriber:
    """
    Downloads a video's audio and transcribes it, cleaning up after
    itself. One instance serves a build; the model loads on first use.

    Attributes:
        work_dir (str): the folder audio files are written under while
            they are transcribed. Each video gets its own temporary
            folder inside it, removed when the video is done.
    """

    def __init__(self, work_dir=None):
        self.work_dir = work_dir or os.path.join(cache_module.CACHE_YOUTUBE_DIR, AUDIO_WORK_DIR_NAME)

    def transcribe(self, video_id, language="en", progress=None):
        """
        One video's transcript from its audio.

        Args:
            video_id (str): the video's identifier.
            language (str): the caption language configured first.
            progress (Callable[[str], None] | None): receives one line
                per stage.

        Returns:
            tuple[dict, str, list[dict]]: what yt-dlp learned about the
            video (see metadata_from_info), the language code the model
            worked in, and the timed lines.

        Raises:
            YouTubeError: if video_id is not a video identifier.
            AudioTranscriptionUnavailable, AudioTranscriptionFailed: as
                download_audio and transcribe_audio raise them.
        """
        report = progress or (lambda message: None)
        os.makedirs(self.work_dir, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"{checked_video_id(video_id)}-", dir=self.work_dir) as folder:
            path, metadata = download_audio(video_id, folder)
            size = os.path.getsize(path)
            report(f"    downloaded {size // 1_000_000} MB of audio; transcribing with Whisper {WHISPER_MODEL}...")
            language_code, lines = transcribe_audio(path, language=language)
        return metadata, language_code, lines
