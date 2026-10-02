"""FR-CHN-08: Gmail push watch registration, renewal before the 7-day expiry, and stop.

PRD 11.2 (Gmail -> Tilo by push notification), 11.6 FR-CHN-08, 6.3 (Pub/Sub carries Gmail push
notifications; Cloud Tasks/Scheduler run the autopilot polling fallback). Gmail expires a users.watch
registration after 7 days, so the watcher must re-register before then. API_FR_CHN_08.md.
"""

from __future__ import annotations

import contextlib

import pytest
from _chn08_lib import DAY_S, RIYA, SAM, TOPIC, WATCH_TTL_S, make_rig


def test_FR_CHN_08_module_constants_match_gmail_and_the_prd():
    from tilo_channels import gmail_watch as gw

    assert gw.WATCH_TTL_S == WATCH_TTL_S, "Gmail watch registrations last 7 days"
    assert 0 < gw.RENEW_BEFORE_S < gw.WATCH_TTL_S
    assert gw.POLL_INTERVAL_S > 0
    assert 1 <= gw.RESYNC_MAX_MESSAGES <= 50, "bounded by config/connectors.yaml gmail limits.batch_size"


def test_FR_CHN_08_start_registers_an_inbox_watch_on_the_configured_topic():
    rig = make_rig()

    rig.watcher.start(RIYA)

    watches = rig.mailbox.calls_of("watch", RIYA)
    assert len(watches) == 1
    assert watches[0].args["topic_name"] == TOPIC
    assert watches[0].args["label_ids"] == ["INBOX"]
    assert rig.mailbox.watch_active(RIYA)
    assert rig.mailbox.calls_of("watch", SAM) == [], "only the user started is watched"


def test_FR_CHN_08_mail_from_before_start_is_not_triaged_but_new_mail_is():
    """PRD 11.6: "New mail is triaged". Mail already in the inbox when the watch starts is not new
    (API_FR_CHN_08.md default: the cursor starts at the history id watch() returns)."""
    rig = make_rig()
    old = rig.mailbox.deliver(RIYA)

    rig.watcher.start(RIYA)
    new = rig.mailbox.deliver(RIYA)
    response = rig.push(RIYA)

    assert 200 <= response.status < 300
    assert rig.triage.ids(RIYA) == [new.message_id]
    assert old.message_id not in rig.triage.all_ids()


def test_FR_CHN_08_renew_due_does_nothing_for_a_fresh_watch():
    rig = make_rig()
    rig.watcher.start(RIYA)

    rig.clock.advance(60)
    rig.watcher.renew_due()

    assert len(rig.mailbox.calls_of("watch", RIYA)) == 1, "no re-watch while the watch is far from expiry"


def test_FR_CHN_08_watch_is_renewed_before_it_expires():
    from tilo_channels.gmail_watch import RENEW_BEFORE_S

    rig = make_rig()
    rig.watcher.start(RIYA)
    first_expiry = rig.mailbox.watch_expires_at(RIYA)
    assert first_expiry is not None

    rig.clock.advance(first_expiry - rig.clock() - RENEW_BEFORE_S + 1)  # inside the renewal window
    rig.watcher.renew_due()

    assert len(rig.mailbox.calls_of("watch", RIYA)) == 2
    renewed = rig.mailbox.watch_expires_at(RIYA)
    assert renewed is not None and renewed > first_expiry
    assert rig.clock() < first_expiry, "renewed before the old registration lapsed"


def test_FR_CHN_08_watch_never_lapses_over_thirty_days_of_hourly_sweeps():
    rig = make_rig()
    rig.watcher.start(RIYA)
    rig.watcher.start(SAM)

    for _ in range(30 * 24):
        rig.clock.advance(3600)
        rig.watcher.renew_due()
        assert rig.mailbox.watch_active(RIYA), (
            f"Riya's watch lapsed at day {(rig.clock() - rig.mailbox.calls[0].at) / DAY_S:.2f}"
        )
        assert rig.mailbox.watch_active(SAM)
    renewals = len(rig.mailbox.calls_of("watch", RIYA)) - 1
    assert renewals >= 30 // 7, "re-registered at least once per 7-day lifetime"


def test_FR_CHN_08_a_failed_renewal_is_retried_on_the_next_sweep_before_expiry():
    from tilo_channels.gmail_watch import RENEW_BEFORE_S

    rig = make_rig()
    rig.watcher.start(RIYA)
    expiry = rig.mailbox.watch_expires_at(RIYA)
    assert expiry is not None
    rig.clock.advance(expiry - rig.clock() - RENEW_BEFORE_S + 1)

    rig.mailbox.fail_next["watch"] = 1
    with contextlib.suppress(Exception):  # the sweeper may report the failure; it must not lose the user
        rig.watcher.renew_due()
    rig.clock.advance(min(3600.0, RENEW_BEFORE_S / 4))
    rig.watcher.renew_due()

    assert rig.mailbox.watch_expires_at(RIYA) is not None
    assert rig.mailbox.watch_expires_at(RIYA) > expiry, "the second sweep renewed the watch"


def test_FR_CHN_08_renewal_does_not_skip_mail_that_arrived_before_it():
    """watch() returns the mailbox's current history id. Replacing the cursor with it would skip mail
    that arrived, push lost, just before the renewal."""
    from tilo_channels.gmail_watch import RENEW_BEFORE_S

    rig = make_rig()
    rig.watcher.start(RIYA)
    expiry = rig.mailbox.watch_expires_at(RIYA)
    assert expiry is not None
    rig.clock.advance(expiry - rig.clock() - RENEW_BEFORE_S + 1)

    unpushed = rig.mailbox.deliver(RIYA)  # its push was lost
    rig.watcher.renew_due()
    later = rig.mailbox.deliver(RIYA)
    rig.push(RIYA)

    assert rig.triage.ids(RIYA) == [unpushed.message_id, later.message_id]


def test_FR_CHN_08_stop_unregisters_and_later_pushes_and_polls_do_nothing():
    from tilo_channels.gmail_watch import POLL_INTERVAL_S

    rig = make_rig()
    rig.watcher.start(RIYA)
    rig.watcher.start(SAM)

    rig.watcher.stop(RIYA)
    assert len(rig.mailbox.calls_of("stop_watch", RIYA)) == 1
    assert not rig.mailbox.watch_active(RIYA)

    rig.mailbox.deliver(RIYA)
    response = rig.push(RIYA)
    rig.clock.advance(POLL_INTERVAL_S + 1)
    rig.watcher.poll_due()
    rig.clock.advance(WATCH_TTL_S)
    rig.watcher.renew_due()

    assert 200 <= response.status < 300, "a push for a stopped user is acknowledged, not retried for ever"
    assert rig.triage.ids(RIYA) == []
    assert rig.mailbox.calls_of("list_history", RIYA) == []
    assert rig.mailbox.calls_of("recent_inbox", RIYA) == []
    assert len(rig.mailbox.calls_of("watch", RIYA)) == 1, "a stopped user is never re-watched"
    assert len(rig.mailbox.calls_of("watch", SAM)) >= 2, "other users keep their watch"


@pytest.mark.parametrize("user", [RIYA])
def test_FR_CHN_08_watch_state_survives_a_restart(user):
    """A new instance on the same store renews and serves the user without calling start() again."""
    from tilo_channels.gmail_watch import RENEW_BEFORE_S

    rig = make_rig()
    rig.watcher.start(user)
    expiry = rig.mailbox.watch_expires_at(user)
    assert expiry is not None
    other = rig.new_watcher()

    rig.clock.advance(expiry - rig.clock() - RENEW_BEFORE_S + 1)
    other.renew_due()
    mail = rig.mailbox.deliver(user)
    other.on_push(user, str(mail.history_id))

    assert len(rig.mailbox.calls_of("watch", user)) == 2
    assert rig.triage.ids(user) == [mail.message_id]
