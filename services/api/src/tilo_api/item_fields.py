"""tilo_api.item_fields: the person supplies a field a live item document lacks (ADR-0035 L6b, FR-CON-02).

`POST /worlds/{world_id}/cards/{card_id}/fields` `{"fields": {"subject": "..."}}` answers the run's needs-field card.
Authorisation comes first and is the owner's alone (a full web session, the world's owner, the card open): anyone else
gets the one 404 before any value is looked at, so the route is no oracle for what a card needs. The run then checks
the values (a plain 422 reason when the document would refuse them), keeps them for the waiting step, and answers the
card `provide` through CardStore, staging and answering under the run's lock so the values belong to the answer that
wins. A people POST: strict JSON, 32 KiB cap, the people write limit. The values are never logged or put in an event;
they reach the person's approval only as the pinned document.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from tilo_api import deps, side_effect_fields
from tilo_api.cards import _STATUS, CardStore, answering_principal, get_channels_caller, session_allows
from tilo_api.people import _PeopleRoute
from tilo_api.people_writes import json_body
from tilo_api.runs import answer_guard, get_card_store, world_owner

logger = logging.getLogger("tilo_api.item_fields")
router = APIRouter(route_class=_PeopleRoute)


class _FieldsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, str]


def _owned_run(
    world_id: str, card_id: str, principal: deps.Principal, from_channels: bool, store: deps.Store,
    cards: CardStore, record_owner: str | None,
) -> tuple[Any, deps.Principal]:  # fmt: skip
    """The run whose open card this is, for the world's owner on a full web session only; else the one 404."""
    if not principal.full_session:  # an anonymous demo session has no run that sends
        raise HTTPException(status_code=403, detail="forbidden")
    actor = answering_principal(
        principal, world_id, record_owner=record_owner, cards=cards, from_channels=from_channels
    )
    run = store.runs.get(world_id)
    if actor is None or run is None or actor.role != "owner" or not cards.is_open(world_id, card_id):
        raise HTTPException(status_code=404)  # one answer for every caller who may not supply: no oracle
    if from_channels or not session_allows(actor, actor.channel, False):
        raise HTTPException(status_code=404)
    return run, actor


@router.get("/worlds/{world_id}/cards/{card_id}/fields")
def asked_fields(
    world_id: str,
    card_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    from_channels: Annotated[bool, Depends(get_channels_caller)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    cards: Annotated[CardStore, Depends(get_card_store)],
    record_owner: Annotated[str | None, Depends(world_owner)],
) -> JSONResponse:
    """What the form asks (ADR-0035 L6c): the fields this card is waiting for, with labels and hints from the config.
    Same authorisation as the POST; no value is ever returned."""
    run, _ = _owned_run(world_id, card_id, principal, from_channels, store, cards, record_owner)
    asked = run.asked_fields(card_id)
    if asked is None:
        raise HTTPException(status_code=404)
    return JSONResponse(status_code=200, content={"fields": side_effect_fields.describe(asked)})


@router.post("/worlds/{world_id}/cards/{card_id}/fields", dependencies=[Depends(answer_guard)])
def supply_fields(
    world_id: str,
    card_id: str,
    body: Annotated[_FieldsBody, Depends(json_body(_FieldsBody))],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    from_channels: Annotated[bool, Depends(get_channels_caller)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    cards: Annotated[CardStore, Depends(get_card_store)],
    record_owner: Annotated[str | None, Depends(world_owner)],
) -> JSONResponse:
    run, actor = _owned_run(world_id, card_id, principal, from_channels, store, cards, record_owner)
    with run.fields_lock:  # stage and answer as one step: the values belong to the answer that wins
        try:
            staged = run.stage_fields(card_id, body.fields)
        except LookupError:
            raise HTTPException(status_code=404) from None
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"outcome": "rejected", "reason": str(exc)})
        try:
            result = cards.answer(world_id, card_id, option="provide", channel=actor.channel, principal=actor)
        except Exception as exc:  # the event write failed; the card stays open and the fields can be sent again
            run.unstage_fields(card_id, staged)
            logger.warning("fields could not be answered: %s", type(exc).__name__)
            return JSONResponse(status_code=503, content={"outcome": "error", "reason": "event_write_failed"})
        if result.outcome != "answered":
            run.unstage_fields(card_id, staged)
            return JSONResponse(
                status_code=_STATUS.get(result.reason or "", 400),
                content={"outcome": "rejected", "reason": result.reason},
            )
    return JSONResponse(status_code=200, content={"outcome": "answered"})
