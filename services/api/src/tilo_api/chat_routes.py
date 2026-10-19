"""Owner-scoped Quick chat transcripts. Quick itself creates no world or event."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from tilo_api import deps, ephemeral

router = APIRouter()
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_DEV: MemoryChatStore | None = None


class MemoryChatStore:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, dict[str, Any]]] = {}
        self.lock = threading.Lock()

    def list(self, owner: str) -> list[dict[str, Any]]:
        with self.lock:
            return sorted(self.items.get(owner, {}).values(), key=lambda item: (-item["updated_at"], item["id"]))[:100]

    def put(self, owner: str, item: dict[str, Any]) -> None:
        with self.lock:
            entries = self.items.setdefault(owner, {})
            if item["id"] not in entries and len(entries) >= 100:
                raise HTTPException(409, "chat_limit")
            entries[item["id"]] = item


class FirestoreChatStore:
    def __init__(self, client: Any) -> None:
        self.client = client

    def _collection(self, owner: str) -> Any:
        digest = hashlib.sha256(owner.encode()).hexdigest()
        return self.client.collection(f"orgs/{deps.ORG_ID}/chat_users/{digest}/chats")

    def list(self, owner: str) -> list[dict[str, Any]]:
        items = [snap.to_dict() for snap in self._collection(owner).stream()]
        return sorted(
            (item for item in items if isinstance(item, dict)),
            key=lambda item: (-item.get("updated_at", 0), item.get("id", "")),
        )[:100]

    def put(self, owner: str, item: dict[str, Any]) -> None:
        collection = self._collection(owner)
        ref = collection.document(item["id"])
        if not ref.get().exists and sum(1 for _ in collection.limit(101).stream()) >= 100:
            raise HTTPException(409, "chat_limit")
        ref.set(item)


def get_chat_store(request: Request) -> MemoryChatStore | FirestoreChatStore:
    global _DEV
    if (demo := ephemeral.for_request(request)) is not None:
        return demo._once("chats", MemoryChatStore)
    if not deps.enforced():
        if _DEV is None:
            _DEV = MemoryChatStore()
        return _DEV
    people = deps.get_people_stores(request)
    client = getattr(people.work_items, "_client", None)
    if client is None:
        raise HTTPException(503, "not_configured")
    return FirestoreChatStore(client)


Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]
Store = Annotated[MemoryChatStore | FirestoreChatStore, Depends(get_chat_store)]


def _owner(principal: deps.Principal) -> str:
    if principal.demo_session:
        raise HTTPException(403, "demo_read_only")
    return principal.user_id


@router.get("/v1/me/chats")
def list_chats(principal: Principal, store: Store) -> JSONResponse:
    return JSONResponse({"chats": store.list(_owner(principal))}, headers={"Cache-Control": "no-store"})


@router.put("/v1/me/chats/{chat_id}")
async def put_chat(chat_id: str, request: Request, principal: Principal, store: Store) -> JSONResponse:
    owner = _owner(principal)
    if not _ID.fullmatch(chat_id):
        raise HTTPException(422, "chat_id")
    raw = await request.body()
    if len(raw) > 65536:
        raise HTTPException(413, "chat_too_large")
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(422, "chat_body") from exc
    if not isinstance(body, dict) or not isinstance(body.get("title"), str) or not isinstance(body.get("turns"), list):
        raise HTTPException(422, "chat_body")
    title = body["title"].strip()[:80]
    turns = body["turns"]
    if not title or not 1 <= len(turns) <= 100:
        raise HTTPException(422, "chat_body")
    clean: list[dict[str, Any]] = []
    seen: set[int] = set()
    for turn in turns:
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), int) or turn["id"] in seen:
            raise HTTPException(422, "chat_turn")
        question = turn.get("question")
        state = turn.get("state")
        if (
            not isinstance(question, str)
            or not 1 <= len(question) <= 500
            or state not in ("answered", "switch", "error")
        ):
            raise HTTPException(422, "chat_turn")
        field = "text" if state == "answered" else "message" if state == "error" else "reason"
        value = turn.get(field)
        if not isinstance(value, str) or len(value) > 16000:
            raise HTTPException(422, "chat_turn")
        seen.add(turn["id"])
        clean.append(
            {
                "id": turn["id"],
                "question": question,
                "state": state,
                field: value,
                **({"sample": bool(turn.get("sample")), "seconds": 0, "cost": None} if state == "answered" else {}),
            }
        )
    item = {"id": chat_id, "title": title, "updated_at": time.time_ns(), "turns": clean}
    store.put(owner, item)
    return JSONResponse(item, headers={"Cache-Control": "no-store"})
