"""Taught skills: `POST /v1/skills`, `GET /v1/skills`, `GET /v1/skills/{id}`, `GET /v1/learn` (SKILLS-2, FR-SKL-04;
contracts/taught_skill.schema.json, taught_skill.rules.md TS-01, TS-02, TS-04 to TS-07; ADR-0034).

The owner is `Principal.user_id` and the org `deps.ORG_ID`; nothing in a request names either. A saved skill starts as
`learning`. Code, never a model, sets `must_ask`, the estimates and every stamp; a client that asks for a step with a
must-ask verb to run without asking is refused (BQ-TAUGHT-1), not silently changed. A skill is read by its owner and,
for a `team` scope, by the current members of that team, re-read from the people record on every call (TS-01). One 404
body for every refusal to read. Writes the store only: no event (the next slice), no model, no clock but the seam.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, StrictBool, model_validator
from tilo_people.directory import Directory
from tilo_people.stores import PeopleStores
from tilo_planning.artifacts import new_ulid
from tilo_policy.schemas import conforms

from tilo_api import deps
from tilo_api.people import _PeopleRoute
from tilo_api.people_writes import Refusal, Text, Writer, _Closed, json_body
from tilo_api.skill_store import SkillStore

logger = logging.getLogger("tilo_api.skills")
router = APIRouter(route_class=_PeopleRoute)

_ROOT = Path(__file__).resolve().parents[4] / "config"
_SKILL_ID = re.compile(r"tsk_[0-9A-Za-z_]{1,48}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MUST_ASK_VERBS = frozenset({"send", "post", "pay", "delete", "share", "book"})
Verb = Literal["read", "draft", "write", "send", "post", "pay", "delete", "share", "book"]


@dataclass(frozen=True)
class SkillConfig:
    credits_per_step: float
    seconds_per_step: int
    event_types: frozenset[str]
    prices_as_of: str


def load_skill_config(root: Path = _ROOT) -> SkillConfig:
    """`config/skills.yaml` (prior per step, TS-07 event allow-list) and the price date of `config/prices.yaml`; a file
    that is missing or unusable falls back to the shipped numbers (the three registered event types)."""
    credits, seconds, events, as_of = 3, 20, ("meeting.minuted", "work_item.created", "world.completed"), "2026-09-24"
    try:
        data = yaml.safe_load((root / "skills.yaml").read_text(encoding="utf-8"))
        prior, listed = data["prior"], data["triggers"]["event_types"]
        if (
            type(prior["credits_per_step"]) in (int, float)
            and prior["credits_per_step"] >= 0
            and type(prior["seconds_per_step"]) is int
            and prior["seconds_per_step"] >= 0
            and isinstance(listed, list)
            and all(isinstance(e, str) for e in listed)
        ):
            credits, seconds, events = prior["credits_per_step"], prior["seconds_per_step"], tuple(listed)
    except Exception:
        logger.warning("config/skills.yaml not read; using the shipped defaults")
    try:
        found = str(yaml.safe_load((root / "prices.yaml").read_text(encoding="utf-8"))["effective_date"])
        as_of = found if _DATE.fullmatch(found) else as_of
    except Exception:
        logger.warning("config/prices.yaml date not read; using the shipped default")
    return SkillConfig(credits, seconds, frozenset(events), as_of)


# --- the body ---------------------------------------------------------------------------------------------------


class StepIn(_Closed):
    text: Text
    tool: Annotated[str, Field(max_length=64)]
    action: Annotated[str, Field(max_length=64)]
    verb: Verb
    ask_first: StrictBool | None = None


class CapturedIn(_Closed):
    text: Text


class ScopeIn(_Closed):
    kind: Literal["just_me", "team"]
    team: Annotated[str, Field(max_length=64)] | None

    @model_validator(mode="after")
    def _team_exactly_for_team(self) -> ScopeIn:
        if (self.kind == "team") != (self.team is not None):
            raise ValueError("team")
        return self


class TriggerIn(_Closed):
    kind: Literal["on_demand", "schedule", "event"]
    schedule_id: Annotated[str, Field(max_length=64)] | None = None
    event_type: Annotated[str, Field(max_length=64)] | None = None
    filter: Annotated[dict[str, Annotated[str, Field(max_length=64)]], Field(max_length=3)] | None = None

    @model_validator(mode="after")
    def _fields_match_kind(self) -> TriggerIn:
        wanted = {"on_demand": (), "schedule": ("schedule_id",), "event": ("event_type",)}[self.kind]
        given = tuple(n for n in ("schedule_id", "event_type") if getattr(self, n) is not None)
        if given != wanted or (self.filter is not None and self.kind != "event"):
            raise ValueError("trigger")
        return self


class QuestionIn(_Closed):
    text: Text
    options: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=10)]


class SkillIn(_Closed):
    name: Text
    scope: ScopeIn
    trigger: TriggerIn
    plan_steps: Annotated[list[StepIn], Field(min_length=1, max_length=20)]
    captured_steps: Annotated[list[CapturedIn], Field(max_length=20)] = Field(default_factory=list)
    clarifying_question: QuestionIn | None = None


# --- the record -------------------------------------------------------------------------------------------------


def _declared(registry: Any, tool: str, action: str) -> dict[str, Any] | None:
    """The connector's own entry for the action in config/connectors.yaml (TS-06); None when it lists none."""
    if tool not in registry:
        return None
    return next((a for a in registry.get(tool)["actions"] if a.get("id") == action), None)


def plan_steps(steps: list[StepIn], text: Callable[[str], str], registry: Any) -> list[dict[str, Any]]:
    """Plan steps with code-set `must_ask` and `ask_first` (TS-04); SKILLS-4 builds Tilo's version through this too."""
    plan = []
    for step in steps:
        declared = _declared(registry, step.tool, step.action)
        if declared is None:
            raise Refusal(422, "unknown_action")
        must_ask = step.verb in _MUST_ASK_VERBS or declared.get("risk_tier") != "T1"  # TS-04: unlisted tier is T3
        if must_ask and step.ask_first is False:
            raise Refusal(422, "ask_first_required")
        plan.append(
            {
                "text": text(step.text),
                "tool": step.tool,
                "action": step.action,
                "verb": step.verb,
                "ask_first": must_ask or bool(step.ask_first),
                "must_ask": must_ask,
            }
        )
    return plan


def estimates_for(plan: list[dict[str, Any]], cfg: SkillConfig) -> dict[str, Any]:
    return {  # TS-05: while learning, every step that is not a read stops to ask
        "credits_per_run": cfg.credits_per_step * len(plan),
        "seconds_per_run": cfg.seconds_per_step * len(plan),
        "asks_per_run": sum(1 for s in plan if s["verb"] != "read"),
        "source": "prior",
        "prices_as_of": cfg.prices_as_of,
    }


def _trigger(body: TriggerIn, cfg: SkillConfig) -> dict[str, Any]:
    if body.kind == "event" and body.event_type not in cfg.event_types:
        raise Refusal(422, "event_not_allowed")  # TS-07
    event = None if body.kind != "event" else {"type": body.event_type, "filter": dict(body.filter or {})}
    return {"kind": body.kind, "schedule_id": body.schedule_id, "event": event}


def build_record(
    body: SkillIn, w: Writer, teams: set[str], registry: Any, cfg: SkillConfig, skill_id: str
) -> dict[str, Any]:
    if body.scope.kind == "team" and body.scope.team not in teams:
        raise Refusal(403, "forbidden")  # TS-02: a team the owner is not in
    plan = plan_steps(body.plan_steps, w.text, registry)
    question = body.clarifying_question
    record = {
        "id": skill_id,
        "org_id": w.org,
        "owner": w.actor,
        "name": w.text(body.name),
        "scope": body.scope.model_dump(),
        "status": "learning",
        "paused": False,
        "method": "describe",
        "captured": [{"text": w.text(c.text), "artifact": None} for c in body.captured_steps],
        "plan": plan,
        "question": None
        if question is None
        else {"text": w.text(question.text), "options": [w.text(o) for o in question.options], "answer": None},
        "trigger": _trigger(body.trigger, cfg),
        "estimates": estimates_for(plan, cfg),
        "tool_access": {},
        "good_runs": 0,
        "version": 1,
        "created_at": w.now,
        "updated_at": w.now,
    }
    if not conforms("taught_skill.schema.json", record):
        raise Refusal(422, "invalid_record")
    return record


# --- the routes -------------------------------------------------------------------------------------------------


def _guarded[T](work: Callable[[], T]) -> T:
    """404 and 422 pass; an unwired store is the route class's 503 `not_configured`; any other failure a fixed 503."""
    try:
        return work()
    except (HTTPException, NotImplementedError):
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="unavailable") from None


def _teams(stores: PeopleStores, user: str, now: str) -> set[str]:
    """The caller's current teams (memberships re-read from the people record, ADR-0015); no record is the one 404."""
    directory = Directory.of(s.record for s in stores.persons.list(deps.ORG_ID))
    me = directory.record(user)
    if me is None:
        raise HTTPException(status_code=404, detail="not_found")
    return {m["team"] for m in me["memberships"] if directory.is_member(user, m["team"], now)}


def _now(clock: Callable[[], str]) -> str:
    now = clock()
    if not isinstance(now, str):
        raise TypeError("clock")
    return now


def _sorted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (r["name"], r["id"]))


@router.post("/v1/skills", status_code=201)
def create_skill_route(
    body: Annotated[SkillIn, Depends(json_body(SkillIn))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[SkillStore, Depends(deps.get_skill_store)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    redact: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    registry: Annotated[Any, Depends(deps.get_connector_registry)],
) -> dict[str, Any]:
    """Save a skill the person described: it starts as Learning (FR-SKL-04)."""

    def save() -> dict[str, Any]:
        now = _now(clock)
        teams = _teams(stores, principal.user_id, now)
        writer = Writer(stores, deps.ORG_ID, principal.user_id, now, redact)
        record = build_record(body, writer, teams, registry, load_skill_config(), "tsk_" + new_ulid())
        store.put(record)
        return record

    return _guarded(save)


def _readable(store: SkillStore, stores: PeopleStores, principal: deps.Principal, clock: Callable[[], str]) -> list:
    now = _now(clock)
    teams = _teams(stores, principal.user_id, now)
    return _sorted(store.list_visible(deps.ORG_ID, principal.user_id, teams))


@router.get("/v1/skills")
def list_skills_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[SkillStore, Depends(deps.get_skill_store)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """The caller's own skills and those of their current teams, by name then id."""
    return {"skills": _guarded(lambda: _readable(store, stores, principal, clock))}


@router.get("/v1/skills/{skill_id}")
def get_skill_route(
    skill_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[SkillStore, Depends(deps.get_skill_store)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """One skill; absent, malformed, another org's or one the caller may not read is the same 404 (TS-01)."""

    def read() -> dict[str, Any]:
        teams = _teams(stores, principal.user_id, _now(clock))
        found = None if _SKILL_ID.fullmatch(skill_id) is None else store.get(deps.ORG_ID, skill_id)
        if found is None or not (
            found["owner"] == principal.user_id
            or (found["scope"]["kind"] == "team" and found["scope"]["team"] in teams)
        ):
            raise HTTPException(status_code=404, detail="not_found")
        return found

    return _guarded(read)


@router.get("/v1/learn")
def learn_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[SkillStore, Depends(deps.get_skill_store)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> dict[str, Any]:
    """Skills still learning that the caller may read; ratings and the helpers report are later slices."""
    learning = _guarded(lambda: [r for r in _readable(store, stores, principal, clock) if r["status"] == "learning"])
    return {"learning": learning, "needs_rating": [], "helpers": None}
