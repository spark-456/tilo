"""Test doubles for FR-CHN-13 (threaded send via Gmail through the outbox, exactly once). The API they drive is
pinned in API_FR_CHN_13.md.

Nothing here is production logic. The send path under test is the real one end to end: the FR-CHN-10 `Drafter`
(scripted model), the FR-CHN-11 `Autopilot`, the real `tilo_connectors.Outbox` over its `InMemoryOutboxStore`, and the
real `tilo_connectors.adapters.GmailAdapter`. Only these are doubles:

- `FakeGmailApi`: the Gmail REST endpoints behind the adapter's injected `Transport` seam. It serves the test thread
  as Gmail metadata, answers the adapter's earlier-attempt search (`rfc822msgid:... in:sent`), and records every
  `messages/send`. Faults on demand for the next send: a 503 (nothing sent), a dropped request (nothing sent), a lost
  answer after Gmail accepted it, or a process death right after Gmail accepted it. No network, no real mail.
- `FakeBroker`: hands the adapter an access token assembled at runtime (never a real or real-looking token).
- `LazyDraftArtifacts`: resolves the new `tilo_channels.autopilot_send.DraftArtifacts` at call time, so a missing
  module fails the test that sends, not the import of this file.
- `outbox_skips_ob01_evidence()`: the autopilot's OB-01 evidence wiring is not built yet (BQ-158, BQ-184), so the real
  outbox's `tilo_policy.check_entry` is replaced by an accept-all for these tests only. Schema (OB-04), fresh-state
  (OB-02) and idempotency-key (OB-03) checks of the real outbox still run.

Addresses are fictional `.example` domains.
"""

from __future__ import annotations

import base64
import contextlib
import copy
import email
import email.policy
import email.utils
import functools
import importlib
import json as jsonlib
import secrets
import threading
import unittest.mock
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import tilo_policy
import yaml
from _chn10_lib import USER, Msg, Thread, answer, make_rig, message_id_header
from _chn11_lib import (
    BENIGN,
    DAVID,
    MAILBOX,
    Bench,
    EventLog,
    FakeContacts,
    FakePolicy,
    MemoryDraftStore,
    autopilot_module,
    context,
)
from _chn_contracts_lib import REPO_ROOT
from tilo_connectors import InMemoryOutboxStore, Outbox
from tilo_connectors.adapters import GMAIL_API, GmailAdapter, TransportError

__all__ = ["BENIGN", "DAVID", "MAILBOX", "USER", "Msg", "Thread", "answer", "context", "message_id_header"]

REFERENCES = "<a1-earlier@mail.example> <a2-earlier@mail.example>"


def send_module() -> Any:
    """Imported at call time so a missing module fails the test, not collection."""
    return importlib.import_module("tilo_channels.autopilot_send")


def needs_send_module(test: Callable[..., Any]) -> Callable[..., Any]:
    """A missing `tilo_channels.autopilot_send` fails once, before Hypothesis generates or shrinks anything."""

    @functools.wraps(test)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        send_module()
        return test(*args, **kwargs)

    return wrapper


def iso(seconds: float) -> str:
    ms = round(seconds * 1000)
    return datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{ms % 1000:03d}Z"


@contextlib.contextmanager
def outbox_skips_ob01_evidence() -> Iterator[None]:
    """BQ-184: accept-all in place of `tilo_policy.check_entry` while the FR-CHN-13 tests run."""
    with unittest.mock.patch.object(tilo_policy, "check_entry", lambda case, table=None: None):
        yield


def gmail_declaration() -> dict[str, Any]:
    connectors = yaml.safe_load((REPO_ROOT / "config" / "connectors.yaml").read_text(encoding="utf-8"))
    return next(c for c in connectors if c["id"] == "gmail")


class SimulatedCrash(BaseException):
    """A process death (SIGKILL, OOM) in the middle of a send: not an Exception, so nothing catches it as one."""


class FakeBroker:
    def __init__(self) -> None:
        self.token = "-".join(["fake", "gmail", "access", secrets.token_hex(12)])  # assembled at runtime
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def access_token_for_adapter(
        self, user_id: str, adapter_id: str, *, required_scopes: Sequence[str], force_refresh: bool = False
    ) -> str:
        self.calls.append((user_id, adapter_id, tuple(required_scopes)))
        return self.token


@dataclass
class FakeResponse:
    status_code: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def content(self) -> bytes:
        return jsonlib.dumps(self.body).encode()

    def json(self) -> Any:
        return copy.deepcopy(self.body)


@dataclass
class SentMail:
    """One message Gmail accepted on `messages/send`."""

    id: str
    thread_id: str | None
    raw: bytes
    at: float  # the fake clock when Gmail accepted it

    def message(self) -> EmailMessage:
        parsed = email.message_from_bytes(self.raw, policy=email.policy.default)
        assert isinstance(parsed, EmailMessage)
        return parsed

    def header(self, name: str) -> str | None:
        value = self.message()[name]
        return None if value is None else str(value)

    def addresses(self, *names: str) -> list[str]:
        values = [str(v) for n in names for v in (self.message().get_all(n) or [])]
        return [addr for _, addr in email.utils.getaddresses(values) if addr]

    def body(self) -> str:
        part = self.message().get_body(preferencelist=("plain",))
        assert part is not None, "the sent mail has no text/plain body"
        return str(part.get_content()).replace("\r\n", "\n")  # CRLF is the wire's line ending (RFC 5322)


class FakeGmailApi:
    """The Gmail endpoints the adapter's send path calls; thread-safe; records everything."""

    def __init__(self, clock: Any, broker: FakeBroker) -> None:
        self._clock, self._broker = clock, broker
        self._threads: dict[str, list[dict[str, Any]]] = {}
        self.sent: list[SentMail] = []
        self.requests: list[tuple[str, str]] = []
        self.faults: list[str] = []  # for the next sends: "unavailable" | "dropped" | "lost" | "crash"
        self._lock = threading.Lock()

    def add_thread(self, thread: Thread) -> None:
        with self._lock:
            self._threads[thread.thread_id] = [_metadata(thread.thread_id, m) for m in thread.messages]

    def fault(self, *kinds: str) -> None:
        with self._lock:
            self.faults += list(kinds)

    def clear_faults(self) -> None:
        with self._lock:
            self.faults.clear()

    def sent_in(self, thread_id: str) -> list[SentMail]:
        with self._lock:
            return [m for m in self.sent if m.thread_id == thread_id]

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
    ) -> FakeResponse:
        crash = None
        with self._lock:
            self.requests.append((method, url))
            if (headers or {}).get("authorization") != f"Bearer {self._broker.token}":
                return FakeResponse(401, {"error": "unauthenticated"})
            if not url.startswith(GMAIL_API):
                return FakeResponse(404, {"error": "not found"})
            path = url[len(GMAIL_API) :]
            if method == "GET" and path == "/messages":
                return FakeResponse(200, {"messages": self._search(str((params or {}).get("q", "")))})
            if method == "GET" and path.startswith("/threads/"):
                messages = self._threads.get(path[len("/threads/") :])
                if messages is None:
                    return FakeResponse(404, {"error": "no such thread"})
                return FakeResponse(200, {"id": path[len("/threads/") :], "messages": copy.deepcopy(messages)})
            if method == "GET" and path.startswith("/messages/"):  # one message by its Gmail id (FR-PA-07 reads)
                wanted = path[len("/messages/") :]
                found = next((m for messages in self._threads.values() for m in messages if m["id"] == wanted), None)
                if found is None:
                    return FakeResponse(404, {"error": "no such message"})
                return FakeResponse(200, copy.deepcopy(found))
            if method != "POST" or path != "/messages/send":
                return FakeResponse(400, {"error": "FR-CHN-13 fake: unexpected Gmail call"})
            fault = self.faults.pop(0) if self.faults else None
            if fault == "unavailable":
                return FakeResponse(503, {"error": "backend error"})
            if fault == "dropped":
                raise TransportError("the request never reached Gmail")
            body = json if isinstance(json, dict) else {}
            raw = base64.urlsafe_b64decode(str(body.get("raw", "")))
            thread_id = body.get("threadId")
            if thread_id is not None and thread_id not in self._threads:
                return FakeResponse(404, {"error": "no such thread"})
            mail = SentMail(id="s" + secrets.token_hex(8), thread_id=thread_id, raw=raw, at=self._clock())
            self.sent.append(mail)
            if thread_id is not None:
                self._threads[thread_id].append(_sent_metadata(mail))
            answer_body = {"id": mail.id, "threadId": thread_id or mail.id, "labelIds": ["SENT"]}
            if fault == "lost":
                raise TransportError("Gmail sent it, but the answer was lost")
            if fault == "crash":
                crash = SimulatedCrash("the dispatcher died right after Gmail accepted the send")
        if crash is not None:
            raise crash
        return FakeResponse(200, answer_body)

    def _search(self, query: str) -> list[dict[str, str]]:
        words = query.split()
        wanted = [w.split(":", 1)[1] for w in words if w.startswith("rfc822msgid:")]
        if not wanted:
            return []
        hits = [m for m in self.sent if (m.header("Message-ID") or "").strip().strip("<>") == wanted[0]]
        return [{"id": m.id, "threadId": m.thread_id or m.id} for m in hits]


def _metadata(thread_id: str, msg: Msg) -> dict[str, Any]:
    headers = {
        "From": msg.sender,
        "To": ", ".join(msg.to),
        "Cc": ", ".join(msg.cc),
        "Subject": msg.subject,
        "Message-ID": message_id_header(msg.message_id),
        **msg.headers,
    }
    own = MAILBOX in msg.sender.lower()
    return {
        "id": msg.message_id,
        "threadId": thread_id,
        "labelIds": ["SENT"] if own else ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": k, "value": v} for k, v in headers.items() if v],
            "body": {"data": base64.urlsafe_b64encode(msg.body.encode()).decode()},
        },
    }


def _sent_metadata(mail: SentMail) -> dict[str, Any]:
    names = ("To", "Cc", "Subject", "Message-ID", "In-Reply-To", "References")
    headers = [{"name": "From", "value": MAILBOX}]
    headers += [{"name": n, "value": v} for n in names if (v := mail.header(n))]
    return {"id": mail.id, "threadId": mail.thread_id, "labelIds": ["SENT"], "payload": {"headers": headers}}


class LazyDraftArtifacts:
    """The adapter's ArtifactSource: a `DraftArtifacts` over the card store, built on first use."""

    def __init__(self, cards: Any) -> None:
        self._cards = cards
        self.calls: list[tuple[str, int]] = []

    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        self.calls.append((artifact_id, version))
        return send_module().DraftArtifacts(cards=self._cards).get(artifact_id, version)


@dataclass
class Line:
    """One send line: drafter, autopilot, outbox store, Gmail. `new_outbox()` is another tilo-connectors instance
    (its own Outbox and GmailAdapter) over the same store and the same mailbox."""

    bench: Bench
    store: InMemoryOutboxStore
    api: FakeGmailApi
    broker: FakeBroker
    transfers: list[dict] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)
    outbox: Any = None

    @property
    def ap(self) -> Any:
        return self.bench.ap

    @property
    def clock(self) -> Any:
        return self.bench.rig.clock

    def new_outbox(self) -> Outbox:
        adapter = GmailAdapter(
            declaration=gmail_declaration(),
            broker=self.broker,
            transport=self.api,
            artifacts=LazyDraftArtifacts(self.bench.cards),
            owner_of=lambda world_id: USER,
            clock=lambda: iso(self.clock()),
            emit=lambda part: None,
            sleep=lambda seconds: None,
        )
        return Outbox(
            self.store,
            {"gmail": adapter},
            self.transfers.append,
            lambda: iso(self.clock()),
            alert=self.alerts.append,
        )

    def dispatch(self, outbox: Outbox | None = None) -> list[dict]:
        send_module()  # the artifact source the adapter reads is FR-CHN-13's: missing, the test fails here
        return (outbox or self.outbox).dispatch_due()

    def storm(self, ticks: int = 25, *outboxes: Outbox) -> None:
        for n in range(ticks):
            choices = outboxes or (self.outbox,)
            self.dispatch(choices[n % len(choices)])

    def advance(self, seconds: float) -> None:
        self.clock.advance(seconds)

    def thread(self, *, references: str = REFERENCES, answers: Sequence[Any] = (), **kw: Any) -> Thread:
        """A thread in both the quarantined reader (drafting) and the mailbox (sending); the last message is David's
        and carries a References chain."""
        headers = {"References": references} if references else {}
        answers = tuple(answers) or (answer(BENIGN),)
        thread, _ = self.bench.rig.thread(headers=headers, answers=answers, **kw)
        self.api.add_thread(thread)
        return thread

    def draft(self, thread: Thread, *, mode: str = "reply", instruction: str | None = None) -> tuple[Any, Any]:
        """Drafts through the real FR-CHN-10 Drafter (so the draft store holds it): (DraftContext, DraftResult)."""
        kw = {"instruction": instruction} if instruction else {}
        ctx = context(thread, mode=mode, **kw)
        result = self.bench.rig.svc.draft(
            USER,
            instruction_id=ctx.instruction_id,
            thread_id=thread.thread_id,
            instruction=ctx.instruction,
            mailbox=MAILBOX,
            mode=mode,
        )
        assert result.status == "ready", f"FR-CHN-13 test setup: the draft must be ready, got {result.status}"
        return ctx, result

    def entries(self) -> list[dict]:
        return self.store.all_entries()

    def transfers_of(self, outbox_id: str) -> list[dict]:
        return [t for t in self.transfers if t["data"]["outbox_id"] == outbox_id]


def make_line(level: str = "L2", contacts: Sequence[str] = ()) -> Line:
    rig = make_rig()
    broker = FakeBroker()
    line = Line(bench=None, store=InMemoryOutboxStore(), api=FakeGmailApi(rig.clock, broker), broker=broker)  # type: ignore[arg-type]
    cards = MemoryDraftStore()
    bench = Bench(rig, None, FakePolicy(level), FakeContacts(contacts), cards, EventLog())  # type: ignore[arg-type]
    line.bench = bench
    line.outbox = line.new_outbox()
    bench.outbox = line.outbox
    bench.ap = bench.new_autopilot()
    return line


def card_entry(line: Line) -> dict:
    entries = line.entries()
    assert len(entries) == 1, f"expected the card's one outbox entry, found {len(entries)}"
    return entries[0]


def autopilot() -> Any:
    return autopilot_module()
