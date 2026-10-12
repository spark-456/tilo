"""tilo_channels.push_routes: `POST /internal/push/send`, the one place a web push leaves the platform (FR-CHN-17f;
PRD 6.2, 16; SEC-REVIEW-7). tilo-api's outbox adapter is the only caller: the VAPID secret is tilo-channels' alone, so
the outbox lives in tilo-api and its adapter hands the already authorised notice here over an OIDC ID token.

The caller is proven first (a Google-signed token for `TILO_PUSH_AUDIENCE`, a verified email equal to
`TILO_PUSH_CALLER`; `push_verifier`: junk is refused before any certificate fetch, which is cached and bounded, and
runs off the event loop); an unset audience or caller is 503 and nothing is read. The body is JSON only, <= 8 KiB;
every device is checked again as an allowed push service address; the notice is the fixed shape (title, body, tag, a
relative path of the one allowlisted page). Devices go out in parallel so five slow ones cost one timeout. The answer
holds counts and positions, never an endpoint, key, payload or the vendor's text. The real sender exists only on Cloud
Run with the mounted VAPID secret (`production_sender`), else 503 `not_configured`: dev and CI send nothing.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any, Protocol

from fastapi import Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tilo_channels.push_verifier import shared_verifier
from tilo_channels.web_push import (
    OPEN_PATH,
    PushSender,
    PushSubscription,
    SubscriptionGone,
    SubscriptionRefused,
    VapidRef,
    load_config,
    parse_subscription,
)
from tilo_channels.web_push_sender import production_sender

SEND_PATH = "/internal/push/send"  # added to the app by `tilo_channels.app`, a plain route
ENV_AUDIENCE, ENV_CALLER = "TILO_PUSH_AUDIENCE", "TILO_PUSH_CALLER"
MAX_BODY_BYTES = 8192
_PATH = re.compile(rf"^{re.escape(OPEN_PATH)}(\?card=[A-Za-z0-9_-]{{1,64}})?\Z")


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Keys(_Closed):
    p256dh: str = Field(max_length=128)
    auth: str = Field(max_length=64)


class _Device(_Closed):
    endpoint: str = Field(max_length=2048)
    keys: _Keys


class SendIn(_Closed):
    devices: list[_Device] = Field(min_length=1, max_length=5)
    title: str = Field(min_length=1, max_length=80)
    body: str = Field(default="", max_length=200)
    tag: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    path: str = Field(max_length=120)


class Verifier(Protocol):
    def verify(self, token: str, audience: str) -> Mapping[str, Any]: ...


def get_verifier() -> Verifier:
    return shared_verifier()  # bounded, cached certificate fetch; junk refused before any fetch (SEC-REVIEW-7b B2)


def get_sender() -> PushSender | None:
    return production_sender()


def _caller_ok(header: str, verifier: Verifier) -> None:
    """Blocking (a certificate fetch may run): the route calls it in the threadpool, never on the event loop."""
    audience, caller = os.environ.get(ENV_AUDIENCE, ""), os.environ.get(ENV_CALLER, "")
    if not audience or not caller:
        raise HTTPException(status_code=503, detail="not_configured")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        claims = verifier.verify(token.strip(), audience)
    except Exception:  # noqa: BLE001 - any failure to prove the caller is the same answer
        raise HTTPException(status_code=401, detail="unauthorized") from None
    if claims.get("email_verified") is not True or claims.get("email") != caller or claims.get("aud") != audience:
        raise HTTPException(status_code=403, detail="forbidden")


async def _body(request: Request) -> SendIn:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Send application/json.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="body_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="body_too_large")
        chunks.append(chunk)
    try:
        return SendIn.model_validate_json(b"".join(chunks))
    except ValidationError:
        raise HTTPException(status_code=422, detail="invalid_body") from None


async def send(
    request: Request,
    verifier: Annotated[Verifier, Depends(get_verifier)],
    sender: Annotated[PushSender | None, Depends(get_sender)],
) -> JSONResponse:
    await run_in_threadpool(_caller_ok, request.headers.get("authorization", ""), verifier)
    if sender is None:
        raise HTTPException(status_code=503, detail="not_configured")
    body = await _body(request)
    if _PATH.match(body.path) is None:
        raise HTTPException(status_code=422, detail="invalid_body")
    cfg = load_config()
    payload = json.dumps(
        {"title": body.title, "body": body.body, "tag": body.tag, "path": body.path}, separators=(",", ":")
    ).encode("utf-8")
    subs = [_subscription(d) for d in body.devices]
    results = await run_in_threadpool(_fan_out, sender, cfg.vapid, payload, subs)
    return JSONResponse(
        {
            "delivered": results.count("delivered"),
            "gone": [i for i, r in enumerate(results) if r == "gone"],
            "refused": [i for i, r in enumerate(results) if r == "refused"],
        },
        headers={"Cache-Control": "no-store"},
    )


def _subscription(device: _Device) -> PushSubscription | None:
    try:
        return parse_subscription({"endpoint": device.endpoint, "keys": device.keys.model_dump()}, load_config())
    except SubscriptionRefused:
        return None


def _fan_out(sender: PushSender, vapid: VapidRef, payload: bytes, subs: list[PushSubscription | None]) -> list[str]:
    def one(sub: PushSubscription | None) -> str:
        if sub is None:
            return "refused"
        try:
            sender.send(sub, payload, vapid)
        except SubscriptionGone:
            return "gone"
        except Exception:  # noqa: BLE001 - a static answer: nothing of the vendor's text leaves
            return "failed"
        return "delivered"

    run: Callable[[PushSubscription | None], str] = one
    with ThreadPoolExecutor(max_workers=5) as pool:
        return list(pool.map(run, subs))
