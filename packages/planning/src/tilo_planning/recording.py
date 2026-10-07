"""Recording upload ingest (FR-MTG-17): an uploaded audio or video file is transcribed through the injected
`SpeechProvider` and becomes a schema-valid Transcript content dict (`contracts/transcript.schema.json`, FR-MTG-02:
ids `u0001` upward, one line of text per utterance), safety-screened like every other intake path (FR-INT-02, PRD
16.3 item 2), with an origin record. Pure: no store, no event and no network of its own; the caller (FR-MTG-02's
ingest, tilo-api) stores the artifact, writes the Trace event and decides what a flagged transcript may reach.
Lives in `tilo_planning` because it already owns file-type allowlists, size caps and the safety screen for uploads.
Transcript text and speaker labels are untrusted: cleaned here, never executed or sent to a model unscreened."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from tilo_contracts import Transcript
from tilo_providers.interfaces import SafetyProvider, SpeechProvider
from tilo_providers.speech import as_speech_result

MAX_UTTERANCES = 10_000  # contracts/transcript.schema.json maxItems
MAX_TEXT_CHARS, MAX_SPEAKER_CHARS = 4000, 80
SCREEN_CHUNK_CHARS = 20_000  # well under the safety role's own input cap: a long meeting is screened in pieces
_VIDEO_TYPES = frozenset({"video/mp4", "video/webm"})
_AUDIO_TYPE = re.compile(r"audio/[a-z0-9][a-z0-9.+-]*")
_MEETING_ID = re.compile(r"mt_[0-9A-Za-z_]{1,48}")
_STRIPPED = frozenset({"Cc", "Cf", "Zl", "Zp"})  # controls, format characters (bidi, zero-width), separators


class RecordingRejected(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RecordingLimits:  # from config/speech.yaml (SpeechConfig.max_bytes, .max_duration_ms)
    max_bytes: int
    max_duration_ms: int


@dataclass(frozen=True)
class RecordingTranscript:
    content: dict[str, Any]  # a Transcript version's content (FR-MTG-02)
    origin: dict[str, Any]  # the ingest origin record: what was uploaded, never the audio
    safety_flagged: bool  # kept and marked, never dropped: the Trace shows it (FR-MTG-02)
    safety_reason: str | None


def media_type_allowed(media_type: object) -> str:
    """The normalised media type (parameters such as `; codecs=opus` dropped), or `RecordingRejected`:
    only `audio/*`, `video/mp4` and `video/webm`; everything else fails closed."""
    base = media_type.split(";")[0].strip().lower() if isinstance(media_type, str) else ""
    if base in _VIDEO_TYPES or _AUDIO_TYPE.fullmatch(base):
        return base
    raise RecordingRejected("Upload an audio file, or an MP4 or WebM video; this file type is not accepted.")


def _line(text: str, limit: int) -> str:
    """One line: whitespace runs (newlines included) become one space, controls, format characters and line or
    paragraph separators are removed, the result is trimmed and cut to `limit`."""
    collapsed = re.sub(r"\s+", " ", text)
    return "".join(c for c in collapsed if unicodedata.category(c) not in _STRIPPED).strip()[:limit].strip()


def _screen(lines: list[str], safety: SafetyProvider) -> tuple[bool, str | None]:
    chunk, size, flagged, reason = [], 0, False, None
    for line in [*lines, None]:
        if line is not None and size + len(line) < SCREEN_CHUNK_CHARS:
            chunk.append(line)
            size += len(line) + 1
            continue
        if chunk:  # a provider error here propagates: nothing is returned unscreened (fails closed)
            verdict = safety.check("\n".join(chunk))
            if verdict["flagged"] and not flagged:
                flagged, reason = True, verdict.get("reason") or "flagged by the safety provider"
        chunk, size = ([line], len(line) + 1) if line is not None else ([], 0)
    return flagged, reason


def transcribe_recording(
    audio: bytes,
    media_type: str,
    *,
    meeting_id: str,
    speech: SpeechProvider,
    safety: SafetyProvider,
    limits: RecordingLimits,
    declared_duration_ms: int | None = None,
) -> RecordingTranscript:
    """Raises `RecordingRejected` (a reason fit for the person) before any speech call for a bad media type, an
    empty or oversized file, or a declared duration over the cap; after the call for no speech, too many utterances
    or a last offset over the duration cap. A provider or safety error propagates (fails closed)."""
    if not _MEETING_ID.fullmatch(meeting_id):
        raise RecordingRejected("The meeting id is not valid.")
    media_type = media_type_allowed(media_type)
    if not audio:
        raise RecordingRejected("The file is empty.")
    if len(audio) > limits.max_bytes:
        raise RecordingRejected(f"The file is {len(audio)} bytes; the limit is {limits.max_bytes}.")
    if declared_duration_ms is not None and declared_duration_ms > limits.max_duration_ms:
        raise RecordingRejected("The recording is longer than the limit.")

    segments = as_speech_result(speech.transcribe(audio, media_type=media_type))["segments"]
    utterances: list[dict[str, Any]] = []
    for segment in sorted(segments, key=lambda s: s["start_ms"]):  # stable: provider order breaks ties
        text = _line(segment["text"], MAX_TEXT_CHARS)
        if text:
            speaker = _line(segment["speaker"].replace("://", " "), MAX_SPEAKER_CHARS) or "Speaker 1"
            utterances.append({"id": "", "speaker": speaker, "t_ms": segment["start_ms"], "text": text})
    if not utterances:
        raise RecordingRejected("No speech was found in the recording.")
    if len(utterances) > MAX_UTTERANCES:
        raise RecordingRejected("The recording has more utterances than a transcript can hold.")
    if utterances[-1]["t_ms"] > limits.max_duration_ms:
        raise RecordingRejected("The recording is longer than the limit.")
    for number, utterance in enumerate(utterances, 1):
        utterance["id"] = f"u{number:04d}"

    content = {"v": "1.0", "meeting_id": meeting_id, "utterances": utterances}
    Transcript.model_validate(content)  # the contract's own model: never hand back a version that would not store
    flagged, reason = _screen([f"{u['speaker']}: {u['text']}" for u in utterances], safety)
    origin = {
        "kind": "recording-upload",
        "media_type": media_type,
        "size_bytes": len(audio),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "utterances": len(utterances),
    }
    return RecordingTranscript(content, origin, flagged, reason)
