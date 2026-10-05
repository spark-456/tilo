"""CHN-WIRE-4 (FR-CHN-11; issue #307 plan ticket 4; PRD 10.4, OB-01, OB-04, OB-05, BQ-152, BQ-57): everything that
is not a clean `run_after_undo` for exactly this card degrades the card to L1: it waits for the owner's Send,
writes no outbox entry, emits no `policy.applied` and still raises its `approval.requested` gate once.
Also: with the REAL engine
(`coverage.L2_ACTION_RECORDED` is False until ADR-0013 is approved, BQ-57) an L2 candidate always degrades to L1; the
world owner still comes only from the trusted source; and with the REAL `check_entry` the L2 policy entry is still
refused (the OB-01 policy-path evidence is ticket 5). API: API_CHN_WIRE_4.md. No network, no real mail.
"""

from __future__ import annotations

import dataclasses
import types
from typing import Any

import pytest
import tilo_policy
from _chn11_lib import MAILBOX, POLICY_ID, USER, context
from _chn13_lib import iso
from _chn_wire1_lib import make_wire_line, real_check_is_live
from _chn_wire4_lib import (
    OMIT,
    DecideStub,
    EnginePolicy,
    assert_no_send_ever,
    attempt,
    card_id_of,
    decision,
    fresh_ulid,
    gate_decision,
    make_w4,
)
from tilo_policy import coverage

STRANGER = "new.person@elsewhere.example"


def boom(clock: Any) -> Any:
    raise RuntimeError("the policy store is unavailable")


def as_dict(clock: Any) -> Any:
    return dataclasses.asdict(decision(clock))


def look_alike(clock: Any) -> Any:
    return types.SimpleNamespace(**dataclasses.asdict(decision(clock)))


def stamped(**authz: Any):
    def build(clock: Any) -> Any:
        return decision(clock, authz={"by": "policy", "ref": POLICY_ID, "at": iso(clock())} | authz)

    return build


def day_ahead(clock: Any) -> Any:
    return decision(clock, authz={"by": "policy", "ref": POLICY_ID, "at": iso(clock() + 86400)})


CASES: dict[str, Any] = {
    "decide_raises": boom,
    "none": lambda c: None,
    "dict_not_a_decision": as_dict,
    "look_alike_not_a_decision": look_alike,
    "gate": lambda c: gate_decision(),
    "gate_at_l2_with_a_policy_id": lambda c: gate_decision("l2_instruction_required", "L2", POLICY_ID),
    "draft_only": lambda c: decision(c, outcome="draft_only", level="L0", authz=None, undo_window_s=None),
    "run_at_l3": lambda c: decision(c, outcome="run", level="L3", undo_window_s=None),
    "authz_missing": lambda c: decision(c, authz=None),
    "authz_by_person": stamped(by="person", ref=USER),
    "authz_by_team_lead": stamped(by="team_lead", ref="tl_ops"),
    "authz_ref_is_not_the_policy_id": stamped(ref="pol_someone_elses"),
    "authz_at_unreadable": stamped(at="yesterday"),
    "authz_at_not_a_millisecond_utc_timestamp": stamped(at="2026-10-05"),
    "authz_at_a_day_in_the_future": day_ahead,
    "window_zero": lambda c: decision(c, undo_window_s=0),
    "window_none": lambda c: decision(c, undo_window_s=None),
    "window_true": lambda c: decision(c, undo_window_s=True),
    "window_a_string": lambda c: decision(c, undo_window_s="60"),
    "window_negative": lambda c: decision(c, undo_window_s=-5),
    "policy_id_none": lambda c: decision(c, policy_id=None, authz={"by": "policy", "ref": None, "at": iso(c())}),
    "policy_id_blank": lambda c: decision(c, policy_id="", authz={"by": "policy", "ref": "", "at": iso(c())}),
    "policy_id_not_a_policy_id": lambda c: decision(
        c, policy_id="Policy One", authz={"by": "policy", "ref": "Policy One", "at": iso(c())}
    ),
    "tier_t3": lambda c: decision(c, tier="T3"),
    "tier_t1": lambda c: decision(c, tier="T1"),
    "level_l3": lambda c: decision(c, level="L3"),
    "level_l1": lambda c: decision(c, level="L1"),
    "modifiers_present": lambda c: decision(c, modifiers=("new_recipients",)),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_CHN_WIRE_4_FR_CHN_11_a_decision_that_is_not_a_clean_run_after_undo_degrades_to_l1(case: str) -> None:
    """Given a ready T2 draft whose policy answer is `case`; when the card is decided; then it is an L1 card: no
    schedule, no entry, no policy part, one approval.requested; the owner's Send without an approval is refused."""
    w4 = make_w4()
    build = CASES[case]
    w4.policy.respond = lambda user_id, proposal: build(w4.clock)
    ctx, result = w4.pair(w4.thread())

    card = w4.ap.preview(USER, ctx, result)

    assert (card.level, card.undo_window_s, card.scheduled_at) == ("L1", 0, None), case
    assert card.tier == "T2" and "send" in card.options
    assert w4.entries() == [] and w4.ap.policy_applied(USER, card.card_id) is None
    assert w4.of_type("policy.applied") == []
    requested = w4.ap.approval_requested(USER, card.card_id)
    assert requested is not None and requested["data"]["outbox_id"] == card.outbox_id is not None
    assert w4.of_type("approval.requested") == [requested], "the gate is raised once"
    assert w4.ap.send(USER, card.card_id).status == "refused"
    assert_no_send_ever(w4)
    again = w4.new_ap().preview(USER, ctx, result)
    assert again.level == "L1" and len(w4.of_type("approval.requested")) == 1 and w4.entries() == []


def test_CHN_WIRE_4_FR_CHN_11_a_preview_never_raises_because_the_policy_failed() -> None:
    w4 = make_w4()
    w4.policy.respond = lambda user_id, proposal: boom(w4.clock)
    card = w4.ap.preview(USER, *w4.pair(w4.thread()))
    assert card.level == "L1" and len(w4.policy.calls) == 1


# -- the real engine, while L2_ACTION_RECORDED is False --------------------------------------------------------------


def test_CHN_WIRE_4_FR_CHN_11_with_the_real_engine_an_l2_candidate_always_degrades_to_l1_and_writes_no_entry() -> None:
    """Given a contract-valid L2 policy that covers the send; when the real `tilo_policy.decide` answers (ADR-0013 is
    only Proposed, so no instruction counts, BQ-57); then it gates, the card is L1 and the outbox holds nothing."""
    assert coverage.L2_ACTION_RECORDED is False, "this ticket never flips the flag (ADR-0013 awaits the user)"
    w4 = make_w4(EnginePolicy)
    ctx, result = w4.pair(w4.thread())

    card = w4.ap.preview(USER, ctx, result)

    (answer,) = w4.policy.decisions
    assert (answer.outcome, answer.level, answer.policy_id) == ("gate", "L2", POLICY_ID)
    assert answer.reason == "l2_instruction_required", "the policy covered the proposal, so district and facts matched"
    assert (card.level, card.undo_window_s, card.scheduled_at) == ("L1", 0, None)
    assert w4.entries() == [] and w4.ap.policy_applied(USER, card.card_id) is None
    assert w4.ap.approval_requested(USER, card.card_id) is not None and w4.of_type("policy.applied") == []
    assert w4.ap.send(USER, card.card_id).status == "refused"
    assert_no_send_ever(w4)


def test_CHN_WIRE_4_FR_CHN_11_the_real_engine_sees_the_autopilots_district() -> None:
    """A policy scoped to another district covers nothing: the proposal's district is the Autopilot's (no cover)."""
    w4 = make_w4(EnginePolicy)
    w4.ap = w4.new_ap(district="D9")
    card = w4.ap.preview(USER, *w4.pair(w4.thread()))

    (answer,) = w4.policy.decisions
    assert (answer.outcome, answer.reason) == ("gate", "no_covering_policy")
    assert card.level == "L1" and w4.entries() == []


def test_CHN_WIRE_4_FR_CHN_11_the_real_engine_is_never_asked_about_a_t3_card_and_t3_never_runs() -> None:
    w4 = make_w4(EnginePolicy, district=OMIT)
    ctx, result = w4.pair(w4.thread(), cc=(STRANGER,))

    card = w4.ap.preview(USER, ctx, result)

    assert card.tier == "T3" and card.level == "L1" and w4.entries() == []
    assert all(d.outcome == "gate" for d in w4.policy.decisions)


# -- a decision binds to the entry it was made for -------------------------------------------------------------------


def _tampers() -> dict[str, Any]:
    return {
        "cc_added": lambda doc: doc | {"cc": [*doc["cc"], STRANGER]},
        "to_replaced": lambda doc: doc | {"to": [STRANGER]},
        "recipient_dropped": lambda doc: doc | {"to": [], "cc": []},
        "destination_changed": lambda doc: doc | {"thread_id": "t-another-thread"},
        "item_version_changed": lambda doc: doc | {"item": doc["item"] | {"version": doc["item"]["version"] + 1}},
        "item_artifact_changed": lambda doc: doc | {"item": doc["item"] | {"artifact_id": "art_another_draft"}},
        "tier_made_t3": lambda doc: doc | {"tier": "T3", "modifiers": ["new_recipients"]},
    }


@pytest.mark.parametrize("name", sorted(_tampers()))
def test_CHN_WIRE_4_FR_CHN_11_a_decision_cannot_ride_a_card_whose_recipients_destination_or_item_changed(
    name: str,
) -> None:
    """The decision was made for the recipients, destination and item the proposal carried. If the stored card then
    says something else when its first enqueue finally happens (a Cc added after preview, another thread, a new item
    version), no entry is written for it: it drops to L1 and waits for a person (OB-01, OB-05)."""
    w4 = make_w4()
    ctx, result = w4.pair(w4.thread())
    w4.outbox.down = True
    attempt(lambda: w4.ap.preview(USER, ctx, result))  # the decision is stored, the enqueue failed
    card_id = card_id_of(ctx)
    doc = w4.cards.get(USER, card_id)
    assert doc is not None and w4.entries() == [] and w4.ap.policy_applied(USER, card_id) is not None
    w4.cards.put(USER, card_id, _tampers()[name](doc))
    w4.outbox.down = False
    w4.clock.advance(5)  # still inside the freshness bound: the age alone is not what refuses it

    card = attempt(lambda: w4.new_ap().preview(USER, ctx, result))
    attempt(lambda: w4.new_ap().send(USER, card_id))

    assert w4.entries() == [], f"{name}: nothing was decided for this card as it now reads"
    if card is not None:
        assert card.level == "L1" and card.scheduled_at is None
    assert_no_send_ever(w4)


# -- the world owner stays a trusted input ---------------------------------------------------------------------------


def test_CHN_WIRE_4_FR_CHN_11_the_policy_is_never_asked_for_a_non_owner_or_an_unknown_owner() -> None:
    w4 = make_w4(district=OMIT)
    ctx, result = w4.pair(w4.thread())

    with pytest.raises(PermissionError):
        w4.ap.preview("u_mallory", ctx, result)
    with pytest.raises(PermissionError):
        w4.new_ap(world_owner=None).preview(USER, ctx, result)
    with pytest.raises(PermissionError):
        w4.new_ap(world_owner=lambda: (_ for _ in ()).throw(RuntimeError("world record unavailable"))).preview(
            USER, ctx, result
        )

    assert w4.policy.calls == [] and w4.entries() == [] and w4.events.parts == []


# -- the real check_entry still refuses the L2 policy entry (ticket 5 builds the evidence) ---------------------------


def test_CHN_WIRE_4_FR_CHN_11_with_the_real_check_entry_the_l2_policy_entry_is_still_refused() -> None:
    """Fail-closed pin: a fake engine says run_after_undo, but the outbox is the real one and `check_entry`
    is not patched. Ticket 5 (after ADR-0013) builds the policy-path evidence; until then no L2 entry exists and no
    mail goes."""
    real_check_is_live()
    line = make_wire_line("L1")
    stub = DecideStub(line.clock)
    line.bench.policy = stub
    line.bench.ap = line.bench.new_autopilot()
    thread = line.thread()
    instruction_id = fresh_ulid()
    ctx = context(thread, instruction_id=instruction_id)
    result = line.bench.rig.svc.draft(
        USER, instruction_id=instruction_id, thread_id=thread.thread_id, instruction=ctx.instruction, mailbox=MAILBOX
    )
    assert result.status == "ready"

    outcome = attempt(lambda: line.ap.preview(USER, ctx, result))
    attempt(lambda: line.ap.send(USER, card_id_of(ctx)))

    assert len(stub.calls) >= 1, "the policy was consulted"
    assert line.entries() == [], "OB-01: the real check_entry refuses a policy entry without its evidence"
    line.advance(3600)
    line.storm(10)
    assert line.entries() == [] and line.api.sent == [] and line.transfers == []
    assert outcome is None or outcome.level in ("L1", "L2")
    assert tilo_policy.check_entry.__module__ == "tilo_policy.crossref"
