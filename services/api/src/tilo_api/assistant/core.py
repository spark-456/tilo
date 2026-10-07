"""The decision of one question (section 7): rules first, in a fixed order, then at most one model call that may
only pick a fact intent or propose a navigate action. Code checks what the model picks (`vet_navigate`); a model
never decides access and never writes a fact. No clock, no I/O, no writes: `now` is an argument."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from string import Template
from typing import Any, Literal, Protocol

from tilo_people.text import clean_line
from tilo_policy.schemas import conforms

from tilo_api.assistant.config import AssistantConfig, FactIntent
from tilo_api.assistant.facts import Line, fact_lines, match_fact, moment_of, remainder_of, zone_of
from tilo_api.assistant.gate import Ref, RefGate
from tilo_api.assistant.navigation import match_navigation, route_for, vet_navigate
from tilo_api.assistant.status import status_lines, weekly_lines
from tilo_api.assistant.words import about_someone_else, question_key

logger = logging.getLogger("tilo_api.assistant.core")
Choice = Literal["intent", "navigate", "decline", "dropped", "unavailable", "budget", "flagged"]
_TITLE_MAX = 140


@dataclass(frozen=True)
class Ask:
    user: str
    org_id: str
    now: str
    question: str
    screen: str | None
    context: Ref | None  # from gate.context_ref


@dataclass(frozen=True)
class MenuRow:
    ref: Ref
    reason: str | None  # None for a context record that is not a plate row
    group: str | None
    due: str | None
    title: str | None  # None when flagged (PE-21) or untitled; never another person's text
    action: Mapping[str, Any] | None  # route_for(ref)


@dataclass(frozen=True)
class Menu:
    rows: tuple[MenuRow, ...]
    context: MenuRow | None
    refs: frozenset[Ref]  # rows plus context: the only targets a model may name
    fingerprint: str  # sha256 hex of exactly what the model is shown


@dataclass(frozen=True)
class ModelAsk:
    user: str
    org_id: str
    now: str
    question: str  # clean_line(question)
    question_key: str
    screen: str | None
    context: Ref | None
    menu: Menu
    plate_fingerprint: str  # plate["fingerprint"] (PE-30)


@dataclass(frozen=True)
class ModelDecision:
    choice: Choice
    intent: str | None = None
    action: Mapping[str, Any] | None = None  # unvetted; core runs vet_navigate
    cached: bool = False
    model_calls: int = 0
    credits: float = 0.0  # committed for this question
    saved: float = 0.0  # origin cost of a cache hit
    profile: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None
    prompt: str | None = None  # as sent, for the archive
    raw: str | None = None  # the reply text, at most model.max_output_chars


class Decider(Protocol):
    def decide(self, ask: ModelAsk) -> ModelDecision: ...


class _Unavailable:
    """The decider of replay-only mode (NFR-24): calls nothing."""

    def decide(self, ask: ModelAsk) -> ModelDecision:
        return ModelDecision("unavailable")


UNAVAILABLE: Decider = _Unavailable()


@dataclass(frozen=True)
class Answer:
    outcome: Literal["answered", "navigated", "declined", "failed"]
    decided_by: Literal["rules", "model"]
    lines: tuple[Line, ...]
    ui_action: Mapping[str, Any] | None
    decline: str | None  # a `declines` key, or "empty"
    intent: str | None  # a fact intent id or "navigate"
    model: ModelDecision | None  # None when no decider was asked


def _ref(row: Mapping[str, Any]) -> Ref:
    return Ref(row["ref"]["kind"], row["ref"]["id"])


def _gated_rows(rows: Sequence[Mapping[str, Any]], gate: RefGate) -> list[Mapping[str, Any]]:
    """The plate rows (or parked rows) whose ref conforms and the gate admits, in plate order; the builder and the
    oracle should agree, so a refused row is logged by kind (never by id or title)."""
    kept = []
    for row in rows:
        if not conforms("common.schema.json#/$defs/record_ref", row.get("ref")):
            continue
        ref = _ref(row)
        if gate.allows(ref):
            kept.append(row)
        else:
            logger.warning("assistant.plate_row_refused %s", ref.kind)
    return kept


def _context_title(ref: Ref, gate: RefGate) -> str | None:
    record = gate.record(ref)
    title = None if record is None or record.get("flagged") else record.get("title")
    return clean_line(title)[:_TITLE_MAX] or None if isinstance(title, str) else None


def build_menu(
    rows: Sequence[Mapping[str, Any]],
    context: Ref | None,
    gate: RefGate,
    config: AssistantConfig,
    *,
    limit: int | None = None,
) -> Menu:
    """What a model is shown: the first `model.menu_rows` gated rows that a screen opens (`limit` overrides the
    cut), and the selected record. Flagged titles are withheld (PE-21)."""
    cut = config.model["menu_rows"] if limit is None else limit
    menu_rows: list[MenuRow] = []
    for row in rows:
        action = route_for(_ref(row), gate)
        if action is None:
            continue
        title = None if row["flagged"] or not isinstance(row["title"], str) else row["title"][:_TITLE_MAX]
        menu_rows.append(MenuRow(_ref(row), row["reason"], row["group"], row["due"], title, action))
        if len(menu_rows) == cut:
            break
    chosen = None
    if context is not None:
        chosen = next((m for m in menu_rows if m.ref == context), None)
        if chosen is None:
            plate_row = next((r for r in rows if _ref(r) == context), None)
            if plate_row is not None:
                title = None if plate_row["flagged"] else plate_row["title"]
                chosen = MenuRow(
                    context, plate_row["reason"], plate_row["group"], plate_row["due"], title, route_for(context, gate)
                )
            else:
                chosen = MenuRow(context, None, None, None, _context_title(context, gate), route_for(context, gate))
    refs = frozenset([m.ref for m in menu_rows] + ([chosen.ref] if chosen else []))
    shown = {
        "rows": [[m.ref.kind, m.ref.id, m.reason, m.group, m.due, m.title] for m in menu_rows],
        "context": None if chosen is None else [chosen.ref.kind, chosen.ref.id, chosen.title],
        "facts": [f.id for f in config.facts],
        "routes": [r.route for r in config.navigate],
    }
    fingerprint = hashlib.sha256(json.dumps(shown, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return Menu(tuple(menu_rows), chosen, refs, fingerprint)


def _decline(
    config: AssistantConfig, key: str, decided_by: Literal["rules", "model"], model: ModelDecision | None = None
) -> Answer:
    return Answer("declined", decided_by, (Line(config.declines[key], None),), None, key, None, model)


def _opening(action: Mapping[str, Any], config: AssistantConfig) -> Line:
    route, target = action["route"], action["target"]
    screens = {r.route: r.describe for r in config.navigate}
    screen = config.answer["target_screens"].get(route) or screens.get(route, route)
    source = (
        None if target is None else Ref("pinboard_item" if target["kind"] == "pin" else target["kind"], target["id"])
    )
    return Line(Template(config.answer["opening"]).substitute(screen=screen), source)


def _navigated(
    action: Mapping[str, Any] | None,
    config: AssistantConfig,
    by: Literal["rules", "model"],
    model: ModelDecision | None,
) -> Answer:
    if action is None:  # a rule's own action failed the vet: a bug, never an executed action
        return Answer("failed", "rules", (Line(config.declines["failed"], None),), None, "failed", "navigate", model)
    return Answer("navigated", by, (_opening(action, config),), action, None, "navigate", model)


def _report(
    intent: FactIntent,
    rows: Sequence[Mapping[str, Any]],
    ask: Ask,
    plate: Mapping[str, Any],
    gate: RefGate,
    finished: Callable[[], Sequence[Mapping[str, Any]]] | None,
    tz: str | None,
    config: AssistantConfig,
) -> tuple[tuple[Line, ...], Mapping[str, Any] | None]:
    """FR-PA-08: `status` also reads the gated `done` lane, `weekly` the person's finished items (route-supplied)."""
    now, zone = moment_of(ask.now), zone_of(tz)
    if now is None:
        raise ValueError("now")
    if intent.report == "status":
        done = [r for r in plate["parked"] if r.get("group") == "done" and r["ref"]["kind"] == "work_item"]
        return status_lines(intent, rows, _gated_rows(done, gate), now=now, zone=zone, config=config)
    if finished is None:
        raise ValueError("finished")
    return weekly_lines(intent, rows, finished(), truncated=bool(plate["truncated"]), now=now, zone=zone, config=config)


def _facts(
    intent: FactIntent,
    rows: Sequence[Mapping[str, Any]],
    ask: Ask,
    remainder: frozenset[str],
    tz: str | None,
    config: AssistantConfig,
    by: Literal["rules", "model"],
    model: ModelDecision | None,
    report: Callable[[FactIntent], tuple[tuple[Line, ...], Mapping[str, Any] | None]],
) -> Answer:
    if intent.report is None:
        lines, offer = fact_lines(
            intent, rows, as_of=ask.now, context=ask.context, remainder=remainder, time_zone=tz, config=config
        )
    else:
        lines, offer = report(intent)
    if not any(line.source is not None for line in lines):  # nothing to cite is never `answered` (HR-1)
        return Answer("declined", by, lines, None, "empty", intent.id, model)
    return Answer("answered", by, lines, offer, None, intent.id, model)


def answer(
    ask: Ask,
    *,
    plate: Mapping[str, Any],
    gate: RefGate,
    config: AssistantConfig,
    time_zone: str | None,
    decider: Decider | None,
    finished: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
) -> Answer:
    key = question_key(ask.question)
    if about_someone_else(key, config):  # words only: nothing is looked up, so the reply never depends on anyone else
        return _decline(config, "other_person", "rules")
    rows = _gated_rows(plate["rows"], gate)

    def report(intent: FactIntent) -> tuple[tuple[Line, ...], Mapping[str, Any] | None]:
        return _report(intent, rows, ask, plate, gate, finished, time_zone, config)

    nav = match_navigation(key, rows, ask.context, gate, config)
    if nav is not None:
        if nav.decline is not None:
            return _decline(config, nav.decline, "rules")
        menu = build_menu(rows, ask.context, gate, config, limit=len(rows))
        return _navigated(vet_navigate(nav.action, menu, gate), config, "rules", None)
    intent = match_fact(key, config)
    if intent is not None:
        return _facts(intent, rows, ask, remainder_of(key, intent, config), time_zone, config, "rules", None, report)
    if decider is None:
        return _decline(config, "unknown", "rules")
    menu = build_menu(rows, ask.context, gate, config)
    d = decider.decide(
        ModelAsk(
            ask.user,
            ask.org_id,
            ask.now,
            clean_line(ask.question),
            key,
            ask.screen,
            ask.context,
            menu,
            plate["fingerprint"],
        )
    )
    chosen = next((f for f in config.facts if type(d.intent) is str and f.id == d.intent), None)
    if d.choice == "intent" and chosen is not None:
        return _facts(chosen, rows, ask, frozenset(), time_zone, config, "model", d, report)
    if d.choice == "navigate":
        vetted = vet_navigate(d.action, menu, gate)
        if vetted is not None:
            return _navigated(vetted, config, "model", d)
    if d.choice == "decline":
        return _decline(config, "unknown", "model", d)
    refusals = {"unavailable": "rules_only", "budget": "budget", "flagged": "flagged"}
    if d.choice in refusals:
        return _decline(config, refusals[d.choice], "rules", d)
    return _decline(config, "dropped", "model", d)  # a bad intent id, a failed vet, any other reply
