"""Gmail watch, history and profile endpoints for the FR-CHN-08 adapter tests.
API: services/channels/tests/API_FR_CHN_08.md "GmailAdapter (connectors side)".

A subclass of `_gapi_lib.FakeGoogleApis` (same Transport seam, same token check, same failure injection)
that adds users.watch, users.stop, users.history.list and users.getProfile, and an INBOX label filter on
users.messages.list. No production code; no network; every token comes from the FakeGoogle double.
"""

from __future__ import annotations

import threading
from typing import Any

from _gapi_lib import (
    GMAIL_ALL,
    FakeApiResponse,
    FakeArtifacts,
    FakeGoogleApis,
    GEnv,
    Req,
    ScopeSpy,
    _adapters,
    _error,
)
from _oauth_lib import OWNER, make_env

TOPIC = "projects/demo-tilo/topics/gmail-push"
WATCH_TTL_MS = 7 * 86400 * 1000


class FakeGmailWatchApis(FakeGoogleApis):
    def __init__(self, google: Any, *, now_ms: int = 1_790_931_600_000) -> None:
        super().__init__(google)
        self.now_ms = now_ms
        self.current_history = 5000
        self.history_floor = 0
        self.history_page_size = 100
        self.records: list[tuple[int, str, str, list[str]]] = []  # (history id, message id, thread id, labels)
        self.watching: dict[str, Any] | None = None
        self._hlock = threading.RLock()

    def arrive(self, *, thread_id: str, labels: tuple[str, ...] = ("INBOX", "UNREAD"), **seed: Any) -> dict:
        """New mail: a stored message plus a messageAdded history record."""
        seeded = self.seed_message(thread_id=thread_id, labels=labels, **seed)
        with self._hlock:
            self.current_history += 7
            if "INBOX" in labels:
                self.records.append((self.current_history, seeded["id"], thread_id, list(labels)))
        return seeded

    def expire_history(self) -> None:
        with self._hlock:
            self.history_floor = self.current_history

    def _gmail(self, req: Req, path: str) -> FakeApiResponse:
        with self._hlock:
            if req.method == "POST" and path == "/watch":
                body = req.json or {}
                if not isinstance(body.get("topicName"), str):
                    return _error(400, "INVALID_ARGUMENT")
                self.watching = dict(body)
                return FakeApiResponse(
                    200, {"historyId": str(self.current_history), "expiration": str(self.now_ms + WATCH_TTL_MS)}
                )
            if req.method == "POST" and path == "/stop":
                self.watching = None
                return FakeApiResponse(204, None)
            if req.method == "GET" and path == "/profile":
                return FakeApiResponse(
                    200,
                    {
                        "emailAddress": "owner@example.com",
                        "messagesTotal": len(self.messages),
                        "threadsTotal": 0,
                        "historyId": str(self.current_history),
                    },
                )
            if req.method == "GET" and path == "/history":
                return self._history(req)
            if req.method == "GET" and path == "/messages" and req.params.get("labelIds"):
                labels = req.params["labelIds"]
                labels = [labels] if isinstance(labels, str) else list(labels)
                limit = int(req.params.get("maxResults", 100))
                newest = [r for r in reversed(self.records) if set(labels) <= set(r[3])][:limit]
                return FakeApiResponse(
                    200,
                    {"messages": [{"id": r[1], "threadId": r[2]} for r in newest], "resultSizeEstimate": len(newest)},
                )
        return super()._gmail(req, path)

    def _history(self, req: Req) -> FakeApiResponse:
        start = str(req.params.get("startHistoryId", ""))
        if not start.isdigit():
            return _error(400, "INVALID_ARGUMENT")
        if int(start) < self.history_floor:
            return _error(404, "NOT_FOUND")
        label = req.params.get("labelId")
        added = [r for r in self.records if r[0] > int(start) and (label is None or label in r[3])]
        offset = int(str(req.params.get("pageToken") or "h0")[1:])
        page = added[offset : offset + self.history_page_size]
        history = [
            {
                "id": str(hid),
                "messages": [{"id": mid, "threadId": tid}],
                "messagesAdded": [{"message": {"id": mid, "threadId": tid, "labelIds": list(labels)}}],
            }
            for hid, mid, tid, labels in page
        ]
        body: dict[str, Any] = {"historyId": str(self.current_history)}
        if history:
            body["history"] = history
        if offset + self.history_page_size < len(added):
            body["nextPageToken"] = f"h{offset + self.history_page_size}"
        return FakeApiResponse(200, body)


def make_watch_env(*, gmail_scopes: list[str] | None = None) -> tuple[GEnv, FakeGmailWatchApis]:
    """make_gapi_env, with the watch-capable Gmail fake behind the adapters."""
    from tilo_connectors.adapters import InMemoryPicks
    from tilo_connectors.outbox import Outbox
    from tilo_connectors.store import InMemoryOutboxStore

    env = make_env()
    env.connect(OWNER, "gmail", list(gmail_scopes if gmail_scopes is not None else GMAIL_ALL))
    apis = FakeGmailWatchApis(env.google)
    artifacts = FakeArtifacts()
    spy = ScopeSpy(env.broker)
    picks = InMemoryPicks()
    sleeps: list[float] = []
    gmail, drive = _adapters(env, spy, apis, artifacts, picks, sleeps)
    store = InMemoryOutboxStore()
    outbox = Outbox(store, {"gmail": gmail, "google_drive": drive}, emit=env.emitted.append, clock=env.clock)
    return GEnv(env, apis, artifacts, spy, picks, gmail, drive, outbox, store, sleeps), apis
