"""The CP2 planning flow after intake (FR-INT-03..08; PRD 7.1, 10.1; services/api/tests/API_CL_INT_1.md):
answer the questions, get the approaches, approve one with a budget cap.

Every route needs the signed-in principal, and only the task's creator may use it: anyone else gets the same
404 as an unknown task, before any model call. Model calls go through the provider layer's Router; the grant
is `tilo_planning.budget` run through the deterministic policy engine, never a model. Events are built and
validated by `tilo_planning`; `Store.events` stands in for the world's stream until the harness writer is
wired, and each task appends to it in strictly increasing `seq`.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, date, datetime
from typing import Annotated, Any

import tilo_planning.budget as budget
import tilo_policy
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tilo_planning.approaches import ApproachProposalError, propose_approaches
from tilo_planning.brief import BriefValidationError, ExtractionResult, edit_brief_field
from tilo_planning.intake import IntakeResult
from tilo_planning.questions import apply_answer, generate_questions, record_assumption
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.replay import ReplayMissError
from tilo_providers.router import Router

from tilo_api import deps, runs

logger = logging.getLogger("tilo_api.tasks")
router = APIRouter()

DIRECTOR = "A_director"  # the actor of the Director's planning events
GRANT_CONNECTOR = "internal"  # a budget grant uses no connector
GRANT_DISTRICT = "world"  # a world-level grant sits in no district: only an all-district policy covers it


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    answer: Annotated[str | None, Field(max_length=300)]


class AnswersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[AnswerIn] = Field(default_factory=list)
    brief_edits: dict[str, Any] = Field(default_factory=dict)


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approach_id: str
    budget_cap: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]  # credits, the person's own


def _json_body[Body: BaseModel](model: type[Body]) -> Callable[[Request], Awaitable[Body]]:
    """Strict JSON (no NaN or Infinity), and a 422 that never echoes the input back. Only `application/json` is
    read (415 otherwise): a cross-site form or `text/plain` POST needs no CORS preflight, a JSON one does."""

    async def parse(request: Request) -> Body:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise HTTPException(status_code=415, detail="Send application/json.")
        try:
            return model.model_validate_json(await request.body())
        except ValidationError as exc:
            detail = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
            raise HTTPException(status_code=422, detail=detail) from exc

    return parse


def now_ts() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base(task: deps.TaskRecord, actor: str) -> dict[str, Any]:
    return {"v": "1.0", "ts": now_ts(), "world_id": task.world_id, "run_id": task.run_id, "actor": actor}


def _append(store: deps.Store, task: deps.TaskRecord, events: list[dict[str, Any]]) -> None:
    store.events.setdefault(task.world_id, []).extend(events)
    task.next_seq = max([task.next_seq - 1, *(e["seq"] for e in events)]) + 1


def create_task(store: deps.Store, intake: IntakeResult, extraction: ExtractionResult) -> tuple[str, deps.TaskRecord]:
    """FR-INT-03/04: the task from its intake and the Director's brief (extracted first, so a failed extraction
    stores nothing), then the questions, decided in code."""
    owner = intake.event["actor"]
    draft = copy.deepcopy(extraction.brief)
    draft["sources"] += [
        {"kind": "file", "ref": f.artifact["artifact_id"], "label": f.filename[:120]}
        for f in intake.files
        if f.status == "ok" and not f.safety_flagged  # a flagged file is quarantined: never a source (BQ-99)
    ]
    intake_events = [intake.event, *(e for f in intake.files for e in f.events)]
    task = deps.TaskRecord(owner, intake.world_id, intake.run_id, draft, draft, [], len(intake_events) + 1)
    asked = generate_questions(
        draft, extraction.ambiguous_fields, memory=store.memory, base=_base(task, DIRECTOR), seq=task.next_seq
    )
    task.draft = task.brief = asked.brief
    task.questions = asked.questions
    store.worlds[task.world_id] = deps.WorldRecord(owner=owner, districts={}, run_id=task.run_id)
    _append(store, task, [*intake_events, *asked.memory_hit_events, *([asked.event] if asked.event else [])])
    store.tasks[intake.task_id] = task
    return intake.task_id, task


def _owned(store: deps.Store, task_id: str, principal: deps.Principal) -> deps.TaskRecord:
    task = store.tasks.get(task_id)
    if task is None or task.owner != principal.user_id:  # PRD 10.1: no oracle for another user's task
        raise HTTPException(status_code=404, detail="No such task.")
    return task


def _brief(task: deps.TaskRecord, answers: dict[str, str | None], edits: dict[str, Any]) -> dict[str, Any]:
    brief, today = task.draft, date.today()
    for question in task.questions:
        if question.field in answers and question.field not in edits:  # an edit stands over the answer (BQ-99)
            answer = answers[question.field]
            if answer is None:
                brief = record_assumption(brief, question)
            else:
                brief = apply_answer(brief, question, answer, today=today)
    for field, value in edits.items():
        brief = edit_brief_field(brief, field, value)
    return brief


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict | list):
        for item in value.values() if isinstance(value, dict) else value:
            yield from _strings(item)


def _screen(safety: SafetyProvider, strings: list[str]) -> None:
    """PRD 16.3 items 1-2: what a person adds to the brief reaches the Director, so it is screened first."""
    if not strings:
        return
    try:
        flagged = safety.check("\n".join(strings))["flagged"]
    except (ProviderError, ReplayMissError) as exc:
        raise HTTPException(status_code=503, detail="The safety screen is unavailable; nothing changed.") from exc
    if flagged:
        raise HTTPException(status_code=422, detail="The safety screen flagged this change; rephrase it.")


def _foreign_sources(task: deps.TaskRecord, edits: dict[str, Any]) -> bool:
    """PRD 10.1: a file, connector or memory source must already be this task's (its own uploads, or what code
    applied); a person may add only url and web sources."""
    sources = edits.get("sources")
    if not isinstance(sources, list):
        return False  # the brief's own validation refuses it
    known = {(s["kind"], s["ref"]) for s in task.draft["sources"]}
    added = [(s.get("kind"), s.get("ref")) for s in sources if isinstance(s, dict)]
    return any(kind in ("file", "connector", "memory") and (kind, ref) not in known for kind, ref in added)


Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]
StoreDep = Annotated[deps.Store, Depends(deps.get_store)]


@router.post("/tasks/{task_id}/answers")
def answer_questions(
    task_id: str,
    principal: Principal,
    body: Annotated[AnswersIn, Depends(_json_body(AnswersIn))],
    store: StoreDep,
    safety: Annotated[SafetyProvider, Depends(deps.get_safety)],
) -> dict[str, Any]:
    """FR-INT-03/04: answers, skips (`answer: null`, recorded as "Assumed: ...") and chip edits, every typed
    string screened first (FR-INT-02). No model call; a refused request changes nothing."""
    task = _owned(store, task_id, principal)
    fields = [a.field for a in body.answers]
    if len(set(fields)) != len(fields) or not set(fields) <= {q.field for q in task.questions}:
        raise HTTPException(status_code=422, detail="Answer only the questions that were asked, each once.")
    if _foreign_sources(task, body.brief_edits):
        raise HTTPException(status_code=422, detail="Add only this task's files, or web and url sources.")
    _screen(safety, [a.answer for a in body.answers if a.answer is not None] + list(_strings(body.brief_edits)))
    with task.lock:
        if task.granted:
            raise HTTPException(status_code=409, detail="The budget is approved; the brief is final.")
        answers = {**task.answers, **{a.field: a.answer for a in body.answers}}
        # The last action on a field wins (BQ-99): an answer drops the field's earlier edit; in one request the
        # edit wins, since a JSON body has no order between its answers and its edits.
        answered = {a.field for a in body.answers}
        edits = {**{f: v for f, v in task.edits.items() if f not in answered}, **body.brief_edits}
        try:
            brief = _brief(task, answers, edits)
        except BriefValidationError as exc:
            raise HTTPException(status_code=422, detail=f"That change does not fit the brief: {exc}") from exc
        if brief != task.brief:
            task.approaches = None  # proposed for the old brief
        task.answers, task.edits, task.brief = answers, edits, brief
    return {"brief": brief}


@router.get("/tasks/{task_id}/approaches")
def get_approaches(
    task_id: str, principal: Principal, store: StoreDep, model_router: Annotated[Router, Depends(deps.get_router)]
) -> dict[str, Any]:
    """FR-INT-06: the Director's 2-3 approaches for the confirmed brief, proposed once per brief."""
    task = _owned(store, task_id, principal)
    try:
        credit_usd = deps.providers_config().prices.credit_usd  # before any model call is spent
    except ProviderConfigError as exc:
        logger.warning("provider config unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="The model configuration is not available.") from exc
    with task.lock:
        if any(q.field not in task.answers for q in task.questions):
            raise HTTPException(status_code=409, detail="Answer or skip every question first.")
        if task.approaches is None:
            try:
                base = _base(task, DIRECTOR)
                result = propose_approaches(task.brief, router=model_router, base=base, seq=task.next_seq)
            except ApproachProposalError as exc:
                raise HTTPException(status_code=502, detail="The Director could not propose approaches.") from exc
            _append(store, task, [result.event])
            task.approaches = result.approaches
        approaches = task.approaches
    # Default (PRD silent, BQ-83): the cheapest approach is recommended; ties keep the Director's order.
    recommended = min(approaches, key=lambda a: a["credits"]["max"])["id"]
    return {"task_id": task_id, "approaches": approaches, "recommended": recommended, "credit_usd": credit_usd}


@router.post("/tasks/{task_id}/approve", dependencies=[Depends(deps.require_live_work)])
def approve(
    task_id: str,
    principal: Principal,
    body: Annotated[ApproveIn, Depends(_json_body(ApproveIn))],
    store: StoreDep,
    seams: Annotated[runs.Seams | None, Depends(runs.run_seams)],
) -> dict[str, Any]:
    """FR-INT-08: the owner picks an approach and confirms a cap; the grant is exactly that cap (#106). An L3
    policy may grant it; otherwise the owner's own confirmation does (PRD 10.1, 10.4). The grant then starts
    the task's one run (CL-INT-2); a run that cannot start never changes this answer."""
    task = _owned(store, task_id, principal)
    if body.budget_cap > (ceiling := deps.budget_cap_ceiling()):  # finite already: the body refuses NaN and Infinity
        raise HTTPException(status_code=422, detail=f"One run may use at most {ceiling:g} credits.")
    with store.grant_lock(task.owner), task.lock:  # always in this order: the owner's grants, then the task
        if task.granted:
            raise HTTPException(status_code=409, detail="This task's budget is already approved.")
        if task.approaches is None:
            raise HTTPException(status_code=409, detail="Get the approaches first.")
        if body.approach_id not in {a["id"] for a in task.approaches}:
            raise HTTPException(status_code=422, detail="Pick one of the proposed approaches.")
        now, base, cap = now_ts(), _base(task, task.owner), body.budget_cap
        owned = {w for w, record in store.worlds.items() if record.owner == task.owner}
        earlier = [e for w in owned for e in store.events.get(w, []) if e.get("type") == "budget.granted"]
        outcome = budget.request_budget_grant(
            cap, table=tilo_policy.load_risk_table(), policies=list(store.policies.values()), world_owner=task.owner,
            earlier_grants=earlier, now=now, base=base, seq=task.next_seq, connector=GRANT_CONNECTOR,
            district=GRANT_DISTRICT,
        )  # fmt: skip
        try:
            event = outcome.granted_event or budget.grant_budget_by_person(
                cap, world_owner=task.owner, user=principal.user_id, now=now, base=base, seq=task.next_seq
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Only the world's owner sets budgets.") from exc
        _append(store, task, [event])
        task.granted = True
        approach = next(a for a in task.approaches if a["id"] == body.approach_id)
    if seams is not None:
        try:
            runs.start_run(store, task, approach=approach, budget_cap=cap, seams=seams)
        except Exception:
            logger.exception("the run for task %s did not start", task_id)
    return {"world_id": task.world_id}
