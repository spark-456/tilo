"""CHN-WIRE-1 (FR-CHN-11; security review of PR #317): the world's owner is a trusted input of the Autopilot, never the
`user_id` a caller passes to preview or send, and never the card's own `user_id`. In production mode (no
`fake_evidence`) an Autopilot with no owner, or whose owner lookup fails, previews and sends nothing; one for the
owner's world refuses every other user. Real Drafter, real `tilo_connectors.Outbox`, real `tilo_policy.check_entry`.
"""

from __future__ import annotations

import pytest
from _chn11_lib import RUN, WORLD, autopilot_module
from _chn13_lib import USER
from _chn_wire1_lib import (
    assert_nothing_sent,
    make_wire_line,
    one_sent,
    real_check_is_live,
    requested_part,
    resolved,
    t3_money_body,
    try_send,
    was_refused,
)

MALLORY = "u_mallory"


@pytest.fixture(autouse=True, scope="module")
def _real_check() -> None:
    real_check_is_live()


def autopilot(line, **owner):
    """A production-mode instance over the line's stores and (spied) real outbox, with `owner` as its trusted input."""
    bench = line.bench
    return autopilot_module().Autopilot(
        drafter=bench.rig.svc,
        reader=bench.rig.reader,
        contacts=bench.contacts,
        policy=bench.policy,
        outbox=line.spy,
        cards=bench.cards,
        clock=bench.rig.clock,
        emit=bench.events,
        world_id=WORLD,
        run_id=RUN,
        **owner,
    )


def requests(line) -> list[dict]:
    return [p for p in line.bench.events.parts if p.get("type") == "approval.requested"]


def previewed(line, ap=None):
    thread = line.thread()
    ctx, result = line.draft(thread)
    return ctx, result, (ap or line.ap).preview(USER, ctx, result)


def test_CHN_WIRE_1_FR_CHN_11_a_non_owner_preview_writes_no_card_no_gate_and_emits_nothing() -> None:
    line = make_wire_line("L1")
    thread = line.thread()
    ctx, result = line.draft(thread)

    with pytest.raises(PermissionError):
        line.ap.preview(MALLORY, ctx, result)

    assert requests(line) == [] and line.bench.events.parts == []
    assert line.bench.cards.get(MALLORY, autopilot_module()._card_id(MALLORY, ctx.instruction_id)) is None
    assert line.bench.cards.get(USER, autopilot_module()._card_id(MALLORY, ctx.instruction_id)) is None
    assert_nothing_sent(line)


def test_CHN_WIRE_1_FR_CHN_11_the_mallory_probe_cannot_send_from_the_owners_mailbox() -> None:
    """Mallory previews a T3 card in the owner's world and approves it herself: nothing is queued or sent; the owner's
    own approval of the owner's own card still queues exactly one entry."""
    line = make_wire_line("L1")
    thread = line.thread()
    ctx, result = line.draft(thread)
    with pytest.raises(PermissionError):
        line.ap.preview(MALLORY, ctx, result)
    own = line.ap.preview(USER, ctx, result)
    requested = requested_part(line, own)

    mine = resolved(requested, line, ref=MALLORY)
    assert was_refused(line.ap.send(MALLORY, own.card_id, approval=mine))
    assert was_refused(try_send(line.ap, own.card_id, mine)), "her tap is not the owner's"
    assert_nothing_sent(line)

    approval = resolved(requested, line)
    assert try_send(line.ap, own.card_id, approval).status == "queued"
    entry = one_sent(line)
    assert entry["authz"] == approval["authz"] and entry["authz"]["ref"] == USER


def test_CHN_WIRE_1_FR_CHN_11_a_non_owner_approval_of_the_owners_card_writes_nothing() -> None:
    line = make_wire_line("L1")
    _, _, card = previewed(line)
    requested = requested_part(line, card)

    for approval in (resolved(requested, line, ref=MALLORY), resolved(requested, line)):
        assert was_refused(line.ap.send(MALLORY, card.card_id, approval=approval))
    assert_nothing_sent(line)
    assert try_send(line.ap, card.card_id, resolved(requested, line)).status == "queued"
    one_sent(line)


@pytest.mark.parametrize("owner", [{}, {"world_owner": None}, {"world_owner": ""}, {"world_owner": lambda: None}])
def test_CHN_WIRE_1_FR_CHN_11_a_missing_owner_refuses_preview_and_send(owner: dict) -> None:
    line = make_wire_line("L1")
    _, _, card = previewed(line)
    requested = requested_part(line, card)
    before = len(requests(line))
    blind = autopilot(line, **owner)
    thread = line.thread()
    ctx, result = line.draft(thread)

    with pytest.raises(PermissionError):
        blind.preview(USER, ctx, result)
    assert len(requests(line)) == before

    assert was_refused(try_send(blind, card.card_id, resolved(requested, line)))
    assert_nothing_sent(line)
    assert try_send(line.ap, card.card_id, resolved(requested, line)).status == "queued", "no slot was claimed"


def test_CHN_WIRE_1_FR_CHN_11_a_failed_owner_lookup_refuses_and_a_working_one_allows() -> None:
    line = make_wire_line("L1")
    _, _, card = previewed(line)
    requested = requested_part(line, card)

    def broken() -> str:
        raise ConnectionError("world record unavailable")

    assert was_refused(try_send(autopilot(line, world_owner=broken), card.card_id, resolved(requested, line)))
    assert_nothing_sent(line)
    ported = autopilot(line, world_owner=lambda: USER)
    assert try_send(ported, card.card_id, resolved(requested, line)).status == "queued"
    one_sent(line)


@pytest.mark.parametrize("tier", ["T2", "T3"])
def test_CHN_WIRE_1_FR_CHN_11_a_card_doc_with_another_user_id_opens_nothing(tier: str) -> None:
    """The card's own `user_id` is not a source of the world owner: edited to another user, the owner's approval (and
    that user's) opens nothing."""
    line = make_wire_line("L1")
    thread = line.thread()
    ctx, result = line.draft(thread)
    if tier == "T3":
        from _chn11_lib import pair

        ctx, result = pair(thread, t3_money_body())
    card = line.ap.preview(USER, ctx, result)
    requested = requested_part(line, card)
    doc = line.bench.cards.get(USER, card.card_id)
    line.bench.cards.put(USER, card.card_id, doc | {"user_id": MALLORY})

    for approval in (resolved(requested, line), resolved(requested, line, ref=MALLORY)):
        assert was_refused(try_send(line.ap, card.card_id, approval))
    assert_nothing_sent(line)

    line.bench.cards.put(USER, card.card_id, doc)
    assert try_send(line.ap, card.card_id, resolved(requested, line)).status == "queued"
    one_sent(line)
