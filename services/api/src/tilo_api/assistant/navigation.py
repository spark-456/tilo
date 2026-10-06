"""FR-PA-14: navigation by allow-list (section 6). `vet_navigate` is the one place an action becomes executable,
whoever proposed it: a rule or a model reply must be a `navigate` document of the ui_action contract, on a route
that takes its target kind, naming a record the panel already offered and the person may still read."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tilo_policy.schemas import conforms

from tilo_api.assistant.config import AssistantConfig
from tilo_api.assistant.gate import Ref, RefGate
from tilo_api.assistant.words import question_key, words

if TYPE_CHECKING:
    from tilo_api.assistant.core import Menu

ROUTE_TARGETS: Mapping[str, frozenset[str | None]] = {  # PE-19: a navigate route and its target kind agree
    "plate": frozenset({"work_item", None}),
    "calendar": frozenset({"calendar_entry", None}),
    "meetings": frozenset({None}),
    "meeting": frozenset({"meeting"}),
    "pinboard_team": frozenset({"pin", None}),
    "pinboard_personal": frozenset({"pin", None}),  # only its owner can read it
    "worlds": frozenset({None}),
    "world": frozenset({"world"}),
    "cards": frozenset({"card", None}),
    "connections": frozenset({None}),
    "channels": frozenset({None}),
    "autonomy": frozenset({None}),
    "settings": frozenset({None}),
}
_OPENS = {"work_item": "plate", "calendar_entry": "calendar", "meeting": "meeting", "world": "world", "card": "cards"}


def _action(route: str, target: Mapping[str, str] | None) -> dict[str, Any]:
    return {"kind": "navigate", "route": route, "target": None if target is None else dict(target)}


def route_for(ref: Ref, gate: RefGate) -> dict[str, Any] | None:
    """The navigate action that opens `ref`, or None when the gate refuses it or no screen opens it."""
    if not gate.allows(ref):
        return None
    if ref.kind in _OPENS:
        return _action(_OPENS[ref.kind], {"kind": ref.kind, "id": ref.id})
    if ref.kind == "pinboard_item":
        record = gate.record(ref)
        if record is None:
            return None
        personal = record["scope"]["kind"] == "personal"
        return _action("pinboard_personal" if personal else "pinboard_team", {"kind": "pin", "id": ref.id})
    return _action("plate", None) if ref.kind == "mail" else None  # no route opens a mail row: My plate lists it


@dataclass(frozen=True)
class NavMatch:
    action: Mapping[str, Any] | None
    decline: str | None  # "no_selection"


def match_navigation(
    key: str, rows: Sequence[Mapping[str, Any]], context: Ref | None, gate: RefGate, config: AssistantConfig
) -> NavMatch | None:
    """None unless the question starts with a navigation verb and names a screen, the selection or one row."""
    spoken = words(key, config)
    w = config.words
    if not spoken or spoken[0] not in w["nav_verbs"]:
        return None
    rest = [x for x in spoken[1:] if x not in w["nav_skip"]]
    if not rest:
        return None
    phrases = {p: r for r in config.navigate for p in r.phrases}
    route = phrases.get(" ".join(rest)) or (phrases.get(" ".join(rest[1:])) if rest[0] == "my" else None)
    if route is not None:
        own = route_for(context, gate) if context is not None and route.with_context == context.kind else None
        return NavMatch(own or _action(route.route, None), None)
    named = w["context"] | w["context_nouns"]
    if all(x in named for x in rest) and any(x in w["context"] for x in rest):
        action = None if context is None else route_for(context, gate)
        return NavMatch(action, None) if action is not None else NavMatch(None, "no_selection")
    wanted = {x for x in rest if x not in w["title_skip"]}
    if wanted and any(len(x) >= 3 for x in wanted):
        hits = [
            r for r in rows if isinstance(r["title"], str) and wanted <= set(words(question_key(r["title"]), config))
        ]
        if len(hits) == 1:
            action = route_for(Ref(hits[0]["ref"]["kind"], hits[0]["ref"]["id"]), gate)
            return None if action is None else NavMatch(action, None)
    return None


def vet_navigate(action: object, menu: Menu, gate: RefGate) -> dict[str, Any] | None:
    """A deep copy of `action` when it is a valid, offered, readable navigate; else None."""
    if not conforms("ui_action.schema.json", action) or not isinstance(action, dict) or action["kind"] != "navigate":
        return None
    target = action["target"]
    if (None if target is None else target["kind"]) not in ROUTE_TARGETS[action["route"]]:
        return None
    if target is not None:
        ref = Ref("pinboard_item" if target["kind"] == "pin" else target["kind"], target["id"])
        if ref not in menu.refs or not gate.allows(ref) or route_for(ref, gate) != action:
            return None
    return copy.deepcopy(action)
