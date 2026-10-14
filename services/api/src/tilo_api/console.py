"""tilo_api.console -- the Team Lead console API (FR-HIL-10; PRD 10.5, 10.6, 16.2, 8.3; ADR-0006; BQ-204).

A routed question is shown to the Team Lead of its domain and to nobody else; answering writes the
`question.answered` part before the call returns, so the waiting agent can resume at once. The caller is the
verified principal (role `team_lead`) matched to a Team Lead record of `config/teams.yaml` by user id: the
record's domain is the console's domain, districts do not matter here, and a removed Team Lead (no record) is
refused at the next request. A record counts only if it fits `team_lead.schema.json`, its `assigned_by.by` is the
world's owner and its `assigned_by.at` is not in the future (PRD 16.2, OB-01). Cards routed to another domain or to
the owner, and gates and consents, are never listed and never answerable (404, nothing written). The answer route has
the cards router's guard (Pause all, BQ-90). No tick, poll or timer is on either path."""

from __future__ import annotations

import logging
import statistics
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ConfigDict
from tilo_policy.schemas import conforms

from tilo_api.cards import (
    _STATUS,
    CardStore,
    _AnswerBody,
    _parse_ts,
    answer_safety,
    get_channels_caller,
    session_allows,
)
from tilo_api.deps import Principal, get_current_principal

logger = logging.getLogger("tilo_api.console")
TEAMS_CONFIG = Path(__file__).resolve().parents[4] / "config" / "teams.yaml"


def get_team_leads() -> list[dict]:
    """The Team Lead records (team_lead.schema.json) of config/teams.yaml, read on every request so a removal
    takes effect at once. A file that is not a list of records raises: no records is never guessed."""
    records = yaml.safe_load(TEAMS_CONFIG.read_text(encoding="utf-8")) or []
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise ValueError("config/teams.yaml must be a list of Team Lead records")
    return records


class _ConsoleAnswer(_AnswerBody):
    model_config = ConfigDict(extra="forbid")  # no identity field: who answers is the verified principal


def _assigned(record: dict, owner: str | None, now: str) -> bool:
    """A schema-valid record the world's owner assigned, at or before now; anything else is not an assignment."""
    if owner is None or not conforms("team_lead.schema.json", record):
        return False
    stamp = record["assigned_by"]
    try:
        return stamp["by"] == owner and _parse_ts(stamp["at"]) <= _parse_ts(now)
    except ValueError:
        return False


def _lead_record(principal: Principal, team_leads: list[dict], cards: CardStore, world_id: str) -> dict:
    """The caller's Team Lead record, or 403: a Team Lead role with no current, owner-assigned record is a removed or
    an impersonated one. A user with several records gets the first valid one (BQ-214)."""
    if principal.role == "team_lead":
        owner, now = cards.owner_of(world_id), cards.now()
        for record in team_leads:
            if record.get("user") == principal.user_id and _assigned(record, owner, now):
                return record
    raise HTTPException(status_code=403, detail="You do not have access to this.")


def build_router(
    cards: CardStore | Callable[..., CardStore], *, answer_guard: Callable[..., None] | None = None
) -> APIRouter:
    """`cards` is one CardStore, or a dependency that finds the world's own; `answer_guard` (a dependency) may refuse
    an answer before the store sees it, like `cards.build_router`: Pause all stops the console too."""
    router = APIRouter()
    get_cards = cards if not isinstance(cards, CardStore) else (lambda: cards)
    guards = [Depends(answer_guard)] if answer_guard is not None else []

    @router.get("/worlds/{world_id}/console")
    def console(
        world_id: str,
        principal: Principal = Depends(get_current_principal),
        team_leads: list[dict] = Depends(get_team_leads),
        store: CardStore = Depends(get_cards),
    ) -> dict[str, Any]:
        if principal.world_id != world_id:
            raise HTTPException(status_code=404, detail="Tilo could not find that.")  # same as an unknown world
        lead = _lead_record(principal, team_leads, store, world_id)
        history = store.lead_answers(world_id, principal.user_id)
        times = [h["answer_time_s"] for h in history]
        return {
            "team_lead": lead["id"],
            "domain": lead["domain"],
            "queue": store.list_for_domain(world_id, lead["domain"]),
            "history": history,
            "stats": {"answered": len(times), "median_answer_s": statistics.median(times) if times else None},
        }

    @router.post("/worlds/{world_id}/console/cards/{card_id}/answer", dependencies=guards)
    def answer(
        world_id: str,
        card_id: str,
        body: _ConsoleAnswer,
        safety: Any = Depends(answer_safety),
        principal: Principal = Depends(get_current_principal),
        from_channels: bool = Depends(get_channels_caller),
        team_leads: list[dict] = Depends(get_team_leads),
        store: CardStore = Depends(get_cards),
    ) -> JSONResponse:
        if principal.world_id != world_id:
            raise HTTPException(status_code=404, detail="Tilo could not find that.")
        lead = _lead_record(principal, team_leads, store, world_id)
        if from_channels or not session_allows(principal, principal.channel, False):  # the lead's own signed-in session
            return JSONResponse(status_code=400, content={"outcome": "rejected", "reason": "invalid_channel"})
        try:
            result = store.answer(
                world_id,
                card_id,
                option=body.option,
                text=body.text,
                safety=safety,
                channel=principal.channel,
                principal=principal,
                console_domain=lead["domain"],
            )
        except Exception as exc:  # the event write failed; the card stays open and the answer can be sent again
            logger.warning("a console answer could not be written: %s", type(exc).__name__)
            return JSONResponse(status_code=503, content={"outcome": "error", "reason": "event_write_failed"})
        if result.outcome == "answered":
            return JSONResponse(status_code=200, content={"outcome": "answered"})
        return JSONResponse(
            status_code=_STATUS.get(result.reason or "", 400),
            content={
                "outcome": "rejected",
                "reason": result.reason,
                **({"detail": result.reason} if " " in (result.reason or "") else {}),
            },
        )

    return router
