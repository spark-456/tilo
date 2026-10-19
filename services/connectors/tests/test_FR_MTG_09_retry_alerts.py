"""FR-MTG-09: an entry whose earlier attempt may already have sent never ends `failed` silently (MH-11, MH-12).

A lost answer after the insert leaves an event and its invitations at Google. If the retry then meets a final
refusal (the start has passed) or a store error (the draft read), a person is told or the entry is retried: it is
never `failed` with no alert. Fake Google Calendar, no network.
"""

from __future__ import annotations

from _meeting_host_lib import enqueue, make_host_env, meeting, no_network_and_no_live  # noqa: F401 - autouse guard

SOON_START = "2026-10-06T07:10:00.000Z"
SOON_END = "2026-10-06T07:40:00.000Z"


def _state(host, flow) -> str:
    return host.store.get(flow.entry["id"])["state"]


def test_FR_MTG_09_MH_12_a_start_that_passes_after_a_lost_answer_raises_an_alert_never_a_silent_failure():
    host = make_host_env()
    flow = host.prepare(meeting(start=SOON_START, end=SOON_END))
    host.cal.lose_answer_after_create()
    enqueue(host.outbox, flow.case)
    assert host.outbox.dispatch_due() == [], "the answer was lost: ambiguous, retried"
    assert len(host.cal.created()) == 1, "the event and its invitations exist"

    host.clock.set(SOON_START)  # the retry finds the start has passed
    host.outbox.dispatch_due()

    assert len(host.cal.posts()) == 1, "MH-12 makes no request"
    assert host.alerts, "a person is told: an event may exist"
    assert host.alerts[0]["data"]["alert_id"] == flow.entry["id"]


def test_FR_MTG_09_MH_12_a_start_that_passes_with_no_earlier_attempt_still_fails_without_an_alert():
    host = make_host_env()
    flow = host.prepare(meeting(start=SOON_START, end=SOON_END))
    enqueue(host.outbox, flow.case)
    host.clock.set(SOON_START)

    host.outbox.dispatch_due()

    assert _state(host, flow) == "failed" and host.alerts == [] and host.cal.requests == []


def test_FR_MTG_09_MH_11_a_store_error_on_the_retry_after_a_lost_answer_is_retried_not_failed():
    host = make_host_env()
    flow = host.prepare()
    host.cal.lose_answer_after_create()
    enqueue(host.outbox, flow.case)
    assert host.outbox.dispatch_due() == [], "the answer was lost: ambiguous, retried"

    real_get = host.artifacts.get
    outage = {"on": True}

    def flaky_get(artifact_id, version):
        if outage["on"]:
            raise ConnectionError("store unreachable")
        return real_get(artifact_id, version)

    host.artifacts.get = flaky_get  # type: ignore[method-assign]
    assert host.outbox.dispatch_due() == [], "a transient store error is retried"
    assert _state(host, flow) != "failed", "never failed silently while an event may exist"
    assert len(host.cal.created()) == 1

    outage["on"] = False
    host.clock.advance(3600)  # past any retry delay
    host.outbox.dispatch_due()
    assert _state(host, flow) == "sent", "the retry finds the earlier event and settles"
    assert len(host.cal.created()) == 1, "invited once"
