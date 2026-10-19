"""`GET /cards` (S-06 needs-you queue; FR-HIL-01 card structure, FR-HIL-02 timeouts and batching, FR-HIL-11 an answer on
one channel closes the card everywhere; services/api/tests/API_S_06_CARDS_FEED.md, BQ-S06-1..8).

A read-only feed of the caller's open cards across worlds, oldest first. Visibility and redaction are never
re-implemented: each in-scope world is read through `CardStore.list_for_world(world_id, principal=<the caller narrowed
to that world>)`, the callee of `GET /worlds/{id}/cards`, so a card is exactly what that route shows the same person.
Scope is `GET /worlds`' (BQ-S14-1): an owner covers every world whose record owner is their user id, anyone else only
the world their principal names. A Viewer, a person with no world or an unknown world gets an empty list, never an
error (no membership oracle). Nothing is written: the read never ticks and never closes a card.

The cursor is an opaque keyset position (`created_at`, `world_id`, `card_id`) with a keyed MAC over the caller's user
id, so another person's cursor and a forged one are a 400, and the scope is applied on every page whatever it says.
The key comes from `TILO_CARDS_CURSOR_KEY` when it is at least 32 characters; unset or shorter, a random per-process
key is used (cursors then do not outlive a restart, which only costs a 400 and a fresh first page).
A failing world store is a fixed 503 with no exception text: a partial feed would silently drop a waiting decision.
"""

from __future__ import annotations

import binascii
import dataclasses
import hashlib
import hmac
import json
import logging
import os
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from tilo_api import runs
from tilo_api.cards import as_read_by
from tilo_api.deps import Principal, Store, get_current_principal, get_store
from tilo_api.worlds_list import _MAX_CURSOR_CHARS, _b64, _unb64

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_LIMIT, MAX_LIMIT = 20, 100
_MIN_KEY_CHARS = 32
_PROCESS_KEY = secrets.token_bytes(32)
_Position = tuple[str, str, str]  # (created_at, world_id, card_id): the total order, oldest first


def _key() -> bytes:
    configured = os.environ.get("TILO_CARDS_CURSOR_KEY", "")
    return configured.encode() if len(configured) >= _MIN_KEY_CHARS else _PROCESS_KEY


def _mac(user_id: str, payload: str) -> str:
    return _b64(hmac.new(_key(), f"cards\0{user_id}\0{payload}".encode(), hashlib.sha256).digest()[:16])


def _encode_cursor(user_id: str, position: _Position) -> str:
    payload = _b64(json.dumps(list(position)).encode())
    return f"{payload}.{_mac(user_id, payload)}"


def _decode_cursor(user_id: str, cursor: str) -> _Position:
    """The position a cursor minted for this user names; a cursor that is not exactly that is a 400."""
    bad = HTTPException(status_code=400, detail="bad_cursor")
    payload, dot, tag = cursor.partition(".")
    if (
        not dot
        or len(cursor) > _MAX_CURSOR_CHARS
        or not hmac.compare_digest(tag.encode(), _mac(user_id, payload).encode())
    ):
        raise bad
    try:
        created_at, world_id, card_id = json.loads(_unb64(payload))
    except (ValueError, TypeError, binascii.Error) as exc:
        raise bad from exc
    if not all(isinstance(part, str) for part in (created_at, world_id, card_id)):
        raise bad
    return (created_at, world_id, card_id)


def _scope(principal: Principal, store: Store) -> list[str]:
    if principal.role == "owner":
        store.load_owner(principal.user_id, settle=True)
        return [w for w, rec in store.worlds.items() if rec.owner == principal.user_id]
    named = store.load_world(principal.world_id, settle=True) if principal.world_id is not None else None
    return [principal.world_id] if principal.world_id is not None and named is not None else []


def _world_cards(principal: Principal, store: Store, world_id: str) -> list[tuple[_Position, dict[str, Any]]]:
    """One world's open cards as the caller may see them; a card with no usable ids or stamp is skipped."""
    narrowed = dataclasses.replace(principal, world_id=world_id)  # only the world changes, never role or user
    try:
        cards = runs.get_card_store(world_id, store).list_for_world(world_id, principal=narrowed)
    except PermissionError:
        return []  # a Viewer, or not a member: nothing shown, as the per-world route shows nothing
    except Exception as exc:
        logger.warning("the needs-you feed could not read a world's cards: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="cards_unavailable") from None
    found = []
    for card in cards:
        if isinstance(card, dict) and all(isinstance(card.get(k), str) for k in ("created_at", "id", "world_id")):
            found.append(card)
    shown = as_read_by(principal, world_id, found)  # what the per-world route shows this session (BQ-XWORLD-9)
    return [((card["created_at"], card["world_id"], card["id"]), card) for card in shown]


@router.get("/cards")
def list_cards(
    principal: Annotated[Principal, Depends(get_current_principal)],
    store: Annotated[Store, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> JSONResponse:
    after = _decode_cursor(principal.user_id, cursor) if cursor is not None else None  # before any world is read
    queue = sorted((c for w in _scope(principal, store) for c in _world_cards(principal, store, w)), key=lambda c: c[0])
    rest = [c for c in queue if after is None or c[0] > after]
    page = rest[:limit]
    items = [{"world_id": card["world_id"], "card_id": card["id"], "card": card} for _, card in page]
    more = len(rest) > limit
    return JSONResponse(
        content={
            "cards": items,
            "count": len(queue),
            "next_cursor": _encode_cursor(principal.user_id, page[-1][0]) if more else None,
        }
    )
