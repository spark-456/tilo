"""Test doubles and builders for FR-CHN-08 (Gmail push watch with polling fallback). API_FR_CHN_08.md.

Package-unique module name (same reason as `_channels_lib.py`). Nothing here is production logic: every
class is a fake for an injected dependency of `tilo_channels.gmail_watch` (the mailbox seam the Gmail
adapter fills in production, the watch-state store, the OIDC verifier, the triage step, the event
writer) or a builder of a Pub/Sub push request. The latency driver at the end is a discrete-event loop
on the fake clock: no sleeps, no network, no paid calls.

No real addresses, tokens or secrets: addresses are at example.com, tokens are assembled at runtime.
"""

from __future__ import annotations

import base64
import copy
import heapq
import itertools
import json
import math
import random
import secrets
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from _channels_lib import T0, FakeClock

DAY_S = 86400
WATCH_TTL_S = 7 * DAY_S  # Gmail expires a users.watch registration after 7 days (Gmail API docs)
TRIAGE_P95_S = 60.0  # PRD 11.6 FR-CHN-08 and NFR-08: new mail -> triaged <= 60 s p95
RESYNC_CAP = 50  # API_FR_CHN_08.md: RESYNC_MAX_MESSAGES, = config/connectors.yaml gmail limits.batch_size

TOPIC = "projects/demo-tilo/topics/gmail-push"
SUBSCRIPTION = "projects/demo-tilo/subscriptions/gmail-push"
AUDIENCE = "https://channels.tilo.test/gmail/push"
PUSH_SA = "gmail-push@demo-tilo.iam.gserviceaccount.com"
GOOGLE_ISSUER = "https://accounts.google.com"

RIYA, SAM, KAI = "u_riya", "u_sam", "u_kai"
ADDRESS = {RIYA: "riya@example.com", SAM: "sam@example.com", KAI: "kai@example.com"}
USER_FOR_ADDRESS = {a: u for u, a in ADDRESS.items()}


# ---------------------------------------------------------------------------
# The mailbox seam (the GmailAdapter in production; API_FR_CHN_08.md "Mailbox")


class HistoryGone(Exception):
    """What the Gmail adapter raises when Google answers 404 to history.list: the startHistoryId is
    older than the history Gmail keeps. Same shape as tilo_connectors AdapterError: `.status == 404`."""

    def __init__(self) -> None:
        super().__init__("Google answered 404")
        self.status = 404


class Unavailable(Exception):
    """A transient Google failure (the adapter's ProviderUnavailable after its own retries)."""

    def __init__(self) -> None:
        super().__init__("Google answered 503")
        self.status = 503


@dataclass
class Mail:
    user_id: str
    message_id: str
    history_id: int
    arrived_at: float


@dataclass
class _Box:
    inbox: list[Mail] = field(default_factory=list)
    current: int = 1000  # the mailbox's current history id
    floor: int = 0  # history.list with a start below this answers 404
    expires_at: float | None = None  # the active watch's expiration (unix s), None when not watching
    topic: str | None = None


@dataclass(frozen=True)
class Call:
    method: str
    user_id: str
    args: dict[str, Any]
    at: float


class FakeMailbox:
    """Per-user Gmail history, watch registrations and the calls made against them.

    `list_history` answers like Gmail's users.history.list with historyTypes=messageAdded and
    labelId=INBOX: the INBOX messages added after `start_history_id`, oldest first, `page_size` per
    page, and the mailbox's current history id. `repeat_ids` lists each id twice, as Gmail does when a
    message appears in more than one history record. Each call advances the fake clock by `latency_s`.
    """

    def __init__(self, clock: FakeClock, *, latency_s: float = 0.2, page_size: int = 100) -> None:
        self._clock = clock
        self._latency_s = latency_s
        self.page_size = page_size
        self.repeat_ids = False
        self._boxes: dict[str, _Box] = {}
        self._lock = threading.RLock()
        self.calls: list[Call] = []
        self.fail_next: dict[str, int] = {}  # method -> how many of its next calls raise Unavailable
        self.fail_users: set[str] = set()  # every call for these users raises Unavailable
        self._ids = itertools.count(1)

    def _box(self, user_id: str) -> _Box:
        return self._boxes.setdefault(user_id, _Box())

    def _enter(self, method: str, user_id: str, **args: Any) -> None:
        with self._lock:
            self.calls.append(Call(method, user_id, dict(args), self._clock()))
            failing = self.fail_next.get(method, 0) > 0 or user_id in self.fail_users
            if self.fail_next.get(method, 0) > 0:
                self.fail_next[method] -= 1
        self._clock.advance(self._latency_s)
        if failing:
            raise Unavailable()

    # -- provisioning (the outside world) ------------------------------------------------------
    def deliver(self, user_id: str, *, label: str = "INBOX") -> Mail:
        """New mail lands now. Non-INBOX mail (e.g. the user's own SENT mail) moves the history id
        but is never listed by an INBOX history query."""
        with self._lock:
            box = self._box(user_id)
            box.current += 1 + next(self._ids) % 3  # history ids grow, with gaps, as Gmail's do
            mail = Mail(user_id, f"m{secrets.token_hex(6)}", box.current, self._clock())
            if label == "INBOX":
                box.inbox.append(mail)
            return mail

    def expire_history(self, user_id: str) -> None:
        """Gmail no longer has history before the current record: any older start answers 404."""
        with self._lock:
            box = self._box(user_id)
            box.floor = box.current

    def current_history_id(self, user_id: str) -> int:
        with self._lock:
            return self._box(user_id).current

    def watch_active(self, user_id: str) -> bool:
        with self._lock:
            box = self._box(user_id)
            return box.expires_at is not None and self._clock() < box.expires_at

    def watch_expires_at(self, user_id: str) -> float | None:
        with self._lock:
            return self._box(user_id).expires_at

    def calls_of(self, method: str, user_id: str | None = None) -> list[Call]:
        with self._lock:
            return [c for c in self.calls if c.method == method and (user_id is None or c.user_id == user_id)]

    # -- the seam ------------------------------------------------------------------------------
    def watch(self, user_id: str, *, topic_name: str, label_ids: Iterable[str]) -> dict[str, Any]:
        labels = list(label_ids)
        self._enter("watch", user_id, topic_name=topic_name, label_ids=labels)
        with self._lock:
            box = self._box(user_id)
            box.topic = topic_name
            box.expires_at = self._clock() + WATCH_TTL_S
            return {"history_id": str(box.current), "expiration": box.expires_at}

    def stop_watch(self, user_id: str) -> None:
        self._enter("stop_watch", user_id)
        with self._lock:
            self._box(user_id).expires_at = None

    def list_history(self, user_id: str, start_history_id: str, *, page_token: str | None = None) -> dict[str, Any]:
        assert isinstance(start_history_id, str) and start_history_id.isdigit(), "history ids are decimal strings"
        self._enter("list_history", user_id, start_history_id=start_history_id, page_token=page_token)
        with self._lock:
            box = self._box(user_id)
            start = int(start_history_id)
            if start < box.floor:
                raise HistoryGone()
            added = [m for m in box.inbox if m.history_id > start]
            offset = int(page_token[1:]) if page_token else 0
            page = added[offset : offset + self.page_size]
            ids: list[str] = []
            for m in page:
                ids += [m.message_id, m.message_id] if self.repeat_ids else [m.message_id]
            more = offset + self.page_size < len(added)
            return {
                "history_id": str(box.current),
                "message_ids": ids,
                "next_page_token": f"p{offset + self.page_size}" if more else None,
            }

    def recent_inbox(self, user_id: str, *, max_results: int) -> dict[str, Any]:
        """The mailbox's current history id (taken first) and the newest INBOX message ids, newest first."""
        self._enter("recent_inbox", user_id, max_results=max_results)
        with self._lock:
            box = self._box(user_id)
            newest = [m.message_id for m in reversed(box.inbox)][: max(0, int(max_results))]
            return {"history_id": str(box.current), "message_ids": newest}


# ---------------------------------------------------------------------------
# Watch-state store, triage step and event writer


class FakeWatchStore:
    """Firestore in production. Values are JSON-able dicts, deep-copied in and out."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, user_id: str) -> dict | None:
        with self._lock:
            value = self._data.get(user_id)
            return copy.deepcopy(value) if value is not None else None

    def put(self, user_id: str, value: dict) -> None:
        json.dumps(value)  # JSON-able, as Firestore needs
        with self._lock:
            self._data[user_id] = copy.deepcopy(value)

    def delete(self, user_id: str) -> None:
        with self._lock:
            self._data.pop(user_id, None)

    def user_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._data)

    def dump(self) -> str:
        with self._lock:
            return json.dumps(self._data, default=str)


@dataclass(frozen=True)
class Triaged:
    user_id: str
    message_id: str
    started: float
    finished: float


class TriageRecorder:
    """The triage step (FR-CHN-09, a tilo-api call in production). Advances the fake clock by
    `latency_s` to stand for the model call. Records overlapping calls for one user: per-user work
    must be serialised. `race_window_s` is a tiny real wait that widens thread interleavings in the
    concurrency tests only."""

    def __init__(self, clock: FakeClock, *, latency_s: float = 3.0, race_window_s: float = 0.0) -> None:
        self._clock = clock
        self._latency_s = latency_s
        self._race = race_window_s
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self.calls: list[Triaged] = []
        self.overlaps: list[tuple[str, str]] = []

    def __call__(self, user_id: str, message_id: str) -> None:
        with self._lock:
            if user_id in self._active:
                self.overlaps.append((user_id, message_id))
            self._active.add(user_id)
        started = self._clock()
        if self._race:
            threading.Event().wait(self._race)
        self._clock.advance(self._latency_s)
        with self._lock:
            self._active.discard(user_id)
            self.calls.append(Triaged(user_id, message_id, started, self._clock()))

    def ids(self, user_id: str) -> list[str]:
        with self._lock:
            return [c.message_id for c in self.calls if c.user_id == user_id]

    def all_ids(self) -> list[str]:
        with self._lock:
            return [c.message_id for c in self.calls]

    def first_finish(self) -> dict[str, float]:
        out: dict[str, float] = {}
        with self._lock:
            for c in self.calls:
                out.setdefault(c.message_id, c.finished)
        return out


class EventLog:
    """The injected `emit`: records every event part the watcher or endpoint writes."""

    def __init__(self) -> None:
        self.parts: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def __call__(self, part: dict[str, Any]) -> None:
        with self._lock:
            self.parts.append(copy.deepcopy(part))


# ---------------------------------------------------------------------------
# OIDC verifier and Pub/Sub push requests


class FakeOidcVerifier:
    """Stands in for google-auth's id_token verification: checks the token's signature (here: that it
    issued it) and its expiry by the fake clock, and returns the claims. Like a verifier that only
    checks the signature, it does NOT enforce aud, iss or email: the endpoint must check those claims.
    Its error messages carry `detail_marker`, so a test can see whether they leak."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self._issued: dict[str, dict[str, Any]] = {}
        self.detail_marker = "verifier-detail-" + secrets.token_hex(6)
        self.calls: list[str] = []

    def issue(self, **overrides: Any) -> str:
        now = self._clock()
        claims: dict[str, Any] = {
            "iss": GOOGLE_ISSUER,
            "aud": AUDIENCE,
            "email": PUSH_SA,
            "email_verified": True,
            "sub": "100000000000000000001",
            "iat": int(now),
            "exp": int(now) + 3600,
        }
        for key, value in overrides.items():
            if value is _DROP:
                claims.pop(key, None)
            else:
                claims[key] = value
        token = "fake-oidc-" + secrets.token_urlsafe(24)
        self._issued[token] = claims
        return token

    def verify(self, token: str, audience: str) -> dict[str, Any]:
        self.calls.append(audience)
        claims = self._issued.get(token)
        if claims is None:
            raise ValueError(f"signature check failed ({self.detail_marker})")
        if "exp" in claims and claims["exp"] <= self._clock():
            raise ValueError(f"token expired ({self.detail_marker})")
        return dict(claims)


_DROP = object()


def drop() -> Any:
    """A claim override that removes the claim."""
    return _DROP


_PUBSUB_IDS = itertools.count(17_000_000_001)


def push_body(
    address: str,
    history_id: Any,
    *,
    pubsub_id: str | None = None,
    data: Any = None,
    raw_data: str | None = None,
) -> bytes:
    """A Pub/Sub push request body as Gmail's watch produces it: message.data is standard base64 of
    {"emailAddress": ..., "historyId": <number>}."""
    if raw_data is None:
        payload = data if data is not None else {"emailAddress": address, "historyId": history_id}
        raw_data = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    pid = pubsub_id or str(next(_PUBSUB_IDS))
    return json.dumps(
        {
            "message": {
                "data": raw_data,
                "messageId": pid,
                "message_id": pid,
                "publishTime": "2026-10-02T09:00:00.000Z",
                "publish_time": "2026-10-02T09:00:00.000Z",
                "attributes": {},
            },
            "subscription": SUBSCRIPTION,
        }
    ).encode("utf-8")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class NotificationRecorder:
    """The endpoint's injected `on_notification(user_id, history_id)` when tested on its own."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.raise_next = 0

    def __call__(self, user_id: str, history_id: str) -> None:
        self.calls.append((user_id, history_id))
        if self.raise_next:
            self.raise_next -= 1
            raise RuntimeError("downstream unavailable " + secrets.token_hex(4))


# ---------------------------------------------------------------------------
# Wiring


@dataclass
class Rig:
    clock: FakeClock
    mailbox: FakeMailbox
    store: FakeWatchStore
    dedupe: Any
    triage: TriageRecorder
    events: EventLog
    verifier: FakeOidcVerifier
    watcher: Any
    endpoint: Any

    def new_watcher(self) -> Any:
        """A second tilo-channels instance on the same stores (Cloud Run scales out)."""
        from tilo_channels.gmail_watch import MailWatcher

        return MailWatcher(
            mailbox=self.mailbox,
            store=self.store,
            dedupe=self.dedupe,
            triage=self.triage,
            clock=self.clock,
            topic_name=TOPIC,
            emit=self.events,
        )

    def push(self, user_id: str, history_id: int | str | None = None) -> Any:
        """An authenticated Gmail push for `user_id` through the endpoint (the mailbox's current id by default)."""
        hid = self.mailbox.current_history_id(user_id) if history_id is None else history_id
        token = self.verifier.issue()
        return self.endpoint.receive(bearer(token), push_body(ADDRESS[user_id], int(hid)))


def make_rig(*, latency_s: float = 0.2, triage_s: float = 3.0, page_size: int = 100, race_window_s: float = 0.0) -> Rig:
    from _channels_lib import MemoryDedupeStore
    from tilo_channels.gmail_watch import GmailPushEndpoint, MailWatcher

    clock = FakeClock(float(T0))
    mailbox = FakeMailbox(clock, latency_s=latency_s, page_size=page_size)
    store = FakeWatchStore()
    dedupe = MemoryDedupeStore(clock)
    triage = TriageRecorder(clock, latency_s=triage_s, race_window_s=race_window_s)
    events = EventLog()
    verifier = FakeOidcVerifier(clock)
    watcher = MailWatcher(
        mailbox=mailbox,
        store=store,
        dedupe=dedupe,
        triage=triage,
        clock=clock,
        topic_name=TOPIC,
        emit=events,
    )
    endpoint = GmailPushEndpoint(
        verifier=verifier,
        audience=AUDIENCE,
        service_account=PUSH_SA,
        accounts=USER_FOR_ADDRESS.get,
        on_notification=watcher.on_push,
        emit=events,
    )
    return Rig(clock, mailbox, store, dedupe, triage, events, verifier, watcher, endpoint)


# ---------------------------------------------------------------------------
# Latency driver (discrete events on the fake clock)


@dataclass
class Scenario:
    users: tuple[str, ...] = (RIYA, SAM, KAI)
    mails_per_user: int = 100
    window_s: float = 3600.0
    push_delay_s: tuple[float, float] = (1.0, 10.0)  # Pub/Sub delivery delay range
    loss: float = 0.0  # share of pushes never delivered
    duplicate: float = 0.0  # share of pushes delivered twice
    outage: tuple[float, float] | None = None  # (from, to) seconds after T0 with every push lost
    seed: int = 8


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def run_scenario(rig: Rig, scenario: Scenario, poll_interval_s: float) -> dict[str, Any]:
    """Mail arrives at random times; each arrival produces a Gmail push delivered after a random delay
    (or lost, or duplicated). The sweeper calls `renew_due()` and `poll_due()` every `poll_interval_s`
    (the cadence the module declares). Returns per-mail latency (arrival -> triage finished)."""
    rnd = random.Random(scenario.seed)
    for user in scenario.users:
        rig.watcher.start(user)
    seq = itertools.count()
    queue: list[tuple[float, int, str, Any]] = []
    for user in scenario.users:
        for _ in range(scenario.mails_per_user):
            heapq.heappush(queue, (T0 + rnd.uniform(0, scenario.window_s), next(seq), "mail", user))
    end = T0 + scenario.window_s + 600
    next_sweep = rig.clock() + poll_interval_s
    mails: list[Mail] = []
    while rig.clock() < end:
        if queue and queue[0][0] <= rig.clock():
            _, _, kind, payload = heapq.heappop(queue)
            if kind == "mail":
                mail = rig.mailbox.deliver(payload)
                mails.append(mail)
                offset = mail.arrived_at - T0
                lost = rnd.random() < scenario.loss or (
                    scenario.outage is not None and scenario.outage[0] <= offset < scenario.outage[1]
                )
                copies = 0 if lost else (2 if rnd.random() < scenario.duplicate else 1)
                for _ in range(copies):
                    at = rig.clock() + rnd.uniform(*scenario.push_delay_s)
                    heapq.heappush(queue, (at, next(seq), "push", (mail.user_id, mail.history_id)))
            else:
                user, hid = payload
                if rig.mailbox.watch_active(user):  # Gmail pushes only while the watch is registered
                    response = rig.push(user, hid)
                    assert 200 <= response.status < 300, f"an authenticated push was refused ({response.status})"
            continue
        if rig.clock() >= next_sweep:
            rig.watcher.renew_due()
            rig.watcher.poll_due()
            next_sweep += poll_interval_s
            continue
        upcoming = min(queue[0][0] if queue else end, next_sweep, end)
        rig.clock.advance(max(0.0, upcoming - rig.clock()))
    finished = rig.triage.first_finish()
    missing = [m.message_id for m in mails if m.message_id not in finished]
    latencies = [finished[m.message_id] - m.arrived_at for m in mails if m.message_id in finished]
    return {"mails": mails, "missing": missing, "latencies": latencies}
