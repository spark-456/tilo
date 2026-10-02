"""Outbox retry policy (#30 items 5 and 6, #163 part A; FR-CON-04, FR-AGT-13, PI-12, OB-02).

Between two attempts of one entry the outbox keeps store-side metadata outside the contract entry
(`outbox.schema.json` has no field for it): a not-before time and an attempt count.

- `RateLimited` carries its `retry_after_s` across ticks (capped at `max_delay_s`).
- `ProviderUnavailable` (a lost answer, 5xx or timeout: the provider may have acted) waits at least
  `ambiguous_delay_s`, so the next earlier-attempt lookup is not defeated by search-index lag.
- Other errors back off exponentially (`backoff_base_s` doubling, capped at `max_delay_s`).
- After `max_attempts` failures, or a failure `max_age_s` after its first failure, the entry ends `failed` and
  one registered `alert.raised` goes to the optional `alert` sink (FR-AGT-13: never a silent stop).
  Errors that wait for a person (missing consent, no or expired connection) use no attempt; the age bounds them.
- A claim re-checks `scheduled_at` (plus `clock_skew_s`) and the not-before inside the store, against the
  store's own clock when it has one (the Firestore store will use server time), never before.

`Outbox(...)` without `retry=` keeps the pinned immediate retries of tests/API.md "Failures" (no delays, no
skew margin) but is still bounded by attempts and age; production passes `RetryPolicy()`.
"""

from __future__ import annotations

import logging

import pytest
from _connectors_lib import WORLD, ManualClock, add_seconds, evidence_from_case, parse_ts
from _oauth_lib import _registry_entry, schema_errors
from tilo_connectors import InMemoryOutboxStore, Outbox
from tilo_connectors.adapters import ProviderUnavailable, RateLimited
from tilo_connectors.fakes import FakeGmail
from tilo_connectors.outbox import RetryPolicy
from tilo_connectors.tokens import InsufficientScope

T0 = "2026-09-29T09:32:09.500Z"


class Scripted(FakeGmail):
    """Raises the scripted errors in order, then sends; records the clock at every call."""

    def __init__(self, clock: ManualClock, errors: list[BaseException] | None = None, forever: Exception | None = None):
        super().__init__()
        self.clock, self.errors, self.forever, self.calls = clock, list(errors or []), forever, []

    def send_reply(self, thread_id, item, recipients, idempotency_key, grant):
        self.calls.append(self.clock())
        if self.forever is not None:
            raise self.forever
        if self.errors:
            raise self.errors.pop(0)
        return super().send_reply(thread_id, item, recipients, idempotency_key, grant)


def _setup(gate_case_factory, *, errors=None, forever=None, retry=None, undo_window_s=0, store=None, **kw):
    clock = ManualClock(T0)
    gmail = Scripted(clock, errors, forever)
    emitted: list[dict] = []
    alerts: list[dict] = []
    outbox = Outbox(
        store if store is not None else InMemoryOutboxStore(),
        {"gmail": gmail},
        emitted.append,
        clock,
        retry=retry if retry is not None else RetryPolicy(),
        alert=kw.pop("alert", alerts.append),
        **kw,
    )
    case = gate_case_factory(undo_window_s=undo_window_s)
    outbox.enqueue(case["entry"], evidence_from_case(case))
    return outbox, gmail, clock, emitted, alerts, case["entry"]["id"]


def _state(outbox: Outbox, outbox_id: str) -> str:
    return outbox._store.get(outbox_id)["state"]


# --- 1. Retry-After is carried across ticks ---------------------------------------------------------


def test_FR_CON_04_rate_limited_entry_is_not_dispatched_before_retry_after(gate_case_factory):
    outbox, gmail, clock, emitted, _, oid = _setup(gate_case_factory, errors=[RateLimited(120)])
    assert outbox.dispatch_due() == []
    clock.advance(119)
    outbox.dispatch_due()
    assert len(gmail.calls) == 1, "a tight dispatch loop must not ignore Retry-After"
    clock.advance(1)
    assert [e["state"] for e in outbox.dispatch_due()] == ["sent"]
    assert len(gmail.sent) == 1 and [p["type"] for p in emitted] == ["data.transfer"]


def test_FR_CON_04_a_huge_retry_after_is_capped_at_max_delay(gate_case_factory):
    outbox, gmail, clock, *_ = _setup(gate_case_factory, errors=[RateLimited(999_999_999)])
    outbox.dispatch_due()
    clock.advance(3599)
    outbox.dispatch_due()
    assert len(gmail.calls) == 1
    clock.advance(1)
    outbox.dispatch_due()
    assert len(gmail.calls) == 2 and len(gmail.sent) == 1


# --- 2. An ambiguous POST waits before the next earlier-attempt lookup ---------------------------------


def test_FR_CON_04_an_ambiguous_failure_waits_the_ambiguous_delay(gate_case_factory):
    outbox, gmail, clock, *_ = _setup(gate_case_factory, errors=[ProviderUnavailable("Google did not answer")])
    outbox.dispatch_due()
    clock.advance(59)
    outbox.dispatch_due()
    assert len(gmail.calls) == 1
    clock.advance(1)
    outbox.dispatch_due()
    assert len(gmail.sent) == 1


def test_FR_CON_04_a_lost_send_answer_makes_no_request_until_the_delay_then_sends_once():
    from _gapi_lib import enqueue, gmail_case, make_gapi_env

    g = make_gapi_env()
    outbox = Outbox(g.store, {"gmail": g.gmail}, g.env.emitted.append, g.env.clock, retry=RetryPolicy())
    enqueue(outbox, gmail_case(item=g.artifacts.put_email("art_retry_1")))
    g.apis.lose_response(lambda r: r.method == "POST" and r.url.endswith("/messages/send"))
    assert outbox.dispatch_due() == []
    requests = len(g.apis.requests)
    outbox.dispatch_due()
    assert len(g.apis.requests) == requests, "no earlier-attempt lookup inside the index-lag window"
    g.env.clock.advance(60)
    assert [e["state"] for e in outbox.dispatch_due()] == ["sent"]
    assert len(g.apis.sent()) == 1


# --- 3. Bounded attempts, exponential backoff, escalation ----------------------------------------------


def test_FR_AGT_13_backoff_doubles_between_attempts_and_caps_at_max_delay(gate_case_factory):
    outbox, gmail, clock, *_ = _setup(
        gate_case_factory, forever=RuntimeError("boom"), retry=RetryPolicy(max_attempts=10, max_age_s=10**6)
    )
    for _ in range(1200):
        outbox.dispatch_due()
        clock.advance(10)
    gaps = [
        round((parse_ts(b) - parse_ts(a)).total_seconds()) for a, b in zip(gmail.calls, gmail.calls[1:], strict=False)
    ]
    assert gaps == [30, 60, 120, 240, 480, 960, 1920, 3600, 3600]


def test_FR_AGT_13_after_max_attempts_the_entry_fails_with_one_registered_alert(gate_case_factory):
    outbox, gmail, clock, emitted, alerts, oid = _setup(gate_case_factory, forever=RuntimeError("Gmail 503"))
    settled: list[dict] = []
    for _ in range(20):
        settled += outbox.dispatch_due()
        clock.advance(3600)
    assert len(gmail.calls) == 8
    assert [(e["id"], e["state"]) for e in settled] == [(oid, "failed")]
    assert emitted == [], "no data.transfer for an entry that never sent"
    assert len(alerts) == 1
    part = alerts[0]
    assert part["type"] == "alert.raised" and part["authz"] is None
    assert _registry_entry("alert.raised")["side_effect"] is False
    assert schema_errors("events/data/alert.raised.schema.json", part["data"]) == []
    assert part["data"] == {"alert_id": oid, "card_id": None}
    assert part["world_id"] == outbox._store.get(oid)["world_id"]


def test_FR_AGT_13_an_entry_failing_past_max_age_ends_failed(gate_case_factory):
    outbox, gmail, clock, _, alerts, oid = _setup(
        gate_case_factory, forever=RuntimeError("boom"), retry=RetryPolicy(max_attempts=1000)
    )
    for _ in range(23):
        outbox.dispatch_due()
        clock.advance(3600)
    assert _state(outbox, oid) != "failed", "younger than 24 h: still retried"
    clock.advance(3600)
    outbox.dispatch_due()
    assert _state(outbox, oid) == "failed" and len(alerts) == 1


def test_FR_AGT_13_errors_waiting_for_a_person_use_no_attempt(gate_case_factory):
    errors = [InsufficientScope(["https://www.googleapis.com/auth/gmail.send"]) for _ in range(20)]
    outbox, gmail, clock, _, alerts, oid = _setup(gate_case_factory, errors=errors)
    for _ in range(25):
        outbox.dispatch_due()
        clock.advance(60)
    assert _state(outbox, oid) == "sent" and alerts == []


def test_FR_AGT_13_an_alert_whose_sink_failed_is_delivered_on_a_later_tick(gate_case_factory):
    calls: list[dict] = []

    def flaky(part: dict) -> None:
        calls.append(part)
        if len(calls) == 1:
            raise RuntimeError("alert writer down")

    outbox, *_rest, oid = _setup(
        gate_case_factory, forever=RuntimeError("x"), retry=RetryPolicy(max_attempts=1), alert=flaky
    )
    outbox.dispatch_due()
    outbox.dispatch_due()
    outbox.dispatch_due()
    assert [p["data"]["alert_id"] for p in calls] == [oid, oid]


def test_FR_AGT_13_without_an_alert_sink_the_failure_is_logged(gate_case_factory, caplog):
    caplog.set_level(logging.ERROR)
    outbox, *_rest, oid = _setup(
        gate_case_factory, forever=RuntimeError("x"), retry=RetryPolicy(max_attempts=1), alert=None
    )
    outbox.dispatch_due()
    assert _state(outbox, oid) == "failed"
    assert any(oid in r.getMessage() for r in caplog.records)


def test_FR_AGT_13_the_default_outbox_still_bounds_attempts(gate_case_factory):
    outbox, gmail, _clock, _, alerts, oid = _setup(gate_case_factory, forever=RuntimeError("x"), retry=None)
    outbox = Outbox(outbox._store, {"gmail": gmail}, [].append, _clock, alert=alerts.append)
    for _ in range(12):
        outbox.dispatch_due()
    assert len(gmail.calls) == 8 and _state(outbox, oid) == "failed" and len(alerts) == 1


def test_FR_WLD_07_a_deferred_entry_can_be_abandoned_and_alerts_stay_in_their_world(gate_case_factory):
    outbox, gmail, clock, _, alerts, oid = _setup(gate_case_factory, errors=[ProviderUnavailable("x")])
    outbox.dispatch_due()
    assert outbox.abandon(oid)["state"] == "failed"
    clock.advance(120)
    outbox.dispatch_due()
    assert len(gmail.calls) == 1 and alerts == []

    pending = InMemoryOutboxStore()  # an instance with no alert sink fails it; the alert waits in the store
    failing = Outbox(pending, {"gmail": Scripted(clock, forever=RuntimeError("x"))}, [].append, clock,
                     retry=RetryPolicy(max_attempts=1), alert=None)  # fmt: skip
    case = gate_case_factory()
    failing.enqueue(case["entry"], evidence_from_case(case))
    failing.dispatch_due()
    other_world: list[dict] = []
    Outbox(pending, {}, [].append, clock, world_id="w_other", alert=other_world.append).dispatch_due()
    Outbox(pending, {}, [].append, clock, world_id=WORLD, alert=alerts.append).dispatch_due()
    assert other_world == [] and [p["data"]["alert_id"] for p in alerts] == [case["entry"]["id"]]


# --- 4. Claims re-check scheduled_at in the store -------------------------------------------------------


def test_OB_02_a_claim_before_scheduled_at_is_refused_by_the_store(gate_case_factory):
    store = InMemoryOutboxStore()
    _setup(gate_case_factory, store=store, undo_window_s=60)
    (entry,) = store.all_entries()
    assert store._claim_for_sending(entry["id"], "h", add_seconds(T0, 59.999), 30) is None
    assert store._claim_for_sending(entry["id"], "h", add_seconds(T0, 60), 30)["state"] == "sending"


def test_PI_12_a_fast_dispatcher_clock_within_the_skew_never_sends_early(gate_case_factory):
    outbox, gmail, clock, *_ = _setup(gate_case_factory, undo_window_s=60, retry=RetryPolicy(clock_skew_s=5))
    clock.advance(64)  # this dispatcher's clock runs up to 5 s fast: true time may be before scheduled_at
    assert outbox.dispatch_due() == [] and gmail.calls == []
    clock.advance(1)
    assert [e["state"] for e in outbox.dispatch_due()] == ["sent"]


def test_PI_12_the_store_clock_wins_over_a_fast_dispatcher_clock(gate_case_factory):
    server = ManualClock(T0)
    outbox, gmail, clock, *_ = _setup(gate_case_factory, undo_window_s=60, store=InMemoryOutboxStore(clock=server))
    clock.advance(600)  # the dispatcher is 10 minutes fast
    server.advance(59)
    assert outbox.dispatch_due() == [] and gmail.calls == []
    assert outbox.cancel(outbox._store.all_entries()[0]["id"])["state"] == "cancelled", "Undo still works"


@pytest.mark.parametrize("field", ["undo_window_s", "scheduled_at"])
def test_OB_02_store_claims_still_accept_entries_without_schedule_fields(field):
    store = InMemoryOutboxStore()
    entry = {"id": "o_1", "world_id": "w", "idempotency_key": "k", "connector": "c", "state": "queued"}
    entry[field] = 60 if field == "undo_window_s" else add_seconds(T0, 60)
    store._insert_if_absent(entry)
    assert store._claim_for_sending("o_1", "h", T0, 30) is not None
