"""The person's own web-push subscription (FR-CHN-17b; PRD 11, 16; BQ-CHN17-1, BQ-CHN17b-1).

`POST /v1/push/subscribe` {endpoint, keys: {p256dh, auth}} stores one browser of the verified principal, `POST
/v1/push/unsubscribe` {endpoint} removes it, `GET /v1/push` says how many devices are stored and whether Tilo can
send to them. Only a full web sign-in session calls (a demo session is 403); the owner is `principal.user_id`, never a
body field. The endpoint is untrusted input: tilo-channels' `parse_subscription` checks it (https, length, push
service host allowlist, key shape) and the store caps the devices per person; a refusal names the problem, never the
value. Endpoint and keys are never logged or returned. A stored subscription alone sends nothing: push needs the
owner's standing L3 `send_push` policy (BQ-CHN17-1, the user's decision), and until it exists the answer says
`off_until_owner_policy` plainly. Every POST counts against the people write limit; every answer is no-store.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, ValidationError
from tilo_channels.web_push import SubscriptionLimit, SubscriptionRefused

from tilo_api import deps
from tilo_api.people import _PeopleRoute
from tilo_api.people_writes import Refusal, _Closed

router = APIRouter(route_class=_PeopleRoute)
ACTION = "send_push"


MAX_BODY_BYTES = 4096  # a subscription is under 1 KiB: nothing larger is read, let alone parsed


def small_json_body[Body: BaseModel](model: type[Body]):  # noqa: ANN201
    """Strict JSON only (415: a cross-site form or `text/plain` POST needs no preflight, so it is refused),
    4 KiB at most before anything is parsed (413), a 422 that never echoes the input (it holds a capability)."""

    async def parse(request: Request) -> Body:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise Refusal(415, "Send application/json.")
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            raise Refusal(413, "body_too_large")
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                raise Refusal(413, "body_too_large")
            chunks.append(chunk)
        try:
            return model.model_validate_json(b"".join(chunks))
        except ValidationError as exc:
            fields = [[*e["loc"][:-1], "?"] if e["type"] == "extra_forbidden" else list(e["loc"]) for e in exc.errors()]
            raise Refusal(422, "invalid_body", fields=fields) from None

    return parse


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
    return {"devices": len(push.for_user(user)), "delivery": _delivery(store, user)}


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
    body: Annotated[SubscribeIn, Depends(small_json_body(SubscribeIn))],
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
    body: Annotated[UnsubscribeIn, Depends(small_json_body(UnsubscribeIn))],
    push: Annotated[Any, Depends(deps.get_push_store)],
    store: Annotated[Any, Depends(deps.get_store)],
) -> dict[str, Any]:
    user = _owner(principal)
    push.remove(user, body.endpoint)  # a device that is not stored is already gone: the same answer
    return _state(push, store, user)
