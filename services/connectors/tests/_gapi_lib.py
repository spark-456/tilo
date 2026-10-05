"""Test doubles for the Gmail and Drive adapter tests (FR-CON-04, FR-CON-05). API_FR_CON_04_05.md.

No production code lives here. What is here:

- FakeGoogleApis: an in-process stand-in for the Gmail and Drive REST endpoints behind the adapters'
  injected Transport seam (`request(method, url, *, params, headers, json, content)`). It accepts only
  bearer tokens the FakeGoogle token double issued, records every request, keeps mailbox and Drive
  state, and fails on demand (a status for the next N matching requests, a lost response, a rejected
  token). Drive queries support the clauses API_FR_CON_04_05.md lists; Gmail queries support
  `rfc822msgid:`, `in:sent`, `in:drafts`, `from:` and plain words.
- FakeArtifacts: a dict-backed ArtifactSource.
- ScopeSpy: wraps the broker and records the scopes each adapter call asked for.
- make_gapi_env(): broker, adapters and an Outbox wired to those doubles.
- Entry factories for outbox cases (gate-authorised, as conftest.gate_case).

Every token is assembled at runtime by the FakeGoogle double; every address is at example.com,
example.net or example.org.
"""

from __future__ import annotations

import base64
import copy
import email
import email.policy
import email.utils
import hashlib
import json as jsonlib
import re
import secrets
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

from _oauth_lib import (
    DRIVE_FILE,
    GMAIL_COMPOSE,
    GMAIL_READONLY,
    GMAIL_SEND,
    OWNER,
    Env,
    gmail_decl,
    make_env,
)
from conftest import gate_case

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
OOXML = "application/vnd.openxmlformats-officedocument."
GAPPS = "application/vnd.google-apps."
# native Google type -> the one OOXML media type Drive converts it from on upload
_NATIVE_SOURCE = {
    GAPPS + "presentation": OOXML + "presentationml.presentation",
    GAPPS + "document": OOXML + "wordprocessingml.document",
    GAPPS + "spreadsheet": OOXML + "spreadsheetml.sheet",
}

GMAIL_ALL = [GMAIL_READONLY, GMAIL_COMPOSE, GMAIL_SEND]
DRIVE_ALL = [DRIVE_FILE]

ME = "owner@example.com"
SUPPLIER = "supplier@example.com"
ATTACKER = "attacker@example.net"


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def marker(label: str) -> str:
    """A unique token to search logs for; never shaped like a credential."""
    return f"{label}{secrets.token_hex(16)}"


def drive_file_decl() -> dict:
    """google_drive at least privilege: drive.file for every capability (API_FR_CON_04_05.md)."""

    def action(action_id: str, capability: str, description: str, tier: str, gate: str) -> dict:
        return {
            "id": action_id,
            "capability": capability,
            "description": description,
            "risk_tier": tier,
            "gate_type": gate,
            "irreversible": False,
        }

    return {
        "id": "google_drive",
        "name": "Google Drive",
        "icon": "folder",
        "auth": "oauth2",
        "scopes": {"read": [DRIVE_FILE], "list": [DRIVE_FILE], "write": [DRIVE_FILE]},
        "capabilities": ["read", "list", "write"],
        "actions": [
            action("read_file", "read", "Read the files you pick in Drive.", "T1", "none"),
            action("list_files", "list", "See the files in the folder you pick.", "T1", "none"),
            action("save_file", "write", "Save finished work in a Tilo folder in your Drive.", "T1", "approval"),
        ],
        "limits": {"per_minute": 60, "batch_size": 50},
        "data_class": {"returns": ["personal", "business"], "redact": []},
    }


# ---------------------------------------------------------------------------
# Responses and requests


class FakeApiResponse:
    def __init__(
        self, status_code: int, body: Any = None, *, headers: dict | None = None, content: bytes | None = None
    ):
        self.status_code = status_code
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        if content is not None:
            self.content = content
            self._json = None
            self.headers.setdefault("content-type", "application/octet-stream")
        else:
            self._json = body
            self.content = jsonlib.dumps(body).encode("utf-8") if body is not None else b""
            self.headers.setdefault("content-type", "application/json")

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("not a JSON response")
        return copy.deepcopy(self._json)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


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

    def names(self, needle: str) -> bool:
        """True when the request names `needle` anywhere: URL, params, json or body."""
        blob = self.url + jsonlib.dumps(self.params, default=str) + jsonlib.dumps(self.json, default=str)
        if self.content:
            blob += self.content.decode("latin-1")
        return needle in blob


@dataclass
class _Failure:
    status: int
    headers: dict
    times: int
    predicate: Callable[[Req], bool]


def _error(status: int, reason: str) -> FakeApiResponse:
    return FakeApiResponse(status, {"error": {"code": status, "message": reason, "status": reason}})


# ---------------------------------------------------------------------------
# The Gmail and Drive double


@dataclass
class _Msg:
    id: str
    thread_id: str
    raw: bytes
    label_ids: list[str]


@dataclass
class _File:
    id: str
    name: str
    mime_type: str
    parents: list[str]
    content: bytes | None
    app_properties: dict[str, str] = field(default_factory=dict)
    trashed: bool = False

    def meta(self) -> dict:
        out: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "mimeType": self.mime_type,
            "parents": list(self.parents),
        }
        if self.content is not None:
            out["size"] = str(len(self.content))
        if self.app_properties:
            out["appProperties"] = dict(self.app_properties)
        return out


class FakeGoogleApis:
    """Gmail and Drive behind the adapters' Transport seam. `request` is the whole surface."""

    def __init__(self, google: Any) -> None:
        self._google = google  # the FakeGoogle token double: the tokens it issued are the valid ones
        self.requests: list[Req] = []
        self.rejected_tokens: set[str] = set()
        self.messages: dict[str, _Msg] = {}
        self.drafts: dict[str, str] = {}  # draft id -> message id
        self.files: dict[str, _File] = {}
        self._failures: list[_Failure] = []
        self._lose: list[Callable[[Req], bool]] = []
        self._lock = threading.RLock()
        self._n = 0

    # -- provisioning --------------------------------------------------------------------------
    def _next_id(self, prefix: str) -> str:
        with self._lock:
            self._n += 1
            return f"{prefix}{self._n:04d}{secrets.token_hex(3)}"

    def seed_message(
        self,
        *,
        thread_id: str,
        from_: str = SUPPLIER,
        to: Iterable[str] = (ME,),
        subject: str = "Delivery date",
        body: str = "Can you confirm the delivery date?",
        reply_to: str | None = None,
        references: str | None = None,
        labels: Iterable[str] = ("INBOX",),
        attachment: tuple[str, str, bytes] | None = None,
    ) -> dict:
        msg = EmailMessage()
        message_id = f"<{secrets.token_hex(8)}@mail.example.com>"
        msg["From"] = from_
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg["Message-ID"] = message_id
        msg["Date"] = "Fri, 02 Oct 2026 09:00:00 +0000"
        if reply_to:
            msg["Reply-To"] = reply_to
        if references:
            msg["References"] = references
            msg["In-Reply-To"] = references.split()[-1]
        msg.set_content(body)
        if attachment is not None:
            name, mime, data = attachment
            maintype, subtype = mime.split("/", 1)
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
        mid = self._next_id("m")
        with self._lock:
            self.messages[mid] = _Msg(mid, thread_id, bytes(msg), list(labels))
        return {"id": mid, "message_id": message_id, "subject": subject, "references": references}

    def seed_file(
        self,
        *,
        name: str,
        content: bytes | None = b"report",
        mime_type: str = "application/pdf",
        parents: Iterable[str] = ("root",),
        file_id: str | None = None,
    ) -> str:
        fid = file_id or self._next_id("f")
        with self._lock:
            self.files[fid] = _File(fid, name, mime_type, list(parents), content)
        return fid

    def seed_folder(self, *, name: str, parents: Iterable[str] = ("root",)) -> str:
        return self.seed_file(name=name, content=None, mime_type=FOLDER_MIME, parents=parents)

    # -- failure injection ---------------------------------------------------------------------
    def fail_next(
        self,
        status: int,
        *,
        times: int = 1,
        headers: dict | None = None,
        when: Callable[[Req], bool] = lambda r: True,
    ) -> None:
        with self._lock:
            self._failures.append(_Failure(status, dict(headers or {}), times, when))

    def clear_failures(self) -> None:
        """Google has recovered: no injected status is returned any more."""
        with self._lock:
            self._failures.clear()

    def lose_response(self, when: Callable[[Req], bool]) -> None:
        """The next matching request is carried out, then the caller sees a TransportError."""
        with self._lock:
            self._lose.append(when)

    def reject_token(self, token: str) -> None:
        with self._lock:
            self.rejected_tokens.add(token)

    # -- inspection ----------------------------------------------------------------------------
    def sent(self) -> list[EmailMessage]:
        with self._lock:
            return [parse_raw(m.raw) for m in self.messages.values() if "SENT" in m.label_ids]

    def sent_records(self) -> list[_Msg]:
        with self._lock:
            return [m for m in self.messages.values() if "SENT" in m.label_ids]

    def draft_messages(self) -> list[EmailMessage]:
        with self._lock:
            return [parse_raw(self.messages[mid].raw) for mid in self.drafts.values()]

    def created_files(self) -> list[_File]:
        with self._lock:
            return [f for f in self.files.values() if f.app_properties.get("_created_by_tilo") == "1"]

    def writes(self) -> list[Req]:
        with self._lock:
            return [r for r in self.requests if r.method != "GET"]

    def reads_naming(self, needle: str) -> list[Req]:
        with self._lock:
            return [r for r in self.requests if r.names(needle)]

    # -- the Transport seam --------------------------------------------------------------------
    def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        headers: Any = None,
        json: Any = None,
        content: bytes | None = None,
        timeout: Any = None,
    ) -> FakeApiResponse:
        from tilo_connectors.adapters import TransportError

        req = Req(
            method.upper(),
            url,
            {k: v for k, v in dict(params or {}).items() if v is not None},
            {str(k).lower(): str(v) for k, v in dict(headers or {}).items()},
            copy.deepcopy(json),
            bytes(content) if content is not None else None,
        )
        assert "?" not in url, f"query belongs in params, not the URL: {url}"
        with self._lock:
            self.requests.append(req)
            failure = next((f for f in self._failures if f.times > 0 and f.predicate(req)), None)
            if failure is not None:
                failure.times -= 1
        if failure is not None:
            return FakeApiResponse(failure.status, {"error": {"code": failure.status}}, headers=failure.headers)
        token = req.token
        if not token or token not in self._google.issued_access or token in self.rejected_tokens:
            return _error(401, "UNAUTHENTICATED")
        response = self._route(req)
        with self._lock:
            lose = next((w for w in self._lose if w(req)), None)
            if lose is not None:
                self._lose.remove(lose)
        if lose is not None:
            raise TransportError("simulated: the response was lost after Google carried out the request")
        return response

    def _route(self, req: Req) -> FakeApiResponse:
        if req.url.startswith(GMAIL_API):
            return self._gmail(req, req.url[len(GMAIL_API) :])
        if req.url == DRIVE_UPLOAD_API:
            return self._drive_upload(req)
        if req.url.startswith(DRIVE_API):
            return self._drive(req, req.url[len(DRIVE_API) :])
        raise AssertionError(f"the fake has no endpoint {req.method} {req.url}")

    # -- Gmail ---------------------------------------------------------------------------------
    def _gmail(self, req: Req, path: str) -> FakeApiResponse:
        with self._lock:
            if req.method == "GET" and path == "/threads":
                return self._threads_list(req)
            if req.method == "GET" and (m := re.fullmatch(r"/threads/([A-Za-z0-9_-]+)", path)):
                msgs = [x for x in self.messages.values() if x.thread_id == m.group(1) and "DRAFT" not in x.label_ids]
                if not msgs:
                    return _error(404, "NOT_FOUND")
                return FakeApiResponse(200, {"id": m.group(1), "messages": [self._resource(x) for x in msgs]})
            if req.method == "GET" and (m := re.fullmatch(r"/messages/([A-Za-z0-9_-]+)", path)):
                msg = self.messages.get(m.group(1))
                return FakeApiResponse(200, self._resource(msg)) if msg else _error(404, "NOT_FOUND")
            if req.method == "GET" and path == "/messages":
                hits = [x for x in self.messages.values() if self._matches(x, str(req.params.get("q", "")))]
                return FakeApiResponse(200, {"messages": [{"id": x.id, "threadId": x.thread_id} for x in hits]})
            if req.method == "GET" and path == "/drafts":
                q = str(req.params.get("q", ""))
                hits = [
                    (d, self.messages[mid]) for d, mid in self.drafts.items() if self._matches(self.messages[mid], q)
                ]
                return FakeApiResponse(
                    200, {"drafts": [{"id": d, "message": {"id": x.id, "threadId": x.thread_id}} for d, x in hits]}
                )
            if req.method == "GET" and path == "/labels":
                return FakeApiResponse(
                    200,
                    {
                        "labels": [
                            {"id": "INBOX", "name": "INBOX", "type": "system"},
                            {"id": "SENT", "name": "SENT", "type": "system"},
                            {"id": "Label_7", "name": "Suppliers", "type": "user"},
                        ]
                    },
                )
            if req.method == "POST" and path == "/messages/send":
                return self._store_message(req.json or {}, ["SENT"])
            if req.method == "POST" and path == "/drafts":
                body = (req.json or {}).get("message") or {}
                created = self._store_message(body, ["DRAFT"])
                if created.status_code != 200:
                    return created
                did = self._next_id("d")
                self.drafts[did] = created.json()["id"]
                return FakeApiResponse(200, {"id": did, "message": created.json()})
        return _error(404, "NOT_FOUND")

    def _threads_list(self, req: Req) -> FakeApiResponse:
        q = str(req.params.get("q", ""))
        labels = req.params.get("labelIds") or []
        labels = [labels] if isinstance(labels, str) else list(labels)
        order: list[str] = []
        for x in self.messages.values():
            if "DRAFT" in x.label_ids or not self._matches(x, q):
                continue
            if labels and not set(labels) <= set(x.label_ids):
                continue
            if x.thread_id not in order:
                order.append(x.thread_id)
        limit = int(req.params.get("maxResults", 100))
        threads = []
        for tid in order[:limit]:
            first = next(x for x in self.messages.values() if x.thread_id == tid)
            threads.append({"id": tid, "snippet": _text_of(parse_raw(first.raw))[:100], "historyId": "1"})
        body: dict[str, Any] = {"threads": threads, "resultSizeEstimate": len(threads)}
        if len(order) > limit:
            body["nextPageToken"] = "page2"
        return FakeApiResponse(200, body)

    def _matches(self, msg: _Msg, q: str) -> bool:
        parsed = parse_raw(msg.raw)
        text = msg.raw.decode("latin-1").lower()
        for token in q.split():
            low = token.lower()
            if low.startswith("rfc822msgid:"):
                wanted = token.split(":", 1)[1].strip("<>")
                if (parsed["Message-ID"] or "").strip().strip("<>") != wanted:
                    return False
            elif low == "in:sent":
                if "SENT" not in msg.label_ids:
                    return False
            elif low == "in:drafts":
                if "DRAFT" not in msg.label_ids:
                    return False
            elif low.startswith("from:"):
                if low.split(":", 1)[1] not in (parsed["From"] or "").lower():
                    return False
            elif low not in text:
                return False
        return True

    def _store_message(self, body: dict, labels: list[str]) -> FakeApiResponse:
        raw = body.get("raw")
        if not isinstance(raw, str):
            return _error(400, "INVALID_ARGUMENT")
        try:
            raw_bytes = b64url_decode(raw)
        except ValueError:
            return _error(400, "INVALID_ARGUMENT")
        thread_id = body.get("threadId")
        if thread_id is not None and not any(x.thread_id == thread_id for x in self.messages.values()):
            return _error(404, "NOT_FOUND")
        mid = self._next_id("m")
        self.messages[mid] = _Msg(mid, thread_id or self._next_id("t"), raw_bytes, labels)
        return FakeApiResponse(200, {"id": mid, "threadId": self.messages[mid].thread_id, "labelIds": labels})

    def _resource(self, msg: _Msg) -> dict:
        parsed = parse_raw(msg.raw)
        return {
            "id": msg.id,
            "threadId": msg.thread_id,
            "labelIds": list(msg.label_ids),
            "snippet": _text_of(parsed)[:100],
            "sizeEstimate": len(msg.raw),
            "payload": _payload(parsed),
        }

    # -- Drive ---------------------------------------------------------------------------------
    def _drive(self, req: Req, path: str) -> FakeApiResponse:
        with self._lock:
            if req.method == "GET" and path == "/files":
                try:
                    hits = [f for f in self.files.values() if _drive_query(f, str(req.params.get("q", "")))]
                except ValueError:
                    return _error(400, "INVALID_ARGUMENT")
                return FakeApiResponse(200, {"files": [_public_meta(f) for f in hits]})
            if req.method == "GET" and (m := re.fullmatch(r"/files/([A-Za-z0-9_-]+)", path)):
                f = self.files.get(m.group(1))
                if f is None:
                    return _error(404, "NOT_FOUND")
                if req.params.get("alt") == "media":
                    if f.content is None:
                        return _error(403, "FORBIDDEN")
                    return FakeApiResponse(200, content=f.content, headers={"content-type": f.mime_type})
                return FakeApiResponse(200, _public_meta(f))
            if req.method == "POST" and path == "/files":
                meta = req.json or {}
                fid = self._next_id("f")
                props = {str(k): str(v) for k, v in (meta.get("appProperties") or {}).items()}
                props["_created_by_tilo"] = "1"
                f = _File(
                    fid,
                    str(meta.get("name", "")),
                    str(meta.get("mimeType", "")),
                    list(meta.get("parents") or ["root"]),
                    None,
                    props,
                )
                self.files[fid] = f
                return FakeApiResponse(200, _public_meta(f))
        return _error(404, "NOT_FOUND")

    def _drive_upload(self, req: Req) -> FakeApiResponse:
        if req.method != "POST" or req.params.get("uploadType") != "multipart":
            return _error(400, "INVALID_ARGUMENT")
        ctype = req.headers.get("content-type", "")
        if not ctype.startswith("multipart/related") or req.content is None:
            return _error(400, "INVALID_ARGUMENT")
        parsed = email.message_from_bytes(
            b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + req.content, policy=email.policy.default
        )
        parts = list(parsed.iter_parts()) if parsed.is_multipart() else []
        if len(parts) != 2:
            return _error(400, "INVALID_ARGUMENT")
        meta = jsonlib.loads(parts[0].get_payload(decode=True).decode("utf-8"))
        data = parts[1].get_payload(decode=True) or b""
        native = _NATIVE_SOURCE.get(str(meta.get("mimeType", "")))
        if native is not None and parts[1].get_content_type() != native:  # Drive converts only the matching OOXML
            return _error(400, "INVALID_ARGUMENT")
        with self._lock:
            fid = self._next_id("f")
            props = {str(k): str(v) for k, v in (meta.get("appProperties") or {}).items()}
            props["_created_by_tilo"] = "1"
            f = _File(
                fid,
                str(meta.get("name", "")),
                str(meta.get("mimeType", "")),
                list(meta.get("parents") or ["root"]),
                data,
                props,
            )
            self.files[fid] = f
        return FakeApiResponse(200, _public_meta(f))


def _public_meta(f: _File) -> dict:
    meta = f.meta()
    props = {k: v for k, v in (meta.get("appProperties") or {}).items() if not k.startswith("_")}
    meta.pop("appProperties", None)
    if props:
        meta["appProperties"] = props
    return meta


_APP_PROP = re.compile(r"appProperties\s+has\s+\{\s*key\s*=\s*'([^']*)'\s+and\s+value\s*=\s*'([^']*)'\s*\}", re.I)


def _drive_query(f: _File, q: str) -> bool:
    """The clauses API_FR_CON_04_05.md lists; anything else is a 400 (ValueError here)."""
    props = {k: v for k, v in f.app_properties.items() if not k.startswith("_")}
    for key, value in _APP_PROP.findall(q):
        if props.get(key) != value:
            return False
    rest = _APP_PROP.sub("APP_PROPERTY_CLAUSE", q)  # already checked above
    for clause in re.split(r"\s+and\s+", rest.strip(), flags=re.I):
        clause = clause.strip()
        if not clause or clause == "APP_PROPERTY_CLAUSE":
            continue
        if m := re.fullmatch(r"'([^']+)'\s+in\s+parents", clause):
            if m.group(1) not in f.parents:
                return False
        elif m := re.fullmatch(r"mimeType\s*(=|!=)\s*'([^']+)'", clause):
            if (f.mime_type == m.group(2)) != (m.group(1) == "="):
                return False
        elif m := re.fullmatch(r"trashed\s*=\s*(true|false)", clause, flags=re.I):
            if f.trashed != (m.group(1).lower() == "true"):
                return False
        elif m := re.fullmatch(r"name\s*=\s*'((?:[^'\\]|\\.)*)'", clause):
            if f.name != m.group(1).replace("\\'", "'").replace("\\\\", "\\"):
                return False
        else:
            raise ValueError(f"unsupported Drive query clause: {clause!r}")
    return True


# ---------------------------------------------------------------------------
# MIME helpers


def parse_raw(raw: bytes) -> EmailMessage:
    return email.message_from_bytes(raw, policy=email.policy.default)  # type: ignore[return-value]


def _text_of(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain",))
    return part.get_content() if part is not None else ""


def _payload(part: EmailMessage) -> dict:
    headers = [{"name": k, "value": str(v)} for k, v in part.items()]
    if part.is_multipart():
        return {
            "mimeType": part.get_content_type(),
            "filename": "",
            "headers": headers,
            "body": {"size": 0},
            "parts": [_payload(p) for p in part.iter_parts()],
        }
    data = part.get_payload(decode=True) or b""
    filename = part.get_filename() or ""
    body: dict[str, Any] = {"size": len(data)}
    if filename:
        body["attachmentId"] = "att" + hashlib.sha256(data).hexdigest()[:16]
    else:
        body["data"] = b64url(data)
    return {"mimeType": part.get_content_type(), "filename": filename, "headers": headers, "body": body}


def recipients_of(msg: EmailMessage) -> set[str]:
    """Every address the message reaches: To, Cc and Bcc."""
    values = [str(v) for h in ("To", "Cc", "Bcc") for v in (msg.get_all(h) or [])]
    return {addr.lower() for _, addr in email.utils.getaddresses(values) if addr}


# ---------------------------------------------------------------------------
# Artifacts and the scope spy


class FakeArtifacts:
    def __init__(self) -> None:
        self._items: dict[tuple[str, int], dict] = {}

    def put_email(
        self,
        artifact_id: str,
        version: int = 1,
        *,
        subject: str = "Re: Delivery date",
        body_text: str = "Thursday works.",
    ) -> dict:
        self._items[(artifact_id, version)] = {"kind": "email", "subject": subject, "body_text": body_text}
        return {"artifact_id": artifact_id, "version": version}

    def put_file(
        self,
        artifact_id: str,
        version: int = 1,
        *,
        name: str = "report.pdf",
        mime_type: str = "application/pdf",
        content: bytes = b"%PDF-1.7 fake report",
    ) -> dict:
        self._items[(artifact_id, version)] = {"kind": "file", "name": name, "mime_type": mime_type, "content": content}
        return {"artifact_id": artifact_id, "version": version}

    def get(self, artifact_id: str, version: int) -> dict:
        return copy.deepcopy(self._items[(artifact_id, version)])


class ScopeSpy:
    """Delegates to the TokenBroker; records the required_scopes of every access_token_for_adapter."""

    def __init__(self, broker: Any) -> None:
        self._broker = broker
        self.asked: list[tuple[str, str, tuple[str, ...]]] = []

    def access_token_for_adapter(
        self, user_id: str, connector: str, *, required_scopes: Iterable[str], **kw: Any
    ) -> str:
        scopes = tuple(required_scopes)
        self.asked.append((user_id, connector, scopes))
        return self._broker.access_token_for_adapter(user_id, connector, required_scopes=scopes, **kw)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._broker, name)


# ---------------------------------------------------------------------------
# Wiring


@dataclass
class GEnv:
    env: Env
    apis: FakeGoogleApis
    artifacts: FakeArtifacts
    spy: ScopeSpy
    picks: Any
    gmail: Any
    drive: Any
    outbox: Any
    store: Any
    sleeps: list[float]

    @property
    def emitted(self) -> list[dict]:
        return self.env.emitted

    def parts_of(self, event_type: str) -> list[dict]:
        return self.env.parts_of(event_type)

    def new_outbox(self) -> tuple[Any, Any, Any]:
        """A second tilo-connectors instance on the same store and the same Google: fresh adapters."""
        from tilo_connectors.outbox import Outbox

        gmail, drive = _adapters(self.env, self.spy, self.apis, self.artifacts, self.picks, self.sleeps)
        return (
            Outbox(
                self.store, {"gmail": gmail, "google_drive": drive}, emit=self.env.emitted.append, clock=self.env.clock
            ),
            gmail,
            drive,
        )


def _adapters(
    env: Env, spy: ScopeSpy, apis: FakeGoogleApis, artifacts: FakeArtifacts, picks: Any, sleeps: list[float], **kw: Any
):
    from tilo_connectors.adapters import DriveAdapter, GmailAdapter

    common = {
        "broker": spy,
        "transport": apis,
        "artifacts": artifacts,
        "owner_of": lambda world_id: OWNER,
        "clock": env.clock,
        "emit": env.emitted.append,
        "sleep": sleeps.append,
    }
    gmail_kw = {k: v for k, v in kw.items() if k in ("max_attempts", "max_attachment_bytes")}
    drive_kw = {k: v for k, v in kw.items() if k in ("max_attempts", "max_download_bytes")}
    gmail = GmailAdapter(declaration=gmail_decl(), **common, **gmail_kw)
    drive = DriveAdapter(declaration=drive_file_decl(), picks=picks, **common, **drive_kw)
    return gmail, drive


def make_gapi_env(
    *, gmail_scopes: list[str] | None = GMAIL_ALL, drive_scopes: list[str] | None = DRIVE_ALL, **adapter_kw: Any
) -> GEnv:
    from tilo_connectors.adapters import InMemoryPicks
    from tilo_connectors.outbox import Outbox
    from tilo_connectors.store import InMemoryOutboxStore

    env = make_env()
    if gmail_scopes is not None:
        env.connect(OWNER, "gmail", list(gmail_scopes))
    if drive_scopes is not None:
        env.connect(OWNER, "google_drive", list(drive_scopes))
    apis = FakeGoogleApis(env.google)
    artifacts = FakeArtifacts()
    spy = ScopeSpy(env.broker)
    picks = InMemoryPicks()
    sleeps: list[float] = []
    gmail, drive = _adapters(env, spy, apis, artifacts, picks, sleeps, **adapter_kw)
    store = InMemoryOutboxStore()
    outbox = Outbox(store, {"gmail": gmail, "google_drive": drive}, emit=env.emitted.append, clock=env.clock)
    return GEnv(env, apis, artifacts, spy, picks, gmail, drive, outbox, store, sleeps)


# ---------------------------------------------------------------------------
# Outbox cases (gate-authorised; tilo_policy.check_entry accepts each shape)

_SEQ = iter(range(9200, 9999))


def next_outbox_id() -> str:
    return f"01JB5VQ000000000000000{next(_SEQ):04d}"


def gmail_case(
    *,
    action_type: str = "send_email",
    item: dict,
    destination: str | None = None,
    recipients: tuple[str, ...] = (SUPPLIER,),
    attachments: list[dict] | None = None,
    idempotency_key: str | None = None,
) -> dict:
    tier = "T1" if action_type == "create_draft" else "T2"
    outbox_id = next_outbox_id()
    case = gate_case(
        outbox_id=outbox_id,
        idempotency_key=idempotency_key or f"r_village_basic_1:U2:{action_type}:{outbox_id[-4:]}",
        connector="gmail",
        action_type=action_type,
        recipients=recipients,
        destination=destination or "placeholder",
        item=item,
        risk_tier=tier,
    )
    case["entry"]["destination"] = destination
    if attachments:  # an attachment makes the entry T3 (OB-04): a person approves on the web
        case["entry"]["attachments"] = list(attachments)
        case["entry"]["modifiers"] = ["attachments"]
        case["entry"]["risk_tier"] = "T3"
        case["reserved_by"]["data"]["risk_tier"] = "T3"
        case["authorised_by"]["data"]["channel"] = "web"
    return case


def drive_case(
    *,
    item: dict,
    destination: str | None = None,
    idempotency_key: str | None = None,
    action_type: str = "save_file",
) -> dict:
    outbox_id = next_outbox_id()
    case = gate_case(
        outbox_id=outbox_id,
        idempotency_key=idempotency_key or f"r_village_basic_1:U3:{action_type}:{outbox_id[-4:]}",
        connector="google_drive",
        action_type=action_type,
        recipients=(),
        destination=destination or "placeholder",
        item=item,
        risk_tier="T1",
    )
    case["entry"]["destination"] = destination
    return case


def enqueue(outbox: Any, case: dict) -> dict:
    from _connectors_lib import evidence_from_case

    return outbox.enqueue(copy.deepcopy(case["entry"]), evidence_from_case(case))


def log_text(caplog: Any) -> str:
    """Everything the log records hold: messages, args and formatted exceptions."""
    out = []
    for record in caplog.records:
        out.append(record.getMessage())
        out.append(repr(record.args))
        if record.exc_info:
            import traceback

            out.append("".join(traceback.format_exception(*record.exc_info)))
        if record.exc_text:
            out.append(record.exc_text)
    return "\n".join(out)
