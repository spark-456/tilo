"""Test doubles for the CL-LIVE-1 tests (real Google adapters behind `tilo_connectors.real.real_adapters`).
API pinned in API_CL_LIVE_1.md. No production code lives here, no network and no real token.

- PlantedTransport: a fake Google behind the adapters' `Transport` seam. It answers Gmail, Drive and Calendar reads
  with PLANTED marker strings (mailbox, Drive and Calendar content), records every request, accepts only the bearer
  tokens the FakeGoogle token double issued, and answers any non-GET with a 200 so a write that gets through is
  visible in `writes()` instead of an exception.
- make_real_env(): a real TokenBroker over the FakeGoogle double (grants given directly, as a finished consent leaves
  them), the shipped config/connectors.yaml registry, the transport and a scope spy. `RealEnv.build(**over)` calls
  `tilo_connectors.real.real_adapters` with the pinned signature.
- Fixtures: a clean process environment (no LIVE, CI, Cloud Run or record switch) and a socket guard.

Every token is assembled at runtime by the _oauth_lib double or by `secrets`; every address is at example.com.
"""

from __future__ import annotations

import base64
import importlib
import json as jsonlib
import os
import secrets
import socket
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from _gapi_lib import ScopeSpy
from _oauth_lib import OWNER, Env, make_env

REPO_ROOT = Path(__file__).resolve().parents[3]
CONNECTORS_YAML = REPO_ROOT / "config" / "connectors.yaml"
REAL_PY = REPO_ROOT / "services" / "connectors" / "src" / "tilo_connectors" / "real.py"

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE_API = "https://www.googleapis.com/drive/v3"
CALENDAR_EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"

GOOGLE_CONNECTORS = ("gmail", "google_drive", "google_calendar")
LIVE_ENV = {"LIVE": "1"}  # the user's switch, in an injected mapping: never in the process environment
WRITE_REFUSAL = "writes are not enabled until CL-LIVE-2"
_PROCESS_SWITCHES = ("LIVE", "CI", "GITHUB_ACTIONS", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_RECORD")


def real() -> Any:
    """`tilo_connectors.real`, imported inside each test so a missing module fails that test, not collection."""
    return importlib.import_module("tilo_connectors.real")


def b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------------------------------------------
# Fixtures


@pytest.fixture(autouse=True)
def clean_process_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No live switch, CI, Cloud Run or record marker in the process; a test that needs one sets it on its own."""
    for name in _PROCESS_SWITCHES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def socket_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """EFF-01: nothing here may reach a host but loopback."""
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def connect(self: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"CL_LIVE_1 tests must not connect to {host!r}")
        return real_connect(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host not in ("127.0.0.1", "::1", "localhost", None):
            raise RuntimeError(f"CL_LIVE_1 tests must not resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


# ---------------------------------------------------------------------------------------------------------
# Planted content


@dataclass(frozen=True)
class Markers:
    """Strings that stand for a person's private content. Random per test, never shaped like a credential."""

    snippet: str = field(default_factory=lambda: "snip" + secrets.token_hex(8))
    subject: str = field(default_factory=lambda: "subj" + secrets.token_hex(8))
    body: str = field(default_factory=lambda: "body" + secrets.token_hex(8))
    drive_name: str = field(default_factory=lambda: "dname" + secrets.token_hex(8))
    drive_text: str = field(default_factory=lambda: "dtext" + secrets.token_hex(8))
    event_title: str = field(default_factory=lambda: "evt" + secrets.token_hex(8))
    error_body: str = field(default_factory=lambda: "errbody" + secrets.token_hex(8))

    def all(self) -> list[str]:
        return [
            self.snippet,
            self.subject,
            self.body,
            self.drive_name,
            self.drive_text,
            self.event_title,
            self.error_body,
        ]


class Resp:
    def __init__(self, status: int, body: Any = None, *, content: bytes | None = None) -> None:
        self.status_code = status
        self.headers = {"content-type": "application/octet-stream" if content is not None else "application/json"}
        self._json = body
        self.content = content if content is not None else jsonlib.dumps(body).encode("utf-8")

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("not JSON")
        return jsonlib.loads(jsonlib.dumps(self._json))


@dataclass(frozen=True)
class Req:
    method: str
    url: str
    params: dict
    headers: dict
    json: Any
    content: bytes | None

    @property
    def token(self) -> str | None:
        value = self.headers.get("authorization", "")
        return value[len("Bearer ") :] if value.startswith("Bearer ") else None


class PlantedTransport:
    """The whole `Transport` surface plus inspection. Reads answer with the planted markers."""

    def __init__(self, google: Any, markers: Markers) -> None:
        self._google, self.markers = google, markers
        self.requests: list[Req] = []
        self._fail: list[tuple[int, Any]] = []

    def fail_next(self, status: int, body: Any = None) -> None:
        self._fail.append((status, body))

    def writes(self) -> list[Req]:
        return [r for r in self.requests if r.method != "GET"]

    def tokens_seen(self) -> set[str]:
        return {r.token for r in self.requests if r.token}

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        headers: Any = None,
        json: Any = None,
        content: bytes | None = None,
    ) -> Resp:
        req = Req(
            method.upper(),
            url,
            {k: v for k, v in dict(params or {}).items() if v is not None},
            {str(k).lower(): str(v) for k, v in dict(headers or {}).items()},
            json,
            content,
        )
        self.requests.append(req)
        if self._fail:
            status, body = self._fail.pop(0)
            return Resp(
                status, body if body is not None else {"error": {"code": status, "message": self.markers.error_body}}
            )
        if req.token not in self._google.issued_access:
            return Resp(401, {"error": {"code": 401, "status": "UNAUTHENTICATED"}})
        if req.method != "GET":
            return Resp(200, {"id": "wrote_" + secrets.token_hex(4), "threadId": "thr_1"})  # a write that got through
        return self._read(req)

    # -- reads ---------------------------------------------------------------------------------
    def _message(self) -> dict:
        m = self.markers
        return {
            "id": "msg_1",
            "threadId": "thr_1",
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": "supplier@example.com"},
                    {"name": "To", "value": "owner@example.com"},
                    {"name": "Subject", "value": m.subject},
                    {"name": "Message-ID", "value": "<m1@mail.example.com>"},
                    {"name": "Date", "value": "Fri, 02 Oct 2026 09:00:00 +0000"},
                ],
                "body": {"data": b64url(m.body), "size": len(m.body)},
            },
        }

    def _read(self, req: Req) -> Resp:  # noqa: PLR0911
        m, url = self.markers, req.url
        if url == GMAIL_API + "/threads":
            return Resp(200, {"threads": [{"id": "thr_1", "snippet": m.snippet}]})
        if url == GMAIL_API + "/threads/thr_1":
            return Resp(200, {"id": "thr_1", "messages": [self._message()]})
        if url == GMAIL_API + "/messages/msg_1":
            return Resp(200, self._message())
        if url == GMAIL_API + "/messages":
            return Resp(200, {"messages": [{"id": "msg_1"}]})
        if url == GMAIL_API + "/profile":
            return Resp(200, {"historyId": "1000"})
        if url == GMAIL_API + "/labels":
            return Resp(200, {"labels": [{"id": "INBOX", "name": "INBOX", "type": "system"}]})
        if url == GMAIL_API + "/history":
            return Resp(200, {"historyId": "1001", "history": [{"messagesAdded": [{"message": {"id": "msg_1"}}]}]})
        if url == DRIVE_API + "/files/file_1":
            if req.params.get("alt") == "media":
                return Resp(200, content=m.drive_text.encode("utf-8"))
            size = str(len(m.drive_text))
            return Resp(200, {"id": "file_1", "name": m.drive_name, "mimeType": "text/plain", "size": size})
        if url == DRIVE_API + "/files":
            return Resp(200, {"files": [{"id": "file_1", "name": m.drive_name, "mimeType": "text/plain"}]})
        if url == CALENDAR_EVENTS:
            event = {
                "id": "ev1",
                "status": "confirmed",
                "summary": m.event_title,
                "start": {"dateTime": "2026-10-02T10:00:00+00:00"},
                "end": {"dateTime": "2026-10-02T11:00:00+00:00"},
            }
            return Resp(200, {"items": [event], "nextSyncToken": "sync_1"})
        return Resp(404, {"error": {"code": 404, "message": "not found"}})


# ---------------------------------------------------------------------------------------------------------
# Wiring


@dataclass
class RealEnv:
    env: Env
    transport: PlantedTransport
    registry: Any
    spy: ScopeSpy
    markers: Markers
    picks: Any
    emitted: list[dict]

    def build(self, **over: Any) -> dict[str, Any]:
        """`real_adapters(broker, registry, transport, user_id=..., environ=LIVE_ENV, ...)` with the pinned keywords."""
        kwargs: dict[str, Any] = {
            "user_id": OWNER,
            "environ": dict(LIVE_ENV),
            "clock": self.env.clock,
            "emit": self.emitted.append,
            "picks": self.picks,
            "sleep": lambda _seconds: None,  # a 429 never really waits in a test
        }
        registry, transport = over.pop("registry", self.registry), over.pop("transport", self.transport)
        kwargs.update(over)
        return real().real_adapters(self.spy, registry, transport, **kwargs)

    def issued_secrets(self) -> list[str]:
        """Every access and refresh token the fake Google issued, and the OAuth client secret."""
        google = self.env.google
        return [*google.issued_access, *google.live_refresh, *self.env.secrets.values()]


def make_real_env(*, connect: Iterable[str] = GOOGLE_CONNECTORS) -> RealEnv:
    from tilo_connectors.adapters import InMemoryPicks
    from tilo_connectors.registry import load_registry

    env = make_env()
    grants = {
        "gmail": [GMAIL_READONLY, GMAIL_COMPOSE],
        "google_drive": [DRIVE_FILE],
        "google_calendar": [CALENDAR_READONLY],
    }
    for connector in connect:
        env.connect(OWNER, connector, grants[connector])
    markers = Markers()
    picks = InMemoryPicks()
    picks.add(OWNER, ["file_1"])  # a typed id the user gave: the only file the Drive reads can name
    return RealEnv(env, PlantedTransport(env.google, markers), load_registry(CONNECTORS_YAML), ScopeSpy(env.broker),
                   markers, picks, [])  # fmt: skip


def read_everything(adapters: dict[str, Any], env: Env) -> dict[str, Any]:
    """Every read the run may make, once: Gmail list/search/get, Drive metadata/read, Calendar read."""
    gmail, drive, cal = adapters["gmail"], adapters["google_drive"], adapters["google_calendar"]
    now = env.clock()
    return {
        "threads": gmail.list_threads(OWNER, max_results=5),
        "search": gmail.search_threads(OWNER, "from:supplier", max_results=5),
        "thread": gmail.get_thread(OWNER, "thr_1"),
        "message": gmail.get_message(OWNER, "msg_1"),
        "labels": gmail.list_labels(OWNER),
        "recent": gmail.recent_inbox(OWNER, max_results=5),
        "meta": drive.get_metadata(OWNER, "file_1"),
        "file": drive.download(OWNER, "file_1"),
        "events": cal.list_events(OWNER, page_size=10, time_min=now, time_max=_plus_day(now)),
    }


def _plus_day(stamp: str) -> str:
    from _connectors_lib import add_seconds

    return add_seconds(stamp, 86400)


def tree_files(root: Path) -> dict[str, bytes]:
    """Every file under `root` (relative posix path -> bytes)."""
    out: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = path.read_bytes()
    return out


def leaks(haystack: str, needles: Iterable[str]) -> list[str]:
    return [n for n in needles if n and n in haystack]


def dump(value: Any) -> str:
    return jsonlib.dumps(value, default=repr, sort_keys=True)


def process_environ_snapshot() -> dict[str, str]:
    return dict(os.environ)
