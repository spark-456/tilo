"""tilo_api.meeting_host_rpc: tilo-api's side of the meeting-host RPC (FR-MTG-09, ADR-0032 decisions 6 to 8, HB-07).

tilo-connectors keeps the bot account's token and makes the Google call; tilo-api posts to its three internal routes
(`contracts/meeting_host_rpc.schema.json`). `MeetingHostRpc` is the client: one per process, an injectable transport
and an injectable ID-token fetcher (production: the metadata server, audience equal to the connectors URL; there is no
shared secret and no API key). `MeetingHostStub` takes `MeetingHostAdapter`'s place in the host run's connector map:
the outbox calls its `execute_side_effect`, and each answer maps to the outcome the ADR table gives. Nothing here
imports `tilo_connectors.tokens`, `.live` or `.adapters` (SEC-02); the wire types are `tilo_contracts`. A token is never
logged, echoed or put in an exception, and an error is a fixed code. The send itself is never retried here: the outbox
retries, and connectors' MH-13 keeps a second try from sending a second invitation.

`connection_views` (ADR-0032 addendum 1, T4b) asks `POST /internal/connections/views` for a person's display views for
`GET /v1/connectors`. It has no side effect, so every failure is "unknown" (`None`): it never raises, is never retried
inside one call and logs a status code at most.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, NamedTuple, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError
from tilo_connectors.errors import AdapterError, PossiblySent, ProviderUnavailable, SideEffectRefused
from tilo_connectors.meeting_host import CONNECTOR_ID, HostReceipt
from tilo_contracts import (
    MeetingHostRpcAlertPart,
    MeetingHostRpcCallbackAnswer,
    MeetingHostRpcConnectionDisconnectAnswer,
    MeetingHostRpcConnectionPart,
    MeetingHostRpcConnectionView,
    MeetingHostRpcDisconnectAnswer,
    MeetingHostRpcError,
    MeetingHostRpcExecuteAnswer,
    MeetingHostRpcReceipt,
    MeetingHostRpcSendAnswer,
    MeetingHostRpcStartAnswer,
    MeetingHostRpcStatusAnswer,
    MeetingHostRpcViewsAnswer,
    MeetingJoin,
)
from tilo_memory.artifacts import ArtifactCorrupt  # noqa: E402

logger = logging.getLogger("tilo_api.meeting_host_rpc")
URL_VAR = "TILO_CONNECTORS_URL"
TIMEOUT_S = 20.0  # one deadline for the token fetch and the request together, under the outbox's 30 s lease (HB-07)
MAX_REPLY_BYTES = 65_536
MAX_REQUEST_BYTES = 65_536  # the connectors body cap (HB-01): a bigger execute is refused here, never half-sent
EXECUTE_PATH = "/internal/side-effects/execute"
VIEWS_TIMEOUT_S = 10.0  # a cold connectors instance costs one wait this long at most; the page's next load asks again
MAX_VIEWS_REPLY_BYTES = 262_144  # 32 views of 16 scopes stay under 160 KiB
VIEWS_PATH = "/internal/connections/views"
CONNECT_PATH = "/internal/connections/"  # start, callback, disconnect (ADR-0035 decision 2)
_SECRET_PARAM = re.compile(r"[?&](?:client_secret|code_verifier|code|access_token|refresh_token)=")
CALLBACK_REFUSALS = frozenset({"start_again", "not_granted", "wrong_account"})  # the callback route's own 400s
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_URL = re.compile(rf"https://(?:{_LABEL}\.)+run\.app")  # https only, a Cloud Run host, no user, port, path or query


class Reply(NamedTuple):
    status: int
    body: bytes


class TransportError(Exception):
    """The call timed out, was cut or could not be made. The request may or may not have arrived."""


class Transport(Protocol):
    def post(self, url: str, body: bytes, headers: Mapping[str, str], timeout_s: float) -> Reply: ...


class HostRpcNotConfigured(Exception):
    """No usable `TILO_CONNECTORS_URL`."""


class HostRpcError(Exception):
    """A call that gave no answer. `kind` is `refused` (connectors refused before anything acted), `not_sent` (the call
    was never made), `unknown` (it may have reached connectors) or `rejected` (only the callback: one of its own three
    400s, named by `code`). Never holds a token, a body or a cause's text."""

    def __init__(self, kind: str, code: str | None = None) -> None:
        super().__init__(kind)
        self.kind, self.code = kind, code


class NotSent(AdapterError):
    """Retryable, and nothing reached Google (the outbox reads a 4xx status as that)."""

    status = 409


def _error_code(body: bytes) -> str | None:
    try:
        return str(MeetingHostRpcError.model_validate_json(body).error)
    except ValidationError:
        return None


def _is_error(body: bytes, code: str) -> bool:
    try:
        return MeetingHostRpcError.model_validate_json(body).error == code
    except ValidationError:
        return False


class RequestsTransport:
    """`requests`, no redirects, the reply read up to `MAX_REPLY_BYTES`. Connect 5 s, then `timeout_s` per read."""

    def post(self, url: str, body: bytes, headers: Mapping[str, str], timeout_s: float) -> Reply:
        import requests  # noqa: PLC0415

        try:
            with requests.post(
                url, data=body, headers=dict(headers), timeout=(min(5.0, timeout_s), timeout_s), allow_redirects=False,
                stream=True,
            ) as response:  # fmt: skip
                cap = MAX_VIEWS_REPLY_BYTES if url.endswith(VIEWS_PATH) else MAX_REPLY_BYTES
                data = response.raw.read(cap + 1, decode_content=True)
                if len(data) > cap:
                    raise TransportError
                return Reply(response.status_code, data)
        except requests.RequestException:
            raise TransportError from None


# SKILLS-LIVE: Google's ID tokens last an hour; one is reused for half of that (one metadata trip, not one per call).
_ID_TOKEN_REUSE_S = 1800.0
_id_tokens: dict[str, tuple[float, str]] = {}
id_token_clock: Callable[[], float] = time.monotonic  # read at call time, so a test can replace it


def metadata_id_token(audience: str) -> str:
    """The runtime account's Google-signed ID token for `audience` (google-auth, from the metadata server), reused for
    `_ID_TOKEN_REUSE_S` per audience. A failed mint is never cached."""
    now = id_token_clock()
    hit = _id_tokens.get(audience)
    if hit is not None and hit[0] > now:
        return hit[1]
    from google.auth.transport.requests import Request  # noqa: PLC0415
    from google.oauth2 import id_token  # noqa: PLC0415

    token = str(id_token.fetch_id_token(Request(), audience))
    _id_tokens[audience] = (now + _ID_TOKEN_REUSE_S, token)
    return token


class _JoinRefusal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: Literal["not_joinable", "no_join_link", "host_not_connected"]


class MeetingHostRpc:
    def __init__(
        self,
        base_url: str,
        *,
        transport: Transport,
        token_for: Callable[[str], str],
        timeout_s: float = TIMEOUT_S,
        views_timeout_s: float = VIEWS_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base, self._transport, self._token_for, self._timeout = base_url, transport, token_for, timeout_s
        self._views_timeout = views_timeout_s
        self._views_local = threading.local()
        self._clock = clock  # the deadline's clock: a test freezes it so the request's budget is exactly the limit

    @property
    def views_not_configured(self) -> bool:
        return getattr(self._views_local, "not_configured", False)

    def __repr__(self) -> str:
        return "MeetingHostRpc()"

    def _post(
        self, route: str, payload: Mapping[str, Any], *, path: str | None = None, timeout_s: float | None = None
    ) -> bytes:
        """The whole call (token fetch and request) under one deadline. Past it, the call is `not_sent` if the request
        had not been handed to the transport yet, else `unknown`; the worker thread is left to finish on its own."""
        stage = {"posted": False}
        box: dict[str, Any] = {}
        done = threading.Event()
        limit = self._timeout if timeout_s is None else timeout_s
        deadline = self._clock() + limit

        def work() -> None:
            try:
                box["value"] = self._call(route, payload, stage, deadline, path or f"/internal/meeting-host/{route}")
            except BaseException as exc:  # noqa: BLE001 - handed to the caller below
                box["error"] = exc
            finally:
                done.set()

        threading.Thread(target=work, name="meeting-host-rpc", daemon=True).start()
        if not done.wait(limit):
            logger.warning("meeting-host %s: the deadline passed", route)
            raise HostRpcError("unknown" if stage["posted"] else "not_sent")
        if "error" in box:
            raise box["error"]
        return bytes(box["value"])

    def _call(
        self, route: str, payload: Mapping[str, Any], stage: dict[str, bool], deadline: float, path: str
    ) -> bytes:
        try:  # HB-01: minted per call for the connectors audience; failing here means nothing was sent
            token = self._token_for(self._base)
        except Exception:  # noqa: BLE001 - the metadata server's text is not ours to echo
            logger.warning("meeting-host %s: no ID token could be minted", route)
            raise HostRpcError("not_sent") from None
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
        data = json.dumps(payload, separators=(",", ":")).encode()
        stage["posted"] = True
        try:
            reply = self._transport.post(f"{self._base}{path}", data, headers, max(0.1, deadline - self._clock()))
        except Exception:  # noqa: BLE001 - a timeout, a cut connection: it may have arrived
            logger.warning("meeting-host %s: the call failed in transit", route)
            raise HostRpcError("unknown") from None
        if reply.status == 200:
            return reply.body
        if route == "join" and reply.status == 409:
            try:
                refusal = _JoinRefusal.model_validate_json(reply.body)
            except ValidationError:
                pass
            else:
                raise HostRpcError("rejected", refusal.error)
        if reply.status == 400 and route == "connect-callback":
            said = _error_code(reply.body)
            if said in CALLBACK_REFUSALS:
                logger.warning("meeting-host %s: answered 400", route)
                raise HostRpcError("rejected", said)
        refused = reply.status in (401, 403, 422) or (reply.status == 503 and _is_error(reply.body, "not_configured"))
        logger.warning("meeting-host %s: answered %s", route, reply.status)
        raise HostRpcError(
            "refused" if refused else "unknown",
            "not_configured" if reply.status == 503 and _is_error(reply.body, "not_configured") else None,
        )

    def join_link(self, receipt: Mapping[str, Any]) -> MeetingJoin:
        """The API supplies its scoped receipt; connectors alone reads the host grant."""
        try:
            checked = MeetingHostRpcReceipt.model_validate(receipt)
            return MeetingJoin.model_validate_json(self._post("join", checked.model_dump(mode="json")))
        except ValidationError:
            raise HostRpcError("unknown") from None

    def status(self, user_id: str) -> MeetingHostRpcStatusAnswer:
        """The principal's own bot-grant state. Any failure is a `HostRpcError`; a store read, so no parts."""
        try:
            got = MeetingHostRpcStatusAnswer.model_validate_json(self._post("status", {"user_id": user_id}))
        except ValidationError:
            raise HostRpcError("unknown") from None
        if got.state == "none" and got.scope_ok:
            raise HostRpcError("unknown")
        return got

    def disconnect(self, user_id: str) -> MeetingHostRpcDisconnectAnswer:
        """The owner's own disconnect (ADR-0032 decision 7). Idempotent at connectors, so the caller may retry any
        failure. `refused` means nothing acted; `unknown` means it may have (a lost answer): retry. Not retried here."""
        try:
            return MeetingHostRpcDisconnectAnswer.model_validate_json(self._post("disconnect", {"user_id": user_id}))
        except ValidationError:
            raise HostRpcError("unknown") from None

    def connection_views(self, user_id: str, *, order: Sequence[str]) -> list[MeetingHostRpcConnectionView] | None:
        """The principal's own display views (HB-08), or None for "unknown": any failure at all, an answer that breaks
        the contract, or one that breaks HB-09 against `order` (the registry's oauth2 connector ids): ids unique and in
        that order. Never raises, never retries, and never logs more than a status code."""
        self._views_local.not_configured = False
        try:
            raw = self._post("views", {"user_id": user_id}, path=VIEWS_PATH, timeout_s=self._views_timeout)
            if len(raw) > MAX_VIEWS_REPLY_BYTES:
                return None
            views = MeetingHostRpcViewsAnswer.model_validate_json(raw).views
            position = {connector: i for i, connector in enumerate(order)}
            last = -1
            for view in views:
                at = position.get(view.connector, -1)
                if at <= last or len(set(view.scopes)) != len(view.scopes):
                    return None
                last = at
                if view.state == "expired" and (view.scopes or view.connected_at is not None):  # the schema's if/then
                    return None
            return list(views)
        except HostRpcError as exc:
            self._views_local.not_configured = exc.code == "not_configured"
            return None
        except Exception:  # noqa: BLE001 - a broken answer is "unknown" whatever broke it; no text is kept
            return None

    def connect_start(self, user_id: str, connector: str, capabilities: Sequence[str]) -> str | None:
        """ADR-0035 `start`: the Google sign-in link for the principal, or None when no scope is missing (LC-06). The
        link has no secret in it (LC-03); the answer is checked against the contract's closed pattern."""
        payload = {"user_id": user_id, "connector": connector, "capabilities": list(capabilities)}
        try:
            raw = self._post("connect-start", payload, path=f"{CONNECT_PATH}start")
            url = MeetingHostRpcStartAnswer.model_validate_json(raw).authorize_url
        except ValidationError:
            raise HostRpcError("unknown") from None
        if url is not None and _SECRET_PARAM.search(url):  # the schema's `not` clause, which the generated type drops
            raise HostRpcError("unknown")
        return url

    def connect_callback(
        self, user_id: str, *, state: str, code: str | None = None, error: str | None = None
    ) -> MeetingHostRpcCallbackAnswer:
        """ADR-0035 `callback`: hands the one-time `state` and `code` (or Google's `error` word) over and nothing else.
        Neither value is logged, kept or put in an exception here. Its own 400s are `rejected` with a code."""
        payload: dict[str, str] = {"user_id": user_id, "state": state}
        if code is not None:
            payload["code"] = code
        if error is not None:
            payload["error"] = error
        try:
            return MeetingHostRpcCallbackAnswer.model_validate_json(
                self._post("connect-callback", payload, path=f"{CONNECT_PATH}callback")
            )
        except ValidationError:
            raise HostRpcError("unknown") from None

    def connect_disconnect(self, user_id: str, connector: str) -> MeetingHostRpcConnectionDisconnectAnswer:
        """ADR-0035 `disconnect` for any connector; idempotent at connectors, so a caller may retry any failure."""
        try:
            return MeetingHostRpcConnectionDisconnectAnswer.model_validate_json(
                self._post(
                    "connect-disconnect",
                    {"user_id": user_id, "connector": connector},
                    path=f"{CONNECT_PATH}disconnect",
                )
            )
        except ValidationError:
            raise HostRpcError("unknown") from None

    def send_invitation(self, entry: Mapping[str, Any], evidence: Mapping[str, Any], draft: Mapping[str, Any]) -> Any:
        """Not a registered SEC-03 name (that list is the connector adapters' methods); a local AST test pins that only
        `MeetingHostStub.execute_side_effect` calls it, and the stub verifies the outbox Grant first."""
        raw = self._post("send", {"entry": entry, "evidence": evidence, "draft": draft})
        try:
            answer = MeetingHostRpcSendAnswer.model_validate_json(raw)
        except ValidationError:
            raise HostRpcError("unknown") from None
        sent, retry = answer.outcome == "sent", answer.outcome == "retry"  # the schema's if/then, which pydantic drops
        if (answer.receipt is not None) != sent or (answer.may_have_sent is not None) != retry:
            raise HostRpcError("unknown")
        return answer

    def execute_entry(
        self, entry: Mapping[str, Any], evidence: Mapping[str, Any], items: Sequence[Mapping[str, Any]]
    ) -> MeetingHostRpcExecuteAnswer:
        """ADR-0035 `execute` for gmail, google_drive and google_calendar. Not a registered SEC-03 name; an AST test
        pins that only `ConnectorRpcStub.execute_side_effect` calls it, and that stub verifies the outbox Grant first. A
        request over the connectors cap is `refused` before any call (BQ-ADR35L5-2). Never retried here."""
        payload = {"entry": entry, "evidence": evidence, "items": list(items)}
        if len(json.dumps(payload, separators=(",", ":")).encode()) > MAX_REQUEST_BYTES:
            raise HostRpcError("refused")
        raw = self._post("execute", payload, path=EXECUTE_PATH)
        try:
            return _execute_checked(MeetingHostRpcExecuteAnswer.model_validate_json(raw))
        except ValidationError:
            raise HostRpcError("unknown") from None


def _execute_checked(answer: MeetingHostRpcExecuteAnswer) -> MeetingHostRpcExecuteAnswer:
    sent, retry = answer.outcome == "sent", answer.outcome == "retry"  # the schema's if/then, which pydantic drops
    if (answer.result is not None) != sent or (answer.may_have_sent is not None) != retry:
        raise HostRpcError("unknown")
    return answer


def open_meeting_host_rpc(
    env: Mapping[str, str], *, transport: Transport | None = None, token_for: Callable[[str], str] | None = None
) -> MeetingHostRpc:
    """The process's client from `TILO_CONNECTORS_URL`; anything but an exact https Cloud Run host is not configured."""
    url = env.get(URL_VAR, "")
    if _URL.fullmatch(url) is None:
        raise HostRpcNotConfigured
    return MeetingHostRpc(url, transport=transport or RequestsTransport(), token_for=token_for or metadata_id_token)


def side_effect_marker(entry: Mapping[str, Any]) -> str:
    """Google's event id for this entry: a pure function of (world_id, idempotency_key), as connectors computes it."""
    return hashlib.sha256(f"{entry['world_id']}\x00{entry['idempotency_key']}".encode()).hexdigest()[:32]


def receipt_matches(entry: Mapping[str, Any], draft: Mapping[str, Any], receipt: MeetingHostRpcReceipt) -> bool:
    """HB-07: the marker, the entry's world, outbox id and draft, the draft's own meeting and owner."""
    item = entry["item"]
    return (
        receipt.event_ref == side_effect_marker(entry)
        and (receipt.world_id, receipt.outbox_id) == (entry["world_id"], entry["id"])
        and (receipt.draft.artifact_id, receipt.draft.version) == (item["artifact_id"], item["version"])
        and (receipt.meeting_id, receipt.owner) == (draft.get("meeting_id"), draft.get("owner"))
    )


class MeetingHostStub:
    """The outbox's `meeting_host` connector in tilo-api. `read_draft(ref)` is the run's hash-checked artifact read,
    `sink(part)` is `on_connection_event` (a sink error never fails the call, MTG-WIRE-1), `store_receipt(receipt)` is
    the run's receipt store. The run hands the evidence for an outbox id (`hand_evidence`) before it enqueues."""

    def __init__(
        self,
        rpc: MeetingHostRpc,
        read_draft: Callable[[dict[str, Any]], bytes],
        sink: Callable[[dict[str, Any]], Any],
        store_receipt: Callable[[HostReceipt], Any],
    ) -> None:
        self._rpc, self._read_draft, self._sink, self._store_receipt = rpc, read_draft, sink, store_receipt
        self._evidence: dict[str, dict[str, Any]] = {}

    def hand_evidence(self, outbox_id: str, evidence: Mapping[str, Any]) -> None:
        self._evidence[outbox_id] = json.loads(json.dumps(evidence))

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Any) -> None:
        grant.verify(entry["idempotency_key"])  # SEC-03: only the outbox's own dispatch, before anything is read
        evidence, item = self._evidence.get(entry["id"]), entry["item"]
        if evidence is None:
            raise SideEffectRefused("no evidence was handed for this entry")
        try:
            raw = self._read_draft({"artifact_id": item["artifact_id"], "version": item["version"]})
        except ArtifactCorrupt:  # AR-01: the bytes are not the pinned ones, and will not become so
            raise SideEffectRefused("the pinned draft does not match its hash") from None
        except Exception:  # noqa: BLE001 - any other read error may pass: nothing was sent, try again
            raise NotSent("the pinned draft cannot be read now") from None
        try:
            document = json.loads(raw)
        except ValueError:
            raise SideEffectRefused("the pinned draft is not a document") from None
        draft = {
            "artifact_id": item["artifact_id"], "version": item["version"],
            "content_sha256": hashlib.sha256(raw).hexdigest(), "content_b64": base64.b64encode(raw).decode("ascii"),
        }  # fmt: skip
        try:  # the outbox hands over the claimed ("sending") entry; the contract takes it as enqueued
            answer = self._rpc.send_invitation({**entry, "state": "queued"}, evidence, draft)
        except HostRpcError as exc:
            if exc.kind == "refused":
                raise SideEffectRefused("connectors refused the send") from None
            if exc.kind == "not_sent":
                raise NotSent("the send was not made") from None
            raise ProviderUnavailable("the send may have reached connectors") from None
        self._deliver(answer.parts, entry["authz"]["ref"])
        if answer.outcome == "refused":
            raise SideEffectRefused("connectors refused the send")
        if answer.outcome == "possibly_sent":
            raise PossiblySent("connectors cannot tell whether it was sent")
        if answer.outcome == "retry":
            if answer.may_have_sent:
                raise ProviderUnavailable("connectors may have sent")
            raise NotSent("connectors had nothing to send with yet")
        receipt = answer.receipt
        if receipt is None or not isinstance(document, dict) or not receipt_matches(entry, document, receipt):
            raise PossiblySent(
                "the receipt does not match the entry"
            )  # HB-07: it is on Google's side, so a person looks
        try:
            self._store_receipt(HostReceipt(**{**receipt.model_dump(), "draft": receipt.draft.model_dump()}))
        except Exception:  # noqa: BLE001 - it was sent; never retried, never "not sent"
            raise PossiblySent("the receipt could not be stored") from None

    def _deliver(self, parts: list[Any], user_id: str) -> None:
        """Only this call's own user's connection parts reach the sink (ADR-0032 decision 7)."""
        for part in parts:
            if isinstance(part, MeetingHostRpcAlertPart):  # ids only; the run records it once
                handed: dict[str, Any] = {
                    "type": part.type, "authz": None, "data": {"alert_id": part.alert_id, "card_id": None},
                }  # fmt: skip
            elif isinstance(part, MeetingHostRpcConnectionPart) and part.user_id == user_id:
                handed = {"type": part.type, "authz": None, "data": {"connector": CONNECTOR_ID}, "user_id": user_id}
            else:
                continue
            try:
                self._sink(handed)
            except Exception as exc:  # noqa: BLE001 - a sink error never fails the call
                logger.warning("a connection part was not handled (%s)", type(exc).__name__)
