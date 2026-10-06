"""FR-CHN-13 "Threaded send via Gmail through the outbox, exactly once" (PRD 11.6). Acceptance test: "Retry storms never
duplicate a send". Sources: PRD 11.2 ("Send in the same thread"), 11.4 Threading ("Replies stay in the thread with
correct reply headers") and Undo, 8.5 and FR-AGT-11 (side effects through the outbox, exactly once), OB-02 and OB-03
(contracts/outbox.rules.md). API pinned in API_FR_CHN_13.md.

End to end: the real Drafter, Autopilot, tilo_connectors Outbox and GmailAdapter; Gmail itself is a fake
(`_chn13_lib.FakeGmailApi`). No real send, no network.
"""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from _chn11_lib import parse_ts
from _chn13_lib import (
    DAVID,
    USER,
    Line,
    SimulatedCrash,
    card_entry,
    make_line,
    needs_send_module,
    outbox_skips_ob01_evidence,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

SUBJECT = "Re: Engine tuneup scheduling"


@pytest.fixture(autouse=True, scope="module")
def _ob01_evidence_is_not_this_ticket():
    with outbox_skips_ob01_evidence():
        yield


def _one_line(value: str | None) -> str | None:
    return None if value is None else " ".join(value.split())


def assert_threaded(line: Line, thread, draft) -> None:
    """Every mail Gmail accepted is a reply in the card's thread, answering the message replied to."""
    for mail in line.api.sent:
        assert mail.thread_id == thread.thread_id, "a reply must go into the thread, never become a new email"
        assert _one_line(mail.header("In-Reply-To")) == draft.in_reply_to
        assert _one_line(mail.header("References")) == draft.references
        assert mail.header("Subject") == SUBJECT


def test_FR_CHN_13_l1_send_is_one_reply_in_the_same_thread_with_reply_headers() -> None:
    line = make_line("L1")
    thread = line.thread()
    ctx, result = line.draft(thread)
    card = line.ap.preview(USER, ctx, result)
    assert (card.level, card.outbox_id) == ("L1", None)
    assert line.api.sent == [], "nothing goes to Gmail before the owner's Send"

    outcome = line.ap.send(USER, card.card_id)
    assert outcome.status == "queued"
    line.dispatch()

    assert len(line.api.sent) == 1
    assert_threaded(line, thread, result.draft)
    mail = line.api.sent[0]
    assert mail.addresses("To", "Cc", "Bcc") == [DAVID]
    assert mail.body().rstrip("\n") == card.body.rstrip("\n")
    entry = card_entry(line)
    assert entry["id"] == outcome.outbox_id
    assert (entry["state"], entry["destination"], entry["recipients"]) == ("sent", thread.thread_id, [DAVID])
    transfers = line.transfers_of(entry["id"])
    assert transfers, "a sent entry emits data.transfer"
    for part in transfers:
        assert part["authz"] == entry["authz"] and entry["authz"]["by"] == "person"
        assert part["data"]["artifact"] == entry["item"] and part["data"]["direction"] == "out"


def test_FR_CHN_13_l2_send_leaves_after_the_undo_window_in_the_thread_exactly_once() -> None:
    line = make_line("L2")
    thread = line.thread()
    ctx, result = line.draft(thread)
    card = line.ap.preview(USER, ctx, result)
    assert card.level == "L2" and card.outbox_id is not None

    line.advance(59)
    line.storm(10)
    assert line.api.sent == [], "nothing leaves inside the 60 s undo window"

    line.advance(1)
    line.storm(25, line.outbox, line.new_outbox())

    assert len(line.api.sent) == 1
    assert_threaded(line, thread, result.draft)
    entry = card_entry(line)
    created = parse_ts(entry["created_at"]).timestamp()
    assert line.api.sent[0].at >= created + 60
    assert entry["state"] == "sent" and entry["authz"]["by"] == "policy"
    assert {p["data"]["outbox_id"] for p in line.transfers} == {entry["id"]}


@pytest.mark.parametrize("level", ["L1", "L2"])
def test_FR_CHN_13_repeated_and_concurrent_send_taps_make_one_entry_and_one_email(level: str) -> None:
    line = make_line(level)
    thread = line.thread()
    ctx, result = line.draft(thread)
    card = line.ap.preview(USER, ctx, result)

    outcomes = [line.ap.send(USER, card.card_id) for _ in range(3)]
    outcomes += [line.bench.new_autopilot().send(USER, card.card_id) for _ in range(2)]
    barrier = threading.Barrier(8)
    lock = threading.Lock()

    def tap() -> None:
        ap = line.bench.new_autopilot()  # a second Cloud Run instance, or the same tap delivered twice
        barrier.wait()
        outcome = ap.send(USER, card.card_id)
        with lock:
            outcomes.append(outcome)

    workers = [threading.Thread(target=tap) for _ in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    line.advance(61)
    line.storm(25, line.outbox, line.new_outbox())

    entry = card_entry(line)
    assert {o.outbox_id for o in outcomes} == {entry["id"]}
    assert {o.status for o in outcomes} <= {"queued", "scheduled"}
    assert len(line.api.sent) == 1, "a duplicate Send never becomes a second email"
    assert_threaded(line, thread, result.draft)


def test_FR_CHN_13_retry_storm_through_gmail_errors_never_duplicates_the_send() -> None:
    line = make_line("L1")
    thread = line.thread()
    ctx, result = line.draft(thread)
    card = line.ap.preview(USER, ctx, result)
    line.ap.send(USER, card.card_id)
    line.api.fault("unavailable", "dropped", "unavailable", "lost", "unavailable", "dropped")

    line.storm(40, line.outbox, line.new_outbox(), line.new_outbox())

    assert len(line.api.sent) == 1
    assert_threaded(line, thread, result.draft)
    entry = card_entry(line)
    assert entry["state"] == "sent"
    assert {p["data"]["outbox_id"] for p in line.transfers} == {entry["id"]}


def test_FR_CHN_13_lost_answer_after_gmail_accepted_is_found_not_sent_again() -> None:
    line = make_line("L1")
    thread = line.thread()
    ctx, result = line.draft(thread)
    card = line.ap.preview(USER, ctx, result)
    line.ap.send(USER, card.card_id)
    line.api.fault("lost")

    line.dispatch()
    assert len(line.api.sent) == 1, "Gmail accepted it; only the answer was lost"
    line.storm(25, line.outbox, line.new_outbox())

    assert len(line.api.sent) == 1
    assert card_entry(line)["state"] == "sent"


def test_FR_CHN_13_dispatcher_dies_after_gmail_accepted_and_the_restart_sends_nothing_more() -> None:
    line = make_line("L2")
    thread = line.thread()
    ctx, result = line.draft(thread)
    line.ap.preview(USER, ctx, result)
    line.advance(60)
    line.api.fault("crash")

    with pytest.raises(SimulatedCrash):
        line.dispatch()
    assert len(line.api.sent) == 1

    restarted = line.new_outbox()  # a new tilo-connectors instance over the same store
    line.advance(31)  # past any send lease the dead instance held
    line.storm(25, restarted)

    assert len(line.api.sent) == 1
    assert_threaded(line, thread, result.draft)
    entry = card_entry(line)
    assert entry["state"] == "sent"
    assert line.transfers_of(entry["id"]), "the restart still records the send as data.transfer"


def test_FR_CHN_13_eight_dispatcher_instances_racing_send_one_email() -> None:
    line = make_line("L2")
    thread = line.thread()
    ctx, result = line.draft(thread)
    line.ap.preview(USER, ctx, result)
    line.advance(60)
    outboxes = [line.new_outbox() for _ in range(8)]
    barrier = threading.Barrier(len(outboxes))
    errors: list[BaseException] = []

    def run(outbox) -> None:
        barrier.wait()
        try:
            for _ in range(5):
                line.dispatch(outbox)
        except BaseException as exc:  # surfaced below, never swallowed
            errors.append(exc)

    workers = [threading.Thread(target=run, args=(o,)) for o in outboxes]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    assert errors == []
    assert len(line.api.sent) == 1
    assert_threaded(line, thread, result.draft)


def test_FR_CHN_13_cancelled_in_the_undo_window_then_a_retry_storm_sends_nothing() -> None:
    line = make_line("L2")
    thread = line.thread()
    ctx, result = line.draft(thread)
    card = line.ap.preview(USER, ctx, result)
    line.advance(30)

    assert line.ap.cancel(USER, card.card_id).status == "cancelled"
    line.advance(120)
    line.storm(25, line.outbox, line.new_outbox())
    line.ap.send(USER, card.card_id)  # a late, duplicate Send tap
    line.storm(10)

    assert line.api.sent == []
    assert card_entry(line)["state"] == "cancelled"
    assert line.transfers == []


_OPS = st.one_of(
    st.tuples(st.just("send"), st.integers(0, 1)),
    st.tuples(st.just("cancel"), st.just(0)),
    st.tuples(st.just("dispatch"), st.integers(0, 1)),
    st.tuples(st.just("fault"), st.sampled_from(["unavailable", "dropped", "lost", "crash"])),
    st.tuples(st.just("advance"), st.integers(1, 45)),
)


@needs_send_module
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(level=st.sampled_from(["L1", "L2"]), ops=st.lists(_OPS, max_size=25))
def test_FR_CHN_13_property_any_storm_sends_each_card_at_most_once_and_always_in_its_thread(
    level: str, ops: list[tuple[str, object]]
) -> None:
    """Under any interleaving of Send taps (two instances), Cancel, dispatch (two instances), Gmail faults (503,
    dropped request, lost answer, process death) and clock moves: at most one email per card, always in its thread
    with reply headers; nothing after a confirmed cancel; a policy send never before created_at + 60 s. Once the storm
    is over, a card that was sent for and not cancelled reaches Gmail exactly once."""
    line = make_line(level)
    thread = line.thread()
    ctx, result = line.draft(thread)
    card = line.ap.preview(USER, ctx, result)
    autopilots = [line.ap, line.bench.new_autopilot()]
    outboxes = [line.outbox, line.new_outbox()]
    cancelled = False

    def check() -> None:
        assert len(line.api.sent) <= 1, "retry storms never duplicate a send"
        assert_threaded(line, thread, result.draft)
        assert not (cancelled and line.api.sent), "no send after a confirmed cancel"
        assert len(line.entries()) <= 1, "one outbox entry per card"
        for entry in line.entries():
            if entry["risk_tier"] == "T3":
                assert entry["authz"]["by"] == "person"
            if entry["authz"]["by"] == "policy" and line.api.sent:
                window = timedelta(seconds=entry["undo_window_s"])
                assert entry["undo_window_s"] >= 60
                assert line.api.sent[0].at >= (parse_ts(entry["created_at"]) + window).timestamp()

    for op, arg in ops:
        if op == "send":
            autopilots[int(arg)].send(USER, card.card_id)  # type: ignore[call-overload]
        elif op == "cancel":
            outcome = line.ap.cancel(USER, card.card_id)
            cancelled = cancelled or (outcome.status == "cancelled" and not line.api.sent)
        elif op == "dispatch":
            try:
                line.dispatch(outboxes[int(arg)])  # type: ignore[call-overload]
            except SimulatedCrash:
                pass
        elif op == "fault":
            line.api.fault(str(arg))
        else:
            line.advance(int(arg))  # type: ignore[call-overload]
        check()

    line.api.clear_faults()
    line.advance(120)
    for outbox in outboxes * 3:
        line.dispatch(outbox)
    check()
    should_send = bool(line.entries()) and not cancelled and line.entries()[0]["state"] != "cancelled"
    assert len(line.api.sent) == (1 if should_send else 0)
