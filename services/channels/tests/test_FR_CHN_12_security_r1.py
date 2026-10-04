"""FR-CHN-12 security review round 1 (PR #259): known means ASCII lower-case equality only (BQ-174), so U+212A
KELVIN SIGN, which `str.lower()` folds to an ASCII "k", never makes an address known, on the contact side or the
draft side, in the local part or the domain. Also: a ready draft with no recipient is never sendable, and Edit on a
format the drafter cannot redraft is refused before it claims the card, so the card stays answerable.
"""

from __future__ import annotations

import secrets
from typing import Any

import pytest
from _chn10_lib import drafting_module
from _chn11_lib import BENIGN, DAVID, USER, context, make_bench, scripted_thread

KELVIN = "K"
KATE = "kate@kayak.example"


def card_for(bench: Any, *, mode: str = "reply", to=(DAVID,), cc=()) -> Any:
    ctx = context(scripted_thread(bench), mode=mode)
    mod = drafting_module()
    draft = mod.Draft(
        artifact_id="art_" + secrets.token_hex(6),
        version=1,
        thread_id=ctx.thread_id,
        mode=mode,
        to=tuple(to),
        cc=tuple(cc),
        bcc=(),
        subject="Re: Engine tune-up scheduling and estimate",
        in_reply_to="<m@mail.example>",
        references="<m@mail.example>",
        body=BENIGN,
        attachments=(),
        safety_flag=False,
    )
    return bench.ap.preview(USER, ctx, mod.DraftResult(ctx.instruction_id, "ready", draft, (), (), False))


def assert_waits(bench: Any, card: Any) -> None:
    assert card.tier == "T3" and "new_recipients" in card.modifiers, (card.tier, card.modifiers)
    assert (card.level, card.outbox_id) == ("L1", None)
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {}


def test_FR_CHN_12_control_an_ascii_contact_in_cc_rides_the_window() -> None:
    bench = make_bench("L2", contacts=(KATE,))
    card = card_for(bench, cc=(KATE,))
    assert (card.tier, card.level) == ("T2", "L2") and card.outbox_id is not None


@pytest.mark.parametrize("contact", [KELVIN + "ate@kayak.example", "kate@" + KELVIN + "ayak.example"])
def test_FR_CHN_12_kelvin_sign_in_a_contact_never_makes_an_ascii_address_known(contact: str) -> None:
    assert contact.lower() == KATE  # the fold the check must not trust
    bench = make_bench("L2")
    bench.contacts.known = {contact}  # as the contacts port returns it: the fake would lower-case it on the way in
    assert_waits(bench, card_for(bench, cc=(KATE,)))


@pytest.mark.parametrize("recipient", [KELVIN + "ate@kayak.example", "kate@" + KELVIN + "ayak.example"])
def test_FR_CHN_12_kelvin_sign_in_a_draft_address_is_a_new_recipient(recipient: str) -> None:
    assert recipient.lower() == KATE
    bench = make_bench("L2", contacts=(KATE,))
    card = card_for(bench, cc=(recipient,))
    assert list(card.cc) == [recipient]
    assert_waits(bench, card)


def test_FR_CHN_12_a_ready_draft_with_no_recipient_is_never_sendable() -> None:
    bench = make_bench("L2")
    card = card_for(bench, to=(), cc=())
    assert "send" not in card.options and (card.level, card.outbox_id) == ("L1", None)
    assert bench.ap.send(USER, card.card_id).status == "refused"
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {}


@pytest.mark.parametrize("mode", ["forward", "new"])
def test_FR_CHN_12_edit_of_a_format_the_drafter_cannot_redraft_leaves_the_card_open(mode: str) -> None:
    bench = make_bench("L2")
    card = card_for(bench, mode=mode)
    with pytest.raises(ValueError):
        bench.ap.edit(USER, card.card_id, "make it shorter", instruction_id="ins-edit-" + secrets.token_hex(4))
    out = bench.ap.send(USER, card.card_id)
    (entry,) = bench.outbox.all()
    assert out.status == "queued" and entry["authz"]["by"] == "person" and entry["risk_tier"] == "T3"
