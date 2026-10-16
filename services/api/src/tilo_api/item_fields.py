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

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from tilo_memory.artifacts import ArtifactError

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
        raise HTTPException(
            status_code=404, detail="Tilo could not find that."
        )  # one answer for every caller who may not supply: no oracle
    if record_owner is not None and actor.user_id != record_owner:  # defence in depth: the role alone is not the owner
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    if from_channels or not session_allows(actor, actor.channel, False):
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
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
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
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
            raise HTTPException(status_code=404, detail="Tilo could not find that.") from None
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


MAX_DOCUMENT_CHARS = 65_536  # one pinned document as shown (show-me); the execute contract's own cap is smaller
MAX_CONTENT_B64 = 43_692  # a file document's content_b64 (contracts: execute item)
_ITEM_FIELDS = {  # the allowlist of the L5 formats: nothing else a document might carry is ever returned
    "email": ("subject", "body_text", "in_reply_to", "references"),
    "file": ("name", "mime_type", "content_b64"),
    "calendar_event": ("title", "start", "end", "time_zone"),
}
_UNAVAILABLE = {"reason": "item_unavailable"}  # one fixed answer: no error text, no byte of a refused document


def shown_document(raw: bytes, recipients: object) -> dict[str, Any] | None:
    """The pinned document's allowlisted fields (+ the card's recipients), or None when it is not one we can show."""
    if len(raw) > MAX_DOCUMENT_CHARS * 4:  # bytes before decoding: a UTF-8 char is at most 4
        return None
    try:
        text = raw.decode("utf-8")
        parsed = json.loads(text) if len(text) <= MAX_DOCUMENT_CHARS else None
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(parsed, dict) or parsed.get("kind") not in _ITEM_FIELDS:
        return None
    kind = str(parsed["kind"])
    out: dict[str, Any] = {"kind": kind}
    for name in _ITEM_FIELDS[kind]:
        value = parsed.get(name)
        if isinstance(value, str) and (name != "content_b64" or len(value) <= MAX_CONTENT_B64):
            out[name] = value
        elif value is not None:
            return None  # a field of the wrong type or size: refused whole, never trimmed
    if kind == "file" and isinstance(parsed.get("origin"), dict) and parsed["origin"].get("kind") == "render":
        out["origin"] = {"kind": "render"}
    guests = parsed.get("attendees")
    reminders = parsed.get("reminders")
    if kind == "calendar_event" and reminders is not None:
        if (
            not isinstance(reminders, list)
            or len(reminders) > 5
            or any(
                not isinstance(row, dict)
                or set(row) != {"method", "minutes"}
                or row["method"] not in ("popup", "email")
                or type(row["minutes"]) is not int
                or not 0 <= row["minutes"] <= 40320
                for row in reminders
            )
        ):
            return None
        out["reminders"] = reminders
    if kind == "calendar_event" and guests is not None:
        if not (
            isinstance(guests, list) and len(guests) <= 50 and all(isinstance(g, str) and len(g) <= 254 for g in guests)
        ):
            return None
        out["attendees"] = guests
    if kind == "email" and isinstance(recipients, list) and all(isinstance(r, str) for r in recipients):
        out["recipients"] = recipients
    return out


@router.get("/worlds/{world_id}/cards/{card_id}/item")
def pinned_item(
    world_id: str,
    card_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    from_channels: Annotated[bool, Depends(get_channels_caller)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    cards: Annotated[CardStore, Depends(get_card_store)],
    record_owner: Annotated[str | None, Depends(world_owner)],
) -> JSONResponse:
    """Show me (ADR-0035 L6d): the document pinned on this open gate card, for the world's owner alone. A READ: no
    event, no state change. The bytes come hash-checked from the artifact store (AR-01); a mismatch, a missing or
    oversize or odd document is one fixed 409 and never the bytes. Everyone else gets the fields route's one 404."""
    run, _ = _owned_run(world_id, card_id, principal, from_channels, store, cards, record_owner)
    card = cards.get(world_id, card_id)
    gate: dict[str, Any] = (card or {}).get("gate") or {} if (card or {}).get("kind") == "gate" else {}
    ref = (gate.get("action") or {}).get("item")
    if not isinstance(ref, dict):
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    try:
        shown = shown_document(run.read_pinned(ref), gate.get("recipients"))
    except (ArtifactError, ValueError):  # absent, corrupt (the hash does not match), busy or a malformed ref
        shown = None
    if shown is None:
        return JSONResponse(status_code=409, content=_UNAVAILABLE)
    return JSONResponse(status_code=200, content=shown)
