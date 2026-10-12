"""The person's own web-push subscription (FR-CHN-17b; PRD 11, 16; BQ-CHN17-1, BQ-CHN17b-1).

`POST /v1/push/subscribe` {endpoint, keys: {p256dh, auth}} stores one browser of the verified principal, `POST
/v1/push/unsubscribe` {endpoint} removes it, `GET /v1/push` says how many devices are stored and whether Tilo can
send to them. Only a full web sign-in session calls (a demo session is 403); the owner is `principal.user_id`, never a
body field. The endpoint is untrusted input: tilo-channels' `parse_subscription` checks it (https, length, push
service host allowlist, key shape) and the store caps the devices per person; a refusal names the problem, never the
value. Endpoint and keys are never logged or returned. A stored subscription alone sends nothing: push needs the
owner's standing L3 `send_push` policy (BQ-CHN17-1, the user's decision), and until it exists the answer says
`off_until_owner_policy` plainly. `public_key` is the deployment's VAPID public key
(`TILO_WEBPUSH_VAPID_PUBLIC_KEY`, not a secret) or null when push is not set up. Every POST counts against the
people write limit; every answer is no-store.
"""

from __future__ import annotations

import os
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import Field
from tilo_channels.web_push import SubscriptionLimit, SubscriptionRefused

from tilo_api import deps
from tilo_api.people import _PeopleRoute
from tilo_api.people_writes import Refusal, _Closed, json_body

router = APIRouter(route_class=_PeopleRoute)
ACTION = "send_push"
ENV_PUBLIC_KEY = "TILO_WEBPUSH_VAPID_PUBLIC_KEY"  # the VAPID PUBLIC key (not a secret), set at deploy
_KEY_SHAPE = re.compile(r"^[A-Za-z0-9_-]{80,100}\Z")


class _Keys(_Closed):
    p256dh: Annotated[str, Field(max_length=128)]
    auth: Annotated[str, Field(max_length=64)]


class SubscribeIn(_Closed):
    endpoint: Annotated[str, Field(max_length=2048)]
    keys: _Keys


class UnsubscribeIn(_Closed):
    endpoint: Annotated[str, Field(max_length=2048)]


def _owner(principal: deps.Principal) -> str:
    if not principal.full_session or principal.channel not in ("web", "mobile_web"):
        raise Refusal(403, "forbidden")  # a demo session or a non-web channel stores no device
    return principal.user_id


def _delivery(store: Any, user: str) -> str:
    """`ready` only when the owner's own standing L3 policy for the push action exists in the store."""
    try:
        store.load_owner(user)
        covered = any(
            p.get("owner") == user and p.get("action_type") == ACTION and p.get("level") == "L3"
            for p in list(store.policies.values())
        )
    except Exception:  # noqa: BLE001 - cannot tell: say it is off, never that it is on
        covered = False
    return "ready" if covered else "off_until_owner_policy"


def _state(push: Any, store: Any, user: str) -> dict[str, Any]:
    key = os.environ.get(ENV_PUBLIC_KEY, "")
    public = key if _KEY_SHAPE.match(key) else None  # the browser needs it to subscribe; None = not set up
    return {"devices": len(push.for_user(user)), "delivery": _delivery(store, user), "public_key": public}


@router.get("/v1/push")
def status(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    push: Annotated[Any, Depends(deps.get_push_store)],
    store: Annotated[Any, Depends(deps.get_store)],
) -> dict[str, Any]:
    return _state(push, store, _owner(principal))


@router.post("/v1/push/subscribe")
def subscribe(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    body: Annotated[SubscribeIn, Depends(json_body(SubscribeIn))],
    push: Annotated[Any, Depends(deps.get_push_store)],
    store: Annotated[Any, Depends(deps.get_store)],
) -> dict[str, Any]:
    user = _owner(principal)
    try:
        push.add(user, {"endpoint": body.endpoint, "keys": {"p256dh": body.keys.p256dh, "auth": body.keys.auth}})
    except SubscriptionLimit:
        raise Refusal(409, "device_limit") from None
    except SubscriptionRefused:
        raise Refusal(422, "invalid_subscription") from None
    return _state(push, store, user)


@router.post("/v1/push/unsubscribe")
def unsubscribe(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    body: Annotated[UnsubscribeIn, Depends(json_body(UnsubscribeIn))],
    push: Annotated[Any, Depends(deps.get_push_store)],
    store: Annotated[Any, Depends(deps.get_store)],
) -> dict[str, Any]:
    user = _owner(principal)
    push.remove(user, body.endpoint)  # a device that is not stored is already gone: the same answer
    return _state(push, store, user)
