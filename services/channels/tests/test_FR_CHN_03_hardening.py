"""FR-CHN-03 / SEC-10 hardening from the #153 reviews (issue #156): code-send caps, number normalisation,
attempt slots that outlive a replaced code, the confirm race, store failures, the opt-in rate and router
exceptions. Defaults: BQ-89 in docs/open-questions.md."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from _channels_lib import FakeClock, FakeSender
from _chn_0305_lib import (
    NUM_KAI,
    NUM_RIYA,
    NUM_STRANGER,
    RIYA,
    SAM,
    THIRTY_DAYS_S,
    WEB_URL,
    FakeBindingStore,
    FakeCipher,
)
from _chn_0305_lib import fake_key as _key
from tilo_channels.binding import SEND_CAPS, BindingService, normalise_number
from tilo_channels.inbound import InboundRouter
from tilo_channels.whatsapp import InboundMessage

_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


class HookStore(FakeBindingStore):
    """Runs `hook` once, right after the first get or put (`hook[0]`) of a key starting with `hook[1]`."""

    def __init__(self) -> None:
        super().__init__()
        self.hook: tuple[str, str, Callable[[], None]] | None = None
        self.fail_put: str | None = None

    def _fire(self, op: str, key: str) -> None:
        if self.hook and self.hook[0] == op and key.startswith(self.hook[1]):
            fn, self.hook = self.hook[2], None
            fn()

    def get(self, key: str) -> dict | None:
        value = super().get(key)
        self._fire("get", key)
        return value

    def put(self, key: str, value: dict) -> None:
        if self.fail_put and key.startswith(self.fail_put):
            raise OSError("store down")
        super().put(key, value)
        self._fire("put", key)


class Rig:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.store = HookStore()
        self.sender = FakeSender(self.clock)
        self.key = _key()
        self.svc = self.service()

    def service(self) -> BindingService:
        return BindingService(
            store=self.store,
            cipher=FakeCipher(),
            sender=self.sender,
            clock=self.clock,
            hash_key=self.key,
            send_caps=SEND_CAPS,
        )

    def code(self, number: str) -> str:
        return _CODE.findall(self.sender.bodies_to(number)[-1])[0]

    def bind(self, user: str, number: str) -> None:
        assert self.svc.start(user, number).ok
        assert self.svc.confirm(user, self.code(number)).ok


def _num(i: int) -> str:
    return f"120255501{i:02d}"  # fictional 555-01xx numbers


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


# --- SEC-10 send caps ----------------------------------------------------------------------------


def test_SEC_10_number_gets_at_most_three_codes_an_hour_across_instances() -> None:
    rig = Rig()
    other = rig.service()  # a second instance on the same store: the caps live in the store
    results = [svc.start(user, NUM_KAI) for svc, user in ((rig.svc, RIYA), (other, SAM), (rig.svc, RIYA))]
    assert all(r.ok for r in results)
    capped = other.start(SAM, NUM_KAI)
    assert (capped.ok, capped.reason) == (False, "rate_limited")
    assert len(rig.sender.bodies_to(NUM_KAI)) == 3
    rig.clock.advance(3600)
    assert rig.svc.start(RIYA, NUM_KAI).ok


def test_SEC_10_number_gets_at_most_ten_codes_a_day() -> None:
    rig = Rig()
    reasons = []
    for hour in range(5):
        reasons += [rig.svc.start(RIYA if i % 2 else SAM, NUM_KAI).reason for i in range(3)]
        rig.clock.advance(3600)
    assert reasons == [None] * 10 + ["rate_limited"] * 5
    assert len(rig.sender.bodies_to(NUM_KAI)) == 10
    rig.clock.advance(86400)
    assert rig.svc.start(RIYA, NUM_KAI).ok


def test_SEC_10_user_gets_at_most_five_codes_an_hour_and_twenty_a_day() -> None:
    rig = Rig()
    hour = [rig.svc.start(RIYA, _num(i)).reason for i in range(10, 16)]
    assert hour == [None] * 5 + ["rate_limited"]
    for h in range(1, 4):
        rig.clock.advance(3600)
        assert [rig.svc.start(RIYA, _num(10 + 5 * h + i)).ok for i in range(1, 6)] == [True] * 5
    assert len(rig.sender.sent) == 20
    rig.clock.advance(3600)
    assert rig.svc.start(RIYA, _num(40)).reason == "rate_limited"


def test_SEC_10_capped_start_keeps_the_pending_code_and_its_attempts() -> None:
    rig = Rig()
    for _ in range(3):
        rig.svc.start(RIYA, NUM_KAI)
    code = rig.code(NUM_KAI)
    assert [rig.svc.confirm(RIYA, _wrong(code)).reason for _ in range(4)] == ["wrong_code"] * 4
    assert rig.svc.start(RIYA, NUM_KAI).reason == "rate_limited"
    assert rig.svc.confirm(RIYA, _wrong(code)).reason == "too_many_attempts"


# --- normalisation ---------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["0012025550101", "+0012025550101", "012025550101", "00000000", "+1 111 111 1111"])
def test_FR_CHN_03_leading_zero_and_degenerate_numbers_are_refused(raw: str) -> None:
    assert normalise_number(raw) is None
    rig = Rig()
    assert rig.svc.start(RIYA, raw).reason == "invalid_number"
    assert rig.sender.sent == []


def test_FR_CHN_03_double_zero_cannot_bypass_number_taken() -> None:
    rig = Rig()
    rig.bind(RIYA, NUM_RIYA)
    assert not rig.svc.start(SAM, "00" + NUM_RIYA).ok
    assert rig.svc.user_for(NUM_RIYA) == RIYA


# --- attempt slots, the confirm race, store failures -------------------------------------------------


def test_FR_CHN_03_new_start_keeps_the_replaced_codes_attempt_slots() -> None:
    rig = Rig()
    rig.svc.start(RIYA, NUM_RIYA)
    old = rig.code(NUM_RIYA)
    for _ in range(4):
        rig.svc.confirm(RIYA, _wrong(old))
    # A confirm that read the old code is still running when a new start replaces it.
    rig.store.hook = ("get", "pending:", lambda: rig.svc.start(RIYA, NUM_RIYA) and None)
    assert rig.svc.confirm(RIYA, _wrong(old)).reason == "too_many_attempts"  # 5 guesses, not 9


def test_FR_CHN_03_losing_confirm_racer_is_not_told_bound() -> None:
    rig = Rig()
    rig.bind(SAM, NUM_KAI)
    rig.clock.advance(THIRTY_DAYS_S + 1)  # Sam's binding lapsed: the number is free again
    rig.bind(RIYA, NUM_RIYA)
    rig.svc.start(RIYA, NUM_KAI)
    riya_code = rig.code(NUM_KAI)
    rig.svc.start(SAM, NUM_KAI)
    sam_code = rig.code(NUM_KAI)
    late: list[Any] = []
    rig.store.hook = ("put", "num:", lambda: late.append(rig.svc.confirm(SAM, sam_code)))
    riya = rig.svc.confirm(RIYA, riya_code)
    assert [r.ok for r in late] == [True]
    assert (riya.ok, riya.reason) == (False, "number_taken")
    assert rig.svc.user_for(NUM_KAI) == SAM
    assert rig.svc.user_for(NUM_RIYA) == RIYA  # the loser keeps the number it had


def test_FR_CHN_03_store_failure_before_the_send_strands_no_code() -> None:
    rig = Rig()
    rig.store.fail_put = "pending:"
    result = rig.svc.start(RIYA, NUM_RIYA)
    assert (result.ok, result.reason) == (False, "unavailable")
    assert rig.sender.sent == []


# --- opt-in rate and router failures ------------------------------------------------------------------


def _msg(n: int, sender: str, text: str = "status of my supplier summary?") -> InboundMessage:
    return InboundMessage(f"wamid.H{n:04d}", sender, 0, "text", text)


def test_FR_CHN_03_opt_in_at_most_once_per_number_per_ten_minutes() -> None:
    rig = Rig()
    router = InboundRouter(bindings=rig.svc, sender=rig.sender, web_url=WEB_URL, opt_in_allowed=rig.svc.allow_opt_in)
    routes = [router.handle(_msg(i, NUM_STRANGER)).route for i in range(4)]
    assert routes == ["opt_in"] * 4
    assert len(rig.sender.bodies_to(NUM_STRANGER)) == 1
    router.handle(_msg(9, NUM_KAI))
    assert len(rig.sender.bodies_to(NUM_KAI)) == 1  # counted per number
    rig.clock.advance(600)
    router.handle(_msg(10, NUM_STRANGER))
    assert len(rig.sender.bodies_to(NUM_STRANGER)) == 2


class _Boom:
    def handle(self, message: InboundMessage) -> Any:
        raise RuntimeError("handler down")


@pytest.mark.parametrize("which", ["keywords", "cards"])
def test_FR_CHN_03_router_reports_a_failed_handler_once(which: str) -> None:
    rig = Rig()
    rig.bind(RIYA, NUM_RIYA)
    before = len(rig.sender.bodies_to(NUM_RIYA))
    kwargs: dict[str, Any] = {which: _Boom()}
    router = InboundRouter(bindings=rig.svc, sender=rig.sender, web_url=WEB_URL, **kwargs)
    assert router.handle(_msg(1, NUM_RIYA)).route == "failed"
    replies = rig.sender.bodies_to(NUM_RIYA)[before:]
    assert len(replies) == 1 and "supplier" not in replies[0]
