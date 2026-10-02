"""POST /intake (FR-INT-01..04): multipart text + files -> task, world.requested, per-file status, the
Director's brief and its clarifying questions (services/api/tests/API_CL_INT_1.md).

The signed-in principal comes first. A business-rule rejection (limits, file type, flagged task text) answers
422 {"error": reason} and stores nothing. The safety screen is built from the `safety` role in the provider
config on every request (PRD 16.3 item 2): no role, a provider the factory refuses, or a screen that cannot
answer closes intake with 503 before anything is stored or sent to a model.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from tilo_planning.artifacts import InMemoryArtifactStore
from tilo_planning.brief import BriefExtractionError
from tilo_planning.intake import (
    MAX_FILES,
    MAX_TOTAL_BYTES,
    IntakeFile,
    IntakeRejected,
    IntakeRequest,
    IntakeResult,
    screen_task_text,
    submit_intake,
)
from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.replay import ReplayMissError
from tilo_providers.router import Router

from tilo_api import deps
from tilo_api.deps import get_safety  # the dependency key tests and callers override
from tilo_api.tasks import create_task

router = APIRouter()
logger = logging.getLogger("tilo_api.intake")

_store = InMemoryArtifactStore()


def get_store() -> InMemoryArtifactStore:
    return _store


def _screen_and_store(request: IntakeRequest, safety: SafetyProvider, store: InMemoryArtifactStore) -> IntakeResult:
    screen_task_text(request, safety=safety)
    return submit_intake(request, safety=safety, store=store)


@router.post("/intake", status_code=201)
async def intake(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    safety: Annotated[SafetyProvider, Depends(get_safety)],  # before any store: fail closed first
    store: Annotated[InMemoryArtifactStore, Depends(get_store)],
    tasks: Annotated[deps.Store, Depends(deps.get_store)],
    model_router: Annotated[Router, Depends(deps.get_router)],
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
    request = IntakeRequest(text=text, files=uploads, user_id=principal.user_id)
    try:
        # CPU-bound extraction and blocking screen and model calls stay off the event loop.
        result = await run_in_threadpool(_screen_and_store, request, safety, store)
    except IntakeRejected as exc:
        return _rejected(exc.reason)
    except (ProviderError, ReplayMissError) as exc:
        logger.warning("safety screen failed: %s", exc)
        raise HTTPException(status_code=503, detail="The safety screen is unavailable; nothing was stored.") from exc
    try:
        task_id, task = await run_in_threadpool(create_task, tasks, result, text, model_router)
    except BriefExtractionError as exc:
        logger.warning("brief extraction failed: %s", exc)
        raise HTTPException(status_code=502, detail="The Director could not draft a brief.") from exc
    body = asdict(result)  # per-file text and events stay server-side
    body["files"] = [{k: v for k, v in f.items() if k not in ("text", "events")} for f in body["files"]]
    questions = [
        {"field": q.field, "text": q.text, "suggested_answers": list(q.suggested_answers)} for q in task.questions
    ]
    return {**body, "task_id": task_id, "brief": task.brief, "questions": questions}


def _rejected(reason: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": reason})
