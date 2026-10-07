"""`POST /v1/assistant/ask` (section 1). The person is the signed-in principal and nothing the body, the question,
a record or a model reply says. Every row and target the panel names passes the PPL-10 oracle as that person
(`gate`), a refused id and an unknown id answer alike, and the question and answer text live only in the redacted
raw archive: the events carry ids, counts and outcomes (PE-12). Rules and templates answer; a model, when one is
wired, only picks a fact intent or proposes a navigate action that code vets."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from tilo_archive import RunArchive
from tilo_metering.flags import FlagStore
from tilo_people.directory import Directory
from tilo_people.stores import PeopleStores
from tilo_policy.schemas import conforms

from tilo_api import deps, desk, events
from tilo_api.assistant.config import AssistantConfig
from tilo_api.assistant.core import UNAVAILABLE, Answer, Ask, Decider, ModelDecision, answer
from tilo_api.assistant.facts import Line
from tilo_api.assistant.gate import Ref, RefGate, screen_of
from tilo_api.people_access import SourceOwners, read_as

logger = logging.getLogger("tilo_api.assistant.route")
router = APIRouter()
MAX_BODY = 8192
_ROUTE = re.compile(r"/[A-Za-z0-9._~%/-]{0,199}")
_RECORD = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ASKED = "A question was asked in the assistant panel."
_SUMMARY = {
    "navigated": "The assistant opened a screen.",
    "declined": "The assistant declined.",
    "failed": "The assistant could not answer.",
}
_HIT = "The assistant reused an earlier answer."


@dataclass(frozen=True)
class Question:
    text: str
    route: str
    record: str | None
    conversation_id: str | None


class _Refused(Exception):
    def __init__(self, status: int, error: str) -> None:
        self.status, self.error = status, error


def _strict(constant: str) -> Any:
    raise ValueError("not JSON")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out = dict(pairs)
    if len(out) != len(pairs):
        raise ValueError("duplicate key")
    return out


def _parse(raw: bytes, config: AssistantConfig) -> Question:
    """Section 1 "Request": strict JSON (no NaN, no duplicate keys), exactly the documented keys."""
    try:
        body = json.loads(raw.decode("utf-8"), parse_constant=_strict, object_pairs_hook=_pairs)
    except (ValueError, RecursionError):
        raise _Refused(422, "bad_body") from None
    if type(body) is not dict or not {"question", "context"} <= set(body) <= {"question", "context", "conversation_id"}:
        raise _Refused(422, "bad_body")
    text = body["question"]
    if type(text) is not str:
        raise _Refused(422, "bad_body")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise _Refused(422, "bad_body") from None
    if not 1 <= len(text) <= config.question_max_chars or not text.strip():
        raise _Refused(422, "question_length")
    ctx = body["context"]
    if type(ctx) is not dict or not {"route", "record"} <= set(ctx) <= {"route", "record", "label"}:
        raise _Refused(422, "bad_context")
    route, record, label = ctx["route"], ctx["record"], ctx.get("label", "")
    if (
        type(route) is not str
        or not _ROUTE.fullmatch(route)
        or not (record is None or (type(record) is str and _RECORD.fullmatch(record)))
        or type(label) is not str
        or len(label) > 120
    ):
        raise _Refused(422, "bad_context")
    conversation = body.get("conversation_id")
    if conversation is not None and not (
        type(conversation) is str and conforms("common.schema.json#/$defs/ulid", conversation)
    ):
        raise _Refused(422, "bad_conversation")
    return Question(text, route, record, conversation)


async def _read(request: Request, principal: deps.Principal, config: AssistantConfig) -> Question:
    if principal.channel not in ("web", "mobile_web"):
        raise _Refused(403, "channel")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise _Refused(415, "content_type")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise _Refused(413, "too_large")
        chunks.append(chunk)
    return _parse(b"".join(chunks), config)


def _archive_opener(request: Request) -> Callable[..., RunArchive]:
    """`deps.get_run_archive` refuses with NotImplementedError until the raw archive is wired: answer 503."""
    provider = request.app.dependency_overrides.get(deps.get_run_archive, deps.get_run_archive)
    try:
        return provider()
    except NotImplementedError:
        raise HTTPException(status_code=503, detail="not_configured") from None


def _part(
    user: str, kind: str, summary: str, data: dict[str, Any], *, actor: str, credits: float = 0, **more: Any
) -> dict[str, Any]:
    """An unstamped event part of the person's Desk world; the writer stamps seq, ts and run id."""
    return {
        "id": events.new_part_id(),
        "type": kind,
        "actor": actor,
        "target": user,
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": credits,
        "summary": summary,
        "cause": more.pop("cause", None),
        "vis": "all",
        "authz": None,
        "data": data,
        **more,
    }


def _failed(config: AssistantConfig) -> Answer:
    return Answer("failed", "rules", (Line(config.declines["failed"], None),), None, "failed", None, None)


def _plate_of(source: deps.PlateSource, user: str, now: str) -> dict[str, Any]:
    plate = source.build(user, now)
    if not conforms("plate.schema.json", plate) or plate["user"] != user:
        raise ValueError("plate does not conform")
    return plate


def _finished(people: PeopleStores, gate: RefGate, org: str, user: str) -> Callable[[], list[Mapping[str, Any]]]:
    """FR-PA-08: the person's own work items as the oracle shows them to them (one owner-index read per request)."""

    def read() -> list[Mapping[str, Any]]:
        views = (gate.record(Ref("work_item", s.record["id"])) for s in people.work_items.list(org, "owner", user))
        return [v for v in views if v is not None]

    return read


def _sources(lines: tuple[Line, ...]) -> list[dict[str, str]]:
    seen: list[dict[str, str]] = []
    for line in lines:
        if line.source is not None and line.source.json() not in seen:
            seen.append(line.source.json())
    return seen[:20]


def _model_cost(d: ModelDecision | None) -> dict[str, Any]:
    if d is None:
        return {"model_calls": 0, "credits": 0.0, "saved_credits": 0.0}
    if d.cached:
        return {"model_calls": 0, "credits": 0.0, "saved_credits": float(d.saved)}
    return {"model_calls": d.model_calls, "credits": float(d.credits), "saved_credits": 0.0}


def _handle(
    q: Question,
    user: str,
    *,
    config: AssistantConfig,
    store: deps.Store,
    writer: deps.EventWriter,
    open_archive: Callable[..., RunArchive],
    people: PeopleStores,
    plates: deps.PlateSource,
    owners: SourceOwners,
    decider: Decider | None,
    replay_only: bool,
) -> dict[str, Any]:
    now = events.now()
    org = deps.ORG_ID
    home = desk.ensure_desk(store, org_id=org, user=user)
    conversation = q.conversation_id or events.new_part_id()
    lock = desk.lock(store, user)

    def archive_append(kind: str, payload: dict[str, Any]) -> str:
        with lock:  # the chain is per run: reopen under the lock so two questions never interleave
            return open_archive(org_id=org, run_id=home.run_id).append(kind, payload)

    def write(part: dict[str, Any]) -> dict[str, Any]:
        try:
            return writer.append(home.world_id, part)
        except Exception:
            raise HTTPException(status_code=503, detail="write_failed") from None

    try:
        asked_ref = archive_append(
            "channel_in", {"conversation_id": conversation, "question": q.text, "route": q.route, "record": q.record}
        )
    except Exception:
        raise HTTPException(status_code=503, detail="write_failed") from None
    screen = screen_of(q.route, config)
    write(
        _part(
            user,
            "assistant.asked",
            _ASKED,
            {"conversation_id": conversation, "message_ref": asked_ref, "screen": screen},
            actor=user,
        )
    )

    try:
        directory = Directory.of(s.record for s in people.persons.list(org))
        plate = _plate_of(plates, user, now)
        refs = frozenset(
            Ref(r["ref"]["kind"], r["ref"]["id"])
            for r in plate["rows"]
            if conforms("common.schema.json#/$defs/record_ref", r["ref"])
        )
        gate = RefGate(
            user=user,
            org_id=org,
            now=now,
            store=store,
            people=people,
            directory=directory,
            source_owners=owners,
            plate_refs=refs,
        )
        context = gate.context_ref(q.record, q.route)
        person = read_as(
            people,
            directory,
            actor=user,
            org_id=org,
            record_kind="person",
            record_id=user,
            now=now,
            source_owners=owners,
        )
        zone = person.get("time_zone") if person else None
    except Exception as exc:
        logger.warning("assistant.plate_unavailable %s", type(exc).__name__)
        reply = _failed(config)
    else:
        ask = Ask(user, org, now, q.text, screen, context)
        try:
            reply = answer(
                ask,
                plate=plate,
                gate=gate,
                config=config,
                time_zone=zone,
                decider=UNAVAILABLE if replay_only else decider,
                finished=_finished(people, gate, org, user),
            )
        except Exception as exc:
            logger.warning("assistant.answer_failed %s", type(exc).__name__)
            reply = _failed(config)

    d = reply.model
    called = d is not None and d.model_calls > 0 and not d.cached
    trace: dict[str, Any] | None = None
    try:
        if d is not None and called:
            role = config.model["role"]
            model_ref = archive_append(
                "model_call",
                {
                    "conversation_id": conversation,
                    "role": role,
                    "profile": d.profile,
                    "prompt": d.prompt,
                    "output": d.raw,
                    "tokens_in": d.tokens_in,
                    "tokens_out": d.tokens_out,
                },
            )
            trace = {
                "model_role": role,
                "profile": d.profile,
                "tokens_in": d.tokens_in,
                "tokens_out": d.tokens_out,
                "tool": None,
                "latency_ms": d.latency_ms,
                "archive_ref": model_ref,
            }
        text = "\n".join(line.text for line in reply.lines)
        answer_ref = archive_append(
            "channel_out",
            {"conversation_id": conversation, "outcome": reply.outcome, "decided_by": reply.decided_by, "text": text},
        )
    except Exception:
        raise HTTPException(status_code=503, detail="write_failed") from None

    cost = _model_cost(d)
    sources = _sources(reply.lines)
    summary = (
        f"The assistant answered from {len(sources)} records."
        if reply.outcome == "answered"
        else _SUMMARY[reply.outcome]
    )
    data = {
        "conversation_id": conversation,
        "message_ref": answer_ref,
        "outcome": reply.outcome,
        "decided_by": reply.decided_by,
        "sources": sources,
        "ui_action": reply.ui_action,
        "cached": bool(d is not None and d.cached),
    }
    extra = {} if trace is None else {"trace": trace}
    replied = _part(
        user,
        "assistant.replied",
        summary,
        data,
        actor="A_assistant" if reply.decided_by == "model" else "system",
        credits=cost["credits"],
        **extra,
    )
    write(replied)
    if d is not None and d.cached and d.saved > 0:  # FR-MTR-06: the saving, once, with the answer it belongs to
        saved = float(d.saved)
        write(
            _part(
                user,
                "memory.hit",
                _HIT,
                {"origin_cost": saved, "lookup_cost": 0, "saved": saved},
                actor="A_assistant",
                cause=replied["id"],
            )
        )
    return {
        "conversation_id": conversation,
        "outcome": reply.outcome,
        "decided_by": reply.decided_by,
        "cached": data["cached"],
        "text": text,
        "lines": [
            {"text": line.text, "source": None if line.source is None else line.source.json()} for line in reply.lines
        ],
        "sources": sources,
        "ui_action": reply.ui_action,
        "cost": cost,
    }


@router.post("/v1/assistant/ask", response_model=None)
async def ask_assistant(
    request: Request,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    config: Annotated[AssistantConfig, Depends(deps.get_assistant_config)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    open_archive: Annotated[Callable[..., RunArchive], Depends(_archive_opener)],
    people: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    plates: Annotated[deps.PlateSource, Depends(deps.get_plate_source)],
    owners: Annotated[SourceOwners, Depends(deps.get_panel_source_owners)],
    decider: Annotated[Decider | None, Depends(deps.get_assistant_decider)],
    flags: Annotated[FlagStore, Depends(deps.get_flag_store)],
) -> Mapping[str, Any] | JSONResponse:
    try:
        question = await _read(request, principal, config)
    except _Refused as refused:
        return JSONResponse(status_code=refused.status, content={"error": refused.error})
    return await run_in_threadpool(
        _handle,
        question,
        principal.user_id,
        config=config,
        store=store,
        writer=writer,
        open_archive=open_archive,
        people=people,
        plates=plates,
        owners=owners,
        decider=decider,
        replay_only=bool(flags.get("replay_only")),
    )
