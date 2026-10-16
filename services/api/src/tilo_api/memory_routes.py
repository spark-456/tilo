"""Private memory routes (ADR-0049 MI-01..03, MI-06, MI-09)."""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from tilo_policy.schemas import conforms
from tilo_providers.interfaces import SafetyProvider

from tilo_api import deps, ephemeral, events
from tilo_api.memory_store import FirestoreMemoryStore, InMemoryMemoryStore, MemoryFull

router = APIRouter()
_ID = re.compile(r"mem_[0-9A-Za-z_]{1,48}\Z")
_DEV_STORE = InMemoryMemoryStore()
_NOT_FOUND = HTTPException(status_code=404, detail="not_found")


def get_memory_store(request: Request) -> Any:
    if (demo := ephemeral.for_request(request)) is not None:
        return demo._once("memory", InMemoryMemoryStore)
    if "K_SERVICE" not in os.environ and "CLOUD_RUN_JOB" not in os.environ:
        return _DEV_STORE
    stores = deps.get_people_stores(request)
    client = getattr(stores.work_items, "_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="not_configured")
    return FirestoreMemoryStore(client)


def get_memory_safety(safety: Annotated[SafetyProvider, Depends(deps.get_safety)]) -> SafetyProvider:
    return safety


class MemoryEvents:
    def __init__(self, writer: deps.EventWriter, desks: deps.DeskWorlds) -> None:
        self.writer, self.desks = writer, desks

    def record(self, actor: str) -> None:
        world = self.desks.desk_world(deps.ORG_ID, actor)
        if not (isinstance(world, str) and world.startswith("w_desk_") and self.desks.desk_owner(world) == actor):
            raise ValueError("not the owner's Desk world")
        self.writer.append(
            world,
            {
                "id": events.new_part_id(),
                "type": "memory.saved",
                "actor": actor,
                "target": actor,
                "summary": "You saved a note for Tilo.",
                "district": None,
                "vis": [],
                "authz": None,
                "data": {"layer": "preferences", "item_count": 1},
            },
        )


def get_memory_events(
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    desks: Annotated[deps.DeskWorlds, Depends(deps.get_desk_worlds)],
) -> MemoryEvents:
    return MemoryEvents(writer, desks)


Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]
Store = Annotated[Any, Depends(get_memory_store)]
Safety = Annotated[SafetyProvider, Depends(get_memory_safety)]
Clock = Annotated[Any, Depends(deps.get_clock)]
Events = Annotated[MemoryEvents, Depends(get_memory_events)]


def _safe_text(value: Any, safety: SafetyProvider, redactor: Any) -> str:
    if not isinstance(value, str):
        raise HTTPException(422, "text")
    text = value.strip()
    if any(unicodedata.category(c) in {"Cc", "Cf", "Co", "Cs", "Zl", "Zp"} for c in text) or any(
        0xFE00 <= ord(c) <= 0xFE0F or 0xE0100 <= ord(c) <= 0xE01EF for c in text
    ):
        raise HTTPException(422, "text")
    try:
        if redactor(text) != text:
            raise HTTPException(422, "text")
        if safety.check(text)["flagged"]:
            raise HTTPException(422, "text")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "safety_unavailable") from exc
    return text


async def _body(request: Request, schema: str, safety: SafetyProvider, redactor: Any) -> dict[str, Any]:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 4096:
            raise HTTPException(413, "body_too_large")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        import json

        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "body") from exc
    if not isinstance(body, dict):
        raise HTTPException(422, "body")
    if "text" in body:
        body["text"] = _safe_text(body["text"], safety, redactor)
    if not conforms(f"memory_item.schema.json#/$defs/{schema}", body):
        allowed = {"text", "kind", "source"} if schema == "create" else {"text", "kind"}
        bad = next((k for k in body if k not in allowed), None)
        if bad is None:
            bad = next((k for k in allowed if k not in body and schema == "create"), None)
        if bad is None:
            bad = next((k for k in body if not conforms(f"memory_item.schema.json#/$defs/{k}", body[k])), "body")
        raise HTTPException(422, bad)
    return body


def _call(operation: Any) -> Any:
    try:
        return operation()
    except MemoryFull as exc:
        raise HTTPException(409, "memory_full") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "store_unavailable") from exc


@router.get("/v1/memory")
def list_memory(principal: Principal, store: Store) -> dict[str, Any]:
    return {"items": _call(lambda: store.list(deps.ORG_ID, principal.user_id))}


@router.post("/v1/memory")
async def create_memory(
    request: Request,
    principal: Principal,
    store: Store,
    safety: Safety,
    clock: Clock,
    memory_events: Events,
    redactor: Annotated[Any, Depends(deps.get_redactor)],
) -> JSONResponse:
    body = await _body(request, "create", safety, redactor)
    item, created = _call(
        lambda: store.create(deps.ORG_ID, principal.user_id, body["text"], body["kind"], body["source"], clock())
    )
    if created:
        try:
            memory_events.record(principal.user_id)
        except Exception as exc:
            _call(lambda: store.delete(deps.ORG_ID, principal.user_id, item["id"]))
            raise HTTPException(503, "event_unavailable") from exc
    return JSONResponse(status_code=201 if created else 200, content=item)


@router.patch("/v1/memory/{item_id}")
async def change_memory(
    item_id: str,
    request: Request,
    principal: Principal,
    store: Store,
    safety: Safety,
    clock: Clock,
    memory_events: Events,
    redactor: Annotated[Any, Depends(deps.get_redactor)],
) -> dict[str, Any]:
    old = _call(lambda: store.get(deps.ORG_ID, principal.user_id, item_id)) if _ID.fullmatch(item_id) else None
    if old is None:
        raise _NOT_FOUND
    body = await _body(request, "update", safety, redactor)
    if all(old.get(k) == v for k, v in body.items()):
        return old
    item = _call(lambda: store.update(deps.ORG_ID, principal.user_id, item_id, body, clock()))
    if item is None:
        raise _NOT_FOUND
    try:
        memory_events.record(principal.user_id)
    except Exception as exc:
        _call(
            lambda: store.update(
                deps.ORG_ID, principal.user_id, item_id, {"text": old["text"], "kind": old["kind"]}, old["updated_at"]
            )
        )
        raise HTTPException(503, "event_unavailable") from exc
    return item


@router.delete("/v1/memory/{item_id}", status_code=204)
def delete_memory(item_id: str, principal: Principal, store: Store) -> Response:
    if not _ID.fullmatch(item_id) or not _call(lambda: store.delete(deps.ORG_ID, principal.user_id, item_id)):
        raise _NOT_FOUND
    return Response(status_code=204)
