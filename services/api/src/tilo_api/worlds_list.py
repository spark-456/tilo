"""`GET /worlds` (S-14 Worlds list and replays, FR-WLD-08; services/api/tests/API_S_14_WORLDS_LIST.md, BQ-S14-1..5).

A read-only list of the caller's worlds, newest first. Every field is derived from the world's recorded events as
the caller's own `GET /worlds/{id}/events` view shows them (nothing stored without an event behind it, HR-1..HR-7):
`title` and `created_at` from the first `world.requested`, `status` from the latest registered `world.*` event,
`last_seq` from the last event the caller can see. Scope: an owner sees every world whose record owner is their
user id (as `GET /costs`); anyone else only the world their principal names. Nothing is written.

The cursor is an opaque keyset position (`created_at`, `world_id`) of the last item served, with a keyed MAC over the
caller's user id, so one person's cursor is refused for another and a forged one is refused. The scope is applied on
every page whatever the cursor says, so a cursor can never widen what a caller sees. The key comes from
`TILO_WORLDS_CURSOR_KEY`; unset, a random per-process key is used (cursors then do not outlive a restart or cross
instances, which only costs a 400 and a fresh first page).
Cost: the order needs each world's `created_at`, read lazily (up to the first `world.requested`); status and
`last_seq` need a full scan, done only for the worlds on the page.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Iterable, Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from tilo_api.deps import Principal, Store, WorldRecord, get_current_principal, get_store
from tilo_api.redaction import _event_hides_district, _is_malformed_event, _is_owner, _safe_districts, _visible

router = APIRouter()

DEFAULT_LIMIT, MAX_LIMIT = 20, 100
_MAX_CURSOR_CHARS = 512
_STATUS = {  # the registered world.* types and the status each sets (BQ-S14-2); any other type changes nothing (HR-5)
    "world.started": "started",
    "world.resumed": "started",
    "world.paused": "paused",
    "world.completed": "completed",
    "world.failed": "failed",
}
_PROCESS_KEY = secrets.token_bytes(32)
_Position = tuple[bool, str, str]  # (has created_at, created_at, world_id): the total order, read newest first


def _key() -> bytes:
    configured = os.environ.get("TILO_WORLDS_CURSOR_KEY")
    return configured.encode() if configured else _PROCESS_KEY


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(user_id: str, payload: str) -> str:
    return _b64(hmac.new(_key(), f"{user_id}\0{payload}".encode(), hashlib.sha256).digest()[:16])


def _encode_cursor(user_id: str, position: _Position) -> str:
    payload = _b64(json.dumps([position[1] if position[0] else None, position[2]]).encode())
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
        created_at, world_id = json.loads(_unb64(payload))
    except (ValueError, TypeError, binascii.Error) as exc:
        raise bad from exc
    if not isinstance(world_id, str) or not (created_at is None or isinstance(created_at, str)):
        raise bad
    return (created_at is not None, created_at or "", world_id)


def _view(principal: Principal, world: WorldRecord, events: Iterable[Any]) -> Iterator[dict]:
    """The events the caller sees, lazily, filtered as `GET /worlds/{id}/events` filters them."""
    owner = _is_owner(principal, world.owner)
    districts = _safe_districts(principal.districts)
    for event in events:
        if _is_malformed_event(event) or not _visible(owner, event.get("vis"), districts):
            continue
        if owner or not _event_hides_district(event, districts):
            yield event


def _requested(view: Iterator[dict]) -> dict | None:
    return next((e for e in view if e["type"] == "world.requested"), None)


def _position(principal: Principal, store: Store, world_id: str, world: WorldRecord) -> _Position:
    first = _requested(_view(principal, world, store.events.get(world_id, [])))
    created_at = first["ts"] if first is not None and isinstance(first["ts"], str) else None
    return (created_at is not None, created_at or "", world_id)


def _item(principal: Principal, store: Store, world_id: str, world: WorldRecord) -> dict[str, Any]:
    seen = list(_view(principal, world, store.events.get(world_id, [])))
    first = _requested(iter(seen))
    title = first["data"].get("title") if first is not None and isinstance(first["data"], dict) else None
    status = "idle"
    for event in seen:
        status = _STATUS.get(event["type"], status)
    # The owner's last stored seq; anyone else the last seq of their own renumbered view (BQ-S14-4, SEC-07).
    last_seq = (seen[-1]["seq"] if seen else 0) if _is_owner(principal, world.owner) else len(seen)
    return {
        "world_id": world_id,
        "title": title if isinstance(title, str) else None,
        "status": status,
        "created_at": first["ts"] if first is not None and isinstance(first["ts"], str) else None,
        "last_seq": last_seq,
    }


@router.get("/worlds")
def list_worlds(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(None),
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
) -> JSONResponse:
    after = _decode_cursor(principal.user_id, cursor) if cursor is not None else None
    if principal.role == "owner":
        store.load_owner(principal.user_id)
        scope = {w: rec for w, rec in store.worlds.items() if rec.owner == principal.user_id}
    else:
        named = store.load_world(principal.world_id) if principal.world_id is not None else None
        scope = {principal.world_id: named} if principal.world_id is not None and named is not None else {}
    ordered = sorted((_position(principal, store, w, rec) for w, rec in scope.items()), reverse=True)
    rest = [p for p in ordered if after is None or p < after]
    page = rest[:limit]
    worlds = [_item(principal, store, p[2], scope[p[2]]) for p in page]
    more = len(rest) > limit
    return JSONResponse(
        content={"worlds": worlds, "next_cursor": _encode_cursor(principal.user_id, page[-1]) if more else None}
    )
