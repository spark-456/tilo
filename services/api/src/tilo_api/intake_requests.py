"""Existing Idempotency-Key protocol for Thinking intake; no new persisted fields or events."""

import asyncio
import hashlib
import json
import re
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from tilo_planning.artifacts import new_ulid
from tilo_planning.intake import IntakeRequest

from tilo_api import quick

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class _Fingerprint(BaseModel):
    digest: str


class _Response(Exception):
    def __init__(self, value: JSONResponse):
        self.value = value


def identifiers(uid: str, key: str | None) -> tuple[str, str, str]:
    if key is None:
        return f"t_{new_ulid()}", f"w_{new_ulid()}", f"r_{new_ulid()}"
    found = []
    for prefix in ("t", "w", "r"):
        raw = json.dumps(["/intake#thinking", uid, key, prefix], separators=(",", ":")).encode()
        number = int.from_bytes(hashlib.sha256(raw).digest()[:16], "big")
        found.append(prefix + "_" + "".join(_ALPHABET[(number >> (5 * i)) & 31] for i in range(25, -1, -1)))
    return found[0], found[1], found[2]


async def once(
    owner: object,
    uid: str,
    key: str,
    request: IntakeRequest,
    scenario: str | None,
    perform: Callable[[], Coroutine[Any, Any, Any]],
) -> Any:
    if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", key) is None:
        raise HTTPException(status_code=422, detail="The Idempotency-Key is not valid.")
    payload = [
        "/intake#thinking",
        uid,
        key,
        request.text,
        scenario,
        [(f.filename, hashlib.sha256(f.content).hexdigest()) for f in request.files],
    ]
    fingerprint = _Fingerprint(digest=hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest())

    def make() -> dict[str, Any]:
        result = asyncio.run(perform())
        if isinstance(result, JSONResponse):
            raise _Response(result)  # refusals leave the existing limiter key free
        return result

    try:
        return await run_in_threadpool(
            quick._limits_of(owner).once,
            uid,
            "/intake#thinking",
            hashlib.sha256(key.encode()).hexdigest(),
            fingerprint,
            make,
        )
    except _Response as response:
        return response.value
