"""The CP2 planning flow after intake (FR-INT-03..08; PRD 7.1, 10.1; services/api/tests/API_CL_INT_1.md):
answer the questions, get the approaches, approve one with a budget cap.

Every route needs the signed-in principal, and only the task's creator may use it: anyone else gets the same
404 as an unknown task, before any model call. Model calls go through the provider layer's Router; the grant
is `tilo_planning.budget` run through the deterministic policy engine, never a model. Events are built and
validated by `tilo_planning`, and every one of them is committed through `EventWriter.append` (ADR-0026 decision 4):
the writer assigns `seq`, and `TaskRecord.next_seq` is only the helpers' `seq=` hint, derived from what was committed.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, date, datetime
from typing import Annotated, Any

import tilo_planning.budget as budget
import tilo_policy
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tilo_metering.flags import FlagStore
from tilo_planning.approaches import ApproachProposalError, propose_approaches
from tilo_planning.brief import BriefValidationError, ExtractionResult, edit_brief_field
from tilo_planning.events import build_event
from tilo_planning.intake import IntakeResult
from tilo_planning.questions import apply_answer, generate_questions, record_assumption
from tilo_planning.scenarios import ScenarioError, load_scenario
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


def _saved(
    store: deps.Store,
    writer: deps.EventWriter | None,
    task_id: str,
    task: deps.TaskRecord,
    parts: list[dict[str, Any]],
    changes: dict[str, Any],
    **records: Any,
) -> deps.TaskRecord:
    """The task with `changes` applied, saved with its event parts through `Store.save` (ADR-0026 decisions 3, 4): the
    store's records change only when that returns, so a refused request changes nothing. `next_seq` is only the helpers'
    `seq=` hint, moved past the parts; the writer assigns the real `seq`."""
    new = dataclasses.replace(task, next_seq=task.next_seq + len(parts), **changes)  # shares the task's lock
    store.save(writer, tasks={task_id: new}, parts={task.world_id: parts} if parts else None, **records)
    return new


def create_task(
    store: deps.Store,
    writer: deps.EventWriter,
    intake: IntakeResult,
    extraction: ExtractionResult,
    scenario: str | None = None,
) -> tuple[str, deps.TaskRecord]:
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
    task.scenario, task.gaps = scenario, extraction.gaps
    asked = generate_questions(
        draft, extraction.ambiguous_fields, memory=store.memory, base=_base(task, DIRECTOR), seq=task.next_seq
    )
    task.draft = task.brief = asked.brief
    task.questions = asked.questions
    parts = [*intake_events, *asked.memory_hit_events, *([asked.event] if asked.event else [])]
    task.next_seq = len(parts) + 1
    world = deps.WorldRecord(owner=owner, districts={}, run_id=task.run_id)
    created = [("worlds", task.world_id), ("tasks", intake.task_id)]
    store.save(
        writer,
        worlds={task.world_id: world},
        tasks={intake.task_id: task},
        parts={task.world_id: parts},
        create=created,
    )
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
    except (ProviderError, ProviderConfigError, ReplayMissError) as exc:
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
WriterDep = Annotated[deps.EventWriter, Depends(deps.get_event_writer)]
FlagsDep = Annotated[FlagStore, Depends(deps.get_switches)]  # deployed: NFR-24's flag or the spend ledger's switch


@router.post("/tasks/{task_id}/answers")
def answer_questions(
    task_id: str,
    principal: Principal,
    body: Annotated[AnswersIn, Depends(_json_body(AnswersIn))],
    store: StoreDep,
    safety: Annotated[SafetyProvider, Depends(deps.get_safety)],
    flags: FlagsDep,
) -> dict[str, Any]:
    """FR-INT-03/04: answers, skips (`answer: null`, recorded as "Assumed: ...") and chip edits, every typed
    string screened first (FR-INT-02). No model call; a refused request changes nothing."""
    task = _owned(store, task_id, principal)
    deps.refuse_if_replay_only(flags)  # NFR-24: after sign-in and the owner check
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
        changes: dict[str, Any] = {"answers": answers, "edits": edits, "brief": brief}
        if brief != task.brief:
            changes["approaches"] = None  # proposed for the old brief
        _saved(store, None, task_id, task, [], changes)
    return {"brief": brief}


@router.get("/tasks/{task_id}/approaches")
def get_approaches(
    task_id: str,
    principal: Principal,
    store: StoreDep,
    writer: WriterDep,
    model_router: Annotated[Router, Depends(deps.get_router)],
    flags: FlagsDep,
) -> dict[str, Any]:
    """FR-INT-06: the Director's 2-3 approaches for the confirmed brief, proposed once per brief."""
    task = _owned(store, task_id, principal)
    deps.refuse_if_replay_only(flags)  # NFR-24: this reaches the Director
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
                result = propose_approaches(
                    task.brief, router=model_router, base=base, seq=task.next_seq, gaps=task.gaps
                )
            except ApproachProposalError as exc:
                deps.raise_if_model_unavailable(exc)
                raise HTTPException(status_code=502, detail="The Director could not propose approaches.") from exc
            task = _saved(store, writer, task_id, task, [result.event], {"approaches": result.approaches})
        assert task.approaches is not None
        approaches = task.approaches
    # Default (PRD silent, BQ-83): the cheapest approach is recommended; ties keep the Director's order.
    recommended = min(approaches, key=lambda a: a["credits"]["max"])["id"]
    return {"task_id": task_id, "approaches": approaches, "recommended": recommended, "credit_usd": credit_usd}


def _load_scenario(task: deps.TaskRecord) -> Any:
    if task.scenario is None:
        return None
    try:
        return load_scenario(task.scenario)
    except ScenarioError as exc:
        logger.warning("a task's scenario no longer loads")  # never the error's text: it can carry file values
        raise HTTPException(status_code=503, detail="The scenario could not be loaded; nothing changed.") from exc


def _scenario_policies(
    task: deps.TaskRecord, scenario: Any, first_seq: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """FR-INT-11: the scenario's autonomy entries as the owner's own policies with one `policy.changed` each (only
    the owner creates a policy, PRD 10.1). Everything is built here and nothing is stored, so a failure leaves no
    partial state and an approve can be retried."""
    if scenario is None:
        return [], []
    at, owner = now_ts(), task.owner
    policies = scenario.policies(owner=owner, at=at)
    events = [
        build_event(
            _base(task, owner), seq=first_seq + offset, type="policy.changed", target=policy["id"], item=None,
            severity="info", tool=None, cause=None, authz={"by": "person", "ref": owner, "at": at},
            data={"policy_id": policy["id"], "change": "created", "level": policy["level"]},
            summary=f"Scenario policy created: {policy['action_type']} at {policy['level']}.",
        )
        for offset, policy in enumerate(policies)
    ]  # fmt: skip
    return policies, events


@router.post("/tasks/{task_id}/approve")
def approve(
    task_id: str,
    principal: Principal,
    body: Annotated[ApproveIn, Depends(_json_body(ApproveIn))],
    store: StoreDep,
    writer: WriterDep,
    seams: Annotated[runs.Seams | None, Depends(runs.run_seams)],
    flags: FlagsDep,
) -> dict[str, Any]:
    """FR-INT-08: the owner picks an approach and confirms a cap; the grant is exactly that cap (#106). An L3
    policy may grant it; otherwise the owner's own confirmation does (PRD 10.1, 10.4). The grant then starts
    the task's one run (CL-INT-2); a run that cannot start never changes this answer."""
    task = _owned(store, task_id, principal)
    deps.refuse_if_replay_only(flags)  # NFR-24: after sign-in and the owner check, before any grant
    getattr(store, "admit_run", lambda: None)()  # a demo may have only a few runs at once (DEMO-EPHEMERAL-1)
    if body.budget_cap > (ceiling := deps.budget_cap_ceiling()):  # finite already: the body refuses NaN and Infinity
        raise HTTPException(status_code=422, detail=f"One run may use at most {ceiling:g} credits.")
    with store.grant_lock(task.owner), task.lock:  # always in this order: the owner's grants, then the task
        if task.granted:
            raise HTTPException(status_code=409, detail="This task's budget is already approved.")
        if task.approaches is None:
            raise HTTPException(status_code=409, detail="Get the approaches first.")
        if body.approach_id not in {a["id"] for a in task.approaches}:
            raise HTTPException(status_code=422, detail="Pick one of the proposed approaches.")
        preload = _load_scenario(task)  # before anything changes: a scenario that no longer loads stops the approval
        now, base, cap = now_ts(), _base(task, task.owner), body.budget_cap
        # the earlier grants and the policies are read across all of the owner's worlds
        store.load_owner(task.owner, settle=True)
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
        policies, policy_events = _scenario_policies(task, preload, event["seq"] + 1)  # built before anything is stored
        approach = next(a for a in task.approaches if a["id"] == body.approach_id)
        # One save: the grant, its policy events, the policies and the task, or none of them (ADR-0026 decision 3).
        task = _saved(
            store, writer, task_id, task, [event, *policy_events], {"granted": True},
            policies={p["id"]: p for p in policies}, policy_worlds={p["id"]: task.world_id for p in policies},
        )  # fmt: skip
    if seams is not None:
        try:
            runs.start_run(store, task, approach=approach, budget_cap=cap, seams=seams)
        except Exception:
            logger.exception("the run for task %s did not start", task_id)
    return {"world_id": task.world_id}
