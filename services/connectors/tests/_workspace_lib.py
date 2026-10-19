"""WORKSPACE_TOOLS ticket A test double: Gmail, Calendar and Drive behind one Transport (ADR-0048). No network.

`FakeWorkspace.request` is the whole surface the adapters use. It records every request, answers what the test seeded
and nothing else. Mail, event and file text are runtime sentinels; no token is ever seeded here.
"""

from __future__ import annotations

import re
from typing import Any

from _gapi_lib import FakeApiResponse, b64url

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE = "https://www.googleapis.com/drive/v3"
EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GAPPS = "application/vnd.google-apps."


def header_list(**headers: str) -> list[dict[str, str]]:
    return [{"name": k.replace("_", "-"), "value": v} for k, v in headers.items()]


def text_part(text: str, mime: str = "text/plain") -> dict[str, Any]:
    return {"mimeType": mime, "body": {"data": b64url(text.encode()), "size": len(text)}}


def file_part(name: str, mime: str, size: int) -> dict[str, Any]:
    return {"mimeType": mime, "filename": name, "body": {"attachmentId": "att1", "size": size}}


class FakeWorkspace:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
        self.messages: dict[str, dict[str, Any]] = {}  # id -> full resource
        self.events: list[dict[str, Any]] = []
        self.files: dict[str, dict[str, Any]] = {}  # id -> {meta, content, exports}
        self.status: int | None = None  # every request answers this status
        self.retry_after: str | None = None

    def add_message(
        self, mid: str, payload: dict[str, Any], labels: tuple[str, ...] = ("INBOX",), snippet: str = ""
    ) -> None:
        self.messages[mid] = {
            "id": mid, "threadId": "t" + mid, "labelIds": list(labels), "snippet": snippet, "payload": payload,
        }  # fmt: skip

    def add_file(self, fid: str, name: str, mime: str, content: bytes = b"", **meta: Any) -> None:
        self.files[fid] = {
            "meta": {"id": fid, "name": name, "mimeType": mime, "modifiedTime": "2026-10-10T08:00:00.000Z", **meta},
            "content": content,
        }  # fmt: skip

    def seen(self, needle: str) -> list[tuple[str, str, dict[str, Any], dict[str, Any]]]:
        return [r for r in self.requests if needle in r[1]]

    def request(self, method: str, url: str, *, params: Any = None, headers: Any = None, json: Any = None,
                content: Any = None) -> Any:  # fmt: skip
        params = dict(params or {})
        self.requests.append((method, url, params, dict(headers or {})))
        if self.status is not None:
            extra = {"retry-after": self.retry_after} if self.retry_after else None
            return FakeApiResponse(self.status, {"error": {"code": self.status}}, headers=extra)
        if url.startswith(GMAIL):
            return self._gmail(url[len(GMAIL) :], params)
        if url.startswith(EVENTS):
            return FakeApiResponse(200, {"items": list(self.events)})
        if url.startswith(DRIVE):
            return self._drive(url[len(DRIVE) :], params, headers or {})
        raise AssertionError(f"unexpected request {url}")

    def _gmail(self, path: str, params: dict[str, Any]) -> Any:
        if path == "/messages":
            ids = list(self.messages)[: int(params.get("maxResults", 100))]
            return FakeApiResponse(200, {"messages": [{"id": i, "threadId": "t" + i} for i in ids]})
        found = self.messages.get(path.removeprefix("/messages/"))
        if found is None:
            return FakeApiResponse(404, {"error": {"code": 404}})
        if params.get("format") == "metadata":
            wanted = {h.lower() for h in params.get("metadataHeaders", [])}
            payload = {"headers": [h for h in found["payload"]["headers"] if h["name"].lower() in wanted]}
            return FakeApiResponse(200, {**found, "payload": payload})
        return FakeApiResponse(200, found)

    def _drive(self, path: str, params: dict[str, Any], headers: dict[str, Any]) -> Any:
        if path == "/files":
            return FakeApiResponse(200, {"files": [f["meta"] for f in self.files.values()]})
        match = re.fullmatch(r"/files/([^/]+)(/export)?", path)
        found = self.files.get(match.group(1)) if match else None
        if found is None:
            return FakeApiResponse(404, {"error": {"code": 404}})
        if match.group(2) or params.get("alt") == "media":  # type: ignore[union-attr]
            return FakeApiResponse(200, content=found["content"])
        return FakeApiResponse(200, found["meta"])
