"""FR-CHN-08: polling fallback. When pushes stop, are lost or fail, the sweeper's poll still triages new
mail within the 60 s budget; an expired history id (Gmail answers 404) triggers one bounded resync.

PRD 11.6 FR-CHN-08 ("Gmail push watch with polling fallback"), 6.3 (Cloud Tasks / Cloud Scheduler run the
"autopilot polling fallback"), NFR-08 (new mail -> triaged <= 60 s p95), NFR-22 (channels queue and retry).
The 404-on-expired-startHistoryId behaviour and the full-sync recovery are Gmail API facts. The resync
bound is `RESYNC_MAX_MESSAGES` (<= the gmail connector's batch_size, 50). API_FR_CHN_08.md "Polling".
"""

from __future__ import annotations

import contextlib

from _chn08_lib import RESYNC_CAP, RIYA, SAM, TRIAGE_P95_S, make_rig


def _poll_interval() -> float:
    from tilo_channels.gmail_watch import POLL_INTERVAL_S

    return float(POLL_INTERVAL_S)


def _sweep_until(rig, deadline: float) -> None:
    """The sweeper calling poll_due() at the module's cadence until `deadline` (fake clock)."""
    step = _poll_interval()
    while rig.clock() < deadline:
        rig.clock.advance(min(step, max(0.0, deadline - rig.clock())) or step)
        rig.watcher.poll_due()


def test_FR_CHN_08_mail_whose_push_never_arrives_is_triaged_by_polling_within_60_s():
    rig = make_rig()
    rig.watcher.start(RIYA)
    mail = rig.mailbox.deliver(RIYA)  # no push at all

    _sweep_until(rig, mail.arrived_at + TRIAGE_P95_S)

    done = rig.triage.first_finish()
    assert mail.message_id in done, "polling found mail no push announced"
    assert done[mail.message_id] - mail.arrived_at <= TRIAGE_P95_S


def test_FR_CHN_08_poll_due_skips_a_user_synced_moments_ago():
    """Polling is the fallback: a user whose history was just read by a push is not polled again at once."""
    rig = make_rig(latency_s=0.0, triage_s=0.0)  # no fake time passes between the push and the sweep
    rig.watcher.start(RIYA)
    rig.mailbox.deliver(RIYA)
    rig.push(RIYA)
    before = len(rig.mailbox.calls_of("list_history", RIYA))

    rig.watcher.poll_due()

    assert len(rig.mailbox.calls_of("list_history", RIYA)) == before


def test_FR_CHN_08_poll_due_lists_history_once_the_poll_interval_has_passed_without_a_push():
    rig = make_rig()
    rig.watcher.start(RIYA)

    rig.clock.advance(_poll_interval() + 1)
    rig.watcher.poll_due()

    assert len(rig.mailbox.calls_of("list_history", RIYA)) >= 1


def test_FR_CHN_08_gap_in_pushes_is_filled_from_history_in_order():
    rig = make_rig()
    rig.watcher.start(RIYA)
    lost1, lost2 = rig.mailbox.deliver(RIYA), rig.mailbox.deliver(RIYA)
    third = rig.mailbox.deliver(RIYA)

    rig.push(RIYA, third.history_id)  # the only push that arrived

    assert rig.triage.ids(RIYA) == [lost1.message_id, lost2.message_id, third.message_id]


def test_FR_CHN_08_transient_history_failure_on_push_loses_no_mail():
    rig = make_rig()
    rig.watcher.start(RIYA)
    mail = rig.mailbox.deliver(RIYA)
    rig.mailbox.fail_next["list_history"] = 1

    with contextlib.suppress(Exception):  # the push may be answered 5xx for redelivery
        rig.watcher.on_push(RIYA, str(mail.history_id))
    _sweep_until(rig, mail.arrived_at + TRIAGE_P95_S)

    assert rig.triage.ids(RIYA) == [mail.message_id]
    assert rig.triage.first_finish()[mail.message_id] - mail.arrived_at <= TRIAGE_P95_S


def test_FR_CHN_08_one_users_failing_mailbox_does_not_block_the_others():
    rig = make_rig()
    rig.watcher.start(RIYA)
    rig.watcher.start(SAM)
    rig.mailbox.fail_users.add(RIYA)
    sam_mail = rig.mailbox.deliver(SAM)
    rig.mailbox.deliver(RIYA)

    rig.clock.advance(_poll_interval() + 1)
    rig.watcher.poll_due()  # must not raise because Riya's mailbox fails

    assert rig.triage.ids(SAM) == [sam_mail.message_id]


def test_FR_CHN_08_expired_history_id_triggers_one_bounded_resync():
    rig = make_rig()
    rig.watcher.start(RIYA)
    seen = rig.mailbox.deliver(RIYA)
    rig.push(RIYA)
    unseen = [rig.mailbox.deliver(RIYA) for _ in range(3)]
    rig.mailbox.expire_history(RIYA)  # e.g. Tilo was down longer than Gmail keeps history

    rig.push(RIYA)

    resyncs = rig.mailbox.calls_of("recent_inbox", RIYA)
    assert len(resyncs) == 1, "one resync, not a loop"
    assert 1 <= resyncs[0].args["max_results"] <= RESYNC_CAP
    assert rig.triage.ids(RIYA) == [seen.message_id] + [m.message_id for m in unseen], (
        "unseen recent mail triaged oldest first; mail triaged before is not triaged again"
    )


def test_FR_CHN_08_resync_is_capped_at_resync_max_messages():
    from tilo_channels.gmail_watch import RESYNC_MAX_MESSAGES

    rig = make_rig()
    rig.watcher.start(RIYA)
    flood = [rig.mailbox.deliver(RIYA) for _ in range(120)]
    rig.mailbox.expire_history(RIYA)

    rig.push(RIYA)

    triaged = rig.triage.ids(RIYA)
    assert len(triaged) <= RESYNC_MAX_MESSAGES
    newest = [m.message_id for m in flood][-len(triaged) :] if triaged else []
    assert triaged == newest, "the newest mail, oldest of those first"
    assert len(rig.mailbox.calls_of("recent_inbox", RIYA)) == 1


def test_FR_CHN_08_after_a_resync_history_resumes_from_the_resync_point():
    rig = make_rig()
    rig.watcher.start(RIYA)
    rig.mailbox.deliver(RIYA)
    rig.mailbox.expire_history(RIYA)
    rig.push(RIYA)
    resync_point = rig.mailbox.current_history_id(RIYA)

    later = rig.mailbox.deliver(RIYA)
    rig.push(RIYA)

    assert rig.triage.ids(RIYA)[-1] == later.message_id
    assert len(rig.mailbox.calls_of("recent_inbox", RIYA)) == 1, "no second resync once the cursor is fresh"
    last = rig.mailbox.calls_of("list_history", RIYA)[-1]
    assert int(last.args["start_history_id"]) >= resync_point, "history resumes from the resync point"
    ids = rig.triage.ids(RIYA)
    assert len(ids) == len(set(ids))


def test_FR_CHN_08_expired_history_found_by_polling_also_resyncs_once():
    rig = make_rig()
    rig.watcher.start(RIYA)
    mail = rig.mailbox.deliver(RIYA)
    rig.mailbox.expire_history(RIYA)

    _sweep_until(rig, mail.arrived_at + TRIAGE_P95_S)

    assert rig.triage.ids(RIYA) == [mail.message_id]
    assert len(rig.mailbox.calls_of("recent_inbox", RIYA)) == 1


def test_FR_CHN_08_watcher_never_fetches_message_content():
    """FR-CHN-08 only finds new mail; reading it is triage's job (FR-CHN-09) through the quarantined reader
    (PRD 16.3). The watcher touches ids and history ids only."""
    rig = make_rig()
    rig.watcher.start(RIYA)
    rig.mailbox.deliver(RIYA)
    rig.push(RIYA)
    rig.mailbox.expire_history(RIYA)
    rig.mailbox.deliver(RIYA)
    rig.push(RIYA)

    methods = {c.method for c in rig.mailbox.calls}
    assert methods <= {"watch", "stop_watch", "list_history", "recent_inbox"}
