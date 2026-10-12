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
import os
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from tilo_metering.flags import FlagStore
from tilo_planning.artifacts import InMemoryArtifactStore
from tilo_planning.brief import BriefExtractionError, extract_brief
from tilo_planning.deliverable_kinds import DeliverableKindsError, load_deliverable_kinds
from tilo_planning.gaps import NothingPossible
from tilo_planning.intake import (
    MAX_FILES,
    MAX_TOTAL_BYTES,
    IntakeFile,
    IntakeRejected,
    IntakeRequest,
    screen_intake,
    screen_task_text,
    submit_intake,
)
from tilo_planning.refusal import RefusalConfigError, TaskRefused
from tilo_planning.scenarios import ScenarioError, load_scenario
from tilo_providers.clock import Clock
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.replay import ReplayMissError
from tilo_providers.router import Router

from tilo_api import deps, ephemeral, intake_requests, quick
from tilo_api.assistant.metering import SpendLedger
from tilo_api.deps import get_safety  # the dependency key tests and callers override
from tilo_api.intake_uploads import RunUploads, UploadStorageError
from tilo_api.tasks import create_task

router = APIRouter()
logger = logging.getLogger("tilo_api.intake")

_store = InMemoryArtifactStore()


def get_store(
    request: Request = None,  # type: ignore[assignment]
    mode: Annotated[deps.Mode, Depends(deps.get_work_mode)] = "replay",
) -> InMemoryArtifactStore:
    demo = ephemeral.for_request(request) if request is not None else None
    if demo is not None:
        return demo.uploads
    if request is None or not ({"K_SERVICE", "CLOUD_RUN_JOB"} & os.environ.keys()):
        return _store
    from tilo_api.intake_uploads import RunUploads

    return RunUploads(
        org_id=deps.ORG_ID,
        artifacts=lambda: deps.get_artifact_store(request, mode),
        archive=lambda **scope: deps.get_run_archive(request)(**scope),
    )  # configured stores are opened only after the Director succeeds


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
    today: Annotated[Clock, Depends(deps.get_today)],
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
    key = http.headers.get("idempotency-key")

    async def perform() -> Any:
        return await _thinking(
            http,
            principal,
            safety,
            store,
            tasks,
            writer,
            model_router,
            flags,
            work_mode,
            today,
            allowance,
            request,
            chosen,
            scenario,
            key,
        )

    if key is None or (chosen and chosen[0] == "quick"):
        return await perform()
    return await intake_requests.once(allowance, principal.user_id, key, request, scenario, perform)


async def _thinking(
    http: Request,
    principal: deps.Principal,
    safety: SafetyProvider,
    store: InMemoryArtifactStore,
    tasks: deps.Store,
    writer: deps.EventWriter,
    model_router: Router,
    flags: FlagStore,
    work_mode: deps.Mode,
    today: Clock,
    allowance: SpendLedger,
    request: IntakeRequest,
    chosen: list[Any],
    scenario: str | None,
    key: str | None,
) -> Any:
    text = request.text
    ids = intake_requests.identifiers(principal.user_id, key)
    if key is not None and not (chosen and chosen[0] == "quick"):
        tasks.load_path({"task_id": ids[0]})
        existing = tasks.tasks.get(ids[0])
        if existing is not None:
            if existing.owner != principal.user_id:
                raise HTTPException(status_code=404, detail="No such task.")
            raise HTTPException(
                status_code=409,
                detail={"code": "intake_already_committed", "task_id": ids[0], "world_id": existing.world_id},
            )
    try:
        # CPU-bound extraction and blocking screen and model calls stay off the event loop.
        await run_in_threadpool(screen_task_text, request, safety=safety)
        if chosen and chosen[0] == "quick":  # COST-FAST-1: the rules answer, offer Thinking, or call the cheap role
            return await _quick(
                http, request, principal.user_id, safety, model_router, allowance, flags, work_mode, scenario
            )
        file_screen = None
        if request.files and isinstance(store, RunUploads):
            try:
                store.task_id = ids[0]
                await run_in_threadpool(store.bind, world_id=ids[1], run_id=ids[2], owner=principal.user_id)
            except HTTPException:
                raise
            except Exception:
                await _abort_uploads(store)
                raise HTTPException(status_code=503, detail="Upload storage is unavailable; retry.") from None
            file_screen = store.screen_file
        prepared = await run_in_threadpool(
            screen_intake, request, safety=safety, director=True, file_screen=file_screen
        )
        # The Director receives only the stored verdict; failed pre-commit attempts clean their owned versions.
        try:
            extraction = await run_in_threadpool(
                extract_brief,
                text,
                router=model_router,
                today=today(),
                source_text=prepared.source_text,
                parts=prepared.parts,
            )
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
        try:  # a bad kinds file stops the task before anything is stored, like a bad refusal list
            kinds = await run_in_threadpool(load_deliverable_kinds)
        except DeliverableKindsError as exc:
            logger.error("deliverable kinds config unusable: %s", exc)
            raise HTTPException(
                status_code=503, detail="Deliverable choices are unavailable; nothing was stored."
            ) from exc
        result = await run_in_threadpool(
            submit_intake,
            request,
            safety=safety,
            store=store,
            prepared=prepared,
            identifiers=ids,
            put_failed=not isinstance(store, RunUploads),
        )
    except IntakeRejected as exc:
        await _abort_uploads(store)
        return _rejected(exc.reason)
    except (ProviderError, ProviderConfigError, ReplayMissError) as exc:
        logger.warning("safety screen failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="The safety screen is unavailable; nothing was stored.") from exc
    except HTTPException:
        await _abort_uploads(store)
        raise
    except UploadStorageError as exc:
        await _abort_uploads(store)
        logger.warning("upload persistence failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Upload storage is unavailable; retry.") from exc
    except BaseException:
        await _abort_uploads(store)
        raise
    try:
        task_id, task = await run_in_threadpool(
            create_task, tasks, writer, result, extraction, scenario=scenario, kinds=kinds
        )
    except HTTPException:
        await _abort_uncommitted(store, tasks, ids)
        raise
    except Exception as exc:
        await _abort_uncommitted(store, tasks, ids)
        logger.warning("intake persistence failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Upload storage is unavailable; retry.") from exc
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


async def _abort_uncommitted(store: InMemoryArtifactStore, tasks: deps.Store, ids: tuple[str, str, str]) -> None:
    try:
        await run_in_threadpool(tasks.load_path, {"task_id": ids[0]})
        if ids[0] in tasks.tasks or ids[1] in tasks.worlds:
            return  # commit may have landed: retention and owner erasure keep the sources intact
    except Exception:
        return  # a failed read cannot establish that deletion is safe
    await _abort_uploads(store)


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
            caps=deps.caps_for(http), key=http.headers.get("idempotency-key"), ledger=deps.ledger_writer_for(http),
        )  # fmt: skip
    except quick.QuickRefusal as refusal:
        return JSONResponse(status_code=refusal.status, content={"error": refusal.message})
    return JSONResponse(body)


async def _abort_uploads(store: InMemoryArtifactStore) -> None:
    try:
        await run_in_threadpool(store.abort)
    except Exception as exc:
        logger.warning("upload cleanup pending: %s", type(exc).__name__)


def _rejected(reason: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": reason})
