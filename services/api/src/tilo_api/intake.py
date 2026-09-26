"""POST /intake (FR-INT-01, FR-INT-02): multipart text + files -> task, world.requested, per-file status.

A business-rule rejection (limits, file type) answers 422 {"error": reason} and stores nothing.
The safety screen comes from the provider layer (PRD 16.3). Until it ships a safety adapter,
none is configured and the route fails closed with 503: nothing is ingested unscreened.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from tilo_planning.artifacts import InMemoryArtifactStore
from tilo_planning.intake import MAX_FILES, MAX_TOTAL_BYTES, IntakeFile, IntakeRejected, IntakeRequest, submit_intake
from tilo_providers.interfaces import SafetyProvider

router = APIRouter()

_store = InMemoryArtifactStore()


def get_store() -> InMemoryArtifactStore:
    return _store


def get_safety() -> SafetyProvider:
    raise HTTPException(status_code=503, detail="No safety provider is configured; intake is closed.")


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
