"""FR-CHN-08: push notifications are handled through Gmail history; each new message is triaged once,
in mailbox order, however pushes are replayed, duplicated, reordered or delivered concurrently.

PRD 11.2 (push notification -> triage), 11.6 FR-CHN-08, and the FR-CHN-02 webhook rule this service
already applies (idempotent, ordered per user; duplicates processed once). A Gmail push carries only the
mailbox's latest history id; the watcher lists history from its own cursor, so a lost or late push loses
nothing. API_FR_CHN_08.md "MailWatcher".
"""

from __future__ import annotations

import threading

from _chn08_lib import KAI, RIYA, SAM, make_rig
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


def _starts(rig, user):
    return [int(c.args["start_history_id"]) for c in rig.mailbox.calls_of("list_history", user)]


def test_FR_CHN_08_one_push_triages_every_new_message_in_mailbox_order():
    rig = make_rig()
    rig.watcher.start(RIYA)
    mails = [rig.mailbox.deliver(RIYA) for _ in range(4)]

    response = rig.push(RIYA)

    assert 200 <= response.status < 300
    assert rig.triage.ids(RIYA) == [m.message_id for m in mails]


def test_FR_CHN_08_history_pages_are_all_followed_before_the_cursor_moves():
    rig = make_rig(page_size=3)
    rig.watcher.start(RIYA)
    mails = [rig.mailbox.deliver(RIYA) for _ in range(8)]

    rig.push(RIYA)

    assert rig.triage.ids(RIYA) == [m.message_id for m in mails]
    tokens = [c.args["page_token"] for c in rig.mailbox.calls_of("list_history", RIYA)]
    assert tokens == [None, "p3", "p6"], "every page fetched, in order"


def test_FR_CHN_08_duplicate_and_replayed_pushes_triage_each_message_once():
    rig = make_rig()
    rig.watcher.start(RIYA)
    mail = rig.mailbox.deliver(RIYA)

    for _ in range(3):
        rig.push(RIYA, mail.history_id)  # Pub/Sub redelivery: the same notification again
    rig.clock.advance(3600)
    rig.push(RIYA, mail.history_id)  # replayed an hour later

    assert rig.triage.ids(RIYA) == [mail.message_id]


def test_FR_CHN_08_message_listed_in_two_history_records_is_triaged_once():
    rig = make_rig()
    rig.mailbox.repeat_ids = True
    rig.watcher.start(RIYA)
    first, second = rig.mailbox.deliver(RIYA), rig.mailbox.deliver(RIYA)

    rig.push(RIYA)

    assert rig.triage.ids(RIYA) == [first.message_id, second.message_id]


def test_FR_CHN_08_out_of_order_pushes_never_move_the_cursor_back():
    rig = make_rig()
    rig.watcher.start(RIYA)
    a, b, c = (rig.mailbox.deliver(RIYA) for _ in range(3))

    rig.push(RIYA, c.history_id)
    rig.push(RIYA, a.history_id)  # late, older notification
    rig.push(RIYA, b.history_id)
    d = rig.mailbox.deliver(RIYA)
    rig.push(RIYA, d.history_id)

    assert rig.triage.ids(RIYA) == [a.message_id, b.message_id, c.message_id, d.message_id]
    starts = _starts(rig, RIYA)
    assert starts == sorted(starts), "history is always listed from a cursor that only moves forward"
    assert starts[-1] >= c.history_id, "after c was handled, history is listed from c's point on"


def test_FR_CHN_08_a_late_push_for_handled_mail_triages_nothing_new():
    rig = make_rig()
    rig.watcher.start(RIYA)
    a = rig.mailbox.deliver(RIYA)
    rig.push(RIYA, a.history_id)

    rig.push(RIYA, a.history_id - 1)

    assert rig.triage.ids(RIYA) == [a.message_id]


def test_FR_CHN_08_a_push_only_reads_its_own_users_history():
    rig = make_rig()
    for user in (RIYA, SAM, KAI):
        rig.watcher.start(user)
    riya = rig.mailbox.deliver(RIYA)
    rig.mailbox.deliver(SAM)

    rig.push(RIYA)

    assert rig.triage.ids(RIYA) == [riya.message_id]
    assert rig.triage.ids(SAM) == []
    assert rig.mailbox.calls_of("list_history", SAM) == []
    assert rig.mailbox.calls_of("list_history", KAI) == []


def test_FR_CHN_08_replay_after_a_restart_does_not_triage_again():
    rig = make_rig()
    rig.watcher.start(RIYA)
    mails = [rig.mailbox.deliver(RIYA) for _ in range(3)]
    rig.push(RIYA)

    restarted = rig.new_watcher()  # same store and dedupe, fresh process
    for m in mails:
        restarted.on_push(RIYA, str(m.history_id))

    assert rig.triage.ids(RIYA) == [m.message_id for m in mails]


def test_FR_CHN_08_concurrent_pushes_in_one_instance_triage_once_and_serialised_per_user():
    rig = make_rig(latency_s=0.0, triage_s=0.0, race_window_s=0.002)
    rig.watcher.start(RIYA)
    rig.watcher.start(SAM)
    mails = {u: [rig.mailbox.deliver(u) for _ in range(6)] for u in (RIYA, SAM)}

    def deliver(user: str, hid: int) -> None:
        rig.push(user, hid)

    threads = [
        threading.Thread(target=deliver, args=(u, m.history_id))
        for u in (RIYA, SAM)
        for m in mails[u]
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    for user in (RIYA, SAM):
        assert rig.triage.ids(user) == [m.message_id for m in mails[user]], "once each, in mailbox order"
    assert rig.triage.overlaps == [], "one user's mail is never triaged by two threads at once"


def test_FR_CHN_08_two_instances_on_the_same_stores_triage_each_message_once():
    rig = make_rig(latency_s=0.0, triage_s=0.0, race_window_s=0.002)
    rig.watcher.start(RIYA)
    other = rig.new_watcher()
    mails = [rig.mailbox.deliver(RIYA) for _ in range(5)]
    hid = str(mails[-1].history_id)

    threads = [threading.Thread(target=w.on_push, args=(RIYA, hid)) for w in (rig.watcher, other) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    ids = rig.triage.ids(RIYA)
    assert sorted(ids) == sorted(m.message_id for m in mails)
    assert len(ids) == len(set(ids)), "no message triaged twice across instances"


# ---------------------------------------------------------------------------
# Property: any interleaving of arrivals, (duplicate, late, lost) pushes and sweeps


_ops = st.lists(
    st.one_of(
        st.tuples(st.just("mail"), st.sampled_from([RIYA, SAM])),
        st.tuples(st.just("push"), st.integers(min_value=0, max_value=40)),  # index into past mail (any order)
        st.tuples(st.just("tick"), st.floats(min_value=0.0, max_value=120.0)),
        st.tuples(st.just("restart"), st.just(0)),
    ),
    min_size=1,
    max_size=40,
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ops=_ops)
def test_FR_CHN_08_property_each_new_message_triaged_exactly_once_in_order(ops):
    from tilo_channels.gmail_watch import POLL_INTERVAL_S

    rig = make_rig(latency_s=0.05, triage_s=0.5)
    rig.watcher.start(RIYA)
    rig.watcher.start(SAM)
    watcher = rig.watcher
    delivered = []
    for op, arg in ops:
        if op == "mail":
            delivered.append(rig.mailbox.deliver(arg))
        elif op == "push" and delivered:
            m = delivered[arg % len(delivered)]
            watcher.on_push(m.user_id, str(m.history_id))
        elif op == "tick":
            rig.clock.advance(arg)
            watcher.poll_due()
        elif op == "restart":
            watcher = rig.new_watcher()
        for user in (RIYA, SAM):
            ids = rig.triage.ids(user)
            assert len(ids) == len(set(ids)), "never triaged twice"
            starts = _starts(rig, user)
            assert starts == sorted(starts), "the cursor never moves back"

    rig.clock.advance(POLL_INTERVAL_S + 1)  # a final sweep catches whatever no push announced
    watcher.poll_due()
    for user in (RIYA, SAM):
        assert rig.triage.ids(user) == [m.message_id for m in delivered if m.user_id == user]
