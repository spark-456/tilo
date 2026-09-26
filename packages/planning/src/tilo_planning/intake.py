"""Task intake (FR-INT-01/02, PRD 7.1). Limits first, then extract and screen every file (PRD 16.3
item 2), then store: a rejection or a provider error stores nothing. Events are built and validated
here, not written; the harness is the single writer per world."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from tilo_providers.interfaces import SafetyProvider

from tilo_planning.artifacts import InMemoryArtifactStore, new_ulid
from tilo_planning.events import build_event as _event
from tilo_planning.events import clip as _clip
from tilo_planning.extraction import FILE_TYPES, ExtractionError, extract, file_type

MAX_TEXT_CHARS = 4000
MAX_FILES = 10
MAX_TOTAL_BYTES = 50 * 1024 * 1024
SAFETY_TOOL = "safety_provider"
_ACCEPTED = "PDF, DOCX, PPTX, XLSX, CSV, PNG or JPG"


class IntakeRejected(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class IntakeFile:
    filename: str
    content: bytes


@dataclass(frozen=True)
class IntakeRequest:
    text: str
    files: list[IntakeFile] = field(default_factory=list)
    channel: str = "web"
    user_id: str = "u_local"  # no sign-in yet (local-first); the API passes the signed-in user later


@dataclass(frozen=True)
class IntakeFileResult:
    filename: str
    status: str  # "ok" | "failed" (unreadable: never passed to a model)
    kind: str  # "native" | "converted"
    text: str | None
    error: str | None
    safety_flagged: bool
    safety_reason: str | None
    artifact: dict[str, Any]
    origin: dict[str, Any]
    events: list[dict[str, Any]]


@dataclass(frozen=True)
class IntakeResult:
    task_id: str
    world_id: str
    run_id: str
    event: dict[str, Any]
    files: list[IntakeFileResult]


def submit_intake(request: IntakeRequest, *, safety: SafetyProvider, store: InMemoryArtifactStore) -> IntakeResult:
    names = _check_limits(request)
    screened = [_screen(name, upload.content, safety) for name, upload in zip(names, request.files, strict=True)]

    task_id, world_id, run_id = f"t_{new_ulid()}", f"w_{new_ulid()}", f"r_{new_ulid()}"
    now = datetime.now(UTC)
    received_at = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    base = {"v": "1.0", "ts": received_at, "world_id": world_id, "run_id": run_id, "actor": request.user_id}
    title = _clip(" ".join(request.text.split()), 140)
    world_event = _event(
        base, seq=1, type="world.requested", target=world_id, item=None, severity="info", tool=None,
        summary=f"Asked for: {title}", cause=None,
        data={"title": title, "channel": request.channel, "destination": None},
    )  # fmt: skip

    files: list[IntakeFileResult] = []
    for seq, name, upload, (text, error, flagged, reason) in zip(
        range(2, 2 + len(names)), names, request.files, screened, strict=True
    ):
        kind, mime_type, _magic = FILE_TYPES[PurePosixPath(name.lower()).suffix]
        stored = store.put(artifact_id=None, filename=name, content=upload.content, content_type=mime_type,
                           task_id=task_id, received_at=received_at)  # fmt: skip
        ref = {"artifact_id": stored.artifact_id, "version": stored.version}
        if error is not None:
            severity, summary, tool = "fyi", f"Could not read {name}: {error}", None
        elif flagged:
            severity, summary, tool = "fyi", f"Safety screen flagged {name}", SAFETY_TOOL
        else:
            severity, summary, tool = "info", f"Stored {name} (version {stored.version})", SAFETY_TOOL
        event = _event(
            base, seq=seq, type="artifact.created", target=stored.artifact_id, severity=severity, tool=tool,
            item={"kind": "document", "artifact_id": stored.artifact_id, "label": _clip(name, 80)},
            summary=summary, cause=world_event["id"], data={"artifact": ref},
        )  # fmt: skip
        status, origin = ("failed" if error else "ok"), dict(stored.origin)
        files.append(IntakeFileResult(name, status, kind, text, error, flagged, reason, ref, origin, [event]))
    return IntakeResult(task_id, world_id, run_id, world_event, files)


def _screen(name: str, content: bytes, safety: SafetyProvider) -> tuple[str | None, str | None, bool, str | None]:
    """(text, error, flagged, reason). An unreadable file is never passed to a model, so not screened."""
    try:
        text = extract(name, content)
    except ExtractionError as exc:
        return None, str(exc), False, None
    if text is None:
        verdict = safety.check("", content=content, mime_type=FILE_TYPES[PurePosixPath(name.lower()).suffix][1])
    else:
        verdict = safety.check(text)
    flagged = bool(verdict["flagged"])
    return text, None, flagged, (verdict.get("reason") or "flagged by the safety provider") if flagged else None


def _check_limits(request: IntakeRequest) -> list[str]:
    if not request.text.strip():
        raise IntakeRejected("Describe the task in text.")
    if len(request.text) > MAX_TEXT_CHARS:
        raise IntakeRejected(f"The text is {len(request.text)} characters; the limit is {MAX_TEXT_CHARS}.")
    if len(request.files) > MAX_FILES:
        raise IntakeRejected(f"{len(request.files)} files attached; the limit is {MAX_FILES}.")
    if sum(len(f.content) for f in request.files) > MAX_TOTAL_BYTES:
        raise IntakeRejected(f"The files total more than {MAX_TOTAL_BYTES // (1024 * 1024)} MB.")
    names = []
    for upload in request.files:
        name = PurePosixPath(upload.filename.replace("\\", "/")).name.strip()
        if not name or file_type(name) is None:
            raise IntakeRejected(f"{_clip(name or 'A file', 80)} is not accepted; attach {_ACCEPTED} files.")
        names.append(name)
    return names
