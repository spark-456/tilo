"""Helpers for the ADR-0035 L6 tests (tilo-api's live Google stubs). Named `_adr35_l6_lib` for the same global
bare-module-name reason as `_mtg09b_lib.py`. Nothing here is business logic: it builds the item documents of
BQ-ADR35L5-1, fakes Google at the adapters' Transport seam (Gmail drafts, Drive saves, Calendar inserts) and reaches the
real `/internal/side-effects/execute` of tilo-connectors in process through `MeetingHostRpc`'s transport seam with a
fake ID-token verifier and the fake broker of `_mtg09b_lib`: no network, no paid call, no LIVE, every token assembled at
run time, every address at example.org.
"""

from __future__ import annotations

import base64
import json
import secrets
from collections.abc import Mapping
from typing import Any

from _mtg09b_lib import FakeBroker

NOW = "2026-10-09T09:40:00.000Z"  # after the contract fixtures' approval (09:32:09.5)
SUBJECT, BODY = "subj-" + secrets.token_hex(5), "body-" + secrets.token_hex(5)
TITLE = "title-" + secrets.token_hex(5)
START, END, ZONE = "2026-10-12T09:00:00.000Z", "2026-10-12T09:30:00.000Z", "Asia/Kolkata"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def raw_of(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def email_doc(**more: Any) -> dict[str, Any]:
    return {"kind": "email", "subject": SUBJECT, "body_text": BODY, **more}


def file_doc(name: str = "report.txt", content: bytes = b"hello", **more: Any) -> dict[str, Any]:
    mime = "text/plain"
    return {"kind": "file", "name": name, "mime_type": mime, "content_b64": base64.b64encode(content).decode(), **more}


def event_doc(**more: Any) -> dict[str, Any]:
    return {"kind": "calendar_event", "title": TITLE, "start": START, "end": END, "time_zone": ZONE, **more}


class Resp:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code, self._body, self.headers, self.content = status, body, {}, json.dumps(body).encode()

    def json(self) -> Any:
        return self._body


class FakeGoogle:
    """Gmail drafts, Drive saves and Calendar inserts, as much as one first attempt of each needs."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Any]] = []
        self.drafts: list[Any] = []
        self.sent: list[Any] = []
        self.folders: list[str] = []
        self.saved: list[bytes] = []
        self.events: dict[str, Any] = {}

    def reached(self) -> int:
        return len(self.requests)

    def request(self, method: str, url: str, *, params: Any = None, headers: Any = None, json: Any = None,
                content: bytes | None = None) -> Resp:  # fmt: skip
        self.requests.append((method, url, json))
        if url == GMAIL_API + "/drafts":
            if method == "GET":
                return Resp(200, {})
            self.drafts.append(json)
            return Resp(200, {"id": "dr_" + secrets.token_hex(3), "message": {"id": "m_1", "threadId": ""}})
        if url == GMAIL_API + "/messages/send" and method == "POST":
            self.sent.append(json)
            return Resp(200, {"id": "msg_" + secrets.token_hex(3), "threadId": ""})
        if url == GMAIL_API + "/messages" and method == "GET":
            return Resp(200, {})
        if url == DRIVE_API + "/files" and method == "GET":
            q = str((params or {}).get("q", ""))
            found = [{"id": f} for f in self.folders] if "mimeType" in q else []
            return Resp(200, {"files": found})
        if url == DRIVE_API + "/files" and method == "POST":
            self.folders.append("fld_" + secrets.token_hex(3))
            return Resp(200, {"id": self.folders[-1]})
        if url.startswith(DRIVE_API + "/files/"):
            return Resp(200, {"id": url.rsplit("/", 1)[1], "shared": False})
        if url == DRIVE_UPLOAD_API:
            self.saved.append(content or b"")
            return Resp(200, {"id": "file_" + secrets.token_hex(3), "shared": False})
        if url == EVENTS_URL and method == "POST":
            event_id = json["id"]
            self.events[event_id] = json
            return Resp(200, {"id": event_id, "status": "confirmed"})
        if url.startswith(EVENTS_URL + "/"):
            return Resp(404, {"error": {"code": 404}})
        return Resp(404, {"error": {"code": 404}})


class InProcessConnectors5:
    """tilo-connectors' real routes (ADR-0035 L5) over the fake broker and `FakeGoogle`, behind `MeetingHostRpc`."""

    def __init__(self, google: FakeGoogle, broker: FakeBroker | None = None, clock: Any = None) -> None:
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from tilo_api.meeting_host_rpc import MeetingHostRpc  # noqa: PLC0415
        from tilo_connectors.app import create_app  # noqa: PLC0415
        from tilo_connectors.host_routes import AUDIENCE_VAR, CALLER_VAR, HostRuntime  # noqa: PLC0415

        self.broker = broker or FakeBroker()
        self.audience = "https://tilo-connectors-" + secrets.token_hex(3) + ".a.run.app"
        self.id_token = secrets.token_hex(12)
        caller = "api-" + secrets.token_hex(3) + "@demo-tilo.example.test"
        claims = {"iss": "https://accounts.google.com", "aud": self.audience, "email": caller, "email_verified": True}
        outer = self

        class Verifier:
            def verify(self, token: str, audience: str) -> dict[str, Any]:
                if token != outer.id_token:
                    raise ValueError("bad token")
                return claims

        runtime = HostRuntime(
            {AUDIENCE_VAR: self.audience, CALLER_VAR: caller}, verifier=Verifier(),
            broker_opener=lambda _env, *, emit, alert: self.broker, transport_opener=lambda env: google,
            clock=clock or (lambda: NOW),
        )  # fmt: skip
        self.client = TestClient(create_app(runtime))
        self.posts: list[dict[str, Any]] = []
        self.rpc = MeetingHostRpc(self.audience, transport=self, token_for=lambda audience: self.id_token)

    def post(self, url: str, body: bytes, headers: Any, timeout_s: float) -> Any:
        from tilo_api.meeting_host_rpc import Reply  # noqa: PLC0415

        self.posts.append(json.loads(body))
        response = self.client.post(url.removeprefix(self.audience), content=body, headers=dict(headers))
        return Reply(response.status_code, response.content)
