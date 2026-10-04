"""CHN-WIRE-1 (FR-CHN-11; issue #307 plan ticket 1, issue #256 gate 3), part (a): when the Autopilot previews an L1 or
T3 card it reserves the outbox entry's id and records an `approval.requested` part (contracts/events/data/
approval.requested.schema.json; outbox rule OB-01, "On a gate, approval.requested reserved the entry's id"). Sources:
PRD 10.3 and 10.4 (T3 needs a person), 11.4 Preview, EV-05 (approval.requested never authorises: authz null),
contracts/outbox.rules.md OB-01 and OB-05, services/channels/tests/API_CHN_WIRE_1.md (pinned names and the id mapping).

Real Drafter, real Autopilot in production mode (no `fake_evidence`), real outbox. No network, no real mail.
"""

from __future__ import annotations

import importlib
import json
import re

import pytest
import tilo_policy.schemas as policy_schemas
from _chn11_lib import pair
from _chn13_lib import DAVID, USER
from _chn_wire1_lib import make_wire_line, real_check_is_live, requested_part, t3_money_body
from hypothesis import given
from hypothesis import strategies as st

GATE_ID = re.compile(r"^G[0-9]{1,4}$")
ULID = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")


@pytest.fixture(autouse=True, scope="module")
def _real_check() -> None:
    real_check_is_live()


def gate_module():
    """Imported at call time so a missing module fails the test that needs it, not collection."""
    return importlib.import_module("tilo_channels.autopilot_gate")


def emitted_requests(line) -> list[dict]:
    return [p for p in line.bench.events.parts if p.get("type") == "approval.requested"]


def l1_card(line):
    thread = line.thread()
    ctx, result = line.draft(thread)
    return ctx, result, line.ap.preview(USER, ctx, result)


def t3_card(line):
    thread = line.thread()
    ctx, result = pair(thread, t3_money_body())
    return ctx, result, line.ap.preview(USER, ctx, result)


def test_CHN_WIRE_1_FR_CHN_11_l1_preview_emits_one_contract_valid_approval_requested() -> None:
    """Given an L1 card with a ready T2 draft; when it is previewed; then exactly one `approval.requested` part is
    emitted, valid against its contract, with authz null (it never authorises), the card's action, tier and pinned
    item, and no approver or Team Lead (the owner alone may answer)."""
    line = make_wire_line("L1")
    _, result, card = l1_card(line)
    assert (card.level, card.tier, card.status) == ("L1", "T2", "ready")

    parts = emitted_requests(line)
    assert len(parts) == 1, f"one approval.requested per previewed L1 card, got {len(parts)}"
    part = parts[0]
    assert policy_schemas.event_ok(part, ("approval.requested",)), "the part must be valid against its contract"
    assert part["authz"] is None, "EV-05: approval.requested never authorises"
    data = part["data"]
    assert GATE_ID.fullmatch(data["gate_id"]) and ULID.fullmatch(data["card_id"]) and ULID.fullmatch(data["outbox_id"])
    assert (data["action_type"], data["risk_tier"]) == ("send_email", "T2")
    assert data["item"] == {"artifact_id": result.draft.artifact_id, "version": result.draft.version}
    assert data["irreversible"] is True, "a sent email cannot be taken back (fixtures/outbox/crossref: true)"
    assert (data["approver"], data["team_lead"]) == (None, None)
    assert requested_part(line, card) == part, "the stored part is the emitted part"


def test_CHN_WIRE_1_FR_CHN_11_t3_preview_emits_approval_requested_at_tier_t3() -> None:
    """Given a T3 card (money in the body); when it is previewed; then its gate says T3 and the card is still L1 with
    nothing scheduled and nothing in the outbox."""
    line = make_wire_line("L1")
    _, _, card = t3_card(line)
    assert (card.level, card.tier) == ("L1", "T3")

    [part] = emitted_requests(line)
    assert policy_schemas.event_ok(part, ("approval.requested",))
    assert part["data"]["risk_tier"] == "T3"
    assert line.entries() == [], "nothing waiting at a gate is in the outbox"
    assert line.api.sent == []


def test_CHN_WIRE_1_FR_CHN_11_the_gate_reserves_the_outbox_id_the_card_shows() -> None:
    """OB-01: `approval.requested` reserves the id its entry will get. The card's `outbox_id` is that id from the
    preview on (it was None at L1 before this ticket), and it is a valid ULID no other card shares."""
    line = make_wire_line("L1")
    _, _, first = l1_card(line)
    _, _, second = l1_card(line)

    one, two = requested_part(line, first), requested_part(line, second)
    assert first.outbox_id == one["data"]["outbox_id"] and second.outbox_id == two["data"]["outbox_id"]
    assert one["data"]["outbox_id"] != two["data"]["outbox_id"]
    assert one["data"]["card_id"] != two["data"]["card_id"]


def test_CHN_WIRE_1_FR_CHN_11_ids_follow_the_pinned_mapping_of_the_autopilot_card_id() -> None:
    """The autopilot card id ("apc_" + sha256[:32]) maps to the gate's ULID `card_id` and `G<n>` `gate_id` through
    `tilo_channels.autopilot_gate` (API_CHN_WIRE_1.md), so tilo-api and the Autopilot agree without a contract change.
    """
    line = make_wire_line("L1")
    _, _, card = l1_card(line)
    mapping = gate_module()
    data = requested_part(line, card)["data"]
    assert data["card_id"] == mapping.gate_card_id(card.card_id)
    assert data["gate_id"] == mapping.gate_id_for(card.card_id)


@given(user=st.from_regex(r"u_[0-9A-Za-z_]{1,48}", fullmatch=True), instruction=st.text(min_size=1, max_size=40))
def test_CHN_WIRE_1_FR_CHN_11_property_the_mapping_is_deterministic_and_contract_valid(
    user: str, instruction: str
) -> None:
    import hashlib

    apc = "apc_" + hashlib.sha256(f"{user}\n{instruction}".encode()).hexdigest()[:32]
    mapping = gate_module()
    card_id, gate_id = mapping.gate_card_id(apc), mapping.gate_id_for(apc)
    assert card_id == mapping.gate_card_id(apc) and gate_id == mapping.gate_id_for(apc), "deterministic, no clock"
    assert ULID.fullmatch(card_id), "common.schema.json ulid"
    assert GATE_ID.fullmatch(gate_id), "common.schema.json gate_id"


def test_CHN_WIRE_1_FR_CHN_11_mapping_gives_distinct_gate_card_ids_to_distinct_cards() -> None:
    """The gate's `card_id` identifies the card in OB-01, so two cards never share one (gate ids are 1 to 9999 and may
    repeat across cards: OB-01 always matches the gate, card and outbox ids together)."""
    import hashlib

    mapping = gate_module()
    cards = ["apc_" + hashlib.sha256(f"u_a\nins-{n}".encode()).hexdigest()[:32] for n in range(2000)]
    assert len({mapping.gate_card_id(c) for c in cards}) == len(cards)


def test_CHN_WIRE_1_FR_CHN_11_replayed_preview_returns_the_same_part_and_emits_nothing_new() -> None:
    """Given a previewed card; when the same instruction is previewed again (a retry, a restart, a second instance);
    then the card and its part are the same, and no second approval.requested is emitted."""
    line = make_wire_line("L1")
    ctx, result, card = l1_card(line)
    original = requested_part(line, card)
    assert len(emitted_requests(line)) == 1

    again = line.ap.preview(USER, ctx, result)
    other = line.bench.new_autopilot()
    line.advance(30)
    replay = other.preview(USER, ctx, result)

    assert again.card_id == replay.card_id == card.card_id
    assert again.outbox_id == replay.outbox_id == card.outbox_id
    assert requested_part(line, card, other) == original
    assert len(emitted_requests(line)) == 1, "a replay emits no new approval.requested"


def test_CHN_WIRE_1_FR_CHN_11_the_part_lives_in_the_card_doc_so_a_restart_finds_it() -> None:
    line = make_wire_line("L1")
    _, _, card = l1_card(line)
    original = requested_part(line, card)

    restarted = line.bench.new_autopilot()
    line.advance(3600)
    assert requested_part(line, card, restarted) == original
    assert requested_part(line, card, restarted)["data"]["outbox_id"] == card.outbox_id


def test_CHN_WIRE_1_FR_CHN_11_the_part_carries_no_mail_text() -> None:
    """Cards hold mail text; no event does (autopilot module doc, PRD 16.3)."""
    line = make_wire_line("L1")
    _, _, card = t3_card(line)
    blob = json.dumps(requested_part(line, card)) + json.dumps(emitted_requests(line))
    for text in (DAVID, "refund", "deposit", card.subject, card.body, "Friday"):
        assert text not in blob


def test_CHN_WIRE_1_FR_CHN_11_an_edit_redraft_is_a_new_proposal_with_its_own_gate() -> None:
    """Edit cancels the pending send and redrafts at L1 (BQ-155): the new card has its own reserved id, card id and
    part, and the superseded card's part is unchanged."""
    from _chn10_lib import answer
    from _chn11_lib import BENIGN_V2
    from _chn13_lib import BENIGN

    line = make_wire_line("L1")
    thread = line.thread(answers=(answer(BENIGN), answer(BENIGN_V2)))
    ctx, result = line.draft(thread)
    card = line.ap.preview(USER, ctx, result)
    old = requested_part(line, card)

    redraft = line.ap.edit(USER, card.card_id, "make it friendlier", instruction_id="ins-edit-wire1")
    assert redraft is not None and redraft.card_id != card.card_id
    new = requested_part(line, redraft)

    assert new["data"]["card_id"] != old["data"]["card_id"]
    assert new["data"]["outbox_id"] != old["data"]["outbox_id"] and redraft.outbox_id == new["data"]["outbox_id"]
    assert requested_part(line, card) == old
    assert len(emitted_requests(line)) == 2
