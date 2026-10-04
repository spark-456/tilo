"""Test doubles for the live Gmail smoke harness tests (FR-CON-04, PRD 5.4 CP1). API_FR_CON_04_live_smoke.md.

No production code lives here. What is here:

- FakeGoogleServer: a real HTTP server on an ephemeral 127.0.0.1 port that plays Google's token endpoint
  (POST /token, /revoke, backed by the FakeGoogle double of _oauth_lib) and Gmail (backed by the
  FakeGoogleApis double of _gapi_lib, plus GET /profile and a labelIds/maxResults-aware GET /messages).
  It records every request, and a test can script a response for any request (redirect, delay, status).
- TrapServer: a second loopback server that must receive nothing (the target of a redirect).
- World / world fixture: the fakes wired together with the OAuth environment a smoke run reads.
- Running / start_smoke / approve / get_callback: run `run_smoke` in a thread, read its consent URL, play
  the browser's redirect back to the callback listener.
- no_external_network: an autouse guard that fails a test that tries to resolve or connect to anything
  outside 127.0.0.0/8, or to open a browser.
- Leak and event helpers.

Every secret is assembled at runtime by the _oauth_lib doubles; every address is at example.com/.net/.org.
"""

from __future__ import annotations

import http.client
import http.server
import io
import json
import queue
import socket
import threading
import unicodedata
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from _gapi_lib import GMAIL_API, FakeGoogleApis, marker
from _oauth_lib import (
    _EVENT_REGISTRY,
    CONTRACTS,
    REVOKE_URL,
    TOKEN_URL,
    Env,
    RecordingTokenStore,
    authz_errors,
    make_env,
    parse_auth_url,
    schema_errors,
)

GMAIL_PREFIX = "/gmail/v1/users/me"
CALLBACK_PATH = "/oauth/google/callback"

_REAL_GETADDRINFO = socket.getaddrinfo
_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(name="hangup_port")
def live_hangup_port():
    """A loopback port that accepts a connection and drops it at once: a network failure that is fast.
    (A closed port takes seconds to refuse on Windows.)"""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)

    def serve() -> None:
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    yield int(listener.getsockname()[1])
    listener.close()


def port_is_closed(port: int, host: str = "127.0.0.1") -> bool:
    """True when nothing accepts a TCP connection on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        try:
            _REAL_CONNECT(s, (host, port))
        except OSError:
            return True
    return False


# ---------------------------------------------------------------------------
# The network guard


@dataclass
class Guard:
    violations: list[str] = field(default_factory=list)


def _loopback(host: Any) -> bool:
    text = str(host)
    return text in ("localhost", "::1", "") or text.startswith("127.")


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch: pytest.MonkeyPatch):
    """Nothing in these tests may leave 127.0.0.0/8 or open a browser. A refusal that a test provokes must
    come from the code under test before it resolves or connects: this guard is the safety net behind it."""
    guard = Guard()

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any):
        if host is not None and not _loopback(host):
            guard.violations.append(f"resolve {host}")
            raise OSError("blocked by the test network guard")
        return _REAL_GETADDRINFO(host, *args, **kwargs)

    def connect(self: socket.socket, address: Any):
        if isinstance(address, tuple) and not _loopback(address[0]):
            guard.violations.append(f"connect {address[0]}")
            raise OSError("blocked by the test network guard")
        return _REAL_CONNECT(self, address)

    def connect_ex(self: socket.socket, address: Any):
        if isinstance(address, tuple) and not _loopback(address[0]):
            guard.violations.append(f"connect {address[0]}")
            return 1
        return _REAL_CONNECT_EX(self, address)

    def no_browser(*args: Any, **kwargs: Any):
        guard.violations.append("open a browser")
        return False

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, name, no_browser)
    yield guard
    assert guard.violations == [], f"the test left loopback: {guard.violations}"


# ---------------------------------------------------------------------------
# Servers


@dataclass(frozen=True)
class Hit:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]  # lower-case names
    body: bytes

    @property
    def form(self) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(self.body.decode("utf-8", "replace"), keep_blank_values=True).items()}

    @property
    def json(self) -> Any:
        return json.loads(self.body) if self.body else None


Reply = tuple[int, dict[str, str], bytes]


def json_reply(status: int, body: Any, headers: dict[str, str] | None = None) -> Reply:
    return status, {"Content-Type": "application/json", **(headers or {})}, json.dumps(body).encode("utf-8")


class _QuietServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:  # a client that hung up is not news
        return


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature of the base class
        return

    def _serve(self) -> None:
        owner: Any = self.server.owner  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        parts = urlsplit(self.path)
        hit = Hit(
            self.command,
            parts.path,
            parse_qs(parts.query, keep_blank_values=True),
            {k.lower(): v for k, v in self.headers.items()},
            body,
        )
        try:
            status, headers, payload = owner.respond(hit)
        except Exception as exc:  # noqa: BLE001 - an unexpected request is a 500 the test can see
            status, headers, payload = json_reply(500, {"error": f"fake server: {type(exc).__name__}: {exc}"})
        try:
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            return  # the client gave up (a timeout test)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve  # noqa: N815


class _ServerBase:
    def __init__(self) -> None:
        self.hits: list[Hit] = []
        self._lock = threading.Lock()
        self._http = _QuietServer(("127.0.0.1", 0), _Handler)
        self._http.owner = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._http.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._http.shutdown()
        self._http.server_close()

    @property
    def port(self) -> int:
        return int(self._http.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _record(self, hit: Hit) -> None:
        with self._lock:
            self.hits.append(hit)

    def hits_to(self, *, method: str | None = None, prefix: str = "") -> list[Hit]:
        with self._lock:
            return [h for h in self.hits if h.path.startswith(prefix) and method in (None, h.method)]

    def respond(self, hit: Hit) -> Reply:
        raise NotImplementedError


class TrapServer(_ServerBase):
    """The place an off-host redirect would lead. Any request it sees is a failure."""

    def respond(self, hit: Hit) -> Reply:
        self._record(hit)
        return json_reply(200, {"trap": True})


class FakeGoogleServer(_ServerBase):
    """Google's token endpoint and Gmail over real HTTP on 127.0.0.1. Paths are the real ones: /token,
    /revoke and /gmail/v1/users/me/...; the smoke reaches them by mapping Google's hosts to base_url."""

    def __init__(self, env: Env, apis: FakeGoogleApis) -> None:
        super().__init__()
        self.env, self.apis = env, apis
        self.hooks: list[Callable[[Hit], Reply | None]] = []
        self.release = threading.Event()  # set at teardown: ends every scripted delay

    def stop(self) -> None:
        self.release.set()
        super().stop()

    def overrides(self) -> dict[str, str]:
        return {
            "oauth2.googleapis.com": self.base_url,
            "gmail.googleapis.com": self.base_url,
            "www.googleapis.com": self.base_url,
        }

    # -- scripting -----------------------------------------------------------------------------
    def reply(self, path: str, reply: Reply | Callable[[Hit], Reply], *, times: int = 1_000) -> None:
        left = [times]

        def hook(hit: Hit) -> Reply | None:
            if hit.path != path or left[0] <= 0:
                return None
            left[0] -= 1
            return reply(hit) if callable(reply) else reply

        self.hooks.append(hook)

    def delay(self, path: str, seconds: float) -> None:
        def hook(hit: Hit) -> Reply | None:
            if hit.path == path:
                self.release.wait(seconds)
            return None

        self.hooks.append(hook)

    # -- inspection ----------------------------------------------------------------------------
    def gmail_hits(self, method: str | None = None) -> list[Hit]:
        return self.hits_to(method=method, prefix=GMAIL_PREFIX)

    def token_posts(self) -> list[Hit]:
        return self.hits_to(method="POST", prefix="/token")

    def writes(self) -> list[Hit]:
        """Every request that could change something at Google: not a GET, not the token endpoint."""
        with self._lock:
            return [h for h in self.hits if h.method != "GET" and h.path not in ("/token", "/revoke")]

    def sends(self) -> list[Hit]:
        with self._lock:
            return [h for h in self.hits if "send" in h.path.lower().split("/")[-1]]

    def draft_posts(self) -> list[Hit]:
        return [h for h in self.hits_to(method="POST", prefix=GMAIL_PREFIX + "/drafts")]

    # -- the fake itself -----------------------------------------------------------------------
    def respond(self, hit: Hit) -> Reply:
        self._record(hit)
        for hook in list(self.hooks):
            scripted = hook(hit)
            if scripted is not None:
                return scripted
        if hit.path in ("/token", "/revoke") and hit.method == "POST":
            url = TOKEN_URL if hit.path == "/token" else REVOKE_URL
            answer = self.env.google.post(url, data=hit.form)
            return json_reply(answer.status_code, answer.json())
        if hit.path.startswith(GMAIL_PREFIX):
            return self._gmail(hit)
        return json_reply(404, {"error": "no such fake endpoint"})

    def _authorised(self, hit: Hit) -> bool:
        value = hit.headers.get("authorization", "")
        token = value[len("Bearer ") :] if value.startswith("Bearer ") else None
        return bool(token) and token in self.env.google.issued_access and token not in self.apis.rejected_tokens

    def _gmail(self, hit: Hit) -> Reply:
        sub = hit.path[len(GMAIL_PREFIX) :]
        params: dict[str, Any] = {k: (v[0] if len(v) == 1 else v) for k, v in hit.query.items()}
        if hit.method == "GET" and sub in ("/profile", "/messages", "/threads") and "q" not in params:
            if not self._authorised(hit):
                return json_reply(401, {"error": {"code": 401}})
            if sub == "/profile":
                return json_reply(200, {"emailAddress": "owner@example.com", "historyId": "4242"})
            return self._messages(params) if sub == "/messages" else self._threads(params)
        response = self.apis.request(hit.method, GMAIL_API + sub, params=params, headers=hit.headers, json=hit.json)
        headers = {k: v for k, v in response.headers.items() if k != "content-length"}
        return response.status_code, headers, response.content

    def _found(self, params: dict[str, Any]) -> list[Any]:
        labels = params.get("labelIds") or []
        labels = [labels] if isinstance(labels, str) else list(labels)
        with self.apis._lock:
            return [
                m
                for m in reversed(list(self.apis.messages.values()))  # newest first, as Gmail lists
                if "DRAFT" not in m.label_ids and set(labels) <= set(m.label_ids)
            ]

    def _messages(self, params: dict[str, Any]) -> Reply:
        found = self._found(params)
        listed = [{"id": m.id, "threadId": m.thread_id} for m in found[: int(params.get("maxResults", 100))]]
        return json_reply(200, {"messages": listed, "resultSizeEstimate": len(found)})

    def _threads(self, params: dict[str, Any]) -> Reply:
        order = list(dict.fromkeys(m.thread_id for m in self._found(params)))
        listed = [{"id": t, "snippet": "", "historyId": "1"} for t in order[: int(params.get("maxResults", 100))]]
        return json_reply(200, {"threads": listed, "resultSizeEstimate": len(order)})


# ---------------------------------------------------------------------------
# The assembled world


@dataclass
class World:
    env: Env
    apis: FakeGoogleApis
    server: FakeGoogleServer
    callback_port: int
    environ: dict[str, str]
    store: RecordingTokenStore
    sleeps: list[float] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)

    def secrets(self) -> list[str]:
        """Every secret value this world has made so far (client secret, codes, access and refresh tokens)."""
        google = self.env.google
        found = [self.env.settings.client_secret, *self.codes, *google.issued_access, *google.live_refresh]
        return list(dict.fromkeys(found))

    def seed_inbox(self, count: int, *, hostile_subject: str | None = None) -> list[dict]:
        """`count` INBOX messages, oldest first, each with a distinct date, sender, subject and a body marker."""
        seeded = []
        for i in range(count):
            body = marker("body")
            subject = f"Subject {i} {marker('s')}"
            sender = f"sender{i}@example.com"
            if hostile_subject is not None and i == count - 1:
                subject = hostile_subject
            made = self.apis.seed_message(thread_id=f"thr_{i}", from_=sender, subject=subject, body=body)
            date = f"Mon, 28 Sep 2026 08:{i:02d}:00 +0000"
            message = self.apis.messages[made["id"]]
            message.raw = message.raw.replace(b"Fri, 02 Oct 2026 09:00:00 +0000", date.encode("ascii"))
            seeded.append({"id": made["id"], "date": date, "from": sender, "subject": subject, "body": body})
        return seeded


@pytest.fixture(name="world")
def live_world():
    env = make_env()
    apis = FakeGoogleApis(env.google)
    server = FakeGoogleServer(env, apis)
    server.start()
    callback_port = free_port()
    environ = {
        "LIVE": "1",
        "GOOGLE_OAUTH_CLIENT_ID": env.settings.client_id,
        "GOOGLE_OAUTH_CLIENT_SECRET": env.settings.client_secret,
        "GOOGLE_OAUTH_REDIRECT_BASE_URL": f"http://127.0.0.1:{callback_port}",
    }
    yield World(env, apis, server, callback_port, environ, RecordingTokenStore())
    server.stop()


# ---------------------------------------------------------------------------
# Driving a smoke run


class Running:
    """`target(on_consent_url, out)` runs in a thread; the test plays the browser."""

    def __init__(self, target: Callable[[Callable[[str], None], io.StringIO], Any]) -> None:
        self.out = io.StringIO()
        self.result: Any = None
        self.error: BaseException | None = None
        self._urls: queue.Queue[str] = queue.Queue()
        self._url: str | None = None
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(target,), daemon=True)
        self._thread.start()

    def _run(self, target: Callable[[Callable[[str], None], io.StringIO], Any]) -> None:
        try:
            self.result = target(self._urls.put, self.out)
        except BaseException as exc:  # noqa: BLE001 - handed to the test
            self.error = exc
        finally:
            self._done.set()

    def url(self, timeout: float = 15.0) -> str:
        while self._url is None:
            try:
                self._url = self._urls.get(timeout=0.05)
            except queue.Empty:
                if self._done.is_set() and self._urls.empty():
                    raise AssertionError(f"the run ended without a consent URL: {self.error!r}") from None
                timeout -= 0.05
                assert timeout > 0, "no consent URL within the time limit"
        return self._url

    def finish(self, timeout: float = 30.0) -> Running:
        assert self._done.wait(timeout), "run_smoke did not finish in time"
        return self

    def value(self, timeout: float = 30.0) -> Any:
        self.finish(timeout)
        if self.error is not None:
            raise self.error
        return self.result

    def raised(self, kind: type[BaseException] = Exception, timeout: float = 30.0) -> BaseException:
        self.finish(timeout)
        assert self.error is not None, f"expected {kind.__name__}, the run returned {self.result!r}"
        assert isinstance(self.error, kind), f"expected {kind.__name__}, got {self.error!r}"
        return self.error


def start_smoke(world: World, *, environ: dict[str, str] | None = None, **options: Any) -> Running:
    def target(on_url: Callable[[str], None], out: io.StringIO) -> Any:
        from tilo_connectors.live import run_smoke

        return run_smoke(
            environ=world.environ if environ is None else environ,
            out=out,
            on_consent_url=on_url,
            endpoint_overrides=world.server.overrides(),
            allow_loopback_http=True,
            sleep=world.sleeps.append,
            store=world.store,
            **options,
        )

    return Running(target)


def get_callback(
    port: int, params: dict[str, Any] | list[tuple[str, str]] | None, *, path: str = CALLBACK_PATH, method: str = "GET"
) -> tuple[int, dict[str, str], str]:
    """The browser's redirect: one HTTP request to the callback listener."""
    target = path + (("?" + urlencode(params)) if params else "")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, target)
        response = conn.getresponse()
        text = response.read().decode("utf-8", "replace")
        return response.status, {k.lower(): v for k, v in response.getheaders()}, text
    finally:
        conn.close()


def approve(
    world: World, run: Running, *, granted: list[str] | None = None, extra: dict[str, str] | None = None
) -> tuple[Any, str, tuple[int, dict[str, str], str]]:
    """The person signs in at Google (granting `granted`, by default what was asked); Google redirects back."""
    flow = parse_auth_url(run.url())
    code = world.env.google.issue_code(
        flow.scopes if granted is None else granted,
        challenge=flow.query["code_challenge"],
        redirect_uri=flow.query["redirect_uri"],
    )
    world.codes.append(code)
    reply = get_callback(world.callback_port, {"code": code, "state": flow.state, **(extra or {})})
    return flow, code, reply


def deny(world: World, run: Running) -> tuple[Any, tuple[int, dict[str, str], str]]:
    flow = parse_auth_url(run.url())
    return flow, get_callback(world.callback_port, {"error": "access_denied", "state": flow.state})


# ---------------------------------------------------------------------------
# Checks


def has_control(text: str) -> bool:
    return any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in text)


def event_problems(parts: list[dict]) -> list[str]:
    """Every emitted part is a registered type with a fixture, valid data, and authz exactly when the
    registry says the type is a side effect."""
    problems: list[str] = []
    registered = _EVENT_REGISTRY["types"]
    for part in parts:
        kind = part.get("type")
        entry = registered.get(kind)
        if entry is None:
            problems.append(f"{kind}: not in contracts/events/registry.yaml (needs contract change)")
            continue
        if not (CONTRACTS / entry["fixture"]).is_file():
            problems.append(f"{kind}: fixture {entry['fixture']} is missing")
        problems += [f"{kind}: {e}" for e in schema_errors(f"events/data/{kind}.schema.json", part.get("data"))]
        if entry["side_effect"]:
            errors = authz_errors(part.get("authz"))
            problems += [f"{kind}: authz {e}" for e in errors]
            if not errors and part["authz"]["by"] not in entry["authz_by"]:
                problems.append(f"{kind}: authz.by {part['authz']['by']} is not allowed")
        elif part.get("authz") is not None:
            problems.append(f"{kind}: not a side effect, so authz must be null")
    return problems
