"""Capture a skill by describing it, and Tilo's version of it (SKILLS-4, FR-SKL-01 and FR-SKL-02, text path;
ADR-0034 decisions 3 and 4; taught_skill.rules.md TS-03, TS-04, TS-11).

`POST /v1/skills/captures` {method: "describe", text} turns the words into captured steps (one model call) and stores a
DRAFT taught-skill record in the skill store (status `draft`, the empty plan the schema allows; its id is `tsk_...`
because the events name the skill). `POST /v1/skills/captures/{id}/version` turns the captured steps into Tilo's
version (a second call): plan steps, at most one question. The description and the steps are untrusted text; a model's
reply is untrusted data: it is checked against a closed schema, a tool or action that config/connectors.yaml does not
list is dropped, and code alone sets `must_ask`, `ask_first` and the estimates (the same code as `POST /v1/skills`).
One `skill.captured` event per captured step and one `skill.version_proposed`, ids and counts only, in the owner's
Desk world. A failed model call, an invalid or unsafe reply is a fixed 502 `draft_failed`; none of its words are echoed.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from tilo_memory.artifacts import ArtifactStore, Scope
from tilo_metering.flags import FlagStore
from tilo_planning.artifacts import new_ulid
from tilo_policy.schemas import conforms
from tilo_providers.interfaces import GenerateRequest, SafetyProvider
from tilo_providers.media import MediaPart
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.router import Router
from tilo_providers.schema_guard import first_error

from tilo_api import deps, events, skills_understand
from tilo_api.connectors_list import _optional_views
from tilo_api.people import _PeopleRoute
from tilo_api.people_events import _DESK_WORLD, WorkEvents, get_work_events
from tilo_api.people_writes import Refusal, Writer, _capped_body, _Closed, json_body
from tilo_api.skill_store import SkillStore
from tilo_api.skills_routes import (
    _SKILL_ID,
    _guarded,
    _now,
    _teams,
    estimates_for,
    load_skill_config,
    plan_steps,
)

logger = logging.getLogger("tilo_api.skills_capture")
router = APIRouter(route_class=_PeopleRoute)

CAPTURE_ROLE = "skill_capture"  # the one place (ADR-0034 decision 3); config/models.yaml names its profiles
_MAX_TEXT = 4000
_DROPPED = frozenset(
    {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}
)  # control, format (zero-width), line/paragraph separators
_JOINED = re.compile(
    r"\band\s+(?:what|which|who|whom|whose|when|where|how|why|should|do|does|did|can|could|would|will|is|are)\b", re.I
)
_GOOGLE_DEFAULTS = ("gmail", "google_drive", "google_calendar")  # the sign-in tools every person has (TEACH-PAIRS)
_LINE = {"type": "string", "minLength": 1, "maxLength": 200, "pattern": "^[^\\r\\n]+$"}
_VERBS = ["read", "draft", "write", "send", "post", "pay", "delete", "share", "book"]
_CAPTURE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["steps"],
    "properties": {
        "steps": {
            "type": "array",
            "minItems": 3,
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text"],
                "properties": {"text": _LINE},
            },
        }
    },
}
_VERSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["steps", "question"],
    "properties": {
        "inputs": {"type": "array", "maxItems": 8, "items": {"type": "object"}},  # TS-19: code keeps the valid slots
        "hosts": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 253}},  # TS-18
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "tool", "action", "verb"],
                "properties": {
                    "text": _LINE,
                    "tool": {"type": "string", "maxLength": 64},
                    "action": {"type": "string", "maxLength": 64},
                    "verb": {"enum": _VERBS},
                },
            },
        },
        "question": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "options"],
                    "properties": {
                        "text": _LINE,
                        "options": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 4,
                            "items": {"type": "string", "minLength": 1, "maxLength": 60, "pattern": "^[^\\r\\n]+$"},
                        },
                    },
                },
            ]
        },
    },
}


class ArtifactRefIn(_Closed):
    artifact_id: Annotated[str, Field(min_length=1, max_length=64)]
    version: Annotated[int, Field(ge=1)]


class CaptureIn(_Closed):
    method: Literal["describe"]
    text: Annotated[str, Field(min_length=1, max_length=_MAX_TEXT)]
    documents: Annotated[list[ArtifactRefIn], Field(max_length=skills_understand.MAX_DOCUMENTS)] | None = None


class _Failed(Exception):
    """The model's part failed (call, reply or output); the cause is never shown."""


def _draft_failed() -> HTTPException:
    return HTTPException(status_code=502, detail="draft_failed")


def _not_understood() -> Refusal:
    return Refusal(422, "not_understood")


def _description(raw: str, redact: Callable[[str], str]) -> str:
    """NFKC, then no control, format or separator character (a line break and a tab stay), then the secret redactor."""
    folded = unicodedata.normalize("NFKC", raw.replace("\r\n", "\n").replace("\r", "\n"))
    text = "".join(" " if c == "\t" else c for c in folded if c in "\n\t" or unicodedata.category(c) not in _DROPPED)
    text = redact(text.strip()).strip()
    if not text or len(text) > _MAX_TEXT:
        raise _not_understood()
    return text


def _flagged(safety: SafetyProvider, text: str) -> bool:
    try:
        return bool(safety.check(text)["flagged"])
    except Exception:
        raise HTTPException(status_code=503, detail="unavailable") from None  # a screen that is down never passes


def _ask(
    router: Router, system: str, prompt: str, schema: dict[str, Any], parts: list[MediaPart] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One call through the Router; returns the reply (checked against `schema`) and the event's credits and trace."""
    try:
        result = router.generate(
            CAPTURE_ROLE,
            GenerateRequest(system=system, prompt=prompt, json_mode=True, response_schema=schema, parts=parts or None),
        )
        text = None if result.response is None else result.response.text
        if result.outcome != "ok" or type(text) is not str:
            raise _Failed
        doc = json.loads(text)
        if first_error(doc, schema) is not None:
            raise _Failed
        used = result.attempts[-1]
    except _Failed:
        raise _draft_failed() from None
    except Exception as exc:  # a provider, router or parse failure: the type only, never the words
        logger.warning("skill draft model call failed: %s", type(exc).__name__)
        raise _draft_failed() from None
    credits = 0.0
    try:
        config, quote = deps.providers_config(), deps.providers_config().price(used.profile_id)
        credits = float(
            config.credits(((used.tokens_in or 0) * quote.input + (used.tokens_out or 0) * quote.output) / 1e6)
        )
    except Exception:
        logger.warning("skill draft credits not worked out")
    trace = {
        "model_role": CAPTURE_ROLE,
        "profile": used.profile_id,
        "tokens_in": used.tokens_in,
        "tokens_out": used.tokens_out,
        "tool": None,
        "latency_ms": int(round(used.latency_ms)),
        "archive_ref": None,
    }
    return doc, {"credits": credits, "trace": trace}


def _usable(registry: Any, views: Any, user_id: str) -> list[str]:
    """TEACH-PAIRS: the tools this person can use now, in the registry's order: their connected connectors, the Google
    sign-in tools, and any tool that needs no sign-in. A view that cannot be read counts as not connected."""
    connected = set(_GOOGLE_DEFAULTS)
    for tool in registry.ids():
        if registry.get(tool)["auth"] != "oauth2" or views is None:
            continue
        try:
            if views.view(user_id, tool)[0] == "connected":
                connected.add(tool)
        except Exception:  # noqa: BLE001, S112 - unknown state is never "connected"; no text is shown
            continue
    return [t for t in registry.ids() if t in connected or registry.get(t)["auth"] != "oauth2"]


def _ready(flags: FlagStore) -> None:
    deps.refuse_if_replay_only(flags)
    try:
        configured = CAPTURE_ROLE in deps.providers_config().roles
    except Exception:
        configured = False
    if not configured:
        raise HTTPException(status_code=503, detail="not_configured")


def _desk(we: WorkEvents, org: str, owner: str) -> str:
    world = we.desks.desk_world(org, owner)
    if type(world) is not str or _DESK_WORLD.fullmatch(world) is None or we.desks.desk_owner(world) != owner:
        raise ValueError("not the owner's Desk world")
    return world


def _part(
    kind: str, owner: str, summary: str, data: dict[str, Any], key: tuple[str, ...], used: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": events.stable_part_id(*key),
        "type": kind,
        "actor": owner,
        "target": owner,
        "summary": summary,
        "vis": [],
        "authz": None,
        "data": data,
        **used,
    }


@router.post("/v1/skills/captures", status_code=201)
def capture_route(
    body: Annotated[CaptureIn, Depends(json_body(CaptureIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[SkillStore, Depends(deps.get_skill_store)],
    stores: Annotated[Any, Depends(deps.get_people_stores)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    safety: Annotated[SafetyProvider, Depends(deps.get_safety)],
    model_router: Annotated[Router, Depends(deps.get_router)],
    flags: Annotated[FlagStore, Depends(deps.get_flag_store)],
    we: Annotated[WorkEvents, Depends(get_work_events)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
) -> dict[str, Any]:
    """Describe a skill in words (and, optionally, attached documents): 201 with the captured steps (text only) and
    the id of the draft."""
    _ready(flags)
    text = _description(body.text, redact)
    if _flagged(safety, text):
        raise _not_understood()
    blocks, doc_texts, parts = "", [], []
    if body.documents:
        scope = Scope(deps.ORG_ID, _guarded(lambda: _desk(we, deps.ORG_ID, principal.user_id)), principal.user_id)
        refs = [r.model_dump() for r in body.documents]
        blocks, doc_texts, parts = skills_understand.read_documents(artifacts, scope, refs, redact)
        if doc_texts and _flagged(safety, "\n".join(doc_texts)):
            raise _not_understood()
    system = load_prompt("skill_describe", "capture_system.md")
    variables = {"description": neutralise_marker(text, "DESCRIPTION"), "documents": blocks}
    task = load_prompt("skill_describe", "capture_task.md", variables)
    doc, used = _ask(model_router, system, task, _CAPTURE_SCHEMA, parts)

    def save() -> dict[str, Any]:
        now, owner = _now(clock), principal.user_id
        writer = Writer(stores, deps.ORG_ID, owner, now, redact)
        try:
            texts = [writer.text(s["text"]) for s in doc["steps"]]
        except Refusal:
            raise _draft_failed() from None
        if _flagged(safety, "\n".join(texts)):
            raise _draft_failed()
        skill_id, cfg = "tsk_" + new_ulid(), load_skill_config()
        record = {
            "id": skill_id,
            "org_id": deps.ORG_ID,
            "owner": owner,
            "name": "Untitled skill",
            "scope": {"kind": "just_me", "team": None},
            "status": "draft",
            "paused": False,
            "method": "describe",
            "captured": [{"text": t, "artifact": None} for t in texts],
            "plan": [],
            "question": None,
            "trigger": {"kind": "on_demand", "schedule_id": None, "event": None},
            "estimates": estimates_for([], cfg),
            "tool_access": {},
            "good_runs": 0,
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        if not conforms("taught_skill.schema.json", record):
            raise _draft_failed()
        world = _desk(we, deps.ORG_ID, owner)
        store.put(record)
        for number in range(1, len(texts) + 1):  # HR-1: one event per step; the model call's cost rides on step 1
            data = {"skill": skill_id, "method": "describe", "step": number, "artifact": None}
            part = _part(
                "skill.captured",
                owner,
                "A step was added to a new skill.",
                data,
                (skill_id, "captured", str(number)),
                used if number == 1 else {},
            )
            we.writer.append(world, part)
        return {"capture_id": skill_id, "captured_steps": [{"text": t} for t in texts]}

    return _guarded(save)


def _view(
    draft: dict[str, Any], registry: Any, views: Any, team: Any, cannot: list[dict[str, str]] | None
) -> dict[str, Any]:
    q = draft["question"]
    joined = skills_understand.connected(registry, views, draft["owner"])
    return {
        "capture_id": draft["id"],
        "plan_steps": draft["plan"],
        "clarifying_question": None if q is None else {"text": q["text"], "options": q["options"]},
        "estimates": draft["estimates"],
        "inputs": draft.get("inputs", []),
        "hosts": draft.get("hosts", []),
        "cannot": cannot,  # null: a repeat answer no longer knows which steps were dropped (never an empty list)
        "needs_setup": skills_understand.needs_setup(draft["plan"], registry, joined, team),  # TS-21: never stored
    }


def _one_question(question: dict[str, Any] | None, text: Callable[[str], str]) -> dict[str, Any] | None:
    """At most one question about one thing: two question marks, or two clauses joined by 'and', and it is dropped."""
    if question is None:
        return None
    line = text(question["text"])
    if line.count("?") > 1 or _JOINED.search(line):
        return None
    return {"text": line, "options": [text(o) for o in question["options"]], "answer": None}


@router.post("/v1/skills/captures/{capture_id}/version")
def version_route(
    capture_id: str,
    _: Annotated[bytes, Depends(_capped_body)],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[SkillStore, Depends(deps.get_skill_store)],
    stores: Annotated[Any, Depends(deps.get_people_stores)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    safety: Annotated[SafetyProvider, Depends(deps.get_safety)],
    model_router: Annotated[Router, Depends(deps.get_router)],
    flags: Annotated[FlagStore, Depends(deps.get_flag_store)],
    registry: Annotated[Any, Depends(deps.get_connector_registry)],
    views: Annotated[Any, Depends(_optional_views)],
    we: Annotated[WorkEvents, Depends(get_work_events)],
    team: Annotated[Any, Depends(skills_understand.team_state)],
) -> dict[str, Any]:
    """Tilo's version of the person's own draft; asked twice it answers the same version (no new call, no new event)."""

    def find() -> dict[str, Any]:
        found = None if _SKILL_ID.fullmatch(capture_id) is None else store.get(deps.ORG_ID, capture_id)
        if found is None or found["owner"] != principal.user_id or found["status"] != "draft":
            raise HTTPException(status_code=404, detail="not_found")
        return found

    draft = _guarded(find)
    if draft["plan"]:
        return _view(draft, registry, views, team, None)
    _ready(flags)
    allow = skills_understand.capture_tools()
    steps_block = "\n".join(f"{n}. {neutralise_marker(c['text'], 'STEPS')}" for n, c in enumerate(draft["captured"], 1))
    usable = _usable(registry, views, principal.user_id)
    actions = "\n".join(
        f'tool "{tool}", action "{a["id"]}": {a["description"]}'
        for tool in usable
        for a in registry.get(tool)["actions"]
        if a["id"] in allow.get(tool, ())
    )
    preferred = ", ".join(t for t in usable if registry.get(t)["auth"] == "oauth2")
    system = load_prompt("skill_describe", "version_system.md")  # static: the person's tools ride in the task (EFF-04)
    variables = {"steps": steps_block, "actions": actions, "preferred": preferred}
    doc, used = _ask(model_router, system, load_prompt("skill_describe", "version_task.md", variables), _VERSION_SCHEMA)
    kept, cannot, steered = skills_understand.allocate(registry, doc["steps"], usable, allow)
    if not kept or steered:  # SKILL-TEACH-422 / TEACH-PAIRS: nothing usable, or a step lost to an unconnected tool
        retry = load_prompt("skill_describe", "version_retry.md", variables)
        again_doc, again = _ask(model_router, system, retry, _VERSION_SCHEMA)
        again_kept, again_cannot, _steered = skills_understand.allocate(registry, again_doc["steps"], usable, allow)
        if len(again_kept) >= len(kept):  # the first reply stays when the second keeps fewer steps
            doc, kept, cannot = again_doc, again_kept, again_cannot
        used = {"credits": used["credits"] + again["credits"], "trace": again["trace"]}
    typed = " ".join(c["text"] for c in draft["captured"]).casefold() if draft["method"] == "describe" else None
    hosts = skills_understand.clean_hosts(doc.get("hosts"), kept, typed)
    if not hosts:  # TS-18: a browse step names the hosts it may open; with none kept it cannot run
        cannot += [{"text": k.text, "reason": "no_host"} for k in kept if k.action == "browse_web"]
        kept = [k for k in kept if k.action != "browse_web"]

    def save() -> dict[str, Any]:
        now, owner = _now(clock), principal.user_id
        writer = Writer(stores, deps.ORG_ID, owner, now, redact)
        try:
            if not kept:
                raise _not_understood()
            plan = plan_steps(kept, writer.text, registry)
            question = _one_question(doc["question"], writer.text)
            said = [*(c["text"] for c in draft["captured"]), *(s["text"] for s in plan)]
            question = skills_understand.own_address_question(question, said)
            lost = [{"text": writer.text(c["text"]), "reason": c["reason"]} for c in cannot]
            inputs = [
                {**i, "label": writer.text(i["label"])} for i in skills_understand.clean_inputs(doc.get("inputs"))
            ]
        except Refusal as refusal:
            raise (refusal if refusal.detail == "not_understood" else _draft_failed()) from None
        shown = "\n".join([s["text"] for s in plan] + ([question["text"], *question["options"]] if question else []))
        if _flagged(safety, shown):
            raise _draft_failed()
        extra = {**({"inputs": inputs} if inputs else {}), **({"hosts": hosts} if hosts else {})}
        after = {
            **draft,
            "plan": plan,
            "question": question,
            "estimates": estimates_for(plan, load_skill_config()),
            "updated_at": now,
            **extra,
        }
        if not conforms("taught_skill.schema.json", after):
            raise _draft_failed()
        world = _desk(we, deps.ORG_ID, owner)
        store.put(after)
        est = after["estimates"]
        data = {
            "skill": draft["id"],
            "version": draft["version"],
            "steps": len(plan),
            "asks": est["asks_per_run"],
            "question": question is not None,
            "credits_per_run": est["credits_per_run"],
            "source": est["source"],
        }
        try:
            we.writer.append(
                world,
                _part(
                    "skill.version_proposed",
                    owner,
                    "Tilo proposed a version of a skill.",
                    data,
                    (draft["id"], "version_proposed", str(draft["version"])),
                    used,
                ),
            )
        except Exception:
            store.put(draft)  # the proposal only exists once its event does
            raise
        return _view(after, registry, views, team, lost)

    return _guarded(save)


@router.get("/v1/skills/{skill_id}/needs-setup")
def needs_setup_route(
    skill_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[SkillStore, Depends(deps.get_skill_store)],
    stores: Annotated[Any, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    registry: Annotated[Any, Depends(deps.get_connector_registry)],
    views: Annotated[Any, Depends(_optional_views)],
    team: Annotated[Any, Depends(skills_understand.team_state)],
) -> dict[str, Any]:
    """What a skill the caller may read still needs (TS-21): worked out now from their connections and the team's
    levels, never stored. Absent, malformed or unreadable is the one 404 (TS-01)."""

    def read() -> dict[str, Any]:
        teams = _teams(stores, principal.user_id, _now(clock))
        found = None if _SKILL_ID.fullmatch(skill_id) is None else store.get(deps.ORG_ID, skill_id)
        if found is None or not (
            found["owner"] == principal.user_id
            or (found["status"] != "draft" and found["scope"]["kind"] == "team" and found["scope"]["team"] in teams)
        ):
            raise HTTPException(status_code=404, detail="not_found")
        joined = skills_understand.connected(registry, views, principal.user_id)
        return {"needs_setup": skills_understand.needs_setup(found["plan"], registry, joined, team)}

    return _guarded(read)
