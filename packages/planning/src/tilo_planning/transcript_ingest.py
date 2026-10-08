"""Transcript ingest (FR-MTG-02): the meet-bot package (`transcript.jsonl` + optional `state.json`) or an uploaded VTT,
SRT or plain-text file becomes a safety-screened, versioned `Transcript` artifact (`contracts/transcript.schema.json`,
ids `u0001` upward) with an origin record. The parsers are pure and deterministic: no model, no network, nothing in
the input is ever executed or followed; they only produce `{speaker, start_ms, text}` segments, the same shape the
recording path (FR-MTG-17) produces, so `recording.normalise_segments` is the single cleaner for both. A flagged line
is kept and marked, never dropped; the Trace shows it on the registered `artifact.created` event (severity `fyi`,
`trace.tool` `safety_provider`, as for a flagged intake file). The only effects are the store write and the returned
event: no tool call, no outbox entry, no send. The caller (tilo-api) owns the upload route, `seq` and what a flagged
transcript may reach."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from tilo_memory.artifacts import MAX_TEXT, NewVersion, Origin, Scope
from tilo_providers.interfaces import SafetyProvider

from tilo_planning.events import build_event
from tilo_planning.recording import _MEETING_ID, RecordingRejected, _line, _screen, normalise_segments

TranscriptRejected = RecordingRejected  # one refusal type for every transcript source; `.reason` fits the person

MAX_INPUT_BYTES = 4_000_000  # twice the 2,000,000-byte stored cap: timing lines and tags are overhead (BQ-MTG02-1)
MAX_STATE_BYTES = 1_000_000
MAX_LINES = 100_000
MAX_JSON_LINE_CHARS = 100_000
MAX_OFFSET_MS = 360_000_000  # 100 hours: a larger or non-finite offset is clamped, never trusted
MAX_TITLE_CHARS = 120
SAFETY_TOOL = "safety_provider"
KINDS = ("vtt", "srt", "text", "meet-bot")
_EXTENSIONS = {".vtt": "vtt", ".srt": "srt", ".txt": "text", ".text": "text", ".jsonl": "meet-bot"}
_TIME = r"(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[.,](\d{3})"
_CUE = re.compile(rf"\s*{_TIME}\s*-->\s*{_TIME}(?:\s.*)?")  # anything after the end time is cue settings: ignored
_NEWLINE = re.compile(r"\r\n|\r|\n")
_VOICE = re.compile(r"<v(?:\.[^\s<>]*)*[ \t]+([^<>]*)>")
_TAG = re.compile(r"<(?:/?[A-Za-z][^<>]*|\d[^<>]*)>")  # <c.x>, </v>, <i>, <font ...>, <00:00:01.000>; "a < b" stays
_ASS = re.compile(r"\{\\[^{}]*\}")
_BLOCK_NOT_A_CUE = re.compile(r"(NOTE|STYLE|REGION)(\s|$)")
_SPEAKER_PREFIX = re.compile(r"([^:]{1,60}):\s+(\S.*)")  # "Name: text"; a colon not followed by a space is text


@dataclass(frozen=True)
class ParsedTranscript:
    segments: list[dict[str, Any]]  # {speaker, start_ms, text}, untrusted, in file order
    title: str | None  # state.json `agenda_title`, cleaned
    skipped: int  # meet-bot lines that were not usable JSON rows


@dataclass(frozen=True)
class TranscriptIngest:
    artifact: dict[str, Any]  # {artifact_id, version}
    content: dict[str, Any]  # the stored Transcript version content
    origin: dict[str, Any]  # what was uploaded (kind, size, sha256, utterance count), never the upload
    safety_flagged: bool
    safety_reason: str | None
    title: str | None
    events: list[dict[str, Any]]  # unwritten: the harness is the single writer (seq order is the caller's)


def kind_for_filename(name: object) -> str:
    """The ingest kind for an uploaded file name (by extension), or `TranscriptRejected`."""
    ext = "." + name.rsplit(".", 1)[1].lower() if isinstance(name, str) and "." in name else ""
    if ext not in _EXTENSIONS:
        raise TranscriptRejected("Upload a VTT, SRT or text file, or the meet-bot transcript.jsonl.")
    return _EXTENSIONS[ext]


def _lines(data: bytes) -> list[str]:
    if not isinstance(data, bytes) or not data:
        raise TranscriptRejected("The file is empty.")
    if len(data) > MAX_INPUT_BYTES:
        raise TranscriptRejected(f"The file is {len(data)} bytes; the limit is {MAX_INPUT_BYTES}.")
    try:
        if b"\x00" in data:
            raise ValueError("binary")
        lines = _NEWLINE.split(data.decode("utf-8-sig"))  # strict UTF-8; a byte order mark is dropped
    except ValueError:
        raise TranscriptRejected("The file is not UTF-8 text.") from None
    if len(lines) > MAX_LINES:
        raise TranscriptRejected(f"The file has more than {MAX_LINES} lines.")
    return lines


def _offset_ms(value: Any) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        return None
    return round(max(0, min(value, MAX_OFFSET_MS / 1000)) * 1000)


def _prefixed(text: str) -> tuple[str, str]:
    match = _SPEAKER_PREFIX.fullmatch(text)
    return (match[1], match[2]) if match else ("", text)


def _cue(block: list[str], kind: str) -> dict[str, Any] | None:
    if kind == "vtt" and _BLOCK_NOT_A_CUE.match(block[0]):
        return None
    at = next((i for i, line in enumerate(block[:2]) if _CUE.fullmatch(line)), None)  # at most one id line before
    match = _CUE.fullmatch(block[at]) if at is not None else None
    if at is None or match is None:
        return None
    h, m, s, ms = (int(g or 0) for g in match.groups()[:4])
    raw = " ".join(block[at + 1 :])
    voice = _VOICE.search(raw)
    text = html.unescape(_TAG.sub("", _ASS.sub("", raw)))
    speaker, text = (html.unescape(voice[1]), text) if voice else _prefixed(text.strip())
    return {"speaker": speaker, "start_ms": min(((h * 60 + m) * 60 + s) * 1000 + ms, MAX_OFFSET_MS), "text": text}


def _timed(lines: list[str], kind: str) -> list[dict[str, Any]]:
    if kind == "vtt":
        if not re.match(r"WEBVTT(\s|$)", lines[0]):
            raise TranscriptRejected("This is not a WebVTT file.")
        lines = lines[next((i for i, line in enumerate(lines) if not line.strip()), len(lines)) :]  # drop the header
    segments, block = [], []
    for line in [*lines, ""]:
        if line.strip():
            block.append(line)
        elif block:
            cue = _cue(block, kind)
            segments += [cue] if cue else []
            block = []
    return segments


def _meet_bot(lines: list[str]) -> tuple[list[dict[str, Any]], int]:
    """`{speaker, text, t}` rows, `t` in seconds from the start of the session (the bot's own `transcript.jsonl`)."""
    segments, skipped, last = [], 0, 0
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line) if len(line) <= MAX_JSON_LINE_CHARS else None
        except (ValueError, RecursionError):
            row = None
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            skipped += 1
            continue
        offset = _offset_ms(row.get("t"))
        last = last if offset is None else offset  # an unusable `t` keeps the previous offset, so file order holds
        speaker = row.get("speaker")
        segments.append({"speaker": speaker if isinstance(speaker, str) else "", "start_ms": last, "text": row["text"]})
    return segments, skipped


def _title(state: bytes | None) -> str | None:
    if not state:
        return None
    if len(state) > MAX_STATE_BYTES:
        raise TranscriptRejected(f"state.json is {len(state)} bytes; the limit is {MAX_STATE_BYTES}.")
    try:
        doc = json.loads(state.decode("utf-8-sig"))
    except (ValueError, RecursionError):
        return None  # optional metadata: an unreadable state.json is ignored, never guessed at
    title = doc.get("agenda_title") if isinstance(doc, dict) else None
    return (_line(title, MAX_TITLE_CHARS) or None) if isinstance(title, str) else None


def parse_transcript(kind: str, data: bytes, *, state: bytes | None = None) -> ParsedTranscript:
    """Pure: bounded, tolerant of CRLF and a BOM, refuses binary; the segments are not yet cleaned or ordered."""
    if kind not in KINDS:
        raise TranscriptRejected("This transcript format is not supported.")
    lines = _lines(data)
    if kind == "meet-bot":
        segments, skipped = _meet_bot(lines)
        return ParsedTranscript(segments, _title(state), skipped)
    if kind == "text":
        parts = [_prefixed(line.strip()) for line in lines if line.strip()]
        return ParsedTranscript([{"speaker": s, "start_ms": 0, "text": t} for s, t in parts], None, 0)
    return ParsedTranscript(_timed(lines, kind), None, 0)


def ingest_transcript(
    kind: str,
    data: bytes,
    *,
    state: bytes | None = None,
    meeting_id: str,
    scope: Scope,
    run_id: str,
    store: Any,
    safety: SafetyProvider,
    ts: str,
    actor: str,
    seq: int,
    cause: str | None = None,
    parent: dict[str, Any] | None = None,
) -> TranscriptIngest:
    """Raises `TranscriptRejected` (a reason fit for the person) before any screening or write for a bad meeting id,
    kind, size, encoding or content; a safety-provider error propagates before the write (fails closed); the store's
    own refusals (`ArtifactRefused`) propagate. `parent` makes the next version of an earlier transcript."""
    if not _MEETING_ID.fullmatch(meeting_id):
        raise TranscriptRejected("The meeting id is not valid.")
    parsed = parse_transcript(kind, data, state=state)
    content = normalise_segments(parsed.segments, meeting_id=meeting_id, what="transcript")
    payload = json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_TEXT:
        raise TranscriptRejected("The transcript is too large to store.")
    lines = [f"{u['speaker']}: {u['text']}" for u in content["utterances"]]
    flagged, reason = _screen([*lines, *([parsed.title] if parsed.title else [])], safety)

    stored = store.put(scope, NewVersion("application/json", payload, run_id, Origin(kind="upload"), parent=parent))
    record = stored.record
    if record["screening"] == "flagged" and not flagged:  # the store's own verdict on the stored bytes counts too
        flagged, reason = True, "flagged by the safety provider"
    if record["redacted"]:  # report what is stored, not what was parsed
        content = json.loads(store.read(scope, stored.ref))
    origin: dict[str, Any] = {
        "kind": kind,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "utterances": len(content["utterances"]),
    }
    if parsed.skipped:
        origin["skipped_lines"] = parsed.skipped

    ref = stored.ref
    summary = (
        "Safety screen flagged the transcript" if flagged else f"Stored the transcript ({origin['utterances']} lines)"
    )
    event_data: dict[str, Any] = (
        {"artifact": ref, "previous_version": parent["version"]}
        if parent is not None
        else {k: record[k] for k in ("content_sha256", "media_type", "size_bytes")} | {"artifact": ref}
    )
    event = build_event(
        {"v": "1.0", "ts": ts, "world_id": scope.world_id, "run_id": run_id, "actor": actor},
        tool=SAFETY_TOOL,
        summary=summary,
        type="artifact.created" if parent is None else "artifact.versioned",
        seq=seq,
        target=ref["artifact_id"],
        severity="fyi" if flagged else "info",
        item={"kind": "document", "artifact_id": ref["artifact_id"], "label": "Transcript"},
        cause=cause,
        data=event_data,
    )
    return TranscriptIngest(ref, content, origin, flagged, reason, parsed.title, [event])
