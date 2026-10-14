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
import hashlib
import json
import logging
import threading
from collections.abc import Awaitable, Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Annotated, Any

import tilo_planning.budget as budget
import tilo_policy
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tilo_metering.flags import FlagStore
from tilo_planning.approaches import ApproachProposalError, propose_approaches
from tilo_planning.brief import BriefValidationError, ExtractionResult, edit_brief_field
from tilo_planning.deliverable_kinds import DeliverableKind, DeliverableKindsError
from tilo_planning.events import build_event
from tilo_planning.intake import IntakeResult
from tilo_planning.questions import apply_answer, generate_questions, record_assumption
from tilo_planning.scenarios import ScenarioError, load_scenario
from tilo_providers.clock import Clock
from tilo_providers.config import ProviderConfigError
from tilo_providers.diagnostics import log_caught
from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.replay import ReplayMissError
from tilo_providers.router import Router

from tilo_api import deps, runs
from tilo_api.people_writes import _capped_body

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
        raw = await _capped_body(request)
        try:
            return model.model_validate_json(raw)
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
    kinds: Sequence[DeliverableKind] | None = None,
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
        draft,
        extraction.ambiguous_fields,
        memory=store.memory,
        base=_base(task, DIRECTOR),
        seq=task.next_seq,
        topic_questions=extraction.questions,
        kinds=kinds,
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


def _latest(store: deps.Store, task_id: str) -> deps.TaskRecord:
    """The record saved last, read again after the task's lock is taken (a prefetch or a second request may have stored
    a newer one). A commit that failed evicts its entries, so this reloads from the store; gone is the unknown-task 404,
    never a KeyError."""
    task = store.load_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="No such task.")
    return task


def _brief(task: deps.TaskRecord, answers: dict[str, str | None], edits: dict[str, Any], today: date) -> dict[str, Any]:
    brief = task.draft
    for question in task.questions:
        if question.field in answers and question.field not in edits:  # an edit stands over the answer (BQ-99)
            answer = answers[question.field]
            if answer is None:
                try:
                    brief = record_assumption(brief, question, today=today)
                except BriefValidationError:  # a skip is never refused (SIMPLE-RUN-2): the guess stands as asked
                    brief = {**brief, "assumptions": [*brief["assumptions"], _assumption_line(question)]}
            else:
                brief = apply_answer(brief, question, answer, today=today)
    for field, value in edits.items():
        brief = edit_brief_field(brief, field, value, today=today)
    return brief


def _assumption_line(question: Any) -> dict[str, Any]:
    guess = question.suggested_answers[0] if question.suggested_answers else ""
    return {"question": question.text[:300], "assumed": f"{question.label or question.field}: {guess}"[:300]}


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
        log_caught(exc, __name__, locals())
        raise HTTPException(status_code=503, detail="The safety screen is unavailable; nothing changed.") from exc
    if flagged:
        raise HTTPException(status_code=422, detail="The safety screen flagged this change; rephrase it.")


def _director_strings(task: deps.TaskRecord, answers: list[AnswerIn]) -> list[str]:
    """The model-written strings an answer or a skip puts into the brief (INTAKE-QUALITY-1): the text of each Director
    question answered, and the guess a skip takes. A typed answer is screened with the person's other strings."""
    by_field = {a.field: a.answer for a in answers}
    return [
        text
        for q in task.questions
        if q.label is not None and q.field in by_field
        for text in (q.text, *([q.suggested_answers[0]] if by_field[q.field] is None else []))
    ]


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
    writer: WriterDep,
    model_router: Annotated[Router, Depends(deps.get_router)],
    safety: Annotated[SafetyProvider, Depends(deps.get_safety)],
    flags: FlagsDep,
    clock: Annotated[Clock, Depends(deps.get_today)],
) -> dict[str, Any]:
    """FR-INT-03/04: answers, skips (`answer: null`, recorded as "Assumed: ...") and chip edits, every typed
    string screened first (FR-INT-02). No model call in the request; a refused request changes nothing. Once every
    question has an answer and the brief is saved, the approaches are proposed in the background (APPROACH-SPEED),
    so GET /approaches returns the stored result or waits on that one call."""
    task = _owned(store, task_id, principal)
    deps.refuse_if_replay_only(flags)  # NFR-24: after sign-in and the owner check
    fields = [a.field for a in body.answers]
    if len(set(fields)) != len(fields) or not set(fields) <= {q.field for q in task.questions}:
        raise HTTPException(status_code=422, detail="Answer only the questions that were asked, each once.")
    if _foreign_sources(task, body.brief_edits):
        raise HTTPException(status_code=422, detail="Add only this task's files, or web and url sources.")
    typed = [a.answer for a in body.answers if a.answer is not None]
    _screen(safety, typed + _director_strings(task, body.answers) + list(_strings(body.brief_edits)))
    with task.lock:
        task = _latest(store, task_id)  # the record saved last: a prefetch may have stored the approaches meanwhile
        if task.granted:
            raise HTTPException(status_code=409, detail="The budget is approved; the brief is final.")
        answers = {**task.answers, **{a.field: a.answer for a in body.answers}}
        # The last action on a field wins (BQ-99): an answer drops the field's earlier edit; in one request the
        # edit wins, since a JSON body has no order between its answers and its edits.
        answered = {a.field for a in body.answers}
        edits = {**{f: v for f, v in task.edits.items() if f not in answered}, **body.brief_edits}
        try:
            brief = _brief(task, answers, edits, clock())
        except BriefValidationError as exc:
            raise HTTPException(status_code=422, detail=f"That change does not fit the brief: {exc}") from exc
        except DeliverableKindsError as exc:  # the file changed for the worse since the question was asked
            logger.error("deliverable kinds config unusable: %s", exc)
            raise HTTPException(
                status_code=503, detail="Deliverable choices are unavailable; nothing changed."
            ) from exc
        changes: dict[str, Any] = {"answers": answers, "edits": edits, "brief": brief}
        if brief != task.brief:
            changes["approaches"] = None  # proposed for the old brief
        saved = _saved(store, None, task_id, task, [], changes)
        if brief != task.brief:
            saved.approaches_work["version"] = saved.approaches_work.get("version", 0) + 1
        prefetch = saved.approaches is None and all(q.field in answers for q in saved.questions)
        if prefetch:
            _queue_approaches(store, writer, task_id, saved, model_router, clock)
    return {"brief": brief}


def _proposed(
    store: deps.Store,
    writer: deps.EventWriter | None,
    task_id: str,
    task: deps.TaskRecord,
    model_router: Router,
    clock: Clock,
) -> deps.TaskRecord:
    """Wait outside the task lock; concurrent GETs and answers share one bounded worker."""
    while True:
        with task.lock:
            task = _latest(store, task_id)
            if any(q.field not in task.answers for q in task.questions):
                raise HTTPException(status_code=409, detail="Answer or skip every question first.")
            if task.approaches is not None:
                return task
            work = task.approaches_work
            if work.get("computed") == work.get("version", 0):
                result = work["result"]
                return _saved(store, writer, task_id, task, [result.event], {"approaches": result.approaches})
            future = _queue_approaches(store, writer, task_id, task, model_router, clock)
            if future is None:
                raise HTTPException(status_code=503, detail="The Director is busy; try again shortly.")
        future.result()


def _compute_approaches(task: deps.TaskRecord, model_router: Router, clock: Clock) -> Any:
    try:
        result = propose_approaches(
            task.brief,
            router=model_router,
            base=_base(task, DIRECTOR),
            seq=task.next_seq,
            gaps=task.gaps,
            today=clock(),
        )
    except ApproachProposalError as exc:
        deps.raise_if_model_unavailable(exc)
        raise HTTPException(status_code=502, detail="The Director could not propose approaches.") from exc
    return result


_PREFETCH = ThreadPoolExecutor(max_workers=4, thread_name_prefix="approaches")
_PREFETCH_SLOTS = threading.BoundedSemaphore(32)  # running + queued tasks; edits never enqueue another job


def _queue_approaches(
    store: deps.Store,
    writer: deps.EventWriter | None,
    task_id: str,
    task: deps.TaskRecord,
    model_router: Router,
    clock: Clock,
) -> Future | None:
    """Called under task.lock. One future per task, including failures for the same version."""
    work = task.approaches_work
    future = work.get("future")
    version = work.get("version", 0)
    if future is not None and (not future.done() or work.get("finished") == version):
        return future
    slots = _PREFETCH_SLOTS
    if not slots.acquire(blocking=False):
        return None
    future = Future()
    work["future"] = future
    try:
        _PREFETCH.submit(_prefetch_approaches, store, writer, task_id, model_router, clock, future, slots)
    except Exception as caught_error:
        log_caught(caught_error, __name__, locals())
        work.pop("future", None)
        slots.release()
        raise
    return future


def _prefetch_approaches(
    store: deps.Store,
    writer: deps.EventWriter | None,
    task_id: str,
    model_router: Router,
    clock: Clock,
    future: Future,
    slots: threading.BoundedSemaphore,
) -> None:
    """Coalesce edits to the latest version. Compute unlocked, publish only if still current.

    Keep a computed result even if publication fails, so replay never pays to compute it twice.
    """
    task = _latest(store, task_id)
    work = task.approaches_work
    try:
        while True:
            with task.lock:
                task = _latest(store, task_id)
                version = work.get("version", 0)
                snapshot = dataclasses.replace(task, brief=copy.deepcopy(task.brief))
                if (
                    task.approaches is not None
                    or task.granted
                    or any(q.field not in task.answers for q in task.questions)
                ):
                    work["finished"] = version
                    future.set_result(None)
                    return
            result, error = None, None
            try:
                deps.providers_config()
                if work.get("computed") == version:
                    result = work["result"]
                else:
                    result = _compute_approaches(snapshot, model_router, clock)
            except Exception as exc:
                log_caught(exc, __name__, locals())
                error = exc
            with task.lock:
                task = _latest(store, task_id)
                if work.get("version", 0) != version:
                    continue  # stale result/error: no event, no cache, only the newest pending brief runs
                if error is None:
                    work.update(computed=version, result=result)
                    try:
                        _saved(store, writer, task_id, task, [result.event], {"approaches": result.approaches})
                    except Exception as exc:
                        log_caught(exc, __name__, locals())
                        error = exc
                work["finished"] = version
                if error is None:
                    future.set_result(None)
                else:
                    future.set_exception(error)
                    logger.warning("approaches prefetch for a task did not complete: %s", type(error).__name__)
                return
    finally:
        slots.release()


@router.get("/tasks/{task_id}/approaches")
def get_approaches(
    task_id: str,
    principal: Principal,
    store: StoreDep,
    writer: WriterDep,
    model_router: Annotated[Router, Depends(deps.get_router)],
    flags: FlagsDep,
    clock: Annotated[Clock, Depends(deps.get_today)],
) -> dict[str, Any]:
    """FR-INT-06: the Director's 2-3 approaches for the confirmed brief, proposed once per brief."""
    task = _owned(store, task_id, principal)
    deps.refuse_if_replay_only(flags)  # NFR-24: this reaches the Director
    try:
        credit_usd = deps.providers_config().prices.credit_usd  # before any model call is spent
    except ProviderConfigError as exc:
        logger.warning("provider config unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="The model configuration is not available.") from exc
    task = _proposed(store, writer, task_id, task, model_router, clock)
    assert task.approaches is not None
    approaches = task.approaches
    # Default (PRD silent, BQ-83): the cheapest approach is recommended; ties keep the Director's order.
    recommended = min(approaches, key=lambda a: a["credits"]["max"])["id"]
    return {
        "task_id": task_id,
        "approaches": approaches,
        "recommended": recommended,
        "credit_usd": credit_usd,
        # SIMPLE-RUN-2: the most one approval may grant, so a one-step Start sends min(estimate, ceiling), never a 422.
        "budget_ceiling": deps.budget_cap_ceiling(),
    }


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


_NOT_STARTED = (
    "Tilo could not start this run just now. Nothing was started and nothing was charged. "
    "Press Start again in a minute; if it keeps happening, the problem is on our side."
)


def _loud() -> bool:
    """Deployed, a run that cannot start is a plain 503 (SIMPLE-RUN-2). Locally and in tests the stores are often
    deliberately absent, so the long-standing answer stays: the grant is recorded and a world answers 200."""
    return deps.enforced()


def _run_started(store: deps.Store, task: deps.TaskRecord) -> bool:
    store.settle(task.world_id)
    return task.world_id in store.runs or any(e["type"] == "world.started" for e in store.events.get(task.world_id, []))


def _granted_cap(store: deps.Store, task: deps.TaskRecord, asked: float) -> float:
    """The cap this task's grant recorded, which a second Start keeps (the request's number never raises it)."""
    for event in reversed(store.events.get(task.world_id, [])):
        if event.get("type") == "budget.granted":
            try:
                return float(event["data"]["cap"])
            except (KeyError, TypeError, ValueError) as caught_error:
                log_caught(caught_error, __name__, locals())
                break
    return asked


def _start(
    store: deps.Store, task: deps.TaskRecord, *, approach: dict, budget_cap: float, seams: runs.Seams | None
) -> None:
    """Start the task's one run. A start that fails is a 503 in plain words, never a 200 onto a world that never
    moves (SIMPLE-RUN-2, LIVE-PATH-AUDIT-A finding 6). The grant stays recorded, so Start again retries only this."""
    if seams is None:
        return  # local and tests only (`_loud` refuses before this when deployed): nothing to start with
    try:
        runs.start_run(store, task, approach=approach, budget_cap=budget_cap, seams=seams)
    except Exception as exc:
        log_caught(exc, __name__, locals())
        if _loud():
            raise HTTPException(status_code=503, detail=_NOT_STARTED) from exc


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
    if _loud() and task.granted and not _run_started(store, task):
        # SIMPLE-RUN-2: the budget was approved but the run never started (it could not be wired, or the start failed):
        # Start again starts it with the grant already recorded, so the person is never stuck on "already approved".
        approach = next((a for a in task.approaches or [] if a["id"] == body.approach_id), None)
        if approach is None:
            raise HTTPException(status_code=422, detail="Pick one of the proposed approaches.")
        if seams is None:
            raise HTTPException(status_code=503, detail=_NOT_STARTED)
        _start(store, task, approach=approach, budget_cap=_granted_cap(store, task, body.budget_cap), seams=seams)
        return {"world_id": task.world_id}
    if (
        seams is None and _loud()
    ):  # SIMPLE-RUN-2: loud and before the grant, so nothing is approved or charged for a run that cannot go
        logger.error("approve refused: the run seams are not wired (task %s)", task_id)
        raise HTTPException(status_code=503, detail=_NOT_STARTED)
    getattr(store, "admit_run", lambda: None)()  # a demo may have only a few runs at once (DEMO-EPHEMERAL-1)
    if body.budget_cap > (ceiling := deps.budget_cap_ceiling()):  # finite already: the body refuses NaN and Infinity
        raise HTTPException(status_code=422, detail=f"One run may use at most {ceiling:g} credits.")
    with store.grant_lock(task.owner), task.lock:  # always in this order: the owner's grants, then the task
        task = _latest(store, task_id)  # the record saved last (a prefetch may have stored the approaches)
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
    _start(store, task, approach=approach, budget_cap=cap, seams=seams)
    return {"world_id": task.world_id}


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _again_ids(world_id: str) -> tuple[str, str, str]:
    """The ids of a world's "Start it again" run: derived from the old world, so pressing twice is one new world."""
    found = []
    for prefix in ("t", "w", "r"):
        raw = json.dumps(["/worlds/rerun", world_id, prefix], separators=(",", ":")).encode()
        number = int.from_bytes(hashlib.sha256(raw).digest()[:16], "big")
        found.append(prefix + "_" + "".join(_CROCKFORD[(number >> (5 * i)) & 31] for i in range(25, -1, -1)))
    return found[0], found[1], found[2]


@router.post("/worlds/{world_id}/rerun")
def rerun(
    world_id: str,
    principal: Principal,
    store: StoreDep,
    writer: WriterDep,
    seams: Annotated[runs.Seams | None, Depends(runs.run_seams)],
    flags: FlagsDep,
) -> dict[str, Any]:
    """RERUN-1: a world whose latest world event is the X-ORPHAN-1 restart failure is started again as a NEW run of the
    same task: the same brief, the approach the person approved and the cap they granted, through the approve path
    (so the policy engine, the ceiling and the owner's grants decide again). Only the owner; anyone else gets the
    unknown-world 404. Any other latest world event or failure reason is a 409. Pressing twice is one new world."""
    from .durable_store import STARTUP_RESTARTED

    world = store.load_world(world_id)
    if world is None or world.owner != principal.user_id:
        raise HTTPException(status_code=404, detail="No such world.")
    deps.refuse_if_replay_only(flags)  # NFR-24: after sign-in and the owner check, before anything is stored
    store.settle(world_id)
    stream = store.events.get(world_id, [])

    last = next((e for e in reversed(stream) if e["type"].startswith("world.")), None)
    if last is None or last["type"] != "world.failed" or last.get("data", {}).get("reason") != STARTUP_RESTARTED:
        raise HTTPException(status_code=409, detail="Only a run stopped by a Tilo restart can be started again.")
    old = store.load_world_task(world_id)
    planned = next((e for e in reversed(stream) if e["type"] == "world.planned"), None)
    if old is None or old.approaches is None or planned is None:
        raise HTTPException(status_code=409, detail="This world has no approved task to start again.")
    if any(src.get("kind") == "file" for src in old.brief.get("sources", [])):
        raise HTTPException(
            status_code=409,
            detail="This task used attached files, which stay with the first run. Describe it again from Home.",
        )
    task_id, new_world, new_run = _again_ids(world_id)
    # The durable store, not this process's cache: a second press on another instance (after scale to zero) finds the
    # first one's task and dedupes. Pressed twice is one new world once its run started; a first press whose start
    # failed falls through to `approve`, which starts it again with the grant it recorded (SIMPLE-RUN-2).
    again = store.load_task(task_id)
    if again is not None and again.granted and (not _loud() or _run_started(store, again)):
        return {"world_id": again.world_id, "task_id": task_id}
    cap = _granted_cap(store, old, 0.0)
    if cap <= 0:
        raise HTTPException(status_code=409, detail="This world has no approved budget to start again.")
    # What `approve` refuses before it grants is refused here first: a refusal leaves no orphan world or task.
    if seams is None and _loud():
        logger.error("rerun refused: the run seams are not wired (world %s)", world_id)
        raise HTTPException(status_code=503, detail=_NOT_STARTED)
    getattr(store, "admit_run", lambda: None)()
    if cap > (ceiling := deps.budget_cap_ceiling()):
        raise HTTPException(status_code=422, detail=f"One run may use at most {ceiling:g} credits.")
    if again is None:
        fresh = deps.TaskRecord(
            old.owner, new_world, new_run, copy.deepcopy(old.draft), copy.deepcopy(old.brief), list(old.questions), 1,
            answers=dict(old.answers), edits=copy.deepcopy(old.edits), approaches=copy.deepcopy(old.approaches),
            granted=False, scenario=old.scenario, gaps=old.gaps,
        )  # fmt: skip
        store.save(
            writer,
            worlds={new_world: deps.WorldRecord(owner=old.owner, districts={}, run_id=new_run)},
            tasks={task_id: fresh},
            create=[("worlds", new_world), ("tasks", task_id)],
        )
    body = ApproveIn(approach_id=str(planned["data"]["approach"]), budget_cap=cap)
    approve(task_id, principal, body, store, writer, seams, flags)
    return {"world_id": new_world, "task_id": task_id}
