"""POST /intake (FR-INT-01..04): multipart text + files -> task, world.requested, per-file status, the
Director's brief and its clarifying questions (services/api/tests/API_CL_INT_1.md).

The signed-in principal comes first. A business-rule rejection (limits, file type, flagged task text) answers
422 {"error": reason} and stores nothing; an out-of-policy task (FR-INT-12) adds `alternative` and `category`,
both configured text. The safety screen is built from the `safety` role in the provider
config on every request (PRD 16.3 item 2): no role, a provider the factory refuses, or a screen that cannot
answer closes intake with 503 before anything is stored or sent to a model.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from tilo_metering.flags import FlagStore
from tilo_planning.artifacts import InMemoryArtifactStore
from tilo_planning.brief import BriefExtractionError, extract_brief
from tilo_planning.gaps import NothingPossible
from tilo_planning.intake import (
    MAX_FILES,
    MAX_TOTAL_BYTES,
    IntakeFile,
    IntakeRejected,
    IntakeRequest,
    screen_task_text,
    submit_intake,
)
from tilo_planning.refusal import RefusalConfigError, TaskRefused
from tilo_planning.scenarios import ScenarioError, load_scenario
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.replay import ReplayMissError
from tilo_providers.router import Router

from tilo_api import deps, quick
from tilo_api.assistant.metering import SpendLedger
from tilo_api.deps import get_safety  # the dependency key tests and callers override
from tilo_api.tasks import create_task

router = APIRouter()
logger = logging.getLogger("tilo_api.intake")

_store = InMemoryArtifactStore()


def get_store() -> InMemoryArtifactStore:
    return _store


@router.post("/intake", status_code=201)
async def intake(
    http: Request,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    safety: Annotated[SafetyProvider, Depends(get_safety)],  # before any store: fail closed first
    store: Annotated[InMemoryArtifactStore, Depends(get_store)],
    tasks: Annotated[deps.Store, Depends(deps.get_store)],
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    model_router: Annotated[Router, Depends(deps.get_router)],
    flags: Annotated[FlagStore, Depends(deps.get_switches)],
    work_mode: Annotated[deps.Mode, Depends(deps.get_work_mode)],
    allowance: Annotated[SpendLedger, Depends(deps.get_spend_ledger)],
    text: Annotated[str, Form()] = "",
    scenario: Annotated[str | None, Form()] = None,
    mode: Annotated[str | None, Form()] = None,  # COST-FAST-1: "quick" or "thinking" (read from the form below)
    files: Annotated[list[UploadFile], File()] = [],  # noqa: B006 (FastAPI copies defaults)
) -> Any:
    deps.refuse_if_replay_only(flags)  # NFR-24: after sign-in, before any work
    chosen = (await http.form()).getlist("mode")  # exactly one of quick or thinking; two fields are never resolved
    if len(chosen) > 1 or (chosen and chosen[0] not in ("quick", "thinking")):
        return _rejected("The mode must be quick or thinking.")  # the value is never echoed
    if scenario is not None:  # FR-INT-11: an unknown or hostile id stores nothing; nothing is created at intake
        try:
            await run_in_threadpool(load_scenario, scenario)
        except ScenarioError:
            return _rejected("That scenario is not available.")
    if len(files) > MAX_FILES:
        return _rejected(f"{len(files)} files attached; the limit is {MAX_FILES}.")
    uploads, remaining = [], MAX_TOTAL_BYTES
    for upload in files:
        content = await upload.read(remaining + 1)  # never hold more than the limit in memory
        remaining -= len(content)
        if remaining < 0:
            return _rejected(f"The files total more than {MAX_TOTAL_BYTES // 1_000_000} MB.")
        uploads.append(IntakeFile(filename=upload.filename or "", content=content))
    request = IntakeRequest(text=text, files=uploads, user_id=principal.user_id)
    try:
        # CPU-bound extraction and blocking screen and model calls stay off the event loop.
        await run_in_threadpool(screen_task_text, request, safety=safety)
        if chosen and chosen[0] == "quick":  # COST-FAST-1: the rules answer, offer Thinking, or call the cheap role
            return await _quick(
                http, request, principal.user_id, safety, model_router, allowance, flags, work_mode, scenario
            )
        # The Director reads only the screened text, and runs before anything is stored: a failure leaves no
        # artifacts without a task (BQ-99).
        try:
            extraction = await run_in_threadpool(extract_brief, text, router=model_router)
        except TaskRefused as refused:
            # FR-INT-12: configured text only (reason, nearest task, category); nothing stored, no further call.
            return JSONResponse(
                status_code=422,
                content={"error": refused.reason, "alternative": refused.alternative, "category": refused.category},
            )
        except NothingPossible as nothing:
            # FR-INT-15: acceptable but nothing Tilo can do; plain, with the alternatives, never a refusal.
            return JSONResponse(
                status_code=422, content={"error": nothing.message, "gaps": [g.as_dict() for g in nothing.gaps]}
            )
        except RefusalConfigError as exc:  # fail closed: no refusal list or gap list, no brief
            logger.error("refusal config unusable: %s", exc)
            raise HTTPException(status_code=503, detail="Task screening is unavailable; nothing was stored.") from exc
        except BriefExtractionError as exc:
            # A category only: the error text can quote the model's output.
            logger.warning("brief extraction failed: %s", type(exc.__cause__ or exc).__name__)
            deps.raise_if_model_unavailable(exc)
            raise HTTPException(status_code=502, detail="The Director could not draft a brief.") from exc
        result = await run_in_threadpool(submit_intake, request, safety=safety, store=store)
    except IntakeRejected as exc:
        return _rejected(exc.reason)
    except (ProviderError, ProviderConfigError, ReplayMissError) as exc:
        logger.warning("safety screen failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="The safety screen is unavailable; nothing was stored.") from exc
    task_id, task = await run_in_threadpool(create_task, tasks, writer, result, extraction, scenario=scenario)
    body = asdict(result)  # per-file text and events stay server-side
    body["files"] = [{k: v for k, v in f.items() if k not in ("text", "events")} for f in body["files"]]
    questions = [
        {"field": q.field, "text": q.text, "suggested_answers": list(q.suggested_answers)} for q in task.questions
    ]
    return {
        **body,
        "mode": "thinking",
        "task_id": task_id,
        "brief": task.brief,
        "questions": questions,
        "scenario": scenario,
        "gaps": [g.as_dict() for g in task.gaps],
    }


async def _quick(
    http: Request,
    request: IntakeRequest,
    uid: str,
    safety: SafetyProvider,
    model_router: Router,
    allowance: SpendLedger,
    flags: FlagStore,
    work_mode: deps.Mode,
    scenario: str | None,
) -> JSONResponse:
    """COST-FAST-1: nothing is created or stored; the body is the answer or the offer to switch to Thinking."""
    try:
        body = await run_in_threadpool(
            quick.respond, text=request.text, uid=uid, has_files=bool(request.files), scenario=scenario,
            safety=safety, router=model_router, allowance=allowance, switches=flags, mode=work_mode,
            caps=deps.caps_for(http), key=http.headers.get("idempotency-key"),
        )  # fmt: skip
    except quick.QuickRefusal as refusal:
        return JSONResponse(status_code=refusal.status, content={"error": refusal.message})
    return JSONResponse(body)


def _rejected(reason: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": reason})
