"""NFR-08 (PRD 17.1): "New mail -> triaged | <= 60 s p95".

Measured from the moment mail lands in the inbox to the moment the triage step returns, on the code's own
injectable clock (`FakeClock`), with fake mailbox, store, triage and OIDC verifier: nothing sleeps for a
minute, nothing touches the network. Default taken where the PRD is silent: "triaged" is the end of the
triage step (FR-CHN-09 through tilo-api), the same reading FR-CHN-08 uses (PRD 11.6), and "new mail" is mail
that arrives after the watch starts (BQ-121).

FR-CHN-08's latency test runs four fixed scenarios of 300 mails. These add what it does not: the cadence the
code enforces against the 60 s bound, the same p95 stated a second way (the share of mails over 60 s), a
worst-case (not only p95) bound for the polling fallback, a burst on one mailbox, and a property over seeds,
push delay, loss and duplication.
"""

from __future__ import annotations

import pytest
from _chn08_lib import (
    KAI,
    RIYA,
    SAM,
    TRIAGE_P95_S,
    Scenario,
    make_rig,
    p95,
    run_scenario,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

BOUND_S = 60.0  # NFR-08


def _over_bound(latencies: list[float]) -> int:
    return sum(1 for value in latencies if value > BOUND_S)


def _assert_p95_within_bound(result: dict, rig, label: str) -> None:
    """p95 <= 60 s stated two ways: the nearest-rank 95th percentile, and at most 5 % of mails over 60 s."""
    latencies = result["latencies"]
    assert result["missing"] == [], f"{label}: {len(result['missing'])} mails were never triaged"
    ids = rig.triage.all_ids()
    assert len(ids) == len(set(ids)), f"{label}: a mail was triaged twice"
    assert latencies, f"{label}: no mail was measured"
    assert p95(latencies) <= BOUND_S, f"{label}: p95 {p95(latencies):.1f} s > 60 s"
    assert _over_bound(latencies) <= 0.05 * len(latencies), (
        f"{label}: {_over_bound(latencies)} of {len(latencies)} mails took over 60 s"
    )


def test_NFR_08_the_helper_bound_is_the_prd_bound():
    """The bound the FR-CHN-08 helpers assert against is NFR-08's number (60 s), not a looser one."""
    assert TRIAGE_P95_S == BOUND_S


def test_NFR_08_poll_cadence_leaves_room_inside_60s():
    """With every push lost, a mail waits for the next sweep, then for triage. The sweep cadence the code
    declares must leave a whole extra cycle of room under the bound (BQ-123: 30 s, because a 60 s cadence
    would leave no margin); its renewal window must be a real window inside Gmail's 7-day watch."""
    from tilo_channels.gmail_watch import POLL_INTERVAL_S, RENEW_BEFORE_S, WATCH_TTL_S

    assert 0 < POLL_INTERVAL_S <= BOUND_S / 2, f"POLL_INTERVAL_S={POLL_INTERVAL_S} leaves no margin under 60 s"
    assert 0 < RENEW_BEFORE_S < WATCH_TTL_S


@pytest.mark.parametrize(
    "label,scenario",
    [
        ("450 mails, healthy push", Scenario(mails_per_user=150, push_delay_s=(1.0, 10.0), seed=101)),
        (
            "450 mails, 30 % lost and 30 % duplicated pushes",
            Scenario(mails_per_user=150, push_delay_s=(1.0, 40.0), loss=0.3, duplicate=0.3, seed=102),
        ),
        ("450 mails, no push ever arrives", Scenario(mails_per_user=150, loss=1.0, seed=103)),
        (
            "450 mails, push outage for the middle 30 minutes",
            Scenario(mails_per_user=150, push_delay_s=(1.0, 10.0), outage=(900.0, 2700.0), seed=104),
        ),
    ],
)
def test_NFR_08_new_mail_is_triaged_within_60s_p95_over_a_batch_of_450(label, scenario):
    from tilo_channels.gmail_watch import POLL_INTERVAL_S

    rig = make_rig(latency_s=0.2, triage_s=3.0)
    result = run_scenario(rig, scenario, float(POLL_INTERVAL_S))

    assert len(result["mails"]) == 450
    _assert_p95_within_bound(result, rig, label)


def test_NFR_08_polling_fallback_alone_triages_every_mail_inside_60s_not_only_p95():
    """The fallback is what keeps the bound when Pub/Sub fails, so its worst case is held, not just p95:
    with no push at all and a sparse mailbox, no single mail waits more than 60 s."""
    from tilo_channels.gmail_watch import POLL_INTERVAL_S

    rig = make_rig(latency_s=0.2, triage_s=3.0)
    result = run_scenario(rig, Scenario(mails_per_user=40, loss=1.0, seed=105), float(POLL_INTERVAL_S))

    _assert_p95_within_bound(result, rig, "polling only")
    assert max(result["latencies"]) <= BOUND_S, f"slowest mail took {max(result['latencies']):.1f} s"
    assert rig.mailbox.calls_of("list_history"), "the fallback must have read history"


def test_NFR_08_a_burst_on_one_mailbox_is_triaged_within_60s_p95():
    """Ten mails land in the same second on one mailbox (triage runs one call at a time per user, 3 s
    each): the 95th percentile of the batch is still inside 60 s, and the mailbox's backlog is gone after."""
    from tilo_channels.gmail_watch import POLL_INTERVAL_S

    rig = make_rig(latency_s=0.2, triage_s=3.0)
    rig.watcher.start(RIYA)
    mails = [rig.mailbox.deliver(RIYA) for _ in range(10)]
    arrived = {m.message_id: m.arrived_at for m in mails}
    rig.push(RIYA)
    for _ in range(4):  # sweeps at the declared cadence pick up anything the push left
        rig.clock.advance(float(POLL_INTERVAL_S))
        rig.watcher.poll_due()

    finished = rig.triage.first_finish()
    assert set(finished) == set(arrived), "every mail of the burst must be triaged"
    latencies = [finished[i] - arrived[i] for i in arrived]
    assert p95(latencies) <= BOUND_S, f"burst p95 {p95(latencies):.1f} s"
    assert len(rig.triage.all_ids()) == len(set(rig.triage.all_ids())), "triaged once each"


def test_NFR_08_one_users_failing_mailbox_does_not_delay_another_users_mail_past_60s():
    """A user whose mailbox keeps failing (503) must not hold the sweep back for the others: their mail
    is still triaged inside 60 s of arriving."""
    from tilo_channels.gmail_watch import POLL_INTERVAL_S

    rig = make_rig(latency_s=0.2, triage_s=3.0)
    for user in (RIYA, SAM, KAI):
        rig.watcher.start(user)
    rig.mailbox.fail_users.add(RIYA)
    delivered = [rig.mailbox.deliver(user) for user in (SAM, KAI, SAM, KAI)]
    for _ in range(3):
        rig.clock.advance(float(POLL_INTERVAL_S))
        rig.watcher.poll_due()

    finished = rig.triage.first_finish()
    for mail in delivered:
        assert mail.message_id in finished, "another user's failure left this mail untriaged"
        assert finished[mail.message_id] - mail.arrived_at <= BOUND_S


@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    seed=st.integers(min_value=0, max_value=10_000),
    loss=st.sampled_from([0.0, 0.2, 0.5, 1.0]),
    duplicate=st.sampled_from([0.0, 0.3]),
    push_max_s=st.sampled_from([5.0, 20.0, 45.0]),
)
def test_NFR_08_p95_within_60s_and_exactly_once_property(seed, loss, duplicate, push_max_s):
    """For any seed and any push delay, loss and duplication in range, a batch of 120 mails across
    three mailboxes is triaged exactly once each with p95 <= 60 s."""
    from tilo_channels.gmail_watch import POLL_INTERVAL_S

    rig = make_rig(latency_s=0.2, triage_s=3.0)
    scenario = Scenario(mails_per_user=40, push_delay_s=(1.0, push_max_s), loss=loss, duplicate=duplicate, seed=seed)
    result = run_scenario(rig, scenario, float(POLL_INTERVAL_S))

    assert len(result["mails"]) == 120
    _assert_p95_within_bound(result, rig, f"seed={seed} loss={loss} dup={duplicate} push<={push_max_s}")
