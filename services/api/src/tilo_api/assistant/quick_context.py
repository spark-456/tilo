"""FR-PA-19: bounded, read-only facts for Quick's user turn."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from tilo_providers.prompts import neutralise_marker

MAX_CONTEXT_BYTES = 1500  # A byte bound also bounds byte-tokenised provider inputs.
_ROUTE = re.compile(r"/[A-Za-z0-9._~%/-]{0,119}")


def parse_client_context(raw: Any) -> tuple[list[dict[str, str]], str]:
    """The client can supply earlier words and its page, never authoritative record facts."""
    if not isinstance(raw, str) or len(raw) > 6500:
        return [], ""
    try:
        data = json.loads(raw)
    except ValueError:
        return [], ""
    if not isinstance(data, dict) or set(data) != {"route", "history"}:
        return [], ""
    route, history = data["route"], data["history"]
    if not isinstance(route, str) or not _ROUTE.fullmatch(route) or not isinstance(history, list):
        return [], ""
    turns = []
    for item in history[-6:]:
        if not isinstance(item, dict) or set(item) != {"question", "answer"}:
            continue
        question, answer = item["question"], item["answer"]
        if isinstance(question, str) and isinstance(answer, str):
            turns.append({"question": question[:500], "answer": answer[:500]})
    return turns, route


def _rows(value: Any, key: str) -> list[Mapping[str, Any]]:
    rows = value.get(key, []) if isinstance(value, Mapping) else []
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _short(value: Any, limit: int = 120) -> str:
    return " ".join(str(value or "").split())[:limit]


def format_context(
    facts: Mapping[str, Any],
    plate: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    route: str,
    world_results: Mapping[str, str],
) -> str:
    """Serialize only fields projected by caller-scoped readers; data cannot close its fence."""
    lines: list[dict[str, str]] = []
    if route:
        lines.append({"page": _short(route)})
    for turn in reversed(list(history)[-6:]):
        lines.append(
            {"prior_question": _short(turn.get("question"), 60), "prior_answer": _short(turn.get("answer"), 60)}
        )
    worlds = _rows(facts.get("worlds"), "worlds")[:4]
    worlds.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    for row in worlds:
        wid = str(row.get("world_id"))
        lines.append(
            {
                "world": _short(row.get("title")),
                "status": _short(row.get("status"), 30),
                "result": _short(world_results.get(wid)),
            }
        )
    plate_rows = _rows(plate, "rows")
    for row in plate_rows:
        lines.append({"needs_you": _short(row.get("title")), "due": _short(row.get("at"), 30)})
    calendar = _rows(facts.get("calendar"), "items")
    calendar.sort(key=lambda row: str(row.get("start")))
    for row in calendar[:5]:
        lines.append({"agenda": _short(row.get("title")), "at": _short(row.get("start"), 35)})
    pins = _rows(facts.get("pins"), "items")
    pins.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    for row in pins[:4]:
        lines.append({"pin": _short(row.get("title")), "note": _short(row.get("body"), 80)})
    for team in facts.get("teams", [])[:10]:
        lines.append({"team": _short(team, 60)})
    workspace = facts.get("workspace", {})
    for row in _rows(workspace, "skills")[:8]:
        if row.get("status") == "active" and not row.get("paused"):
            lines.append({"skill": _short(row.get("name"))})
    for row in _rows(workspace, "connectors")[:8]:
        if row.get("state") == "connected":
            lines.append({"connector": _short(row.get("id"))})
    body = "<<<CONTEXT\n"
    for line in lines:
        item = neutralise_marker(json.dumps(line, ensure_ascii=True, separators=(",", ":")), "CONTEXT") + "\n"
        if len((body + item + "CONTEXT>>>").encode("utf-8")) > MAX_CONTEXT_BYTES:
            continue
        body += item
    return body + "CONTEXT>>>"


def build_context(request: Any, principal: Any, store: Any, history: Sequence[Mapping[str, Any]], route: str) -> str:
    """Reuse the context and plate read oracles; unavailable sources contribute no facts."""
    from tilo_api import deps  # noqa: PLC0415
    from tilo_api.connectors_list import _optional_views  # noqa: PLC0415
    from tilo_api.context_panel import _context  # noqa: PLC0415

    def resolve(factory: Any) -> Any:
        provider = request.app.dependency_overrides.get(factory, factory)
        if provider is factory and factory in (deps.get_people_stores, deps.get_source_owners, deps.get_plate_sources):
            return provider(request)
        return provider()

    facts: Mapping[str, Any] = {}
    plate: Mapping[str, Any] = {}
    results: dict[str, str] = {}
    if not principal.demo_session:
        try:
            people, clock, owners = (
                resolve(deps.get_people_stores),
                resolve(deps.get_clock),
                resolve(deps.get_source_owners),
            )
            facts = _context(
                principal,
                people,
                clock,
                owners,
                store,
                resolve(deps.get_skill_store),
                resolve(deps.get_connector_registry),
                _optional_views(request),
            )
            own_worlds = [
                row
                for row in _rows(facts.get("worlds"), "worlds")
                if getattr(store.worlds.get(row.get("world_id")), "owner", None) == principal.user_id
            ]
            facts = {**facts, "worlds": {"worlds": own_worlds}}
            for row in own_worlds:
                wid = row.get("world_id")
                world = store.worlds.get(wid) if isinstance(wid, str) else None
                if world is not None and world.owner == principal.user_id:
                    for event in reversed(store.events.get(wid, [])):
                        if event.get("type") in ("world.completed", "world.failed"):
                            results[wid] = str(event.get("summary") or "")
                            break
            try:
                source = resolve(deps.get_plate_sources)
                cards = []
                for fact in source.cards(principal.user_id):
                    card = fact.get("data", {})
                    mine = fact.get("world_owner") == principal.user_id or fact.get("approver") == principal.user_id
                    if mine and fact.get("answered") is False and card.get("kind") in ("gate", "consent", "needs_you"):
                        cards.append({"title": card.get("what_happened"), "at": card.get("created_at")})
                cards.sort(key=lambda row: str(row.get("at") or ""), reverse=True)
                plate = {"rows": cards[:8]}
            except Exception:
                pass  # A missing card source cannot widen scope or make up cards.
        except Exception:
            pass  # Quick can still answer without a broken optional context read.
    return format_context(facts, plate, history, route, results)
