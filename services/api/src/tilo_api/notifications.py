"""`GET /v1/notifications`: the owner's bell (NOTIF-1; services/api/tests/test_NOTIF_1_notifications.py, BQ-NOTIF-1).

Read-only and derived, nothing stored (HR-1): an open card of the owner's is a "needs" item, and an `artifact.created`
or `data.transfer` event in one of the owner's worlds is a "done" item (a hosted meeting's success writes exactly
these). Cards are read as `GET /cards` reads them. Titles are fixed text per source, and an item carries ids only, so
no address, link, card text or event summary can reach the bell. Newest first; `count` is the whole bell, `limit`
(1 to 100, default 20) cuts the list. Only a world's owner gets items; anyone else gets an empty bell, never an error.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from tilo_api.cards_feed import _scope, _world_cards
from tilo_api.deps import Principal, Store, get_current_principal, get_store
from tilo_api.redaction import _is_malformed_event

router = APIRouter()

DEFAULT_LIMIT, MAX_LIMIT = 20, 100
_ARTIFACT_ID = re.compile(r"art_[0-9A-Za-z_]{1,48}")  # common.schema.json#/$defs/artifact_id
_NEEDS_TITLES = {
    "gate": "A send is waiting for your approval",
    "consent": "A connection is waiting for your answer",
    "meeting": "A meeting is waiting for your answer",
}
_NEEDS_DEFAULT = "A decision is waiting for you"
_DONE_TITLES = {"artifact.created": "An item is ready", "data.transfer": "An item was sent"}


def _item(kind: str, id_: str, created_at: str, world_id: str, title: str, **ref: str) -> dict[str, Any]:
    return {
        "id": id_, "kind": kind, "created_at": created_at, "world_id": world_id, "title": title,
        "card_id": ref.get("card_id"), "artifact_id": ref.get("artifact_id"),
    }  # fmt: skip


@router.get("/v1/notifications")
def list_notifications(
    principal: Annotated[Principal, Depends(get_current_principal)],
    store: Annotated[Store, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> JSONResponse:
    items: list[dict[str, Any]] = []
    if principal.role == "owner":
        for world_id in _scope(principal, store):
            for _, card in _world_cards(principal, store, world_id):
                title = _NEEDS_TITLES.get(str(card.get("kind")), _NEEDS_DEFAULT)
                items.append(_item("needs", f"c:{card['id']}", card["created_at"], world_id, title, card_id=card["id"]))
            for event in store.events.get(world_id, []):
                if (
                    _is_malformed_event(event)
                    or not isinstance(event["type"], str)
                    or event["type"] not in _DONE_TITLES
                ):
                    continue
                data = event["data"] if isinstance(event["data"], dict) else {}
                artifact = data.get("artifact_id")
                ref = (
                    {"artifact_id": artifact} if isinstance(artifact, str) and _ARTIFACT_ID.fullmatch(artifact) else {}
                )
                title = _DONE_TITLES[event["type"]]
                items.append(_item("done", f"e:{event['id']}", str(event["ts"]), world_id, title, **ref))
    items.sort(key=lambda n: (n["created_at"], n["id"]), reverse=True)
    return JSONResponse(content={"notifications": items[:limit], "count": len(items)})
