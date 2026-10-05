"""CHN-WIRE-1 (FR-CHN-11; issue #307 plan ticket 1), parts (b) and (d): a person's Send of an L1 or T3 card, with the
`approval.resolved` that `tilo-api` recorded for the tap, reaches the REAL outbox with the OB-01 evidence the REAL
`tilo_policy.check_entry` accepts, and the entry's `authz` is COPIED from that approval, never re-stamped (the old
`authority | {"at": created}` made `authz.at` the enqueue time, so OB-01 "carries that authorisation unchanged" failed).
Sources: PRD 10.4 (T3 always needs a person), 11.4, SEC-06, OB-01, OB-05 (contracts/outbox.rules.md),
contracts/fixtures/outbox/crossref/valid/gate_*.json, services/channels/tests/API_CHN_WIRE_1.md.

End to end: real Drafter, real Autopilot (production mode), real `tilo_connectors.Outbox` and `GmailAdapter`; Gmail is a
fake. `tilo_policy.check_entry` is NOT patched anywhere in this file. No network, no real mail.
"""

from __future__ import annotations

import threading

import pytest
import tilo_policy
from _chn11_lib import pair
from _chn13_lib import DAVID, USER, iso
from _chn_wire1_lib import (
    evidence_of,
    make_wire_line,
    one_sent,
    real_check_is_live,
    requested_part,
    resolved,
    t3_money_body,
    try_send,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


@pytest.fixture(autouse=True, scope="module")
def _real_check() -> None:
    real_check_is_live()


def card_for(line, tier: str):
    thread = line.thread()
    if tier == "T3":
        ctx, result = pair(thread, t3_money_body())
    else:
        ctx, result = line.draft(thread)
    card = line.ap.preview(USER, ctx, result)
    assert card.tier == tier and card.level == "L1"
    return thread, result, card


@pytest.mark.parametrize("tier", ["T2", "T3"])
def test_CHN_WIRE_1_FR_CHN_11_person_send_reaches_gmail_exactly_once_with_the_persons_authz(tier: str) -> None:
    """Given an L1 (T2) or T3 card and the owner's approve; when Send is tapped; then one entry is written under the
    reserved id, authorised by that person, and it is sent exactly once; the data.transfer carries the same authz."""
    line = make_wire_line("L1")
    thread, result, card = card_for(line, tier)
    requested = requested_part(line, card)
    line.advance(4)
    approval = resolved(requested, line)

    outcome = try_send(line.ap, card.card_id, approval)

    assert outcome is not None and outcome.status == "queued"
    assert outcome.outbox_id == requested["data"]["outbox_id"], "the entry has the id approval.requested reserved"
    entry = one_sent(line)
    assert entry["id"] == requested["data"]["outbox_id"] == card.outbox_id
    assert entry["authz"] == approval["authz"] == {"by": "person", "ref": USER, "at": approval["authz"]["at"]}
    assert (entry["action_type"], entry["risk_tier"], entry["item"]) == (
        "send_email",
        tier,
        {"artifact_id": result.draft.artifact_id, "version": result.draft.version},
    )
    assert (entry["recipients"], entry["destination"], entry["undo_window_s"]) == ([DAVID], thread.thread_id, 0)
    assert line.api.sent[0].thread_id == thread.thread_id
    transfers = line.transfers_of(entry["id"])
    assert transfers and all(t["authz"] == approval["authz"] and t["authz"]["by"] == "person" for t in transfers)


def test_CHN_WIRE_1_FR_CHN_11_authz_is_copied_from_the_approval_never_restamped() -> None:
    """The person tapped at time A and the Autopilot enqueues at time B > A. OB-01: the entry's `authz` equals the
    approval's, `at` included, so `authz.at` is the tap time and `created_at` the enqueue time."""
    line = make_wire_line("L1")
    _, _, card = card_for(line, "T2")
    approval = resolved(requested_part(line, card), line)
    tap = approval["authz"]["at"]
    line.advance(9)
    enqueued_at = iso(line.clock())

    assert try_send(line.ap, card.card_id, approval).status == "queued"

    entry = one_sent(line)
    assert entry["authz"]["at"] == tap, "authz.at is the person's tap time"
    assert entry["created_at"] == enqueued_at, "created_at is the enqueue time (the injected clock)"
    assert entry["created_at"] != tap, "created_at is when the entry was written, not when the person tapped"
    assert entry["authz"] == approval["authz"]


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    tier=st.sampled_from(["T2", "T3"]),
    tap_after=st.integers(0, 900),
    send_after=st.integers(0, 900),
    channel=st.sampled_from(["web", "mobile_web"]),
)
def test_CHN_WIRE_1_FR_CHN_11_property_entry_authz_always_equals_the_approvals(
    tier: str, tap_after: int, send_after: int, channel: str
) -> None:
    line = make_wire_line("L1")
    _, _, card = card_for(line, tier)
    line.advance(tap_after)
    approval = resolved(requested_part(line, card), line, channel=channel)
    line.advance(send_after)

    assert try_send(line.ap, card.card_id, approval).status == "queued"

    [entry] = line.entries()
    assert entry["authz"] == approval["authz"]
    assert entry["id"] == approval["data"]["outbox_id"]
    assert (entry["risk_tier"] == "T3") == (tier == "T3")
    assert entry["authz"]["by"] == "person", "no T3 without a person"


def test_CHN_WIRE_1_FR_CHN_11_evidence_handed_to_the_outbox_is_the_gate_path_the_real_check_reads() -> None:
    """The evidence is {reserved_by: the approval.requested part, authorised_by: the approval.resolved part,
    world_owner, policy None, team_lead None, instruction None, earlier_applied none}, and the real `check_entry`
    accepts the case the outbox builds from it."""
    line = make_wire_line("L1")
    _, _, card = card_for(line, "T2")
    requested = requested_part(line, card)
    approval = resolved(requested, line)
    assert try_send(line.ap, card.card_id, approval).status == "queued"

    [(entry, evidence)] = evidence_of(line)
    assert evidence["reserved_by"] == requested
    assert evidence["authorised_by"] == approval
    assert evidence["world_owner"] == USER, "the card's owner: the actor of the world's world.requested"
    assert evidence["policy"] is None and evidence["team_lead"] is None and evidence["instruction"] is None
    assert evidence["earlier_applied"] in (None, []), "gate path: no policy, so no earlier policy actions"
    case = {**evidence, "entry": entry, "transfer": None, "rule": None}
    assert tilo_policy.check_entry(case) is None, "the real OB-01 / OB-05 check accepts the Autopilot's evidence"


def test_CHN_WIRE_1_FR_CHN_11_t3_whatsapp_send_with_a_checked_pin_is_accepted() -> None:
    """SEC-06: a T3 gate answered on WhatsApp opens only with `pin_verified` true, which tilo-channels sets only after
    it checked the PIN; with it, the Send goes through."""
    line = make_wire_line("L1")
    _, _, card = card_for(line, "T3")
    approval = resolved(requested_part(line, card), line, channel="whatsapp", pin_verified=True)

    assert try_send(line.ap, card.card_id, approval).status == "queued"

    entry = one_sent(line)
    assert entry["risk_tier"] == "T3" and entry["authz"] == approval["authz"]


def test_CHN_WIRE_1_FR_CHN_11_t2_whatsapp_tap_needs_no_pin() -> None:
    line = make_wire_line("L1")
    _, _, card = card_for(line, "T2")
    approval = resolved(requested_part(line, card), line, channel="whatsapp", pin_verified=False)

    assert try_send(line.ap, card.card_id, approval).status == "queued"
    assert one_sent(line)["risk_tier"] == "T2"


def test_CHN_WIRE_1_FR_CHN_11_t3_web_send_needs_no_pin() -> None:
    line = make_wire_line("L1")
    _, _, card = card_for(line, "T3")
    approval = resolved(requested_part(line, card), line, channel="web", pin_verified=False)

    assert try_send(line.ap, card.card_id, approval).status == "queued"
    assert one_sent(line)["authz"] == approval["authz"]


@pytest.mark.parametrize("tier", ["T2", "T3"])
def test_CHN_WIRE_1_FR_CHN_11_replayed_and_concurrent_sends_create_one_entry(tier: str) -> None:
    """Repeated Send taps, a second instance and eight racing threads, all with the same approval: one entry, one
    email (OB-03 key `autopilot:<card id>`)."""
    line = make_wire_line("L1")
    _, _, card = card_for(line, tier)
    approval = resolved(requested_part(line, card), line)

    outcomes = [try_send(line.ap, card.card_id, approval) for _ in range(3)]
    outcomes.append(try_send(line.bench.new_autopilot(), card.card_id, approval))
    barrier, lock = threading.Barrier(8), threading.Lock()

    def tap() -> None:
        ap = line.bench.new_autopilot()
        barrier.wait()
        outcome = try_send(ap, card.card_id, approval)
        with lock:
            outcomes.append(outcome)

    workers = [threading.Thread(target=tap) for _ in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    assert all(o is not None and o.outbox_id == card.outbox_id for o in outcomes)
    entry = one_sent(line)
    assert entry["authz"] == approval["authz"]


def test_CHN_WIRE_1_FR_CHN_11_a_second_approval_after_the_first_changes_nothing() -> None:
    """One card, one entry: a later approval (another tap) finds the entry the first one wrote, with the first
    approval's authz."""
    line = make_wire_line("L1")
    _, _, card = card_for(line, "T2")
    requested = requested_part(line, card)
    first = resolved(requested, line)
    line.advance(10)
    second = resolved(requested, line)
    assert first["authz"]["at"] != second["authz"]["at"]

    assert try_send(line.ap, card.card_id, first).status == "queued"
    again = try_send(line.ap, card.card_id, second)

    assert again is None or again.status in ("queued", "refused")
    entry = one_sent(line)
    assert entry["authz"] == first["authz"]
