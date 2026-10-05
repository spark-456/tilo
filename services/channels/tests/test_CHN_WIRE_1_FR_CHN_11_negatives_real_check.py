"""CHN-WIRE-1 (FR-CHN-11; issue #307 plan ticket 1), part (c): NEGATIVES against the REAL `tilo_policy.check_entry`
(no monkeypatch anywhere). Every way a Send can lack a valid person's approval leaves no outbox entry, no Gmail call and
no data.transfer. Sources: contracts/outbox.rules.md OB-01 (the entry's authz equals the `approval.resolved` that
answered approve on the same gate, card and outbox id; the answerer is the world's owner, the named Approver or an
allowed Team Lead; a gate opens only in a signed-in session, never over WhatsApp: ADR-0019), OB-04 (T3 is never
authorised by a policy), OB-05 (the entry is what the gate showed), PRD 10.4, SEC-06, and the fail-closed rule of
`Outbox.enqueue`.
API: services/channels/tests/API_CHN_WIRE_1.md. Every test first asserts the card's `approval.requested` part exists, so
none passes by accident while the wiring is missing.
"""

from __future__ import annotations

import copy
import inspect

import pytest
from _chn11_lib import RUN, WORLD, FakeOutbox, autopilot_module, fake_evidence_kwargs, make_bench, pair
from _chn13_lib import USER
from _chn_wire1_lib import (
    OTHER_PERSON,
    assert_nothing_sent,
    load_policy_applied_part,
    make_wire_line,
    one_sent,
    real_check_is_live,
    requested_part,
    resolved,
    t3_money_body,
    try_send,
    was_refused,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

OTHER_ULID = "01JB5VQ0000000000000009999"
TIERS = ["T2", "T3"]


@pytest.fixture(autouse=True, scope="module")
def _real_check() -> None:
    real_check_is_live()


def card_for(line, tier: str, *, ap=None):
    thread = line.thread()
    ctx, result = pair(thread, t3_money_body()) if tier == "T3" else line.draft(thread)
    card = (ap or line.ap).preview(USER, ctx, result)
    assert card.tier == tier and card.level == "L1"
    return card


def refused_and_untouched(line, card, approval) -> None:
    outcome = try_send(line.ap, card.card_id, approval)
    assert was_refused(outcome), f"a Send without a valid approval must be refused, got {outcome}"
    assert_nothing_sent(line)


def then_a_valid_approval_still_works(line, card, requested) -> None:
    """A refusal does not consume the card: the owner's proper approval afterwards queues exactly one entry."""
    approval = resolved(requested, line)
    assert try_send(line.ap, card.card_id, approval).status == "queued"
    assert one_sent(line)["authz"] == approval["authz"]


# -- no approval --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tier", TIERS)
def test_CHN_WIRE_1_FR_CHN_11_send_without_an_approval_writes_no_entry(tier: str) -> None:
    """Given a previewed L1 / T3 card; when Send arrives with no approval (None, or the old two-argument call); then
    nothing is queued or sent, however long the clock runs. A Send is the person's tap relayed by tilo-api: without
    that tap there is no authorisation to copy."""
    line = make_wire_line("L1")
    card = card_for(line, tier)
    requested = requested_part(line, card)

    refused_and_untouched(line, card, None)
    assert was_refused(line.ap.send(USER, card.card_id)), "the old call without an approval is refused too"
    assert_nothing_sent(line)
    then_a_valid_approval_still_works(line, card, requested)


@pytest.mark.parametrize(
    "bad", ["approve", True, 7, [], {}, {"type": "approval.resolved"}, {"authz": None, "data": {}}]
)
def test_CHN_WIRE_1_FR_CHN_11_a_malformed_approval_is_refused_not_raised(bad: object) -> None:
    line = make_wire_line("L1")
    card = card_for(line, "T2")
    requested_part(line, card)
    refused_and_untouched(line, card, bad)  # type: ignore[arg-type]


def test_CHN_WIRE_1_FR_CHN_11_an_approval_that_breaks_its_contract_is_refused() -> None:
    line = make_wire_line("L1")
    card = card_for(line, "T2")
    good = resolved(requested_part(line, card), line)
    for broken in (
        {**good, "type": "approval.requested", "authz": None},
        {**good, "data": {k: v for k, v in good["data"].items() if k != "pin_verified"}},
        {**good, "data": {**good["data"], "channel": "email"}},  # gates are never answered by email
        {**good, "data": {**good["data"], "extra": 1}},
        {**good, "authz": {**good["authz"], "at": "yesterday"}},
        {**good, "authz": {"by": "person", "ref": "not a user id", "at": good["authz"]["at"]}},
    ):
        refused_and_untouched(line, card, broken)


# -- another gate, card or outbox id ------------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["gate_id", "card_id", "outbox_id"])
@pytest.mark.parametrize("tier", TIERS)
def test_CHN_WIRE_1_FR_CHN_11_an_approval_for_another_gate_card_or_outbox_id_opens_nothing(
    tier: str, field: str
) -> None:
    line = make_wire_line("L1")
    card = card_for(line, tier)
    requested = requested_part(line, card)
    other = "G9999" if requested["data"]["gate_id"] != "G9999" else "G9998"
    wrong = other if field == "gate_id" else OTHER_ULID

    refused_and_untouched(line, card, resolved(requested, line, **{field: wrong}))
    then_a_valid_approval_still_works(line, card, requested)


@pytest.mark.parametrize("tier", TIERS)
def test_CHN_WIRE_1_FR_CHN_11_another_cards_approval_opens_nothing_on_this_card(tier: str) -> None:
    """The owner approved card B; handing that approval to card A's Send writes nothing for A."""
    line = make_wire_line("L1")
    card_a, card_b = card_for(line, tier), card_for(line, tier)
    part_a, part_b = requested_part(line, card_a), requested_part(line, card_b)
    assert part_a["data"]["card_id"] != part_b["data"]["card_id"]

    refused_and_untouched(line, card_a, resolved(part_b, line))
    assert try_send(line.ap, card_b.card_id, resolved(part_b, line)).status == "queued"
    [entry] = line.entries()
    assert entry["id"] == part_b["data"]["outbox_id"], "only card B got an entry"


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    swap=st.lists(st.booleans(), min_size=3, max_size=3).filter(any),
    gate=st.from_regex(r"G[0-9]{1,4}", fullmatch=True),
    card=st.from_regex(r"[0-7][0-9A-HJKMNP-TV-Z]{25}", fullmatch=True),
    outbox=st.from_regex(r"[0-7][0-9A-HJKMNP-TV-Z]{25}", fullmatch=True),
    tier=st.sampled_from(TIERS),
)
def test_CHN_WIRE_1_FR_CHN_11_property_no_entry_unless_gate_card_and_outbox_ids_all_match(
    swap: list[bool], gate: str, card: str, outbox: str, tier: str
) -> None:
    line = make_wire_line("L1")
    placed = card_for(line, tier)
    requested = requested_part(line, placed)
    real = requested["data"]
    changes = {
        k: v
        for (k, v), on in zip((("gate_id", gate), ("card_id", card), ("outbox_id", outbox)), swap, strict=True)
        if on
    }
    if all(real[k] == v for k, v in changes.items()):
        return  # the draw happened to equal the real ids: not a mismatch
    outcome = try_send(line.ap, placed.card_id, resolved(requested, line, **changes))
    assert was_refused(outcome)
    assert line.entries() == [] and line.api.sent == []


# -- the answer: option, answerer, channel ------------------------------------------------------------------------


@pytest.mark.parametrize("option", ["hold", "edit"])
@pytest.mark.parametrize("tier", TIERS)
def test_CHN_WIRE_1_FR_CHN_11_only_approve_opens_a_gate(tier: str, option: str) -> None:
    """CR-07, OB-01: a gate answered hold or edit writes nothing."""
    line = make_wire_line("L1")
    card = card_for(line, tier)
    requested = requested_part(line, card)
    refused_and_untouched(line, card, resolved(requested, line, option=option))
    then_a_valid_approval_still_works(line, card, requested)


@pytest.mark.parametrize(
    ("by", "ref"),
    [
        ("person", OTHER_PERSON),  # not the world's owner, and no Approver was assigned (approver is null)
        ("team_lead", "tl_harbour_ops"),  # no Team Lead allowance on this gate (team_lead is null)
        ("policy", "pol_autopilot_l2"),  # a policy never answers a gate: OB-01 "person's approval stamped as a policy"
    ],
)
@pytest.mark.parametrize("tier", TIERS)
def test_CHN_WIRE_1_FR_CHN_11_only_the_worlds_owner_opens_the_gate(tier: str, by: str, ref: str) -> None:
    line = make_wire_line("L1")
    card = card_for(line, tier)
    requested = requested_part(line, card)
    assert requested["data"]["approver"] is None and requested["data"]["team_lead"] is None
    refused_and_untouched(line, card, resolved(requested, line, by=by, ref=ref))
    then_a_valid_approval_still_works(line, card, requested)


@pytest.mark.parametrize("tier", TIERS)
@pytest.mark.parametrize("pin_verified", [False, True])
def test_CH_RM_SEC_06_CHN_WIRE_1_FR_CHN_11_an_answer_on_whatsapp_opens_nothing_pin_or_not(
    tier: str, pin_verified: bool
) -> None:
    """ADR-0019 (SD-01, SEC-06 as amended): a gate opens only in a signed-in session, so OB-01 (the real check_entry)
    refuses an approval.resolved over WhatsApp, PIN or not; the owner's signed-in approval still works."""
    line = make_wire_line("L1")
    card = card_for(line, tier)
    requested = requested_part(line, card)
    refused_and_untouched(line, card, resolved(requested, line, channel="whatsapp", pin_verified=pin_verified))
    then_a_valid_approval_still_works(line, card, requested)


# -- a policy is never a person (OB-04) ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier", TIERS)
def test_CHN_WIRE_1_FR_CHN_11_a_policy_part_never_opens_a_gate_card_and_never_a_t3(tier: str) -> None:
    """OB-04, OB-01: T3 is authorised by a person or Team Lead, never a policy. A `policy.applied` part handed in as
    the approval, with this card's outbox id, opens neither the T3 card nor (this ticket has no policy path) the L1
    card."""
    line = make_wire_line("L1")
    card = card_for(line, tier)
    requested = requested_part(line, card)
    policy_part = copy.deepcopy(load_policy_applied_part())
    policy_part["data"]["outbox_id"] = requested["data"]["outbox_id"]
    policy_part["authz"]["at"] = resolved(requested, line)["authz"]["at"]

    refused_and_untouched(line, card, policy_part)


# -- OB-05: the entry is exactly what the gate showed ----------------------------------------------------------------


def _tamper(line, card, **changes) -> None:
    doc = line.bench.cards.get(USER, card.card_id)
    line.bench.cards.put(USER, card.card_id, doc | changes)


def test_CHN_WIRE_1_FR_CHN_11_an_entry_for_another_item_version_than_the_gate_reserved_is_refused() -> None:
    """OB-05: `item` (artifact and version) equals approval.requested's. The evidence's reserved_by is the part
    recorded at preview, never rebuilt from the card as it is now, so a changed card cannot reshape its own gate."""
    line = make_wire_line("L1")
    card = card_for(line, "T2")
    requested = requested_part(line, card)
    item = requested["data"]["item"]
    _tamper(line, card, item={"artifact_id": item["artifact_id"], "version": item["version"] + 1})

    refused_and_untouched(line, card, resolved(requested, line))


def test_CHN_WIRE_1_FR_CHN_11_an_entry_of_another_risk_tier_than_the_gate_showed_is_refused() -> None:
    """OB-05: `risk_tier` equals approval.requested's: a card that became T3 after its T2 gate went out needs a new
    gate."""
    line = make_wire_line("L1")
    card = card_for(line, "T2")
    requested = requested_part(line, card)
    _tamper(line, card, tier="T3")

    refused_and_untouched(line, card, resolved(requested, line))


def test_CHN_WIRE_1_FR_CHN_11_a_part_the_caller_adds_never_replaces_the_stored_one() -> None:
    """The caller supplies only the approval. A forged `approval.requested` (another tier) riding along as an extra key
    is ignored or the Send is refused; the evidence's reserved_by is always the part the Autopilot stored."""
    line = make_wire_line("L1")
    card = card_for(line, "T3")
    requested = requested_part(line, card)
    forged = copy.deepcopy(requested)
    forged["data"]["risk_tier"] = "T2"
    approval = resolved(requested, line)
    approval["reserved_by"] = forged

    outcome = try_send(line.ap, card.card_id, approval)

    if was_refused(outcome):
        assert_nothing_sent(line)
    else:
        [(entry, evidence)] = line.spy.calls
        assert evidence["reserved_by"] == requested and evidence["reserved_by"] != forged
        assert entry["risk_tier"] == "T3"


# -- a stopped card never gets an entry (GATE-A semantics keep) ----------------------------------------------------


@pytest.mark.parametrize("tier", TIERS)
def test_CHN_WIRE_1_FR_CHN_11_a_cancelled_card_never_gets_an_entry(tier: str) -> None:
    line = make_wire_line("L1")
    card = card_for(line, tier)
    requested = requested_part(line, card)
    assert line.ap.cancel(USER, card.card_id).status == "cancelled"

    refused_and_untouched(line, card, resolved(requested, line))


def test_CHN_WIRE_1_FR_CHN_11_an_edited_card_never_gets_an_entry_and_the_redraft_needs_its_own_approval() -> None:
    from _chn10_lib import answer
    from _chn11_lib import BENIGN, BENIGN_V2

    line = make_wire_line("L1")
    thread = line.thread(answers=(answer(BENIGN), answer(BENIGN_V2)))
    ctx, result = line.draft(thread)
    card = line.ap.preview(USER, ctx, result)
    old = requested_part(line, card)
    redraft = line.ap.edit(USER, card.card_id, "friendlier", instruction_id="ins-edit-wire1-neg")
    assert redraft is not None
    new = requested_part(line, redraft)

    refused_and_untouched(line, card, resolved(old, line))  # the superseded card
    refused_and_untouched(line, redraft, resolved(old, line))  # the old gate does not open the new card
    assert try_send(line.ap, redraft.card_id, resolved(new, line)).status == "queued"
    assert one_sent(line)["id"] == new["data"]["outbox_id"]


# -- the fake-evidence mode: tests only, never production ------------------------------------------------------------


def test_CHN_WIRE_1_FR_CHN_11_fake_evidence_is_an_explicit_constructor_flag_off_by_default() -> None:
    """The FR-CHN-11/13 benches send without an approval over a fake outbox. That mode is the explicit
    `fake_evidence=True`; production wiring never passes it, so its default is False (security reviewer: check it)."""
    parameter = inspect.signature(autopilot_module().Autopilot).parameters.get("fake_evidence")
    assert parameter is not None, "Autopilot(fake_evidence=...) is not built yet (API_CHN_WIRE_1.md)"
    assert parameter.default is False and parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_CHN_WIRE_1_FR_CHN_11_fake_evidence_keeps_the_old_send_over_a_fake_outbox() -> None:
    """With `fake_evidence=True` and a fake outbox (as the FR-CHN-11 benches), Send needs no approval."""
    assert fake_evidence_kwargs() == {"fake_evidence": True}, "Autopilot(fake_evidence=...) is not built yet"
    bench = make_bench("L1")
    thread = bench.rig.thread(answers=())[0]
    ctx, result = pair(thread, "Hi David,\n\nFriday 2pm works for us. See you then.\n\nBest,\nSarah")
    card = bench.ap.preview(USER, ctx, result)
    assert isinstance(bench.outbox, FakeOutbox) and card.outbox_id is None

    outcome = bench.ap.send(USER, card.card_id)

    assert outcome.status == "queued"
    assert bench.outbox.entries[outcome.outbox_id]["authz"]["by"] == "person"
    assert bench.events.parts == [], "the fake-evidence mode builds no approval.requested"


def test_CHN_WIRE_1_FR_CHN_11_fake_evidence_is_not_a_bypass_of_the_real_check() -> None:
    """`fake_evidence=True` only changes what the Autopilot hands the outbox; the real outbox and the real
    `check_entry` still refuse its evidence, so the mode cannot authorise anything on its own."""
    assert fake_evidence_kwargs() == {"fake_evidence": True}, "Autopilot(fake_evidence=...) is not built yet"
    line = make_wire_line("L1")
    legacy = autopilot_module().Autopilot(
        drafter=line.bench.rig.svc,
        reader=line.bench.rig.reader,
        contacts=line.bench.contacts,
        policy=line.bench.policy,
        outbox=line.outbox,
        cards=line.bench.cards,
        clock=line.bench.rig.clock,
        world_id=WORLD,
        run_id=RUN,
        **fake_evidence_kwargs(),
    )
    thread = line.thread()
    ctx, result = line.draft(thread)
    card = legacy.preview(USER, ctx, result)

    outcome = try_send(legacy, card.card_id, None)

    assert was_refused(outcome)
    assert_nothing_sent(line)
