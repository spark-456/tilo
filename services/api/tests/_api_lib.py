"""Factories, schema validation and the principal override for services/api acceptance tests
(ticket ST-3a). Kept out of conftest.py under a package-unique module name: every test
directory in the repo has its own conftest.py, so `from conftest import ...` resolves to
whichever one was imported first when the whole suite runs together.
"""

from __future__ import annotations

import json
import pathlib
import threading
import time
from dataclasses import dataclass
from typing import Any

import jsonschema
from fastapi import Request
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

# tilo_api.deps is this ticket's own pinned addition (API_ST3a.md); it does not exist on the
# tests/P4-01 base this branch starts from, so this import fails at collection time with
# ModuleNotFoundError until the builder adds it. That failure is the "right reason" this
# directory's tests fail today.
from tilo_api import (
    app,  # noqa: F401  (imported for the `client` fixture below)
    deps,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

OWNER = "u_owner"
WORLD = "w_village_basic"


# ---------------------------------------------------------------------------
# Contract schema validation (mirrors tests/contracts/_lib.py and
# packages/policy/tests/conftest.py's style; kept self-contained here since this ticket may not
# edit anything outside services/api/tests/).


def contracts_dir() -> pathlib.Path:
    return REPO_ROOT / "contracts"


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_registry() -> Registry:
    resources: list[tuple[str, Resource]] = []
    for path in sorted(contracts_dir().glob("**/*.schema.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        uri = data.get("$id") or path.resolve().as_uri()
        resources.append((uri, Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


_REGISTRY = build_registry()


def validate_event(event: dict) -> None:
    """event.schema.json, plus its type's data schema (events/data/<type>.schema.json) -- the
    two checks EV-02 needs. Raises jsonschema.ValidationError with a clear path on failure."""
    event_schema = load_json(contracts_dir() / "event.schema.json")
    validator_cls = jsonschema.validators.validator_for(event_schema, default=jsonschema.Draft202012Validator)
    validator_cls(event_schema, registry=_REGISTRY).validate(event)

    data_schema_path = contracts_dir() / "events" / "data" / f"{event['type']}.schema.json"
    data_schema = load_json(data_schema_path)
    validator_cls = jsonschema.validators.validator_for(data_schema, default=jsonschema.Draft202012Validator)
    validator_cls(data_schema, registry=_REGISTRY).validate(event["data"])


# ---------------------------------------------------------------------------
# Plain data factories (policy.schema.json, event.schema.json shapes; API_ST3a.md's Principal,
# WorldRecord, DistrictRecord, Store). Every function returns a fresh, independent structure;
# callers mutate their own copy. Timestamps stay inside 2026-09-29 (the same day
# contracts/fixtures/outbox/crossref and packages/policy/tests use) so same-UTC-day comparisons
# need no date gymnastics.


def stamp(at: str, by: str = OWNER) -> dict:
    return {"by": by, "at": at}


def ulid(n: int) -> str:
    """A common.schema.json#/$defs/ulid-shaped string: `[0-7][0-9A-HJKMNP-TV-Z]{25}`. An
    all-digit suffix after a leading '0' satisfies it (every digit is valid Crockford base32)."""
    return f"01JB5VQ0{n:018d}"


def base_policy(
    *,
    id_: str = "pol_test",
    action_type: str = "send_email",
    level: str = "L2",
    owner: str = OWNER,
    connectors: tuple[str, ...] = ("gmail",),
    recipients: tuple[str, ...] = (),
    domains: tuple[str, ...] = ("example.com",),
    districts: tuple[str, ...] = (),
    per_day: int | None = 20,
    credits: float | None = 50,
    undo_window_s: int = 60,
    expiry: str | None = None,
    team_lead_domains: tuple[str, ...] = (),
    history: list[dict] | None = None,
    created_at: str = "2026-09-29T09:30:00.000Z",
) -> dict:
    """A policy.schema.json record; override individual fields per test. Mirrors
    packages/policy/tests/conftest.py's base_policy so fixtures built here would also be valid
    input to tilo_policy.decide's `policies` list."""
    hist = history if history is not None else [{"by": owner, "at": created_at, "change": "Created", "level": level}]
    return {
        "id": id_,
        "owner": owner,
        "action_type": action_type,
        "scope": {
            "connectors": list(connectors),
            "recipients": list(recipients),
            "domains": list(domains),
            "districts": list(districts),
        },
        "limits": {"per_day": per_day, "credits": credits},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": level,
        "undo_window_s": undo_window_s,
        "expiry": expiry,
        "notify_channel": "whatsapp",
        "team_lead_domains": list(team_lead_domains),
        "created_by": stamp(created_at, owner),
        "changed_by": None,
        "history": hist,
    }


def base_event(
    *,
    seq: int,
    type_: str,
    data: dict,
    world_id: str = WORLD,
    actor: str = OWNER,
    target: str | None = None,
    district: str | None = None,
    vis: Any = "all",
    authz: dict | None = None,
    summary: str = "test event",
    ts: str = "2026-09-29T09:30:00.000Z",
    cause: str | None = None,
) -> dict:
    """An event.schema.json record with every non-payload field defaulted."""
    return {
        "v": "1.0",
        "id": ulid(seq),
        "seq": seq,
        "ts": ts,
        "world_id": world_id,
        "run_id": "r_village_basic_1",
        "type": type_,
        "actor": actor,
        "target": target or world_id,
        "level": None,
        "district": district,
        "item": None,
        "severity": "info",
        "credits": 0,
        "summary": summary,
        "cause": cause,
        "vis": vis,
        "authz": authz,
        "data": data,
        "trace": {
            "model_role": None,
            "profile": None,
            "tokens_in": None,
            "tokens_out": None,
            "tool": None,
            "latency_ms": None,
            "archive_ref": None,
        },
    }


def make_district(name: str, summary: str) -> deps.DistrictRecord:
    return deps.DistrictRecord(name=name, summary=summary)


RUN_ID = "r_village_basic_1"  # matches base_event's own default run_id, so a fixture built from
# base_event() and one stamped by FakeEventWriter for the same world compare equal on run_id.


def make_world(
    *,
    owner: str = OWNER,
    owner_channels: tuple[str, ...] = ("web", "whatsapp", "email"),
    districts: dict[str, deps.DistrictRecord | None] | None = None,
    run_id: str = RUN_ID,
    paused: bool = False,
) -> deps.WorldRecord:
    """paused (round-4 addition, API_ST3a.md's WorldRecord.paused): defaults to False like every
    fresh world; a test proving the pause dedupe reads the flag, not "did anything change this
    call," passes paused=True directly to seed an already-paused world."""
    return deps.WorldRecord(
        owner=owner, owner_channels=owner_channels, districts=districts or {}, run_id=run_id, paused=paused
    )


def make_store(
    *,
    worlds: dict[str, deps.WorldRecord] | None = None,
    policies: dict[str, dict] | None = None,
    policy_worlds: dict[str, str] | None = None,
    events: dict[str, list[dict]] | None = None,
    pending_events: dict[str, list[dict]] | None = None,
) -> deps.Store:
    """pending_events (round-3 addition, API_ST3a.md "Pending writes"): world_id -> event parts
    Stop-all or Pause-all built but could not hand to EventWriter.append yet (the writer raised).
    Defaults to {} like every other collection here; a test that never exercises writer failure
    never needs to pass it."""
    return deps.Store(
        worlds=worlds or {},
        policies=policies or {},
        policy_worlds=policy_worlds or {},
        events=events or {},
        pending_events=pending_events or {},
    )


def make_principal(
    *,
    user_id: str = OWNER,
    role: str = "owner",
    world_id: str | None = WORLD,
    domain: str | None = None,
    channel: str = "web",
    districts: tuple[str, ...] = (),
) -> deps.Principal:
    """world_id defaults to WORLD (this file's one fixture world) so every existing-owner-ish
    test is a member of the world it acts on without saying so; a test proving the round-1
    membership-oracle finding (ST-3a round 2) passes world_id=None or a different world's id
    explicitly. channel (round-6/ST-3a-2, API_ST3a.md "What changed since round 5" item 5, issue
    #38 item 5) is the principal's own resolved session channel; it defaults to "web" like every
    other channel default in this ticket. deps.Principal does not carry this field yet -- every
    test that passes a non-default channel (or relies on this default at all, since it is passed
    through unconditionally) fails with TypeError until the builder adds it, the same failure mode
    ambiguity 4's WorldRecord.paused went through in round 4."""
    return deps.Principal(
        user_id=user_id, role=role, world_id=world_id, domain=domain, channel=channel, districts=districts
    )


def as_principal(principal: deps.Principal):
    app.dependency_overrides[deps.get_current_principal] = lambda: principal


PRINCIPAL_HEADER = "x-test-principal"


def as_principal_by_header(mapping: dict[str, deps.Principal]) -> None:
    """Installs a get_current_principal override keyed by an HTTP header instead of a single
    global value (round-4 addition: as_principal's single global lambda races when two threads
    issue concurrent requests as *different* principals -- e.g. proving a kill switch against one
    world never blocks on another world's writer latency, which needs each world's own owner.
    `mapping` is built once, before any thread starts, and only ever read afterwards, so
    concurrent requests need no lock; each caller sends its own key with every request via the
    PRINCIPAL_HEADER header, e.g. client.post(url, headers={PRINCIPAL_HEADER: "big"})."""

    def _resolve(request: Request) -> deps.Principal:
        key = request.headers.get(PRINCIPAL_HEADER)
        return mapping[key]

    app.dependency_overrides[deps.get_current_principal] = _resolve


def as_writer(writer) -> None:
    """Overrides get_event_writer mid-test with something other than the `writer` fixture's plain
    FakeEventWriter -- a FlakyEventWriter or SlowEventWriter below, for the round-3 pending-write
    and concurrency findings. The `client` fixture's own override runs first at TestClient
    creation; FastAPI resolves dependency_overrides per request, so re-assigning the key here
    before a test's client.post/get calls takes effect on every following request in that test."""
    app.dependency_overrides[deps.get_event_writer] = lambda: writer


# ---------------------------------------------------------------------------
# FakeEventWriter: the in-memory stand-in for "the harness is the only writer of events" (PRD
# 15.3), installed in every test via the `writer` fixture (conftest.py). It is the one place
# id/seq/ts/run_id are stamped, on purpose (PI-18): tilo-api hands it an unstamped *part* and this
# double is what proves, by recording every call, that tilo-api never computed those fields
# itself (round-1 finding: tilo-api invented run_id = f"r_{world_id}" and rescanned
# store.events[world_id] for the next seq on every single event, O(n) per call inside an O(n)
# loop). A per-world counter here is O(1) per call instead.

_EVENT_PART_KEYS = (
    "type",
    "actor",
    "target",
    "level",
    "district",
    "item",
    "severity",
    "credits",
    "summary",
    "cause",
    "vis",
    "authz",
    "data",
)

_STAMPED_ONLY_KEYS = ("id", "seq", "ts", "run_id")

_ALLOWED_PART_KEYS = frozenset(_EVENT_PART_KEYS) | {"trace"}


@dataclass
class RecordedWrite:
    world_id: str
    part: dict  # exactly what tilo-api passed, before this double stamped anything


class FakeEventWriter:
    def __init__(self, store: deps.Store) -> None:
        self.store = store
        self.calls: list[RecordedWrite] = []
        self._counters: dict[str, int] = {}

    def append(self, world_id: str, part: dict) -> dict:
        self.calls.append(RecordedWrite(world_id=world_id, part=dict(part)))
        seq = self._counters.get(world_id, 0) + 1
        self._counters[world_id] = seq
        world = self.store.worlds.get(world_id)
        run_id = world.run_id if world is not None else f"r_{world_id[:44]}"
        trace = part.get(
            "trace",
            {
                "model_role": None,
                "profile": None,
                "tokens_in": None,
                "tokens_out": None,
                "tool": None,
                "latency_ms": None,
                "archive_ref": None,
            },
        )
        event = {
            "v": "1.0",
            "id": ulid(seq),
            "seq": seq,
            "ts": part.get("ts") or "2026-09-29T09:30:00.000Z",
            "world_id": world_id,
            "run_id": run_id,
            "type": part["type"],
            "actor": part.get("actor", "system"),
            "target": part.get("target", world_id),
            "level": part.get("level"),
            "district": part.get("district"),
            "item": part.get("item"),
            "severity": part.get("severity", "info"),
            "credits": part.get("credits", 0),
            "summary": (part.get("summary") or "")[:140] or "test event",
            "cause": part.get("cause"),
            "vis": part.get("vis", "all"),
            "authz": part.get("authz"),
            "data": part.get("data", {}),
            "trace": trace,
        }
        self.store.events.setdefault(world_id, []).append(event)
        return event


def make_writer(store: deps.Store) -> FakeEventWriter:
    return FakeEventWriter(store)


class FlakyEventWriter(FakeEventWriter):
    """A stand-in for "the harness is down" (round-3 qa/security finding: FR-HIL-07's kill switch
    must still lower every targeted policy to L1 even when EventWriter.append raises, and the
    parts that could not be written must be kept as pending parts, not lost). While `failing` is
    True (or while the call count is within `fail_first_n`) every `append` raises before touching
    `self.calls` or the store, exactly like an unreachable harness process. Flip `failing` back to
    False, or let `fail_first_n` run out, to prove a later call flushes whatever is pending,
    exactly once each -- never zero times, never twice."""

    def __init__(self, store: deps.Store, *, failing: bool = True, fail_first_n: int | None = None) -> None:
        super().__init__(store)
        self.failing = failing
        self.fail_first_n = fail_first_n
        self._attempts = 0

    def append(self, world_id: str, part: dict) -> dict:
        self._attempts += 1
        should_fail = self.failing if self.fail_first_n is None else self._attempts <= self.fail_first_n
        if should_fail:
            raise RuntimeError("event writer unreachable (test double)")
        return super().append(world_id, part)


class SlowEventWriter(FakeEventWriter):
    """Sleeps `delay_s` before every append, widening the race window for the round-3 qa
    concurrency finding: two concurrent kill-switch calls (threads) against a slow writer must
    still leave exactly one policy.changed (or world.paused) per policy/world, not two."""

    def __init__(self, store: deps.Store, *, delay_s: float = 0.05) -> None:
        super().__init__(store)
        self.delay_s = delay_s

    def append(self, world_id: str, part: dict) -> dict:
        time.sleep(self.delay_s)
        return super().append(world_id, part)


class SlowFlakyEventWriter(FakeEventWriter):
    """Sleeps `delay_s` then always raises (round-4 qa finding: "kill switch within 5s even with
    a slow, failing writer"). Combines SlowEventWriter's latency with FlakyEventWriter's failure
    so a test can prove that neither the per-part write attempt nor the flush of many pending
    parts can be allowed to run serially and synchronously inside whatever the route uses to
    serialize its own mutation -- 200 parts * even a small delay_s would already blow FR-HIL-07's
    5s budget if attempted that way, so a passing test is itself proof the implementation moved
    writer I/O out of that critical path (API_ST3a.md's "Locking" section)."""

    def __init__(self, store: deps.Store, *, delay_s: float = 0.03) -> None:
        super().__init__(store)
        self.delay_s = delay_s

    def append(self, world_id: str, part: dict) -> dict:
        time.sleep(self.delay_s)
        raise RuntimeError("event writer unreachable and slow (test double)")


class BlockingEventWriter(FakeEventWriter):
    """Every `append` call blocks on an internal `threading.Event` until `release()` is called --
    proves the round-5 qa/security finding that a world's lock is never held across writer I/O, and
    that every writer attempt carries its own bounded deadline: a kill switch call must still
    return within its 5s budget (with the un-writable part left pending) even against a writer
    whose `append` never returns *at all*, not merely a slow or a raising one. `entered` is set the
    moment the first call starts blocking, so a test can wait for that before issuing a second,
    concurrent request. A test using this MUST call `release()` (a `finally` block) so no thread is
    left blocked past the test; any call still in flight when released completes normally
    afterwards (a harmless, unobserved write to a store object the test is done with)."""

    def __init__(self, store: deps.Store) -> None:
        super().__init__(store)
        self._gate = threading.Event()
        self.entered = threading.Event()

    def append(self, world_id: str, part: dict) -> dict:
        self.entered.set()
        self._gate.wait()
        return super().append(world_id, part)

    def release(self) -> None:
        self._gate.set()


class ReversedDelayEventWriter(FakeEventWriter):
    """Sleeps a little less on each successive call (the *first* call to arrive sleeps the
    longest, the last sleeps almost none) -- built to make a round-5 "order within a world"
    violation observable. If a world's writer calls are dispatched and *committed* strictly in
    submission order (sequentially, or concurrently with an in-order commit barrier -- API_ST3a.md
    "Order within a world"), the order calls complete in `store.events`/`writer.calls` always
    matches submission order regardless of each call's own delay, since call N+1's *effect* can
    never be recorded before call N's is. If calls are instead committed in raw completion order,
    the short-delay latecomers finish first and jump the queue, which this writer is built to
    surface: the first-submitted call sleeps longest, so it visibly finishes last unless order is
    enforced by something other than arrival timing."""

    def __init__(self, store: deps.Store, *, base_delay_s: float = 0.05, step_s: float = 0.0006) -> None:
        super().__init__(store)
        self._lock = threading.Lock()
        self._n = 0
        self.base_delay_s = base_delay_s
        self.step_s = step_s

    def append(self, world_id: str, part: dict) -> dict:
        with self._lock:
            i = self._n
            self._n += 1
        delay = max(0.0, self.base_delay_s - i * self.step_s)
        time.sleep(delay)
        return super().append(world_id, part)


class LateSuccessEventWriter(FakeEventWriter):
    """The very first call `.append` ever receives sleeps past `_MAX_PART_DEADLINE_S` (round-5's
    0.5s per-part deadline) before succeeding for real; every later call succeeds immediately.
    Built for the round-6/ST-3a-2 finding (issue #38 item 2): a part whose attempt misses its
    deadline is queued pending while the underlying attempt keeps running in the background: if
    that late attempt is allowed to write for real without ever being cleared from pending, a
    later flush re-sends the very same part and it lands in store.events twice.
    `first_call_settled` is set the instant the slow first call's real append has actually landed
    in the store, so a test can wait for that deterministically instead of guessing a sleep
    length."""

    def __init__(self, store: deps.Store, *, delay_s: float = 0.7) -> None:
        super().__init__(store)
        self.delay_s = delay_s
        self._first_call_started = False
        self._lock = threading.Lock()
        self.first_call_settled = threading.Event()

    def append(self, world_id: str, part: dict) -> dict:
        with self._lock:
            is_first = not self._first_call_started
            self._first_call_started = True
        if is_first:
            time.sleep(self.delay_s)
            result = super().append(world_id, part)
            self.first_call_settled.set()
            return result
        return super().append(world_id, part)


class SlowHistoryPolicy(dict):
    """A policy-record test double (plain data with one instrumented read, not production code)
    whose `.get("history")` call rendezvous-and-delays via a 2-party barrier before returning --
    exactly the way BlockingEventWriter widens the race window for a writer call, but for a plain
    in-memory dict read instead of I/O. Built for the round-6/ST-3a-2 finding (issue #38 item 5,
    "Revoke of an unmapped policy is done without a lock"): two concurrent revokes of the same
    unmapped policy each read `history` exactly once; without a lock, both can read the same stale
    value (seed it with `history=None`, not an already-list value, or a shared list's `.append`
    would hide the bug) and one's write silently clobbers the other's. Every call rendezvous with
    the next one, so this only stays correct when exactly two readers ever call `.get("history")`
    on the same instance -- true for two concurrent revokes of one unmapped policy, which each make
    exactly one such call."""

    def __init__(self, *args: Any, delay_s: float = 0.1, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._barrier = threading.Barrier(2, timeout=5)
        self._delay_s = delay_s

    def get(self, key: str, default: Any = None) -> Any:
        if key == "history":
            try:
                self._barrier.wait()
            except threading.BrokenBarrierError:
                pass
            time.sleep(self._delay_s)
        return super().get(key, default)


def make_pending_part(
    *, policy_id: str, change: str = "stop_all", level: str = "L1", summary: str | None = None
) -> dict:
    """A minimal, already-built event *part* (API_ST3a.md's EventWriter.append shape) for seeding
    Store.pending_events directly in a test, standing in for a part an earlier failed call would
    have built. Pure data, no business logic -- the same convention base_event/base_policy follow."""
    return {
        "type": "policy.changed",
        "actor": OWNER,
        "target": None,
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": 0,
        "summary": summary or f"pending part for {policy_id}",
        "cause": None,
        "vis": "all",
        "authz": {"by": "person", "ref": OWNER, "at": "2026-09-29T09:00:00.000Z"},
        "data": {"policy_id": policy_id, "change": change, "level": level},
    }


def assert_part_carries_no_stamped_fields(part: dict) -> None:
    """PI-18: the event part tilo-api hands to EventWriter.append carries none of the four fields
    only a writer may set, and no key outside the part shape API_ST3a.md pins."""
    for key in _STAMPED_ONLY_KEYS:
        assert key not in part, f"tilo-api must not stamp {key!r} itself; found it in the part it built"
    unexpected = set(part) - _ALLOWED_PART_KEYS
    assert not unexpected, f"event part carries unexpected keys: {unexpected}"
