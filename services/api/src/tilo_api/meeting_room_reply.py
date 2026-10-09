"""The meeting room's reply step (ADR-0028 decisions 4 and 5, MR-06, MR-11; MROOM-A1). One agent, one question, one
model call over what the world RECORDED for that agent only. Code builds the grounding set, fences the person's words,
checks every id the model names against the set (one stray id fails the whole reply, never trimmed) and cannot pass a
proposal that holds anything but unit ids and artifact versions. No tool, no connector, no web, no memory search."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from tilo_harness.untrusted import neutralise
from tilo_providers.config import ProviderConfigError, ProvidersConfig
from tilo_providers.interfaces import GenerateRequest, SafetyProvider
from tilo_providers.prompts import load_prompt
from tilo_providers.router import BudgetExceededError, Router, RouterError

ROLES = {"quick": "meeting_room", "thinking": "meeting_room_thinking"}  # config/models*.yaml; `meeting` is the bot's
DECLINED = "I can't take that message, so I have no answer to give."
NO_RECORD = "I have no record of that."
MAX_LINES, MAX_LINE, MAX_TEXT = 60, 300, 4000
_UNIT = re.compile(r"U[0-9]{1,4}")
_ARTIFACT_ID = re.compile(r"art_[0-9A-Za-z_]{1,48}")
_ARTIFACT_EVENTS = ("artifact.created", "artifact.versioned")


class RoomModelUnavailable(Exception):
    """The role is missing, uncapped or unpriced, or every candidate failed (decision 10: the reply is `failed`)."""


class RoomCapped(Exception):
    """The Router refused the call against the room's remaining credits (MT-03)."""


@dataclass(frozen=True)
class Grounding:
    agent: str
    rank: str
    district: str | None
    units: frozenset[str]
    artifacts: frozenset[tuple[str, int]]
    lines: tuple[tuple[int, str, str, str], ...]  # seq, type, unit, summary: what the agent's record says


@dataclass(frozen=True)
class ModelReply:
    text: str
    credits: float
    role: str
    profile: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None


@dataclass(frozen=True)
class Reply:
    outcome: str  # answered, proposed_change, declined, failed
    text: str | None
    units: tuple[str, ...] = ()
    artifacts: tuple[tuple[str, int], ...] = ()
    proposal: tuple[tuple[str, ...], tuple[tuple[str, int], ...]] | None = None  # (units, artifacts)
    credits: float = 0.0
    trace: Mapping[str, Any] | None = None


class RoomModel(Protocol):
    def quote(self, mode: str) -> float:
        """The dearest this mode's call may cost, in credits (reserved before the call, MR-08)."""
        ...

    def reply(self, mode: str, system: str, prompt: str, *, record: Grounding, budget: float) -> ModelReply: ...


def layout_agents(layout: Mapping[str, Any] | None) -> dict[str, tuple[str, str | None]]:
    """agent id -> (rank, district): a Lead's district is the layout's; a worker's is the district its recorded events
    carry (filled by `locate`); the Director has none."""
    semantic = (layout or {}).get("semantic") or {}
    leads = {d["lead"]: d["id"] for lv in semantic.get("levels", []) for d in lv.get("districts", [])}
    return {a["id"]: (a["rank"], leads.get(a["id"])) for a in semantic.get("agents", [])}


def locate(layout: Mapping[str, Any] | None, events: list[dict], agent: str) -> tuple[str, str | None] | None:
    found = layout_agents(layout).get(agent)
    if found is None:
        return None
    rank, district = found
    if rank in ("director", "lead") or district is not None:
        return rank, district
    district = next((e["district"] for e in events if agent in (e["actor"], e["target"]) and e.get("district")), None)
    return rank, district


def _unit_of(event: Mapping[str, Any]) -> str | None:
    unit = (event.get("data") or {}).get("unit")
    return unit if isinstance(unit, str) and _UNIT.fullmatch(unit) else None


def _summary(event: Mapping[str, Any]) -> str:
    text = str(event.get("summary") or "")
    envelope = (event.get("data") or {}).get("envelope")
    if event["type"] == "agent.handoff" and isinstance(envelope, dict):
        text += f" | {envelope.get('summary')} | {'; '.join(map(str, envelope.get('acceptance_criteria') or []))}"
    return text


def ground(layout: Mapping[str, Any] | None, events: list[dict], agent: str) -> Grounding | None:
    """What the world recorded for `agent` (MR-06): its own events (a Lead's: its district's; the Director's: all), the
    units those name or the layout assigns to its district, and the artifact versions they made. Room talk
    (`meeting.*`) is never part of it, and nothing from another district is."""
    where = locate(layout, events, agent)
    if where is None:
        return None
    rank, district = where
    if rank == "director":
        mine = [e for e in events if not e["type"].startswith("meeting.")]
    elif rank == "lead":
        mine = [e for e in events if e.get("district") == district and not e["type"].startswith("meeting.")]
    else:
        mine = [e for e in events if agent in (e["actor"], e["target"]) and not e["type"].startswith("meeting.")]
    semantic = (layout or {}).get("semantic") or {}
    planned = {
        u
        for lv in semantic.get("levels", [])
        for d in lv.get("districts", [])
        if rank == "director" or (rank == "lead" and d["id"] == district)
        for b in d.get("buildings", [])
        for u in b.get("plan_units", [])
    }
    units = planned | {u for e in mine if (u := _unit_of(e))}
    artifacts = set()
    for e in mine:
        art = (e.get("data") or {}).get("artifact")
        if e["type"] in _ARTIFACT_EVENTS and isinstance(art, dict) and type(art.get("version")) is int:
            if isinstance(art.get("artifact_id"), str) and _ARTIFACT_ID.fullmatch(art["artifact_id"]):
                artifacts.add((art["artifact_id"], art["version"]))
    lines = tuple((e["seq"], e["type"], _unit_of(e) or "-", _summary(e)) for e in mine[-MAX_LINES:])
    return Grounding(agent, rank, district, frozenset(units), frozenset(artifacts), lines)


def _prompt(record: Grounding, text: str, mode: str, note: str, lines: tuple) -> tuple[str, str]:
    rows = (
        "\n".join(f"{s} | {t} | {u} | {neutralise(m, limit=MAX_LINE)}" for s, t, u, m in lines) or "(nothing recorded)"
    )
    variables = {"mode": mode, "agent": record.agent, "question": neutralise(text, limit=2000), "record": rows}
    return (
        load_prompt("meeting_room", "reply_system.md", {"agent": record.agent}),
        load_prompt("meeting_room", "reply_task.md", {**variables, "note": note}),
    )


def _screened(safety: SafetyProvider, record: Grounding) -> tuple[tuple, str]:
    """PRD 16.3: flagged recorded content stays out of the prompt, with a note that some did. One screen over the whole
    record, then line by line only when that was flagged."""
    joined = "\n".join(m for *_, m in record.lines)
    if not joined or not safety.check(joined)["flagged"]:
        return record.lines, ""
    kept = tuple(ln for ln in record.lines if not safety.check(ln[3])["flagged"])
    return kept, "Some recorded lines were left out because they were flagged."


def _pairs(items: object) -> tuple[tuple[str, int], ...] | None:
    """[{artifact_id, version}] with exact keys and types, or None."""
    if not isinstance(items, list) or not all(
        isinstance(a, dict) and set(a) == {"artifact_id", "version"} for a in items
    ):
        return None
    out = tuple((a["artifact_id"], a["version"]) for a in items)
    return out if all(isinstance(i, str) and type(v) is int for i, v in out) else None


def _parse(raw: object, record: Grounding) -> dict | None:
    """The exact reply shape with exact types, every id inside the grounding set; anything else is None (failed)."""
    try:
        doc = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    if not isinstance(doc, dict) or set(doc) != {"has_record", "text", "units", "artifacts", "proposal"}:
        return None
    text, units, arts, proposal = doc["text"], doc["units"], _pairs(doc["artifacts"]), doc["proposal"]
    if type(doc["has_record"]) is not bool or not isinstance(text, str) or not 1 <= len(text) <= MAX_TEXT:
        return None
    if arts is None or not isinstance(units, list) or not all(isinstance(u, str) for u in units):
        return None
    if len(set(units)) != len(units) or not set(units) <= record.units or not set(arts) <= record.artifacts:
        return None  # MR-06: one id outside the set fails the reply
    if doc["has_record"] != bool(units) or (not doc["has_record"] and arts):
        return None  # an answer cites at least one unit (HR-1); "no record" cites nothing
    change = None
    if proposal is not None:
        shaped = isinstance(proposal, dict) and set(proposal) == {"units", "artifacts"}
        p_units: list = proposal["units"] if shaped else []
        p_arts = _pairs(proposal["artifacts"]) if shaped else None
        ok = shaped and 1 <= len(p_units) <= 10 and all(isinstance(u, str) for u in p_units)
        if not doc["has_record"] or not ok or p_arts is None or len(set(p_units)) != len(p_units):
            return None
        if not set(p_units) <= record.units or not set(p_arts) <= record.artifacts:
            return None
        change = (tuple(p_units), p_arts)
    return {"has_record": doc["has_record"], "text": text, "units": tuple(units), "artifacts": arts, "proposal": change}


def answer(
    model: RoomModel,
    record: Grounding,
    text: str,
    mode: str,
    *,
    safety: SafetyProvider,
    redact: Callable[[str], str],
    budget: float,
) -> Reply:
    """One turn's reply. Never raises for a model or screen problem: that is a `failed` reply with no text. Raises
    RoomCapped when the Router refuses the call against `budget`."""
    try:
        if safety.check(text)["flagged"]:
            return Reply("declined", DECLINED)  # a flagged message is never sent to the model, never a proposal
        lines, note = _screened(safety, record)
        system, prompt = _prompt(record, text, mode, note, lines)
        got = model.reply(mode, system, prompt, record=record, budget=budget)
    except RoomCapped:
        raise
    except Exception:  # an outage is never "not flagged" and never a made-up reply (fail closed)
        return Reply("failed", None)
    trace = {
        "model_role": got.role,
        "profile": got.profile,
        "tokens_in": got.tokens_in,
        "tokens_out": got.tokens_out,
        "tool": None,
        "latency_ms": got.latency_ms,
        "archive_ref": None,
    }
    parsed = _parse(got.text, record)
    if parsed is None:
        return Reply("failed", None, credits=got.credits, trace=trace)
    shown = redact(NO_RECORD if not parsed["has_record"] else parsed["text"])
    outcome = "declined" if not parsed["has_record"] else "proposed_change" if parsed["proposal"] else "answered"
    return Reply(outcome, shown, parsed["units"], parsed["artifacts"], parsed["proposal"], got.credits, trace)


class RouterRoomModel:
    """The production model: the Router's `meeting_room` / `meeting_room_thinking` role (replay unless the request's
    mode is live; PL-01, EFF-01). `quote` is the dearest candidate at both token caps, the Router's budget."""

    def __init__(self, router: Router, providers: ProvidersConfig) -> None:
        self._router, self._providers = router, providers

    def quote(self, mode: str) -> float:
        role = self._providers.roles.get(ROLES[mode])
        if role is None or role.max_input_tokens is None or role.max_output_tokens is None:
            raise RoomModelUnavailable("the room role is missing or has no token caps")
        try:
            return max(
                self._providers.credits((role.max_input_tokens * q.input + role.max_output_tokens * q.output) / 1e6)
                for q in (self._providers.price(p) for p in (role.cascade or (role.primary, role.fallback)) if p)
            )
        except ProviderConfigError:
            raise RoomModelUnavailable("a candidate of the room role has no price") from None

    def reply(self, mode: str, system: str, prompt: str, *, record: Grounding, budget: float) -> ModelReply:
        started = time.monotonic()
        try:
            result = self._router.generate(
                ROLES[mode], GenerateRequest(system=system, prompt=prompt, json_mode=True), budget=budget
            )
        except BudgetExceededError:
            raise RoomCapped from None
        except RouterError:
            raise RoomModelUnavailable("every candidate failed") from None
        if result.outcome != "ok" or result.response is None:
            raise RoomModelUnavailable("no usable reply")
        last = result.attempts[-1] if result.attempts else None
        spent = max(0.0, budget - result.budget) if result.budget is not None else 0.0
        return ModelReply(
            result.response.text,
            spent,
            ROLES[mode],
            getattr(last, "profile_id", None),
            getattr(last, "tokens_in", None),
            getattr(last, "tokens_out", None),
            int((time.monotonic() - started) * 1000),
        )


class FakeRoomModel:
    """Dev mode: a deterministic reply from the grounding set, 0 credits, no network."""

    def quote(self, mode: str) -> float:
        return 0.0

    def reply(self, mode: str, system: str, prompt: str, *, record: Grounding, budget: float) -> ModelReply:
        unit = min(record.units, default=None)
        doc = {
            "has_record": unit is not None,
            "text": "(dev) Answers come from what I recorded." if unit else NO_RECORD,
            "units": [unit] if unit else [],
            "artifacts": [],
            "proposal": None,
        }
        return ModelReply(json.dumps(doc), 0.0, ROLES[mode])
