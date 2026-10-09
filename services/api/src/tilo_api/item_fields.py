"""tilo_api.item_fields: the person supplies a field a live item document lacks (ADR-0035 L6b, FR-CON-02).

`POST /worlds/{world_id}/cards/{card_id}/fields` `{"fields": {"subject": "..."}}` answers the run's needs-field card:
the run checks the values (a plain 422 reason when the document would refuse them), keeps them for the waiting step,
and the card is answered `provide` through the same CardStore rules as any answer (same session, role and Pause-all
guards). The values are never logged or put in an event; they reach the person's approval only as the pinned document.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from tilo_api import deps
from tilo_api.cards import _STATUS, CardStore, answering_principal, get_channels_caller, session_allows
from tilo_api.runs import answer_guard, get_card_store, world_owner

logger = logging.getLogger("tilo_api.item_fields")
router = APIRouter()


class _FieldsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, str]


@router.post("/worlds/{world_id}/cards/{card_id}/fields", dependencies=[Depends(answer_guard)])
def supply_fields(
    world_id: str,
    card_id: str,
    body: _FieldsBody,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    from_channels: Annotated[bool, Depends(get_channels_caller)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    cards: Annotated[CardStore, Depends(get_card_store)],
    record_owner: Annotated[str | None, Depends(world_owner)],
) -> JSONResponse:
    actor = answering_principal(
        principal, world_id, record_owner=record_owner, cards=cards, from_channels=from_channels
    )
    run = store.runs.get(world_id)
    if actor is None or run is None:
        raise HTTPException(status_code=404)
    if from_channels or not session_allows(actor, actor.channel, False):
        return JSONResponse(status_code=403, content={"outcome": "rejected", "reason": "channel_not_permitted"})
    try:
        run.stage_fields(card_id, body.fields)
    except LookupError:
        raise HTTPException(status_code=404) from None
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"outcome": "rejected", "reason": str(exc)})
    try:
        result = cards.answer(world_id, card_id, option="provide", channel=actor.channel, principal=actor)
    except Exception as exc:  # the event write failed; the card stays open and the fields can be sent again
        run.unstage_fields(card_id)
        logger.warning("fields could not be answered: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"outcome": "error", "reason": "event_write_failed"})
    if result.outcome != "answered":
        run.unstage_fields(card_id)
        return JSONResponse(
            status_code=_STATUS.get(result.reason or "", 400), content={"outcome": "rejected", "reason": result.reason}
        )
    return JSONResponse(status_code=200, content={"outcome": "answered"})
