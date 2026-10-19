"""tilo_connectors.live — the live Gmail smoke harness (FR-CON-04, PRD 5.4 CP1, 12.1, SEC-02, EFF-01).

`LiveHttpClient` and `LiveTransport` are the only code that reaches Google: refused unless LIVE is exactly "1", https
to a fixed list of Google hosts, no redirects, always a timeout, no retries (the adapters retry). `CallbackServer`
is the one-shot loopback listener; `run_smoke` is the flow: consent URL, callback, code exchange, up to 5 messages,
and with an address one draft through the outbox. `run_host_smoke` (FR-MTG-09) signs in as the meeting bot and
creates one Meet event with one invitation through the outbox. Tokens stay in memory under a FakeKms; nothing sends
mail (the host check sends the one invitation) or lets a token, code, header or secret reach an exception, a repr or
the output. API: tests/API_FR_CON_04_live_smoke.md.
"""

from __future__ import annotations

import contextlib
import errno
import hmac
import http.client
import http.server
import json as jsonlib
import math
import os
import re
import secrets
import socket
import socketserver
import ssl
import sys
import threading
import time
import unicodedata
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import parse_qs, urlencode, urlsplit

from ._time import add_seconds, format_ts
from .adapters import GmailAdapter, TransportError
from .adapters.meeting_host import MeetingHostAdapter
from .consent import ConsentRefused, ConsentService
from .errors import MeetingHostRefused
from .meeting_host import CONNECTOR_ID as MEETING_HOST
from .meeting_host import (
    InMemoryReceiptStore,
    MeetingEventDraft,
    draft_meeting_event,
    host_gate,
    load_meeting_host_config,
)
from .outbox import Outbox
from .registry import load_registry
from .store import InMemoryOutboxStore
from .tokens import FakeKms, InMemoryTokenStore, OAuthSettings, TokenBroker, TokenStore

ALLOWED_HOSTS: frozenset[str] = frozenset({"oauth2.googleapis.com", "gmail.googleapis.com", "www.googleapis.com"})
DEFAULT_TIMEOUT_S = 30.0
CALLBACK_PATH = "/oauth/google/callback"
_MAX_BODY = 64 * 1024 * 1024
_MAX_HANDLERS = 8  # concurrent callback connections; more are dropped
_MAX_WAIT_S = 3600.0
_CONFIG = Path(__file__).resolve().parents[4] / "config" / "connectors.yaml"
_USER, _WORLD, _RUN = "u_live_smoke", "w_live_smoke", "r_live_smoke"
_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})+")
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DRAFT = {"kind": "email", "subject": "Tilo live smoke test", "body_text": "Created by the Tilo smoke check. Not sent."}


class LiveNotEnabled(RuntimeError):
    """The environment does not say LIVE=1 (EFF-01): nothing live runs."""


class HostRefused(Exception):
    """A request the live layer will not make. Fixed text: never the URL, a header or a form value."""


class SmokeError(Exception):
    """The smoke run failed. Fixed text plus short reasons: never a token, code, body or secret."""


class CallbackTimeout(SmokeError):
    """No valid redirect arrived in time."""


def _require_live(environ: Mapping[str, str] | None) -> None:
    if (os.environ if environ is None else environ).get("LIVE") != "1":
        raise LiveNotEnabled("live access is off: set LIVE=1 in the environment to use it")


def _seconds(value: Any, upper: float = math.inf) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
        raise ValueError("a timeout must be a finite number of seconds above 0")
    if value > upper:
        raise ValueError(f"a timeout can be at most {upper:g} seconds")
    return float(value)


def _checked(url: Any, allowed: frozenset[str]) -> Any:
    """The parts of `url` when it is exactly https, an allowed host, port 443 or none, no userinfo."""
    bad = not isinstance(url, str) or not url.startswith("https://") or len(url) > 8192 or not url.isascii()
    bad = bad or any(c.isspace() or c == "\\" or ord(c) < 32 for c in str(url))
    try:
        parts = urlsplit("" if bad else url)
        port, host = parts.port, parts.hostname or ""
    except ValueError:
        bad = True
    if bad or "@" in parts.netloc or host not in allowed or port not in (None, 443):
        raise HostRefused("this address is not on the allow-list of Google hosts")
    if parts.netloc.lower() not in (host, f"{host}:443"):
        raise HostRefused("this address is not on the allow-list of Google hosts")
    return parts


def _loopback(base: Any) -> tuple[str, int]:
    try:
        parts = urlsplit(base)
        ok = parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost") and parts.port
        ok = ok and parts.path in ("", "/") and not (parts.query or parts.fragment or parts.username)
        port = parts.port
    except (ValueError, AttributeError, TypeError):
        ok, port = False, None
    if not ok or port is None:
        raise ValueError("an endpoint override must be http://127.0.0.1:PORT or http://localhost:PORT")
    return str(parts.hostname), port


@dataclass
class LiveResponse:
    status_code: int
    headers: dict[str, str]  # names lower-case
    content: bytes = field(repr=False)

    def json(self) -> Any:
        return jsonlib.loads(self.content)  # ValueError when it is not JSON


class _LiveBase:
    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        *,
        allowed_hosts: Collection[str] = ALLOWED_HOSTS,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        endpoint_overrides: Mapping[str, str] | None = None,
        allow_loopback_http: bool = False,
    ) -> None:
        _require_live(environ)
        self.timeout_s = _seconds(timeout_s)
        self.allowed_hosts = frozenset(str(h).lower() for h in allowed_hosts)
        if not self.allowed_hosts <= ALLOWED_HOSTS:
            raise ValueError("allowed_hosts can only be narrowed, never widened beyond the Google hosts")
        if endpoint_overrides and not allow_loopback_http:
            raise ValueError("endpoint overrides are a test seam: they need allow_loopback_http=True")
        self._overrides = {str(h).lower(): _loopback(b) for h, b in (endpoint_overrides or {}).items()}
        self._tls: ssl.SSLContext | None = None

    def _exchange(
        self, method: str, url: str, *, query: list[tuple[str, str]], headers: Mapping[str, str], body: bytes | None
    ) -> LiveResponse:
        parts = _checked(url, self.allowed_hosts)  # before DNS and before a socket
        target = parts.path or "/"
        qs = "&".join(q for q in (parts.query, urlencode(query)) if q)
        target += f"?{qs}" if qs else ""
        local = self._overrides.get(parts.hostname)
        status, raw, got, failed = 0, b"", {}, False
        try:
            if local is not None:
                conn: http.client.HTTPConnection = http.client.HTTPConnection(*local, timeout=self.timeout_s)
            else:
                self._tls = self._tls or ssl.create_default_context()
                conn = http.client.HTTPSConnection(parts.hostname, 443, timeout=self.timeout_s, context=self._tls)
            try:
                conn.request(method.upper(), target, body=body, headers={**headers, "connection": "close"})
                reply = conn.getresponse()
                status, got = reply.status, {k.lower(): v for k, v in reply.getheaders()}
                raw = b"" if 300 <= status < 400 else reply.read(_MAX_BODY + 1)
            finally:
                conn.close()
        except (OSError, http.client.HTTPException, ValueError, TypeError, AttributeError):
            failed = True  # raised below, outside the handler: no chained cause can carry a header or a value
        if failed or len(raw) > _MAX_BODY:
            raise TransportError("the request to Google did not complete")
        if 300 <= status < 400:
            raise HostRefused("Google answered with a redirect, which is never followed")
        return LiveResponse(status, got, raw)


class LiveHttpClient(_LiveBase):
    """tokens.HttpClient: one form POST per call, no retry (an authorisation code works once)."""

    def post(self, url: str, *, data: Mapping[str, str]) -> LiveResponse:
        headers = {"content-type": "application/x-www-form-urlencoded", "accept": "application/json"}
        return self._exchange("POST", url, query=[], headers=headers, body=urlencode(dict(data)).encode("utf-8"))


class LiveTransport(_LiveBase):
    """adapters.Transport: one HTTP request per call; 4xx and 5xx come back as responses."""

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
    ) -> LiveResponse:
        query: list[tuple[str, str]] = []
        for key, value in (params or {}).items():
            if value is not None:
                query += [(str(key), str(v)) for v in (value if isinstance(value, list | tuple) else [value])]
        sent = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        body = content
        if json is not None:
            body, sent["content-type"] = jsonlib.dumps(json).encode("utf-8"), "application/json"
        return self._exchange(method, url, query=query, headers=sent, body=body)


@dataclass(frozen=True)
class CallbackResult:
    code: str | None = field(repr=False)
    error: str | None


class _Httpd(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"  # on Windows reuse would let another process share the port
    owner: Any = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._slots = threading.BoundedSemaphore(_MAX_HANDLERS)
        super().__init__(*args, **kwargs)

    def process_request(self, request: Any, client_address: Any) -> None:
        if self._slots.acquire(blocking=False):
            super().process_request(request, client_address)
        else:
            self.shutdown_request(request)  # too many open connections: drop this one at once

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)  # not HTTPServer's: it does a reverse lookup
        self.server_name, self.server_port = "127.0.0.1", self.socket.getsockname()[1]

    def handle_error(self, request: Any, client_address: Any) -> None:
        return


class _Handler(http.server.BaseHTTPRequestHandler):
    timeout = 2  # a silent connection ends here and never holds up the redirect

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the request line holds the code
        return

    def do_GET(self) -> None:  # noqa: N802
        owner: CallbackServer = self.server.owner  # type: ignore[attr-defined]
        status, result = owner._classify(self.path)
        text = {200: "Sign-in received. You can close this tab.", 404: "Not found."}.get(status, "Not accepted.")
        body = text.encode("ascii")
        self.send_response(status)
        for key, value in (("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")):
            self.send_header(key, value)
        for key, value in (("Referrer-Policy", "no-referrer"), ("Content-Length", str(len(body)))):
            self.send_header(key, value)
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        finally:
            if result is not None:
                owner._done.set()


class CallbackServer:
    """Waits for Google's redirect on 127.0.0.1 only; one request carrying `expected_state` ends the wait."""

    def __init__(self, *, expected_state: str, port: int = 8080, timeout_s: float = 300.0) -> None:
        if not isinstance(expected_state, str) or not expected_state:
            raise ValueError("expected_state is required")
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("port must be 0 to 65535")
        self._timeout_s = _seconds(timeout_s, _MAX_WAIT_S)
        self._state = expected_state.encode("utf-8")
        self._lock, self._done = threading.Lock(), threading.Event()
        self._result: CallbackResult | None = None
        self._closed = False
        self._httpd = _Httpd(("127.0.0.1", port), _Handler)
        self._httpd.owner = self
        self.port = int(self._httpd.server_address[1])
        self.address = ("127.0.0.1", self.port)
        threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def __repr__(self) -> str:
        return f"CallbackServer(address={self.address!r})"

    def _classify(self, target: str) -> tuple[int, CallbackResult | None]:
        try:
            parts = urlsplit(target)
            query = parse_qs(parts.query, keep_blank_values=True)
        except ValueError:
            return 400, None
        if parts.path != CALLBACK_PATH:
            return 404, None
        given = query.get("state", [])
        if len(given) != 1 or not hmac.compare_digest(given[0].encode("utf-8"), self._state):
            return 400, None
        codes, errors = query.get("code", []), query.get("error", [])
        if errors:
            result = CallbackResult(None, re.sub(r"[^A-Za-z0-9_.-]", "_", errors[0])[:64] or "unknown_error")
        else:
            result = CallbackResult(codes[0] if len(codes) == 1 and codes[0] else None, None)
            result = result if result.code else CallbackResult(None, "no_code")
        with self._lock:
            if self._result is not None:
                return 400, None
            self._result = result
        return 200, result

    def wait(self) -> CallbackResult:
        try:
            if not self._done.wait(self._timeout_s) or self._result is None:
                raise CallbackTimeout("no sign-in redirect arrived in time")
            return self._result
        finally:
            self.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._httpd.shutdown()
        self._httpd.server_close()


@dataclass
class SmokeResult:
    messages: list[dict[str, str]]
    draft: dict | None
    events: list[dict] = field(default_factory=list)


class _Artifacts:
    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        return dict(_DRAFT)


def _clean(value: Any) -> str:
    """Control characters (Cc, Zl, Zp) become spaces and format characters (Cf) are dropped; text is kept."""
    kinds = {"Cc": " ", "Zl": " ", "Zp": " ", "Cf": "", "Cs": ""}
    return " ".join("".join(kinds.get(unicodedata.category(c), c) for c in str(value)).split())[:200]


def _say(out: TextIO, text: str) -> None:
    try:
        out.write(text + "\n")
    except UnicodeEncodeError:
        out.write(text.encode("ascii", "backslashreplace").decode("ascii") + "\n")
    out.flush()


def _ulid(now: float) -> str:
    value = (int(now * 1000) << 80) | secrets.randbits(80)
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def _draft_case(address: str, now: str) -> tuple[dict, dict]:
    """The outbox entry for the one draft and its evidence: the person who ran the command is the authority."""
    outbox_id, card_id = _ulid(time.time()), _ulid(time.time())
    item = {"artifact_id": "art_live_smoke", "version": 1}
    authz = {"by": "person", "ref": _USER, "at": now}
    entry = {
        "id": outbox_id, "idempotency_key": f"{_RUN}:create_draft:{outbox_id}", "world_id": _WORLD, "run_id": _RUN,
        "action_type": "create_draft", "connector": "gmail", "recipients": [address], "attachments": [],
        "item": item, "destination": None, "modifiers": [], "risk_tier": "T1", "authz": authz,
        "undo_window_s": 0, "scheduled_at": now, "state": "queued", "created_at": now,
    }  # fmt: skip
    ids = {"gate_id": "G1", "card_id": card_id, "outbox_id": outbox_id}
    requested = {"type": "approval.requested", "authz": None, "data": {
        **ids, "action_type": "create_draft", "risk_tier": "T1", "irreversible": False, "item": item,
        "approver": None, "team_lead": None}}  # fmt: skip
    resolved = {"type": "approval.resolved", "authz": authz, "data": {
        **ids, "option": "approve", "channel": "web", "pin_verified": False}}  # fmt: skip
    evidence = {"reserved_by": requested, "authorised_by": resolved, "policy": None, "team_lead": None,
                "world_owner": _USER, "instruction": None, "earlier_applied": None}  # fmt: skip
    return entry, evidence


def _check_options(
    environ: Mapping[str, str], draft_to: str | None, callback_timeout_s: float
) -> tuple[OAuthSettings, int]:
    try:
        settings = OAuthSettings.from_env(environ)
        _seconds(callback_timeout_s, _MAX_WAIT_S)
        base = urlsplit(settings.redirect_base_url)
        local = base.scheme == "http" and base.hostname in ("127.0.0.1", "localhost") and base.path in ("", "/")
    except ValueError as error:
        raise SmokeError(f"the settings cannot be used: {error}") from None
    if not local:
        raise SmokeError("GOOGLE_OAUTH_REDIRECT_BASE_URL must be http on 127.0.0.1 or localhost for this check")
    if draft_to is not None and not (isinstance(draft_to, str) and _ADDRESS.fullmatch(draft_to)):
        raise SmokeError("--draft needs exactly one plain e-mail address")
    return settings, base.port or 80


def run_smoke(
    *,
    environ: Mapping[str, str] | None = None,
    draft_to: str | None = None,
    out: TextIO | None = None,
    on_consent_url: Callable[[str], None] | None = None,
    callback_timeout_s: float = 300.0,
    allowed_hosts: Collection[str] = ALLOWED_HOSTS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    endpoint_overrides: Mapping[str, str] | None = None,
    allow_loopback_http: bool = False,
    store: TokenStore | None = None,
    emit: Callable[[dict], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SmokeResult:
    env = os.environ if environ is None else environ
    _require_live(env)  # first: before anything is validated, printed, bound or sent
    out = sys.stdout if out is None else out
    settings, port = _check_options(env, draft_to, callback_timeout_s)
    net: dict[str, Any] = {"allowed_hosts": allowed_hosts, "timeout_s": timeout_s}
    net |= {"endpoint_overrides": endpoint_overrides, "allow_loopback_http": allow_loopback_http}
    try:
        http_client, transport = LiveHttpClient(env, **net), LiveTransport(env, **net)
        decl = load_registry(_CONFIG).get("gmail")
    except ValueError as error:
        raise SmokeError(f"the options cannot be used: {error}") from None

    events: list[dict] = []

    def record(part: dict) -> None:
        events.append(part)
        if emit is not None:
            emit(part)

    clock = lambda: format_ts(datetime.now(UTC))  # noqa: E731
    broker = TokenBroker(
        store=store or InMemoryTokenStore(),
        kms=FakeKms(),
        http=http_client,
        settings=settings,
        clock=clock,
        emit=record,
    )
    consent = ConsentService(
        connectors={"gmail": decl}, broker=broker, http=http_client, settings=settings, clock=clock, emit=record
    )
    capabilities = ["read", "write"] if draft_to else ["read"]
    url = consent.authorization_url(
        user_id=_USER, connector="gmail", capabilities=capabilities, card_id=_ulid(time.time())
    )
    state = parse_qs(urlsplit(str(url)).query)["state"][0]
    try:
        server = CallbackServer(expected_state=state, port=port, timeout_s=callback_timeout_s)
    except OSError:
        raise SmokeError(f"cannot listen on 127.0.0.1:{port} (is another program using it?)") from None
    try:  # the listener exists before the URL is shown, so a fast redirect cannot be missed
        if _ipv6_taken(server.port):
            raise SmokeError(f"another program listens on [::1]:{server.port}; stop it or pick another port")
        _say(out, f"Open this address in your browser and sign in with Google:\n{url}")
        _say(out, f"Waiting up to {callback_timeout_s:g} s for the redirect on 127.0.0.1:{server.port} ...")
        if on_consent_url is not None:
            on_consent_url(str(url))
        reply = server.wait()
    finally:
        server.close()
    if reply.code is None:
        raise SmokeError(f"the sign-in was not completed ({reply.error})")
    try:
        consent.handle_callback(user_id=_USER, state=state, code=reply.code)
    except Exception as error:  # noqa: BLE001 - ConsentRefused texts are fixed; anything else is not echoed
        raise SmokeError(str(error) if isinstance(error, ConsentRefused) else "the sign-in failed") from None

    adapter = GmailAdapter(
        declaration=decl, broker=broker, transport=transport, artifacts=_Artifacts(), owner_of=lambda world: _USER,
        clock=clock, emit=record, sleep=sleep,
    )  # fmt: skip
    messages = _read(adapter, out)
    draft = _draft(adapter, draft_to, record, clock, out) if draft_to else None
    _say(out, "Done. The sign-in grant stays at Google: remove it at myaccount.google.com/permissions when finished.")
    return SmokeResult(messages, draft, events)


def _ipv6_taken(port: int) -> bool:
    """True when another process already listens on [::1]:port, where a browser may send the code first."""
    try:
        probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        return False  # no IPv6 here
    with probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("::1", port))
        except OSError as error:
            return error.errno in (errno.EADDRINUSE, errno.EACCES)
    return False


def _read(adapter: GmailAdapter, out: TextIO) -> list[dict[str, str]]:
    try:
        ids = adapter.recent_inbox(_USER, max_results=5)["message_ids"][:5]
        found = [adapter.get_message(_USER, i, headers=("Date", "From", "Subject")) for i in ids]
    except Exception as error:  # noqa: BLE001 - adapter and broker texts are fixed; only the kind is shown
        raise SmokeError(f"reading the mailbox failed ({type(error).__name__})") from None
    messages = [{k: _clean(m.get(k, "")) for k in ("date", "from", "subject")} for m in found]
    _say(out, f"Newest {len(messages)} messages (date | from | subject):" if messages else "No messages in the inbox.")
    for m in messages:
        _say(out, f"{m['date']} | {m['from']} | {m['subject']}")
    return messages


def _draft(
    adapter: GmailAdapter, address: str, record: Callable[[dict], None], clock: Callable[[], str], out: TextIO
) -> dict:
    outbox = Outbox(InMemoryOutboxStore(), {"gmail": adapter}, emit=record, clock=clock, world_id=_WORLD)
    entry, evidence = _draft_case(address, clock())
    try:
        outbox.enqueue(entry, evidence)
        settled = outbox.dispatch_due()  # once: a 400 is final, a retryable failure is not retried here
    except Exception as error:  # noqa: BLE001
        raise SmokeError(f"the draft was not created ({type(error).__name__})") from None
    if not any(e["id"] == entry["id"] and e["state"] == "sent" for e in settled):
        with contextlib.suppress(Exception):
            outbox.abandon(entry["id"])
        raise SmokeError("the draft was not created: Google did not accept it")
    _say(out, f"One draft was saved in Gmail Drafts for {address}. Nothing was sent.")
    return {"outbox_id": entry["id"], "state": "sent"}


class _HostDraft:
    """The one draft artifact of the host smoke run, as the adapter's ArtifactSource."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        return dict(jsonlib.loads(self._content))


def _host_case(invite: str, start_in_min: int, now: str) -> tuple[MeetingEventDraft, dict, dict]:
    """The draft, outbox entry and evidence of one smoke meeting: the person who ran the command is the owner, the
    only attendee and the authority (as `_draft_case`); the invitation goes to `invite` alone."""
    owner, org = "u_live_smoke", "org_live_smoke"
    start = add_seconds(now, start_in_min * 60)
    meeting = {
        "id": "mt_live_smoke", "org_id": org, "owner": owner, "title": "Tilo meeting host smoke check",
        "series": None, "scheduled": {"start": start, "end": add_seconds(start, 30 * 60)},
        "agenda": [{"title": "Smoke check", "minutes": 15}], "attendees": [{"name": "Smoke check", "user": owner}],
        "attestation": {"by": owner, "at": now, "notice_version": "1.0.0"}, "source": "bot", "status": "scheduled",
        "ended_reason": None, "minutes_confirmed_by": None, "transcript": None, "minutes": None,
        "delete_transcript_after": None, "delete_minutes_after": None, "created_at": now,
    }  # fmt: skip
    person = {
        "id": owner, "org_id": org, "display_name": "Smoke check", "aliases": [], "email": invite,
        "time_zone": "UTC", "preferred_channel": "email", "org_role": "owner", "memberships": [],
        "created_by": {"by": owner, "at": now},
    }  # fmt: skip
    registry = load_registry(_CONFIG)
    draft = draft_meeting_event(
        meeting=meeting, persons={owner: person}, actor=owner, now=now,
        config=load_meeting_host_config(registry=registry),
    )  # fmt: skip
    stored = {
        "artifact": {"artifact_id": "art_live_smoke_host", "version": 1}, "media_type": "application/json",
        "content_sha256": draft.content_sha256, "origin": {"kind": "unit"}, "screening": "clean",
    }  # fmt: skip
    gate = host_gate(draft, stored, registry.get(MEETING_HOST))
    outbox_id, card_id = _ulid(time.time()), _ulid(time.time())
    authz = {"by": "person", "ref": owner, "at": now}
    entry = {
        "id": outbox_id, "idempotency_key": f"{_RUN}:host:{outbox_id}", "world_id": _WORLD, "run_id": _RUN,
        "action_type": gate["action_type"], "connector": gate["connector"], "recipients": gate["recipients"],
        "attachments": gate["attachments"], "item": gate["item"], "destination": gate["destination"],
        "modifiers": gate["modifiers"], "risk_tier": gate["risk_tier"], "authz": authz,
        "undo_window_s": gate["undo_window_s"], "scheduled_at": now, "state": "queued", "created_at": now,
    }  # fmt: skip
    ids = {"gate_id": "G1", "card_id": card_id, "outbox_id": outbox_id}
    requested = {"type": "approval.requested", "authz": None, "data": {
        **ids, "action_type": gate["action_type"], "risk_tier": gate["risk_tier"], "irreversible": True,
        "item": gate["item"], "approver": None, "team_lead": None}}  # fmt: skip
    resolved = {"type": "approval.resolved", "authz": authz, "data": {
        **ids, "option": "approve", "channel": "web", "pin_verified": False}}  # fmt: skip
    evidence = {"reserved_by": requested, "authorised_by": resolved, "policy": None, "team_lead": None,
                "world_owner": owner, "instruction": None, "earlier_applied": None}  # fmt: skip
    return draft, entry, evidence


def run_host_smoke(
    *,
    invite: str,
    start_in_min: int = 30,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    on_consent_url: Callable[[str], None] | None = None,
    callback_timeout_s: float = 300.0,
    allowed_hosts: Collection[str] = ALLOWED_HOSTS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    endpoint_overrides: Mapping[str, str] | None = None,
    allow_loopback_http: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, str]:
    """FR-MTG-09 first live step (the user only): sign in as the meeting bot, create one event with a Meet link on
    its calendar through the outbox, invite `invite` and print the conference status and the event id. The link is
    never requested, stored or printed. The command line is the approval: the person running it is the authority."""
    env = os.environ if environ is None else environ
    _require_live(env)  # first: before anything is validated, printed, bound or sent
    out = sys.stdout if out is None else out
    settings, port = _check_options(env, None, callback_timeout_s)
    if not (isinstance(invite, str) and _ADDRESS.fullmatch(invite)):
        raise SmokeError("--invite needs exactly one plain e-mail address")
    if isinstance(start_in_min, bool) or not isinstance(start_in_min, int) or not 1 <= start_in_min <= 1440:
        raise SmokeError("--start-in-min must be a whole number of minutes from 1 to 1440")
    net: dict[str, Any] = {"allowed_hosts": allowed_hosts, "timeout_s": timeout_s}
    net |= {"endpoint_overrides": endpoint_overrides, "allow_loopback_http": allow_loopback_http}
    clock = lambda: format_ts(datetime.now(UTC))  # noqa: E731
    try:
        http_client, transport = LiveHttpClient(env, **net), LiveTransport(env, **net)
        decl = load_registry(_CONFIG).get(MEETING_HOST)
        draft, entry, evidence = _host_case(invite, start_in_min, clock())
    except (ValueError, MeetingHostRefused) as error:
        raise SmokeError(f"the options cannot be used: {error}") from None
    owner = draft.owner
    events: list[dict] = []
    broker = TokenBroker(
        store=InMemoryTokenStore(), kms=FakeKms(), http=http_client, settings=settings, clock=clock, emit=events.append
    )
    consent = ConsentService(
        connectors={MEETING_HOST: decl}, broker=broker, http=http_client, settings=settings, clock=clock,
        emit=events.append,
    )  # fmt: skip
    card_id = _ulid(time.time())
    url = consent.authorization_url(user_id=owner, connector=MEETING_HOST, capabilities=["send"], card_id=card_id)
    state = parse_qs(urlsplit(str(url)).query)["state"][0]
    try:
        server = CallbackServer(expected_state=state, port=port, timeout_s=callback_timeout_s)
    except OSError:
        raise SmokeError(f"cannot listen on 127.0.0.1:{port} (is another program using it?)") from None
    try:  # the listener exists before the URL is shown, so a fast redirect cannot be missed
        if _ipv6_taken(server.port):
            raise SmokeError(f"another program listens on [::1]:{server.port}; stop it or pick another port")
        _say(out, f"Open this address in your browser and sign in to Google AS THE MEETING BOT:\n{url}")
        _say(out, f"Waiting up to {callback_timeout_s:g} s for the redirect on 127.0.0.1:{server.port} ...")
        if on_consent_url is not None:
            on_consent_url(str(url))
        reply = server.wait()
    finally:
        server.close()
    if reply.code is None:
        raise SmokeError(f"the sign-in was not completed ({reply.error})")
    try:
        consent.handle_callback(user_id=owner, state=state, code=reply.code)
    except Exception as error:  # noqa: BLE001 - ConsentRefused texts are fixed; anything else is not echoed
        raise SmokeError(str(error) if isinstance(error, ConsentRefused) else "the sign-in failed") from None

    receipts = InMemoryReceiptStore()
    adapter = MeetingHostAdapter(
        declaration=decl, broker=broker, transport=transport, artifacts=_HostDraft(draft.content),
        owner_of=lambda world: owner, receipts=receipts, clock=clock, emit=events.append, sleep=sleep,
    )  # fmt: skip
    outbox = Outbox(InMemoryOutboxStore(), {MEETING_HOST: adapter}, emit=events.append, clock=clock, world_id=_WORLD)
    _say(out, f"Creating one meeting in {start_in_min} min with a Meet link, and one invitation to your address.")
    try:
        outbox.enqueue(entry, evidence)
        settled = outbox.dispatch_due()  # once: a 400 is final, a retryable failure is not retried here
    except Exception as error:  # noqa: BLE001
        raise SmokeError(f"the meeting was not created ({type(error).__name__})") from None
    if not any(e["id"] == entry["id"] and e["state"] == "sent" for e in settled) or not receipts.receipts:
        with contextlib.suppress(Exception):
            outbox.abandon(entry["id"])
        raise SmokeError("the meeting was not created: Google did not accept it")
    receipt = receipts.receipts[0]
    _say(out, f"Created. Conference status: {receipt.conference}. Event id: {receipt.event_ref}.")
    _say(out, "Check the invitation in the test inbox. The Meet link is in it; this check never reads or shows it.")
    _say(out, "Delete the event on the bot's calendar and remove the grant at myaccount.google.com/permissions.")
    return {"event_id": receipt.event_ref, "conference": receipt.conference}
