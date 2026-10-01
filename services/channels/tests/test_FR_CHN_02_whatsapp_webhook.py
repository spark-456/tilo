"""FR-CHN-02 acceptance: WhatsApp webhook, signature verified, idempotent, ordered per user
(PRD 11.1; PRD 16.2 "Spoofed WhatsApp commands"; PRD 16.4 SEC-08 "Forged or replayed requests
rejected"; PRD 11.6 FR-CHN-02: "Replayed or forged webhooks are rejected; duplicates processed once").

Public interface under test: `tilo_channels.whatsapp` (pinned in API.md next to this file). The
package does not exist yet, so every test fails today with ModuleNotFoundError.

Defaults the PRD does not state, chosen here and listed in the ticket report (for
docs/open-questions.md):
- A delivery is "stale" when a message timestamp is more than `max_age_s` older than the injected
  clock; the default `max_age_s` is 300 s (PRD 16.4 SEC-08 gives no number; 300 s is the usual
  webhook tolerance and sits well inside Meta's own retry horizon for fresh traffic).
- A replay (a message id already claimed) is acknowledged with HTTP 200 and outcome "duplicate",
  not an error status: Meta retries non-2xx deliveries, so an error would only invite more
  retries. "Rejected" means the handler is not invoked again.
- A late message older than the sender's newest processed one, but unseen and within the window, is
  still processed once (dropping it would lose a message; ordering is by timestamp within a
  delivery and by arrival across deliveries).
"""

from __future__ import annotations

import hashlib
import hmac
import random
import threading
import time
from collections import Counter, defaultdict

import pytest
from _channels_lib import (
    NUMBER_A,
    NUMBER_B,
    T0,
    FakeClock,
    MemoryDedupeStore,
    Recorder,
    delivery_body,
    image_message,
    make_app_secret,
    sign,
    status_only_body,
    text_message,
    wamid,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_channels.whatsapp import InboundMessage, WhatsAppWebhook, verify_signature

MAX_AGE_S = 300


def make_hook(app_secret=None, *, max_age_s=MAX_AGE_S, start=T0 + 60, handler=None):
    """A webhook wired to fakes. Returns (hook, handler, store, clock, secret)."""
    secret = app_secret if app_secret is not None else make_app_secret()
    clock = FakeClock(start)
    store = MemoryDedupeStore(clock)
    handler = handler if handler is not None else Recorder()
    kwargs = {} if max_age_s is None else {"max_age_s": max_age_s}
    hook = WhatsAppWebhook(app_secret=secret, now=clock, store=store, handler=handler, **kwargs)
    return hook, handler, store, clock, secret


def deliver(hook, secret, messages):
    body = delivery_body(messages)
    return hook.receive(body, sign(secret, body))


# ---------------------------------------------------------------------------
# Signature (SEC-08): HMAC-SHA256 of the raw body with the app secret, X-Hub-Signature-256.


def test_FR_CHN_02_verify_signature_accepts_meta_hmac_sha256_of_raw_body():
    secret = make_app_secret()
    body = b'{"object":"whatsapp_business_account","entry":[]}'
    header = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    assert verify_signature(secret, body, header) is True


@pytest.mark.parametrize(
    "header_for",
    [
        pytest.param(lambda s, b: None, id="missing"),
        pytest.param(lambda s, b: "", id="empty"),
        pytest.param(lambda s, b: "sha256=", id="prefix-only"),
        pytest.param(lambda s, b: hmac.new(s, b, hashlib.sha256).hexdigest(), id="no-prefix"),
        pytest.param(lambda s, b: "sha1=" + hmac.new(s, b, hashlib.sha1).hexdigest(), id="wrong-algorithm"),
        pytest.param(lambda s, b: "sha256=" + hmac.new(s, b, hashlib.sha256).hexdigest()[:-2], id="truncated"),
        pytest.param(lambda s, b: "sha256=" + hmac.new(s, b, hashlib.sha256).hexdigest() + "00", id="too-long"),
        pytest.param(lambda s, b: "sha256=" + "z" * 64, id="non-hex"),
        pytest.param(lambda s, b: "sha256=" + "0" * 64, id="wrong-digest"),
        pytest.param(lambda s, b: " sha256=" + hmac.new(s, b, hashlib.sha256).hexdigest(), id="leading-space"),
        pytest.param(
            lambda s, b: "sha256=" + hmac.new(make_app_secret(), b, hashlib.sha256).hexdigest(), id="other-secret"
        ),
        pytest.param(lambda s, b: "sha256=" + hmac.new(s, b + b" ", hashlib.sha256).hexdigest(), id="other-body"),
    ],
)
def test_FR_CHN_02_verify_signature_rejects_forged_missing_or_malformed(header_for):
    secret = make_app_secret()
    body = delivery_body([text_message(wamid(1), NUMBER_A, T0, "hi")])
    assert verify_signature(secret, body, header_for(secret, body)) is False


def test_FR_CHN_02_forged_delivery_is_rejected_with_401_and_nothing_runs():
    hook, handler, store, _clock, _secret = make_hook()
    body = delivery_body([text_message(wamid(1), NUMBER_A, T0 + 30, "STOP AUTOPILOT")])
    forged = sign(make_app_secret(), body)
    response = hook.receive(body, forged)
    assert response.status == 401
    assert response.outcomes == ()
    assert handler.messages == []
    assert store.claims == []


@pytest.mark.parametrize("header", [None, "", "sha256=", "sha256=nothex", "md5=abc", "garbage"])
def test_FR_CHN_02_missing_or_malformed_signature_header_is_rejected_with_401(header):
    hook, handler, store, _clock, _secret = make_hook()
    body = delivery_body([text_message(wamid(1), NUMBER_A, T0 + 30, "hello")])
    response = hook.receive(body, header)
    assert response.status == 401
    assert handler.messages == []
    assert store.claims == []


def test_FR_CHN_02_forged_delivery_cannot_burn_a_message_id():
    """A forged request carrying a real message id must not make the genuine one a duplicate."""
    hook, handler, _store, _clock, secret = make_hook()
    message = text_message(wamid(7), NUMBER_A, T0 + 30, "hello")
    body = delivery_body([message])
    assert hook.receive(body, sign(make_app_secret(), body)).status == 401
    response = hook.receive(body, sign(secret, body))
    assert response.status == 200
    assert handler.ids() == [wamid(7)]


def test_FR_CHN_02_signature_covers_the_raw_bytes_not_a_reserialisation():
    hook, handler, _store, _clock, secret = make_hook()
    message = text_message(wamid(1), NUMBER_A, T0 + 30, "hello")
    body = delivery_body([message])
    pretty = body.replace(b",", b" ,\n  ")  # same JSON, different bytes
    assert hook.receive(pretty, sign(secret, body)).status == 401  # signature of the other bytes
    assert hook.receive(pretty, sign(secret, pretty)).status == 200
    assert handler.ids() == [wamid(1)]


def test_FR_CHN_02_signed_body_that_is_not_json_is_rejected_with_400():
    hook, handler, store, _clock, secret = make_hook()
    body = b"not json at all"
    response = hook.receive(body, sign(secret, body))
    assert response.status == 400
    assert response.outcomes == ()
    assert handler.messages == []
    assert store.claims == []


def test_FR_CHN_02_status_receipts_are_acknowledged_and_ignored():
    hook, handler, _store, _clock, secret = make_hook()
    body = status_only_body()
    response = hook.receive(body, sign(secret, body))
    assert response.status == 200
    assert response.outcomes == ()
    assert handler.messages == []


# ---------------------------------------------------------------------------
# Parsing and the handler contract.


def test_FR_CHN_02_valid_delivery_is_processed_and_handler_gets_the_parsed_message():
    hook, handler, _store, _clock, secret = make_hook()
    response = deliver(hook, secret, [text_message(wamid(1), NUMBER_A, T0 + 30, "PAUSE")])
    assert response.status == 200
    assert [(o.message_id, o.result) for o in response.outcomes] == [(wamid(1), "processed")]
    (message,) = handler.messages
    assert isinstance(message, InboundMessage)
    assert message.message_id == wamid(1)
    assert message.sender == NUMBER_A
    assert message.timestamp == T0 + 30
    assert message.kind == "text"
    assert message.text == "PAUSE"


def test_FR_CHN_02_non_text_messages_reach_the_handler_with_kind_and_no_text():
    hook, handler, _store, _clock, secret = make_hook()
    deliver(hook, secret, [image_message(wamid(1), NUMBER_A, T0 + 30)])
    (message,) = handler.messages
    assert message.kind == "image"
    assert message.text is None


# ---------------------------------------------------------------------------
# Idempotency: duplicates processed once; replays and stale deliveries rejected.


def test_FR_CHN_02_replayed_delivery_is_not_processed_again():
    hook, handler, _store, _clock, secret = make_hook()
    body = delivery_body([text_message(wamid(1), NUMBER_A, T0 + 30, "hello")])
    header = sign(secret, body)
    first = hook.receive(body, header)
    second = hook.receive(body, header)
    third = hook.receive(body, header)
    assert [o.result for o in first.outcomes] == ["processed"]
    assert [o.result for o in second.outcomes] == ["duplicate"]
    assert [o.result for o in third.outcomes] == ["duplicate"]
    assert second.status == 200 and third.status == 200
    assert handler.ids() == [wamid(1)]


def test_FR_CHN_02_same_message_id_in_a_different_delivery_is_processed_once():
    """Meta retries can regroup messages: the dedupe key is the message id, not the body hash."""
    hook, handler, _store, _clock, secret = make_hook()
    m1 = text_message(wamid(1), NUMBER_A, T0 + 30, "one")
    m2 = text_message(wamid(2), NUMBER_A, T0 + 31, "two")
    deliver(hook, secret, [m1])
    response = deliver(hook, secret, [m1, m2])
    assert [(o.message_id, o.result) for o in response.outcomes] == [(wamid(1), "duplicate"), (wamid(2), "processed")]
    assert handler.ids() == [wamid(1), wamid(2)]


def test_FR_CHN_02_duplicate_message_id_inside_one_delivery_is_processed_once():
    hook, handler, _store, _clock, secret = make_hook()
    m1 = text_message(wamid(1), NUMBER_A, T0 + 30, "one")
    deliver(hook, secret, [m1, dict(m1)])
    assert handler.ids() == [wamid(1)]


def test_FR_CHN_02_dedupe_claim_outlives_the_staleness_window():
    """A replay inside the window must always find its claim: the claim's ttl is at least max_age_s."""
    hook, _handler, store, _clock, secret = make_hook()
    deliver(hook, secret, [text_message(wamid(1), NUMBER_A, T0 + 30, "hello")])
    assert store.claims, "the webhook must claim the message id in the injected store"
    key, ttl_s = store.claims[0]
    assert wamid(1) in key
    assert ttl_s >= MAX_AGE_S


def test_FR_CHN_02_stale_message_is_rejected_and_not_processed():
    hook, handler, _store, clock, secret = make_hook()
    ts = int(clock()) - MAX_AGE_S - 1
    response = deliver(hook, secret, [text_message(wamid(1), NUMBER_A, ts, "old news")])
    assert [(o.message_id, o.result) for o in response.outcomes] == [(wamid(1), "stale")]
    assert handler.messages == []


def test_FR_CHN_02_message_exactly_at_the_window_edge_is_still_fresh():
    hook, handler, _store, clock, secret = make_hook()
    ts = int(clock()) - MAX_AGE_S
    response = deliver(hook, secret, [text_message(wamid(1), NUMBER_A, ts, "edge")])
    assert [o.result for o in response.outcomes] == ["processed"]
    assert handler.ids() == [wamid(1)]


def test_FR_CHN_02_replay_after_the_window_is_rejected_even_if_the_claim_expired():
    hook, handler, store, clock, secret = make_hook()
    body = delivery_body([text_message(wamid(1), NUMBER_A, int(clock()), "hello")])
    header = sign(secret, body)
    assert [o.result for o in hook.receive(body, header).outcomes] == ["processed"]
    clock.advance(MAX_AGE_S * 10)  # long past both the window and any dedupe ttl
    replay = hook.receive(body, header)
    assert [o.result for o in replay.outcomes] == ["stale"]
    assert handler.ids() == [wamid(1)]


def test_FR_CHN_02_default_staleness_window_is_between_one_minute_and_one_hour():
    hook, handler, _store, clock, secret = make_hook(max_age_s=None)
    deliver(hook, secret, [text_message(wamid(1), NUMBER_A, int(clock()) - 60, "a minute ago")])
    deliver(hook, secret, [text_message(wamid(2), NUMBER_A, int(clock()) - 3600, "an hour ago")])
    assert handler.ids() == [wamid(1)]


def test_FR_CHN_02_stale_message_does_not_claim_its_id():
    hook, _handler, store, clock, secret = make_hook()
    deliver(hook, secret, [text_message(wamid(1), NUMBER_A, int(clock()) - MAX_AGE_S - 1, "old")])
    assert store.claims == []


# ---------------------------------------------------------------------------
# Ordering per user (sender).


def test_FR_CHN_02_messages_in_one_delivery_run_in_timestamp_order_per_sender():
    hook, handler, _store, _clock, secret = make_hook()
    messages = [
        text_message(wamid(3), NUMBER_A, T0 + 33, "a3"),
        text_message(wamid(2), NUMBER_B, T0 + 32, "b2"),
        text_message(wamid(1), NUMBER_A, T0 + 31, "a1"),
        text_message(wamid(4), NUMBER_B, T0 + 30, "b1"),
        text_message(wamid(5), NUMBER_A, T0 + 32, "a2"),
    ]
    deliver(hook, secret, messages)
    per_sender = defaultdict(list)
    for m in handler.messages:
        per_sender[m.sender].append(m.text)
    assert per_sender[NUMBER_A] == ["a1", "a2", "a3"]
    assert per_sender[NUMBER_B] == ["b1", "b2"]
    assert len(handler.messages) == 5


def test_FR_CHN_02_equal_timestamps_keep_payload_order():
    hook, handler, _store, _clock, secret = make_hook()
    deliver(
        hook,
        secret,
        [text_message(wamid(i), NUMBER_A, T0 + 30, f"m{i}") for i in (3, 1, 2)],
    )
    assert handler.ids() == [wamid(3), wamid(1), wamid(2)]


def test_FR_CHN_02_deliveries_in_sequence_run_in_arrival_order():
    hook, handler, _store, _clock, secret = make_hook()
    for i in range(1, 6):
        deliver(hook, secret, [text_message(wamid(i), NUMBER_A, T0 + 30 + i, f"m{i}")])
    assert handler.ids() == [wamid(i) for i in range(1, 6)]


def test_FR_CHN_02_late_unseen_message_inside_the_window_is_still_processed_once():
    hook, handler, _store, _clock, secret = make_hook()
    deliver(hook, secret, [text_message(wamid(2), NUMBER_A, T0 + 40, "newer")])
    late = text_message(wamid(1), NUMBER_A, T0 + 35, "older but unseen")
    deliver(hook, secret, [late])
    deliver(hook, secret, [late])
    assert Counter(handler.ids()) == {wamid(1): 1, wamid(2): 1}


class _Probe:
    """Handler double that sleeps inside the call and tracks how many calls per sender overlap."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active: dict[str, int] = defaultdict(int)
        self.max_active: dict[str, int] = defaultdict(int)
        self.ids: list[str] = []

    def __call__(self, message: InboundMessage) -> None:
        with self._lock:
            self.active[message.sender] += 1
            self.max_active[message.sender] = max(self.max_active[message.sender], self.active[message.sender])
        time.sleep(0.01)
        with self._lock:
            self.active[message.sender] -= 1
            self.ids.append(message.message_id)


def _run_threads(targets):
    barrier = threading.Barrier(len(targets))
    errors: list[BaseException] = []

    def wrap(fn):
        def run():
            try:
                barrier.wait(timeout=5)
                fn()
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)

        return run

    threads = [threading.Thread(target=wrap(t)) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors, errors
    assert not any(t.is_alive() for t in threads)


def test_FR_CHN_02_concurrent_deliveries_for_one_sender_never_overlap():
    probe = _Probe()
    hook, _h, _store, _clock, secret = make_hook(handler=probe)
    messages = [text_message(wamid(i), NUMBER_A, T0 + 30 + i, f"m{i}") for i in range(1, 7)]
    _run_threads([lambda m=m: deliver(hook, secret, [m]) for m in messages])
    assert probe.max_active[NUMBER_A] == 1
    assert sorted(probe.ids) == sorted(m["id"] for m in messages)


def test_FR_CHN_02_same_delivery_arriving_concurrently_is_processed_once():
    probe = _Probe()
    hook, _h, _store, _clock, secret = make_hook(handler=probe)
    body = delivery_body([text_message(wamid(1), NUMBER_A, T0 + 30, "once")])
    header = sign(secret, body)
    _run_threads([lambda: hook.receive(body, header) for _ in range(8)])
    assert probe.ids == [wamid(1)]


# ---------------------------------------------------------------------------
# Property tests: exactly once under shuffled duplicate deliveries, and per-sender order.

SENDERS = [NUMBER_A, NUMBER_B, "6594440004"]


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    specs=st.lists(
        st.tuples(st.sampled_from(SENDERS), st.integers(min_value=0, max_value=30)), min_size=1, max_size=12
    ),
    copies=st.lists(st.integers(min_value=1, max_value=3), min_size=12, max_size=12),
    rng=st.randoms(use_true_random=False),
)
def test_FR_CHN_02_property_shuffled_duplicate_deliveries_process_each_message_exactly_once(specs, copies, rng):
    hook, handler, _store, _clock, secret = make_hook()
    messages = [text_message(wamid(i), sender, T0 + off, f"m{i}") for i, (sender, off) in enumerate(specs)]
    deliveries = []
    for i, m in enumerate(messages):
        deliveries.extend([m] * copies[i])
    rng.shuffle(deliveries)
    results = Counter()
    for m in deliveries:
        for o in deliver(hook, secret, [m]).outcomes:
            results[o.result] += 1
    assert Counter(handler.ids()) == Counter(m["id"] for m in messages)
    assert results["processed"] == len(messages)
    assert results["duplicate"] == len(deliveries) - len(messages)
    assert results["stale"] == 0


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    senders=st.lists(st.sampled_from(SENDERS), min_size=1, max_size=15),
    batch_size=st.integers(min_value=1, max_value=5),
    replays=st.integers(min_value=0, max_value=3),
    seed=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_FR_CHN_02_property_per_sender_order_follows_timestamps_and_replays_change_nothing(
    senders, batch_size, replays, seed
):
    rng = random.Random(seed)
    hook, handler, _store, _clock, secret = make_hook()
    # Message i has timestamp T0 + i, so the expected order per sender is index order.
    messages = [text_message(wamid(i), s, T0 + i, f"m{i}") for i, s in enumerate(senders)]
    batches = [messages[i : i + batch_size] for i in range(0, len(messages), batch_size)]
    sent_bodies = []
    for batch in batches:
        shuffled = list(batch)
        rng.shuffle(shuffled)  # within a delivery the payload order is arbitrary
        body = delivery_body(shuffled)
        sent_bodies.append(body)
        hook.receive(body, sign(secret, body))
    for _ in range(replays):  # later replays of any earlier delivery
        body = rng.choice(sent_bodies)
        hook.receive(body, sign(secret, body))
    assert Counter(handler.ids()) == Counter(m["id"] for m in messages)
    for sender in set(senders):
        got = [int(m.message_id.removeprefix("wamid.TEST")) for m in handler.messages if m.sender == sender]
        assert got == sorted(got)
