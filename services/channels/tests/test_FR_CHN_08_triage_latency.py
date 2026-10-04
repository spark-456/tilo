"""FR-CHN-08 acceptance test: "New mail is triaged in <= 60 s p95" (PRD 11.6; NFR-08).

Measured from the moment mail lands in the inbox to the moment the triage step returns, for 300 mails
across 3 users over an hour, on the fake clock with fake providers: Pub/Sub delivery delay, lost,
duplicated and reordered pushes, and a full push outage. The sweeper calls `renew_due()` and
`poll_due()` every `POLL_INTERVAL_S`. Every mail must be triaged exactly once. No sleeps, no network,
no paid calls. Also: only registered, schema-valid events are emitted; nothing secret is logged.
"""

from __future__ import annotations

import contextlib
import logging

import pytest
from _chn08_lib import (
    ADDRESS,
    RIYA,
    TRIAGE_P95_S,
    Scenario,
    bearer,
    make_rig,
    p95,
    push_body,
    run_scenario,
)
from _chn_0305_lib import data_errors, registered_types

SCENARIOS = {
    "healthy-push": Scenario(push_delay_s=(1.0, 10.0)),
    "lossy-reordered-duplicated": Scenario(push_delay_s=(1.0, 30.0), loss=0.2, duplicate=0.2, seed=11),
    "push-outage-20-min": Scenario(push_delay_s=(1.0, 10.0), outage=(1200.0, 2400.0), seed=12),
    "pushes-never-arrive": Scenario(loss=1.0, seed=13),
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_FR_CHN_08_new_mail_triaged_within_60_s_p95(name):
    from tilo_channels.gmail_watch import POLL_INTERVAL_S

    rig = make_rig(latency_s=0.2, triage_s=3.0)
    result = run_scenario(rig, SCENARIOS[name], float(POLL_INTERVAL_S))

    assert result["missing"] == [], f"{len(result['missing'])} mails never triaged"
    ids = rig.triage.all_ids()
    assert len(ids) == len(set(ids)), "each mail triaged exactly once"
    observed = p95(result["latencies"])
    assert observed <= TRIAGE_P95_S, f"{name}: p95 {observed:.1f} s > {TRIAGE_P95_S:.0f} s"


def test_FR_CHN_08_every_emitted_event_is_registered_and_schema_valid():
    """Events across a lossy run, a resync, a failed renewal and refused pushes (only registered types)."""
    from tilo_channels.gmail_watch import POLL_INTERVAL_S, RENEW_BEFORE_S

    rig = make_rig()
    run_scenario(rig, SCENARIOS["lossy-reordered-duplicated"], float(POLL_INTERVAL_S))
    rig.mailbox.expire_history(RIYA)
    rig.mailbox.deliver(RIYA)
    rig.push(RIYA)
    expiry = rig.mailbox.watch_expires_at(RIYA)
    assert expiry is not None
    rig.clock.advance(max(0.0, expiry - rig.clock() - RENEW_BEFORE_S + 1))
    rig.mailbox.fail_next["watch"] = 3
    with contextlib.suppress(Exception):
        rig.watcher.renew_due()
    rig.endpoint.receive({}, push_body(ADDRESS[RIYA], 1))
    rig.endpoint.receive(bearer(rig.verifier.issue(aud="https://evil.example.net")), push_body(ADDRESS[RIYA], 1))

    registered = registered_types()
    for part in rig.events.parts:
        assert part.get("type") in registered, f"unregistered event type {part.get('type')!r}"
        assert data_errors(part["type"], part.get("data")) == [], part["type"]


def test_FR_CHN_08_no_tokens_addresses_or_payloads_in_logs(caplog):
    from tilo_channels.gmail_watch import POLL_INTERVAL_S

    caplog.set_level(logging.DEBUG)
    rig = make_rig()
    token = rig.verifier.issue()
    body = push_body(ADDRESS[RIYA], 99)
    rig.watcher.start(RIYA)
    rig.mailbox.deliver(RIYA)
    rig.endpoint.receive(bearer(token), body)
    rig.endpoint.receive(bearer(token + "x"), body)
    rig.mailbox.fail_next["list_history"] = 1
    rig.mailbox.deliver(RIYA)
    with contextlib.suppress(Exception):
        rig.endpoint.receive(bearer(token), push_body(ADDRESS[RIYA], 120))
    rig.mailbox.expire_history(RIYA)
    rig.clock.advance(float(POLL_INTERVAL_S) + 1)
    rig.watcher.poll_due()

    text = "\n".join([r.getMessage() for r in caplog.records] + [repr(r.args) for r in caplog.records] + [caplog.text])
    for secret in (token, ADDRESS[RIYA], body.decode("utf-8"), rig.verifier.detail_marker):
        assert secret not in text
    assert rig.store.dump().find(token) == -1, "no token is stored in watch state"
