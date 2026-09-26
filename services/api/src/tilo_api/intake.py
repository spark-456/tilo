"""POST /intake (FR-INT-01, FR-INT-02): multipart text + files -> task, world.requested, per-file status.

A business-rule rejection (limits, file type) answers 422 {"error": reason} and stores nothing.
Until the provider layer ships a safety adapter, the screen is `PatternSafetyProvider`: a
deterministic check for instructions aimed at the assistant (no model call).
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from tilo_planning.artifacts import InMemoryArtifactStore
from tilo_planning.intake import MAX_FILES, MAX_TOTAL_BYTES, IntakeFile, IntakeRejected, IntakeRequest, submit_intake
from tilo_providers.interfaces import SafetyProvider

router = APIRouter()

_INJECTION = re.compile(
    r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|your)\b.{0,20}"
    r"\b(instructions?|prompts?|rules)\b",
    re.IGNORECASE | re.DOTALL,
)


class PatternSafetyProvider(SafetyProvider):
    def check(self, text: str, **kwargs: Any) -> dict[str, Any]:
        match = _INJECTION.search(text)
        return {"flagged": bool(match), "reason": "instruction aimed at the assistant" if match else None}


_store = InMemoryArtifactStore()
_safety = PatternSafetyProvider()


def get_store() -> InMemoryArtifactStore:
    return _store


def get_safety() -> SafetyProvider:
    return _safety


@router.post("/intake", status_code=201)
async def intake(
    store: Annotated[InMemoryArtifactStore, Depends(get_store)],
    safety: Annotated[SafetyProvider, Depends(get_safety)],
    text: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile], File()] = [],  # noqa: B006 (FastAPI copies defaults)
) -> Any:
    if len(files) > MAX_FILES:
        return _rejected(f"{len(files)} files attached; the limit is {MAX_FILES}.")
    uploads, remaining = [], MAX_TOTAL_BYTES
    for upload in files:
        content = await upload.read(remaining + 1)  # never hold more than the limit in memory
        remaining -= len(content)
        if remaining < 0:
            return _rejected(f"The files total more than {MAX_TOTAL_BYTES // (1024 * 1024)} MB.")
        uploads.append(IntakeFile(filename=upload.filename or "", content=content))
    try:
        result = submit_intake(IntakeRequest(text=text, files=uploads), safety=safety, store=store)
    except IntakeRejected as exc:
        return _rejected(exc.reason)
    body = asdict(result)  # per-file text and events stay server-side
    body["files"] = [{k: v for k, v in f.items() if k not in ("text", "events")} for f in body["files"]]
    return body


def _rejected(reason: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": reason})
