"""tilo_connectors.host_routes — the internal meeting-host surface (ADR-0032 T3, FR-MTG-09).

Three POST routes (`send`, `status`, `disconnect`) under `/internal/meeting-host/` and `/internal/connections/views`
(ADR-0032 addendum 1: a store read of the caller's display views, no KMS and no Google call), shaped by
`contracts/meeting_host_rpc.schema.json`. Order on every call: configuration (503), caller (HB-01: 401, 403), body cap
of 64 KiB read before parsing, request validated against the contract (422), then the work, and the answer validated
against the contract too. A refusal is a fixed code. No token, OAuth code, Meet link or address is in an answer or a
log line; a failure logs its exception type only.

ADR-0035 L3 adds `/internal/connections/{start,callback,disconnect}` (LC-05, LC-06): the Google sign-in for any oauth2
connector, over `ConsentService` and the broker. The consent flows stay in this process (one instance until ADR-0032
T7). A refusal of the callback is one of three fixed 400 codes; no code, state, verifier or token is ever logged or
echoed. Their parts may name any connector and `connection.established` (`connector_parts`); the meeting-host routes
keep the narrower `parts`.

ADR-0035 L5 adds `/internal/side-effects/execute` (`side_effect_execute.py`, LC-07): `send`'s checks for gmail,
google_drive and google_calendar, with the contract's `result` in place of a receipt.

`send` runs tilo-api's entry through an `Outbox` built for that request over a fresh in-memory store (HB-04, SEC-03 as
everywhere), after the draft is checked (HB-03). The broker is one per process, so the connection parts it emits reach
the answer through a context-local sink: they come back in the answer to the call that caused them. The grant must
predate the approval (HB-06, `adapters.meeting_host.ApprovalBoundBroker`).
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import contextvars
import functools
import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ._schema import common_validator, host_rpc_validator
from ._time import format_ts
from .adapters.meeting_host import ApprovalBoundBroker, MeetingHostAdapter
from .consent import ConsentRefused, ConsentService
from .errors import OutboxRefused
from .host_auth import CertsUnavailable, GoogleOidcVerifier, OidcVerifier, caller_status
from .host_broker import BrokerNotConfigured, BrokerSeam, open_broker, open_transport
from .meeting_host import CALENDAR_EVENTS_OWNED, CONNECTOR_ID, DRAFT_KIND, HostReceipt
from .outbox import Outbox
from .registry import load_registry
from .side_effect_execute import Reach, checked_documents, execute, tier_and_time_ok
from .side_effect_execute import answer as execute_answer
from .store import InMemoryOutboxStore
from .tokens import _ulid, grant_group
from .workspace_read import TOOLS as WORKSPACE_TOOLS
from .workspace_read import invalid_window, read

MAX_BODY_BYTES = 65_536
MAX_PARTS = 16
AUDIENCE_VAR, CALLER_VAR = "TILO_CONNECTORS_AUDIENCE", "TILO_MEETING_HOST_CALLER"
_CONNECTION_PARTS = frozenset({"connection.expired", "connection.rate_limited", "connection.revoked"})
_WIDE_PARTS = _CONNECTION_PARTS | {"connection.established"}  # never connection.consented or .requested (CR-13)
_REFUSALS = {
    "invalid_request": 422,
    "not_configured": 503,
    "start_again": 400,
    "not_granted": 400,
    "wrong_account": 400,
}
_CONFIG = Path(__file__).resolve().parents[4] / "config" / "connectors.yaml"
_ERRORS = {
    401: "unauthenticated",
    403: "forbidden",
    422: "invalid_request",
    502: "not_configured",
    503: "not_configured",
}
_log = logging.getLogger(__name__)


def _now() -> str:
    return format_ts(datetime.now(UTC))


@functools.lru_cache(maxsize=1)
def _declaration() -> dict[str, Any]:
    return load_registry(_CONFIG).get(CONNECTOR_ID)


@functools.lru_cache(maxsize=1)
def _registry() -> Any:
    return load_registry(_CONFIG)


def _declared_scopes(declared: Mapping[str, Any]) -> frozenset[str]:
    """The union of the scopes the registry lists for a connector's capabilities."""
    return frozenset(s for scopes in declared.get("scopes", {}).values() for s in scopes)


def _view(connector: str, stored: Mapping[str, Any], declared: frozenset[str]) -> dict[str, Any]:
    """HB-09: `connected` only for the exact stored state and a list of scopes, else `expired` (connect again)."""
    raw = stored.get("scopes")
    if stored.get("state") != "connected" or not isinstance(raw, list):
        return {"connector": connector, "state": "expired", "scopes": [], "connected_at": None}
    scopes = sorted({s for s in raw if isinstance(s, str) and s in declared})
    since = stored.get("connected_at")
    stamp = since if isinstance(since, str) and common_validator("timestamp").is_valid(since) else None
    return {"connector": connector, "state": "connected", "scopes": scopes, "connected_at": stamp}


def _data(part: Mapping[str, Any]) -> Mapping[str, Any]:
    data = part.get("data")
    return data if isinstance(data, dict) else {}


class Refused(Exception):
    """A fixed refusal of a connection route: the status and the contract's `error` code, nothing else."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code if code in _REFUSALS else "start_again"


class _Parts:
    """What the broker and the adapter emitted during one call, for the call's own user (contract `parts`, or with
    `wide` the contract's `connector_parts`: any connector, and `connection.established`)."""

    def __init__(self, user_id: str, wide: bool = False) -> None:
        self.user_id = user_id
        self.wide = wide
        self.items: list[dict[str, str]] = []

    def add(self, item: dict[str, str]) -> None:
        if len(self.items) < MAX_PARTS:
            self.items.append(item)


class _OneDraft:
    """The adapter's `ArtifactSource`: the one draft this request carried, already hash-checked (HB-03)."""

    def __init__(self, ref: tuple[str, int], document: dict[str, Any]) -> None:
        self._ref, self._document = ref, document

    def get(self, artifact_id: str, version: int) -> dict[str, Any]:
        if (artifact_id, version) != self._ref:
            raise KeyError("not this request's draft")
        return self._document


class _Receipts:
    """The adapter's `ReceiptStore`: keeps the receipt for the answer; connectors stores no artifact."""

    def __init__(self) -> None:
        self.made: list[HostReceipt] = []

    def put(self, receipt: HostReceipt) -> dict[str, Any]:
        self.made.append(receipt)
        return {"artifact_id": "art_receipt_not_stored", "version": 1}

    def get(self, world_id: str, meeting_id: str) -> HostReceipt | None:
        return None


class HostRuntime:
    """Everything the routes share. `env=None` reads the process environment on every request, so a fixed setting needs
    no restart; the broker and the transport are built on first use (`BrokerSeam`, 30 s negative cache)."""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        *,
        verifier: OidcVerifier | None = None,
        broker_opener: Callable[..., Any] = open_broker,
        transport_opener: Callable[..., Any] = open_transport,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._env = env
        self.verifier: OidcVerifier = verifier or GoogleOidcVerifier()
        self._sink: contextvars.ContextVar[_Parts | None] = contextvars.ContextVar("host_parts", default=None)
        self._broker = BrokerSeam(env, emit=self._emit, alert=self._alert, opener=broker_opener)
        self._transport = BrokerSeam(env, emit=self._emit, alert=self._alert, opener=lambda e, **_: transport_opener(e))
        self._clock = clock
        self._consent: tuple[Any, ConsentService] | None = None
        self._consent_lock = threading.Lock()
        self._closing: dict[str, int] = {}
        self._closing_lock = threading.Lock()

    def settings(self) -> tuple[str, str] | None:
        """(audience, caller) from the service's own environment, or None when either is unset (never the request's)."""
        source = os.environ if self._env is None else self._env
        audience, caller = source.get(AUDIENCE_VAR, ""), source.get(CALLER_VAR, "")
        return (audience, caller) if audience and caller else None

    # -- the sink: the broker is one per process, a call's parts are its own ---------------------

    def _emit(self, part: dict[str, Any]) -> None:
        sink = self._sink.get()
        data = _data(part)
        allowed = _WIDE_PARTS if sink is not None and sink.wide else _CONNECTION_PARTS
        if sink is not None and part.get("type") in allowed and part.get("user_id") == sink.user_id:
            connector = data.get("connector")
            if isinstance(connector, str) and (sink.wide or connector == CONNECTOR_ID):
                sink.add({"type": part["type"], "connector": connector, "user_id": sink.user_id})

    def _alert(self, part: dict[str, Any]) -> None:
        sink, data = self._sink.get(), _data(part)
        if sink is None:
            _log.error("a provider revoke failed outside a call and no alert sink was open")
        elif part.get("user_id") == sink.user_id and isinstance(data.get("alert_id"), str):
            sink.add({"type": "alert.raised", "alert_id": data["alert_id"]})

    @contextlib.contextmanager
    def capture(self, user_id: str, *, wide: bool = False) -> Iterator[_Parts]:
        parts = _Parts(user_id, wide)
        token = self._sink.set(parts)
        try:
            yield parts
        finally:
            self._sink.reset(token)

    def _stopped(self, user_id: str) -> bool:
        with self._closing_lock:
            return self._closing.get(user_id, 0) > 0

    @contextlib.contextmanager
    def closing(self, user_id: str) -> Iterator[None]:
        """While a disconnect runs, a send that has not fetched its token yet is refused, not retried. Counted, so
        overlapping disconnects of one user keep it closing until the last ends."""
        with self._closing_lock:
            self._closing[user_id] = self._closing.get(user_id, 0) + 1
        try:
            yield
        finally:
            with self._closing_lock:
                left = self._closing.get(user_id, 1) - 1
                if left > 0:
                    self._closing[user_id] = left
                else:
                    self._closing.pop(user_id, None)

    # -- the three calls (run in a worker thread) --------------------------------------------------

    def status(self, user_id: str) -> dict[str, Any]:
        broker = self._broker.get()
        state = broker.connection_state(user_id, CONNECTOR_ID)
        if state is None:
            return {"state": "none", "scope_ok": False}
        scoped = CALENDAR_EVENTS_OWNED in broker.granted_scopes(user_id, CONNECTOR_ID)
        return {"state": "connected" if state == "connected" else "expired", "scope_ok": scoped}

    def disconnect(self, user_id: str) -> dict[str, Any]:
        broker = self._broker.get()
        with self.closing(user_id), self.capture(user_id) as parts:
            result = broker.disconnect(user_id, CONNECTOR_ID)
        return {"revoked_at_provider": bool(result.revoked_at_provider), "parts": parts.items}

    # -- the three connection calls (ADR-0035 L3) ---------------------------------------------------

    def _consent_service(self) -> ConsentService:
        """One per process and broker: the flows (state, verifier) live in it and nowhere else (LC-03, LC-05)."""
        broker = self._broker.get()
        with self._consent_lock:
            if self._consent is None or self._consent[0] is not broker:
                http, settings = broker.oauth
                registry = _registry()
                known = {name: registry.get(name) for name in registry.ids()}
                service = ConsentService(
                    connectors=known, broker=broker, http=http, settings=settings, clock=self._clock, emit=self._emit
                )
                self._consent = (broker, service)
            return self._consent[1]

    def start(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """LC-06: Google is asked only for the declared scopes of these capabilities minus those already granted."""
        service = self._consent_service()
        try:
            url = service.authorization_url(
                user_id=body["user_id"], connector=body["connector"], capabilities=body["capabilities"], card_id="web"
            )
        except ConsentRefused as refused:
            raise Refused(refused.code) from None
        return {"authorize_url": url}

    def callback(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """LC-05: the state is spent here and must belong to this user; the code is exchanged in this process."""
        service, user_id = self._consent_service(), body["user_id"]
        with self.capture(user_id, wide=True) as parts:
            try:
                result = service.handle_callback(
                    user_id=user_id, state=body["state"], code=body.get("code"), error=body.get("error")
                )
            except ConsentRefused as refused:
                raise Refused(refused.code) from None
        return {"connector": result.connector, "scope_lines": list(result.scope_lines), "parts": parts.items}

    def connection_disconnect(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Google keeps one grant per person (CON-D10): every connector resting on it ends, the last one revokes it."""
        user_id, connector = body["user_id"], body["connector"]
        registry = _registry()
        if connector not in registry or registry.get(connector)["auth"] != "oauth2":
            raise Refused("invalid_request")
        broker, group = self._broker.get(), grant_group(connector)
        sharing = [c for c in registry.ids() if registry.get(c)["auth"] == "oauth2" and grant_group(c) == group]
        confirmed, unconfirmed, spent = False, False, set[str]()
        with self.closing(user_id), self.capture(user_id, wide=True) as parts:
            for name in sharing:
                # All or report: one connector failing never stops the others, and what changed is always answered.
                # Each DISTINCT stored token is revoked (a person's connectors may hold tokens of different consents or
                # accounts); a token already revoked in this call is not revoked twice.
                try:
                    if broker.connection_state(user_id, name) is None:
                        continue
                    result = broker.disconnect(user_id, name, spent=spent)
                except Exception as exc:  # noqa: BLE001 - the type only
                    _log.error("a connection disconnect failed for one connector (%s)", type(exc).__name__)
                    unconfirmed = True
                    continue
                if result.revoked_at_provider:
                    confirmed = True
                else:
                    unconfirmed = unconfirmed or result.provider_error is not None
            if unconfirmed and not any(p["type"] == "alert.raised" for p in parts.items):
                # No kept-revoke alert exists for what failed, so the answer carries one: revoke_pending is true.
                parts.add({"type": "alert.raised", "alert_id": _ulid(self._clock())})
        return {"revoked_at_provider": confirmed and not unconfirmed, "parts": parts.items}

    def connection_views(self, user_id: str) -> dict[str, Any]:
        """ADR-0032 addendum 1 (HB-08, HB-09): this user's stored grants as display views. A store read only."""
        stored = self._broker.get().display_records(user_id)
        registry, views = _registry(), []
        for connector in registry.ids():
            declared = registry.get(connector)
            if declared["auth"] == "oauth2" and connector in stored:
                views.append(_view(connector, stored[connector], _declared_scopes(declared)))
        return {"views": views}

    def retry_pending_revokes(self, user_id: str) -> int:
        """The scheduler hook for ADR-0032 follow-up 4: retries this user's kept revokes (a pending one is dropped
        after seven days). Not a route: the contract has none, and nothing else calls it yet."""
        with self.capture(user_id):
            return int(self._broker.get().retry_pending_revokes(user_id))

    def execute(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """ADR-0035 L5 (LC-07): a person connector's side effect, over the same checks as `send`."""
        entry, evidence = body["entry"], body["evidence"]
        documents = checked_documents(entry, body["items"])
        if documents is None or not tier_and_time_ok(entry, self._clock()):  # HB-03, the table's tier, a real time
            return execute_answer("refused")
        broker, transport = self._broker.get(), self._transport.get()
        with self.capture(evidence["world_owner"], wide=True) as parts:
            return execute(
                body, documents, declaration=_registry().get(entry["connector"]), broker=broker, transport=transport,
                stopped=self._stopped, emit=self._emit, clock=self._clock, parts=parts,
            )  # fmt: skip

    def workspace_read(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """ADR-0048: one agent read of the person's own Gmail, Calendar or Drive (`workspace_read.py`)."""
        if invalid_window(body):  # WT-02, before the broker or Google is touched
            raise Refused("invalid_request")
        broker, transport = self._broker.get(), self._transport.get()
        with self.capture(body["user_id"], wide=True) as parts:
            return read(
                body, declaration=_registry().get(WORKSPACE_TOOLS[body["tool"]]), broker=broker, transport=transport,
                clock=self._clock, emit=self._emit, parts=parts,
            )  # fmt: skip

    def send(self, body: Mapping[str, Any]) -> dict[str, Any]:
        entry, evidence, draft = body["entry"], body["evidence"], body["draft"]
        user_id = entry["authz"]["ref"]
        document = _checked_draft(entry, draft)
        if document is None:  # HB-03
            return _answer("refused", [])
        broker, transport = self._broker.get(), self._transport.get()
        reach, receipts = Reach(transport), _Receipts()
        alerted: list[dict[str, Any]] = []
        with self.capture(user_id) as parts:
            adapter = MeetingHostAdapter(
                declaration=_declaration(),
                broker=ApprovalBoundBroker(broker, approved_at=entry["authz"]["at"], stopped=self._stopped),
                transport=reach,
                artifacts=_OneDraft((draft["artifact_id"], draft["version"]), document),
                owner_of=lambda world_id: evidence["world_owner"],  # HB-05: MH-11 compares this with the draft
                receipts=receipts,
                clock=self._clock,
                emit=self._emit,
                sleep=lambda seconds: None,
            )
            outbox = Outbox(
                InMemoryOutboxStore(),  # HB-04: nothing outlives the request; a retry reads Google's earlier event
                {CONNECTOR_ID: adapter},
                emit=lambda part: None,  # tilo-api's outbox writes the world's one data.transfer
                clock=self._clock,
                world_id=entry["world_id"],
                alert=alerted.append,  # raised only for a failed entry that may have acted; tilo-api raises its own
            )
            try:
                outbox.enqueue(dict(entry), dict(evidence))
            except OutboxRefused:
                return _answer("refused", parts.items)
            try:  # from here on Google may have been reached: no exit may say "not configured" (a final refusal)
                outbox.dispatch_due()
                answer = _outcome(outbox.get(entry["id"]) or {}, receipts, alerted, parts.items, reach.sent > 0)
                if not host_rpc_validator("send_answer").is_valid(answer):
                    raise ValueError("the answer breaks its contract")
                return answer
            except Exception as exc:  # noqa: BLE001 - the type only
                _log.error("a send failed after dispatch began (%s)", type(exc).__name__)
                if reach.sent:
                    return _answer("possibly_sent", parts.items)
                return _answer("retry", parts.items, may_have_sent=False)


def _outcome(
    settled: Mapping[str, Any], receipts: _Receipts, alerted: list[Any], parts: list[dict[str, str]], reached: bool
) -> dict[str, Any]:
    state = settled.get("state")
    if state == "sent" and receipts.made:
        receipt = asdict(receipts.made[0])
        return _answer("sent", parts, receipt={**receipt, "draft": dict(receipt["draft"])})
    if state == "failed":
        return _answer("possibly_sent" if alerted else "refused", parts)
    return _answer("retry", parts, may_have_sent=reached)


def _answer(
    outcome: str,
    parts: list[dict[str, str]],
    *,
    receipt: dict[str, Any] | None = None,
    may_have_sent: bool | None = None,
) -> dict[str, Any]:
    return {"outcome": outcome, "receipt": receipt, "may_have_sent": may_have_sent, "parts": list(parts)}


def _checked_draft(entry: Mapping[str, Any], draft: Mapping[str, Any]) -> dict[str, Any] | None:
    """HB-03: the bytes match their hash, name the entry's item, and parse as a meeting_event; else None."""
    try:
        raw = base64.b64decode(draft["content_b64"], validate=True)
        item = entry["item"]
        if hashlib.sha256(raw).hexdigest() != draft["content_sha256"]:
            return None
        if (draft["artifact_id"], draft["version"]) != (item.get("artifact_id"), item.get("version")):
            return None
        document = json.loads(raw)
    except (binascii.Error, ValueError, KeyError, AttributeError, TypeError, RecursionError):
        return None
    if not (isinstance(document, dict) and document.get("kind") == DRAFT_KIND):
        return None
    # the receipt echoes these two: they must fit the contract before anything is enqueued or sent
    fits = common_validator("meeting_id").is_valid(document.get("meeting_id"))
    return document if fits and common_validator("user_id").is_valid(document.get("owner")) else None


def _error(status: int) -> JSONResponse:
    return JSONResponse({"error": _ERRORS[status]}, status_code=status)


async def _read_body(request: Request) -> bytes | None:
    """The body, or None when it is over the cap; counted as it streams in, so it is never held past the cap."""
    declared = request.headers.get("content-length")
    if declared is not None and not (declared.isascii() and declared.isdigit() and int(declared) <= MAX_BODY_BYTES):
        return None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def host_router(runtime: HostRuntime) -> APIRouter:
    from .host_join import join_router

    router = APIRouter(prefix="/internal")
    router.include_router(join_router(runtime))

    async def serve(request: Request, request_def: str, answer_def: str, work: Callable[[Any], dict[str, Any]]) -> Any:
        settings = runtime.settings()
        if settings is None:
            return _error(503)
        audience, caller = settings
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token or " " in token:
            return _error(401)
        try:
            claims = await run_in_threadpool(runtime.verifier.verify, token, audience)
            refused = caller_status(claims, audience=audience, caller=caller)
        except CertsUnavailable:  # Google's certificates cannot be had now: retryable, never a final 401
            return _error(502)
        except Exception:  # noqa: BLE001 - whatever is wrong with the token, the answer is the same
            return _error(401)
        if refused is not None:
            return _error(refused)
        try:
            raw = await _read_body(request)
            body = json.loads(raw) if raw is not None else None
            valid = body is not None and host_rpc_validator(request_def).is_valid(body)
        except Exception:  # noqa: BLE001 - not JSON, too deep, a dropped connection: nothing was done
            valid = False
        if not valid:
            return _error(422)
        try:
            answer = await run_in_threadpool(work, body)
        except Refused as refusal:
            return JSONResponse({"error": refusal.code}, status_code=_REFUSALS[refusal.code])
        except BrokerNotConfigured:
            return _error(503)
        except Exception as exc:  # noqa: BLE001 - the type only: a message could echo a token or an address
            _log.error("a meeting-host call failed (%s)", type(exc).__name__)
            return _error(503)
        if not host_rpc_validator(answer_def).is_valid(answer):
            _log.error("a meeting-host answer broke its contract")
            return _error(503)
        return JSONResponse(answer)

    @router.post("/meeting-host/send")
    async def send(request: Request) -> Any:
        return await serve(request, "send_request", "send_answer", runtime.send)

    @router.post("/meeting-host/status")
    async def status(request: Request) -> Any:
        return await serve(request, "user_request", "status_answer", lambda body: runtime.status(body["user_id"]))

    @router.post("/meeting-host/disconnect")
    async def disconnect(request: Request) -> Any:
        return await serve(
            request, "user_request", "disconnect_answer", lambda body: runtime.disconnect(body["user_id"])
        )

    @router.post("/side-effects/execute")
    async def side_effect_execute(request: Request) -> Any:
        return await serve(request, "execute_request", "execute_answer", runtime.execute)

    @router.post("/workspace/read")
    async def workspace_read(request: Request) -> Any:
        return await serve(request, "read_request", "read_answer", runtime.workspace_read)

    @router.post("/connections/start")
    async def connection_start(request: Request) -> Any:
        return await serve(request, "start_request", "start_answer", runtime.start)

    @router.post("/connections/callback")
    async def connection_callback(request: Request) -> Any:
        return await serve(request, "callback_request", "callback_answer", runtime.callback)

    @router.post("/connections/disconnect")
    async def connection_disconnect(request: Request) -> Any:
        return await serve(
            request, "connection_disconnect_request", "connection_disconnect_answer", runtime.connection_disconnect
        )

    @router.post("/connections/views")
    async def connection_views(request: Request) -> Any:
        return await serve(
            request, "user_request", "views_answer", lambda body: runtime.connection_views(body["user_id"])
        )

    return router
