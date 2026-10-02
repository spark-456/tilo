"""FR-CHN-03 / FR-CHN-05 / SEC-10 follow-ups from the #158 and #159 reviews (issue #156, part 2): the send
window is claimed before the owner lookup, the number cap spares the last owner, unknown cap keys are
refused, one shared Sender, card sends reserve the card id, repeated Hold or Edit taps write one event.
Defaults: BQ-89 in docs/open-questions.md."""

from __future__ import annotations

import re
import threading
from typing import Any

import pytest
from _channels_lib import FakeClock, FakeSender
from _chn_0305_lib import (
    GATE_T3,
    NUM_KAI,
    NUM_RIYA,
    QUESTION,
    RIYA,
    SAM,
    THIRTY_DAYS_S,
    ApiAnswer,
    CardRig,
    FakeBindingStore,
    FakeCipher,
)
from _chn_0305_lib import fake_key as _key
from tilo_channels import binding, cards, inbound, keywords, whatsapp
from tilo_channels.binding import SEND_CAPS, BindingService

_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


class Rig:
    def __init__(self, **kw: Any) -> None:
        self.clock = FakeClock()
        self.sender = FakeSender(self.clock)
        self.store = FakeBindingStore()
        self.svc = BindingService(
            store=self.store, cipher=FakeCipher(), sender=self.sender, clock=self.clock, hash_key=_key(), **kw
        )

    def bind(self, user: str, number: str) -> None:
        assert self.svc.start(user, number).ok
        assert self.svc.confirm(user, _CODE.findall(self.sender.bodies_to(number)[-1])[0]).ok


def _num(i: int) -> str:
    return f"120255501{i:02d}"


# --- the send window is claimed before the owner lookup (#158) ------------------------------------------


def test_SEC_10_capped_user_cannot_enumerate_bound_numbers() -> None:
    rig = Rig(send_caps=SEND_CAPS)
    rig.bind(SAM, NUM_KAI)
    assert [rig.svc.start(RIYA, _num(i)).reason for i in range(10, 15)] == [None] * 5  # 5 an hour
    result = rig.svc.start(RIYA, NUM_KAI)
    assert (result.ok, result.reason) == (False, "rate_limited")  # not number_taken: nothing learned


def test_SEC_10_refused_starts_count_against_the_user_cap() -> None:
    rig = Rig(send_caps=SEND_CAPS)
    rig.bind(SAM, NUM_KAI)
    assert [rig.svc.start(RIYA, NUM_KAI).reason for _ in range(5)] == ["number_taken"] * 5
    assert rig.svc.start(RIYA, _num(20)).reason == "rate_limited"
    assert rig.sender.bodies_to(_num(20)) == []


# --- the number cap spares the number's last owner ----------------------------------------------------


def test_SEC_10_other_accounts_cannot_lock_the_last_owner_out_of_their_number() -> None:
    rig = Rig(send_caps=SEND_CAPS)
    rig.bind(RIYA, NUM_KAI)
    rig.clock.advance(THIRTY_DAYS_S + 7200)  # the binding lapsed; the number is free again
    assert [rig.svc.start(SAM, NUM_KAI).reason for _ in range(4)] == [None, None, None, "rate_limited"]
    assert rig.svc.start(RIYA, NUM_KAI).ok  # the last owner is not blocked by the cap Sam used up
    assert rig.svc.start(RIYA, NUM_KAI).ok


def test_SEC_10_last_owner_starts_do_not_use_up_the_number_cap() -> None:
    rig = Rig(send_caps=SEND_CAPS)
    rig.bind(RIYA, NUM_KAI)
    rig.clock.advance(THIRTY_DAYS_S + 7200)
    assert [rig.svc.start(RIYA, NUM_KAI).ok for _ in range(3)] == [True] * 3
    assert [rig.svc.start(SAM, NUM_KAI).reason for _ in range(3)] == [None, None, None]


def test_SEC_10_last_owner_still_counts_against_the_user_cap() -> None:
    rig = Rig(send_caps=SEND_CAPS)
    rig.bind(RIYA, NUM_KAI)
    rig.clock.advance(THIRTY_DAYS_S + 7200)
    assert [rig.svc.start(RIYA, NUM_KAI).reason for _ in range(5)] == [None] * 5
    assert rig.svc.start(RIYA, NUM_KAI).reason == "rate_limited"


def _lapsed_then_capped(rig: Rig) -> None:
    """Sam uses the whole number cap on NUM_KAI, an hour after Riya's old holding ended."""
    assert [rig.svc.start(SAM, NUM_KAI).reason for _ in range(4)] == [None, None, None, "rate_limited"]


def _no_link_to(rig: Rig, number: str) -> bool:
    """True when no record but the TTL'd cap slots (number-scoped, no user id) mentions the number's hash."""
    number_hash = rig.svc._mac("number", number)
    return not any(number_hash in f"{k}{v}" for k, v in rig.store._data.items() if not k.startswith("cap:"))


def test_SEC_10_unbound_holder_loses_the_number_cap_exemption_and_leaves_no_link() -> None:
    rig = Rig(send_caps=SEND_CAPS)
    rig.bind(RIYA, NUM_KAI)
    assert rig.svc.unbind(RIYA)
    assert _no_link_to(rig, NUM_KAI)
    rig.clock.advance(3600)  # fresh windows
    _lapsed_then_capped(rig)
    assert rig.svc.start(RIYA, NUM_KAI).reason == "rate_limited"


def test_SEC_10_holder_who_moves_to_another_number_loses_the_old_numbers_exemption() -> None:
    rig = Rig(send_caps=SEND_CAPS)
    rig.bind(RIYA, NUM_KAI)
    rig.bind(RIYA, NUM_RIYA)
    assert _no_link_to(rig, NUM_KAI)
    rig.clock.advance(3600)
    _lapsed_then_capped(rig)
    assert rig.svc.start(RIYA, NUM_KAI).reason == "rate_limited"


# --- unknown cap keys are refused; an explicit empty mapping is no caps ---------------------------------


@pytest.mark.parametrize("caps", [{"number": ((3600, 3),)}, {"n": ((3600, 3),), "x": ()}, {"user": ()}])
def test_SEC_10_unknown_send_caps_keys_are_refused(caps: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="send_caps"):
        Rig(send_caps=caps)


@pytest.mark.parametrize(
    "caps", [{"n": ((0, 3),)}, {"u": ((-60, 3),)}, {"n": ((3600, 0),)}, {"u": ((3600, 3), (86400, -1))}]
)
def test_SEC_10_send_caps_windows_and_limits_must_be_positive(caps: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="send_caps"):
        Rig(send_caps=caps)


def test_SEC_10_explicit_empty_send_caps_means_no_caps_and_the_default_stays_off() -> None:
    for kw in ({"send_caps": {}}, {}):
        rig = Rig(**kw)
        assert [rig.svc.start(RIYA, NUM_KAI).ok for _ in range(8)] == [True] * 8


# --- one shared Sender ----------------------------------------------------------------------------------


def test_FR_CHN_03_binding_inbound_cards_and_keywords_share_one_sender_protocol() -> None:
    assert binding.Sender is inbound.Sender is keywords.Sender is whatsapp.Sender
    assert whatsapp.Sender in cards.CardSender.__mro__


# --- a card id is reserved while its first send is in flight -------------------------------------------


class SlowSender:
    def __init__(self) -> None:
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls = 0
        self._lock = threading.Lock()

    def send_text(self, to: str, body: str) -> None:
        return None

    def send_buttons(self, to: str, body: str, buttons: Any) -> str:
        with self._lock:
            self.calls += 1
            n = self.calls
        self.entered.set()
        self.release.wait(5)
        return f"wamid.SLOW{n}"


def test_FR_CHN_05_two_concurrent_sends_of_one_card_send_once() -> None:
    rig = CardRig()
    slow = SlowSender()
    rig.svc._sender = slow  # swap the sender: the rig's fake does not block
    results: list[Any] = []
    threads = [threading.Thread(target=lambda: results.append(rig.svc.send_card(rig.cards[QUESTION], user_id=RIYA)))]
    threads[0].start()
    assert slow.entered.wait(5)
    threads.append(
        threading.Thread(target=lambda: results.append(rig.svc.send_card(rig.cards[QUESTION], user_id=RIYA)))
    )
    threads[1].start()
    threading.Event().wait(0.2)  # the second call is now at the reservation (or, wrongly, sending)
    slow.release.set()
    for t in threads:
        t.join(5)
    assert slow.calls == 1
    assert sorted((r.outcome, r.message_id) for r in results) == [("sent", "wamid.SLOW1")] * 2
    assert len(rig.events.of_type("channel.message_out")) == 1


def test_FR_CHN_05_a_failed_first_send_releases_the_reservation() -> None:
    rig = CardRig()

    def boom(*a: Any, **k: Any) -> str:
        raise OSError("graph down")

    real = rig.sender.send_buttons
    rig.sender.send_buttons = boom  # type: ignore[method-assign]
    assert rig.svc.send_card(rig.cards[QUESTION], user_id=RIYA).outcome == "failed"
    rig.sender.send_buttons = real  # type: ignore[method-assign]
    assert rig.svc.send_card(rig.cards[QUESTION], user_id=RIYA).outcome == "sent"


# --- repeated Hold or Edit first taps write one event and make one API call --------------------------------


def _gate_stays_open(rig: CardRig, monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(world_id: str, card_id: str, *, option: str, **kw: Any) -> ApiAnswer:
        rig.api.calls.append(dict(world_id=world_id, card_id=card_id, option=option, at=rig.clock(), **kw))
        return ApiAnswer("answered")

    monkeypatch.setattr(rig.api, "answer", answer)


@pytest.mark.parametrize(("option", "reply"), [("hold", "Held."), ("edit", "To edit, open it in Tilo")])
def test_FR_CHN_05_repeated_hold_or_edit_taps_write_one_event_and_one_api_call(
    monkeypatch: pytest.MonkeyPatch, option: str, reply: str
) -> None:
    rig = CardRig()
    _gate_stays_open(rig, monkeypatch)
    sent = rig.send(GATE_T3)
    for _ in range(3):
        assert rig.tap(sent, option, card_id=GATE_T3).outcome == "answered"
    assert len(rig.api.calls) == 1
    assert len(rig.events.of_type("channel.message_in")) == 1
    replies = rig.sender.texts_to(NUM_RIYA)
    assert len(replies) == 3 and len(set(replies)) == 1 and replies[0].startswith(reply)


def test_FR_CHN_05_hold_then_edit_are_different_options_and_each_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = CardRig()
    _gate_stays_open(rig, monkeypatch)
    sent = rig.send(GATE_T3)
    for option in ("hold", "edit", "hold"):
        rig.tap(sent, option, card_id=GATE_T3)
    assert [c["option"] for c in rig.api.calls] == ["hold", "edit"]
    assert [p["data"]["option"] for p in rig.events.of_type("channel.message_in")] == ["hold", "edit"]


def test_FR_CHN_05_repeated_hold_still_cancels_a_pending_pin_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = CardRig()
    _gate_stays_open(rig, monkeypatch)
    sent = rig.send(GATE_T3)
    rig.tap(sent, "hold", card_id=GATE_T3)
    assert rig.tap(sent, "approve", card_id=GATE_T3).outcome == "pin_required"
    assert rig.tap(sent, "hold", card_id=GATE_T3).outcome == "answered"  # deduped, last choice still wins
    assert rig.text(NUM_RIYA, rig.pin).outcome == "pin_late"
    assert rig.pins.checks == [] and len(rig.api.calls) == 1
