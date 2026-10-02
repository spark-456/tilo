"""FR-CHN-03 acceptance, binding side: "Number binding with one-time code, encryption and 30-day
re-confirmation" (PRD 11.6). PRD 11.1: "The user opts in on the web app, enters their number and confirms
a one-time code sent over WhatsApp. Only bound numbers can give commands. Numbers are stored encrypted,
with a hash for lookup. Binding is re-confirmed every 30 days." PRD 15.1 ChannelBinding: user, channel,
number hash, encrypted number, verified at, expires. SEC-06: channel identity binding.

Public interface: `tilo_channels.binding` (API_FR_CHN_03_05.md). The module does not exist yet, so this
file fails at collection with ModuleNotFoundError.

Defaults the PRD does not state (BQ-89): a 6-digit code valid for 10 minutes with 5 attempts; a number
bound to another user is refused at `start` and no code is sent; the 30-day window is
`now < verified_at + 30 d`; the previous number stays bound until the new one is confirmed.
"""

from __future__ import annotations

import importlib
import logging
import re
from typing import Any

import pytest
from _channels_lib import T0, FakeClock, FakeSender
from _chn_0305_lib import (
    CODE_TTL_S,
    KAI,
    MAX_CODE_ATTEMPTS,
    NUM_KAI,
    NUM_RIYA,
    NUM_SAM,
    RIYA,
    SAM,
    THIRTY_DAYS_S,
    TYPED_RIYA,
    FakeBindingStore,
    FakeCipher,
    RaisingSender,
    fake_key,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


def _binding() -> Any:
    """The module under test, imported at call time so each test fails on its own until it exists."""
    return importlib.import_module("tilo_channels.binding")


def BindingService(**kw: Any) -> Any:  # noqa: N802 - stands in for the class
    return _binding().BindingService(**kw)


def normalise_number(raw: str) -> Any:
    return _binding().normalise_number(raw)


_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


class Rig:
    def __init__(self, *, sender: object | None = None) -> None:
        self.clock = FakeClock()
        self.store = FakeBindingStore()
        self.cipher = FakeCipher()
        self.sender = sender if sender is not None else FakeSender(self.clock)
        self.svc = BindingService(
            store=self.store, cipher=self.cipher, sender=self.sender, clock=self.clock, hash_key=fake_key()
        )

    def last_code(self, number: str) -> str:
        bodies = self.sender.bodies_to(number)  # type: ignore[attr-defined]
        assert bodies, "no code was sent to the number"
        codes = _CODE.findall(bodies[-1])
        assert len(codes) == 1, "the code message must carry exactly one 6-digit code"
        return codes[0]

    def bind(self, user: str, number: str) -> None:
        assert self.svc.start(user, number).ok
        result = self.svc.confirm(user, self.last_code(normalise_number(number) or number))
        assert result.ok, result.reason


@pytest.fixture()
def rig() -> Rig:
    return Rig()


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


# --- the happy path -----------------------------------------------------------------------------


def test_FR_CHN_03_start_sends_one_time_code_over_whatsapp(rig: Rig) -> None:
    result = rig.svc.start(RIYA, TYPED_RIYA)
    assert result.ok and result.reason is None
    assert len(rig.sender.sent) == 1
    to, body, _ = rig.sender.sent[0]
    assert to == NUM_RIYA  # the typed E.164 number, normalised to Meta's wa_id
    assert len(_CODE.findall(body)) == 1


def test_FR_CHN_03_confirm_with_code_binds_number_to_user(rig: Rig) -> None:
    rig.svc.start(RIYA, TYPED_RIYA)
    assert rig.svc.user_for(NUM_RIYA) is None  # unverified: not bound yet
    result = rig.svc.confirm(RIYA, rig.last_code(NUM_RIYA))
    assert result.ok and result.reason is None
    assert rig.svc.user_for(NUM_RIYA) == RIYA
    assert rig.svc.user_for(TYPED_RIYA) == RIYA  # any spelling of the same number
    assert rig.svc.number_for(RIYA) == NUM_RIYA
    status = rig.svc.status(RIYA)
    assert status.state == "bound"
    assert status.number_masked is not None and status.number_masked.endswith("0101")
    assert NUM_RIYA not in status.number_masked and "202555" not in status.number_masked
    assert status.verified_at == pytest.approx(float(T0))
    assert status.expires_at == pytest.approx(float(T0) + THIRTY_DAYS_S)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+1 202-555-0101", "12025550101"),
        ("+1 (202) 555.0101", "12025550101"),
        ("12025550101", "12025550101"),
        ("+12025550101", "12025550101"),
        ("", None),
        ("+1 202 555 01O1", None),  # letter O
        ("1234567", None),  # 7 digits: too short
        ("1234567890123456", None),  # 16 digits: longer than E.164
        ("++12025550101", None),
        ("+1 202 555 0101 ext 2", None),
    ],
)
def test_FR_CHN_03_numbers_normalise_to_wa_id(raw: str, expected: str | None) -> None:
    assert normalise_number(raw) == expected


def test_FR_CHN_03_invalid_number_is_refused_and_nothing_sent(rig: Rig) -> None:
    result = rig.svc.start(RIYA, "not a number")
    assert not result.ok and result.reason == "invalid_number"
    assert rig.sender.sent == []


# --- refusal of unverified numbers ---------------------------------------------------------------


def test_FR_CHN_03_wrong_code_does_not_bind(rig: Rig) -> None:
    rig.svc.start(RIYA, NUM_RIYA)
    result = rig.svc.confirm(RIYA, _wrong(rig.last_code(NUM_RIYA)))
    assert not result.ok and result.reason == "wrong_code"
    assert rig.svc.user_for(NUM_RIYA) is None
    assert rig.svc.status(RIYA).state == "pending"


def test_FR_CHN_03_confirm_without_start_is_refused(rig: Rig) -> None:
    result = rig.svc.confirm(RIYA, "123456")
    assert not result.ok and result.reason == "no_pending"
    assert rig.svc.status(RIYA).state == "none"


def test_FR_CHN_03_code_expires_after_ten_minutes(rig: Rig) -> None:
    rig.svc.start(RIYA, NUM_RIYA)
    code = rig.last_code(NUM_RIYA)
    rig.clock.advance(CODE_TTL_S)  # valid while now < sent_at + 600 s
    result = rig.svc.confirm(RIYA, code)
    assert not result.ok and result.reason == "expired"
    assert rig.svc.user_for(NUM_RIYA) is None


def test_FR_CHN_03_code_just_inside_ttl_still_binds(rig: Rig) -> None:
    rig.svc.start(RIYA, NUM_RIYA)
    code = rig.last_code(NUM_RIYA)
    rig.clock.advance(CODE_TTL_S - 1)
    assert rig.svc.confirm(RIYA, code).ok


def test_FR_CHN_03_code_is_single_use(rig: Rig) -> None:
    rig.svc.start(RIYA, NUM_RIYA)
    code = rig.last_code(NUM_RIYA)
    assert rig.svc.confirm(RIYA, code).ok
    rig.svc.unbind(RIYA)
    again = rig.svc.confirm(RIYA, code)
    assert not again.ok
    assert rig.svc.user_for(NUM_RIYA) is None


def test_FR_CHN_03_fifth_wrong_code_voids_the_pending_code(rig: Rig) -> None:
    rig.svc.start(RIYA, NUM_RIYA)
    code = rig.last_code(NUM_RIYA)
    reasons = [rig.svc.confirm(RIYA, _wrong(code)).reason for _ in range(MAX_CODE_ATTEMPTS)]
    assert reasons[:-1] == ["wrong_code"] * (MAX_CODE_ATTEMPTS - 1)
    assert reasons[-1] == "too_many_attempts"
    late = rig.svc.confirm(RIYA, code)  # even the right code is refused now
    assert not late.ok and late.reason == "too_many_attempts"
    assert rig.svc.user_for(NUM_RIYA) is None
    # A new start issues a new code and resets the attempts.
    rig.svc.start(RIYA, NUM_RIYA)
    assert rig.svc.confirm(RIYA, rig.last_code(NUM_RIYA)).ok


def test_FR_CHN_03_new_start_replaces_the_pending_code(rig: Rig) -> None:
    rig.svc.start(RIYA, NUM_RIYA)
    first = rig.last_code(NUM_RIYA)
    rig.svc.start(RIYA, NUM_RIYA)
    second = rig.last_code(NUM_RIYA)
    if first != second:
        assert rig.svc.confirm(RIYA, first).reason == "wrong_code"
    assert rig.svc.confirm(RIYA, second).ok


def test_FR_CHN_03_codes_are_not_predictable(rig: Rig) -> None:
    codes = set()
    for _ in range(20):
        rig.svc.start(RIYA, NUM_RIYA)
        codes.add(rig.last_code(NUM_RIYA))
    assert len(codes) >= 15  # fresh random codes, not a counter or a constant


def test_FR_CHN_03_code_for_one_user_does_not_confirm_another(rig: Rig) -> None:
    rig.svc.start(RIYA, NUM_RIYA)
    code = rig.last_code(NUM_RIYA)
    rig.svc.start(SAM, NUM_SAM)
    if code != rig.last_code(NUM_SAM):
        assert not rig.svc.confirm(SAM, code).ok
    assert rig.svc.user_for(NUM_RIYA) is None


def test_FR_CHN_03_failed_send_keeps_no_pending_code() -> None:
    rig = Rig(sender=RaisingSender())
    result = rig.svc.start(RIYA, NUM_RIYA)
    assert not result.ok and result.reason == "send_failed"
    assert rig.svc.status(RIYA).state == "none"


# --- rebinding, unbinding, one number to one user ------------------------------------------------


def test_FR_CHN_03_rebinding_moves_the_user_to_the_new_number(rig: Rig) -> None:
    rig.bind(RIYA, NUM_RIYA)
    rig.svc.start(RIYA, NUM_KAI)
    assert rig.svc.user_for(NUM_RIYA) == RIYA  # the old number stays bound until the new one is confirmed
    assert rig.svc.user_for(NUM_KAI) is None
    assert rig.svc.confirm(RIYA, rig.last_code(NUM_KAI)).ok
    assert rig.svc.user_for(NUM_KAI) == RIYA
    assert rig.svc.user_for(NUM_RIYA) is None
    assert rig.svc.number_for(RIYA) == NUM_KAI


def test_FR_CHN_03_unbind_removes_the_binding(rig: Rig) -> None:
    rig.bind(RIYA, NUM_RIYA)
    assert rig.svc.unbind(RIYA) is True
    assert rig.svc.user_for(NUM_RIYA) is None
    assert rig.svc.number_for(RIYA) is None
    assert rig.svc.status(RIYA).state == "none"
    assert rig.svc.unbind(RIYA) is False


def test_FR_CHN_03_unbound_number_can_be_bound_by_someone_else(rig: Rig) -> None:
    rig.bind(RIYA, NUM_RIYA)
    rig.svc.unbind(RIYA)
    rig.bind(SAM, NUM_RIYA)
    assert rig.svc.user_for(NUM_RIYA) == SAM
    assert rig.svc.number_for(RIYA) is None


def test_FR_CHN_03_number_bound_to_another_user_is_refused(rig: Rig) -> None:
    rig.bind(RIYA, NUM_RIYA)
    sent_before = len(rig.sender.sent)
    result = rig.svc.start(SAM, TYPED_RIYA)
    assert not result.ok and result.reason == "number_taken"
    assert len(rig.sender.sent) == sent_before  # no code goes to Riya's phone
    assert rig.svc.user_for(NUM_RIYA) == RIYA


def test_FR_CHN_03_first_confirm_wins_a_contested_number(rig: Rig) -> None:
    rig.svc.start(RIYA, NUM_KAI)
    riya_code = rig.last_code(NUM_KAI)
    rig.svc.start(SAM, NUM_KAI)
    sam_code = rig.last_code(NUM_KAI)
    assert rig.svc.confirm(SAM, sam_code).ok
    late = rig.svc.confirm(RIYA, riya_code)
    assert not late.ok and late.reason == "number_taken"
    assert rig.svc.user_for(NUM_KAI) == SAM


# --- 30-day re-confirmation -----------------------------------------------------------------------


def test_FR_CHN_03_binding_lapses_after_thirty_days(rig: Rig) -> None:
    rig.bind(RIYA, NUM_RIYA)
    rig.clock.advance(THIRTY_DAYS_S - 1)
    assert rig.svc.user_for(NUM_RIYA) == RIYA
    rig.clock.advance(1)
    assert rig.svc.user_for(NUM_RIYA) is None
    assert rig.svc.number_for(RIYA) is None
    assert rig.svc.status(RIYA).state == "expired"


def test_FR_CHN_03_reconfirmation_renews_for_another_thirty_days(rig: Rig) -> None:
    rig.bind(RIYA, NUM_RIYA)
    rig.clock.advance(THIRTY_DAYS_S + 5)
    rig.bind(RIYA, NUM_RIYA)  # same user, same number: allowed, not "number_taken"
    renewed_at = rig.clock()
    assert rig.svc.user_for(NUM_RIYA) == RIYA
    assert rig.svc.status(RIYA).expires_at == pytest.approx(renewed_at + THIRTY_DAYS_S)
    rig.clock.advance(THIRTY_DAYS_S - 1)
    assert rig.svc.user_for(NUM_RIYA) == RIYA


# --- encryption, hash lookup, no plaintext --------------------------------------------------------


def _spellings(number: str) -> list[str]:
    return [number, "+" + number, number[1:], number[-7:]]  # wa_id, E.164, national, subscriber digits


def test_FR_CHN_03_number_is_stored_encrypted_never_in_clear(rig: Rig) -> None:
    rig.svc.start(RIYA, TYPED_RIYA)
    code = rig.last_code(NUM_RIYA)
    rig.svc.confirm(RIYA, code)
    dump = rig.store.dump()
    for spelling in _spellings(NUM_RIYA):
        assert spelling not in dump
    assert code not in dump  # the code is never stored in clear either
    assert NUM_RIYA in rig.cipher.encrypted
    assert any(ct in dump for ct in rig.cipher.ciphertexts())


def test_FR_CHN_03_lookup_by_number_does_not_decrypt_every_binding(rig: Rig) -> None:
    rig.bind(RIYA, NUM_RIYA)
    rig.bind(SAM, NUM_SAM)
    rig.bind(KAI, NUM_KAI)
    rig.cipher.decrypted.clear()
    assert rig.svc.user_for(NUM_SAM) == SAM
    assert len(rig.cipher.decrypted) <= 1  # looked up by hash (PRD 11.1), not by scanning ciphertexts
    rig.cipher.decrypted.clear()
    assert rig.svc.user_for("12025550177") is None
    assert rig.cipher.decrypted == []


def test_FR_CHN_03_lookup_hash_is_keyed(rig: Rig) -> None:
    rig.bind(RIYA, NUM_RIYA)
    other = BindingService(store=rig.store, cipher=rig.cipher, sender=rig.sender, clock=rig.clock, hash_key=fake_key())
    assert other.user_for(NUM_RIYA) is None  # a plain hash of a phone number is trivially reversible


def test_FR_CHN_03_short_hash_key_is_refused() -> None:
    clock = FakeClock()
    with pytest.raises(ValueError):
        BindingService(
            store=FakeBindingStore(), cipher=FakeCipher(), sender=FakeSender(clock), clock=clock, hash_key=b"short"
        )


def test_FR_CHN_03_logs_never_carry_number_or_code(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    rig.svc.start(RIYA, TYPED_RIYA)
    code = rig.last_code(NUM_RIYA)
    rig.svc.confirm(RIYA, _wrong(code))
    rig.svc.confirm(RIYA, code)
    rig.svc.start(SAM, NUM_RIYA)
    text = caplog.text
    for spelling in _spellings(NUM_RIYA):
        assert spelling not in text
    assert code not in text


# --- invariant: one number to one user, one number per user, bound only by a confirmed code -------

_USERS = (RIYA, SAM, KAI)
_NUMBERS = (NUM_RIYA, NUM_SAM, NUM_KAI)

_op = st.one_of(
    st.tuples(st.just("start"), st.sampled_from(_USERS), st.sampled_from(_NUMBERS)),
    st.tuples(st.just("confirm"), st.sampled_from(_USERS), st.booleans()),
    st.tuples(st.just("unbind"), st.sampled_from(_USERS), st.none()),
    st.tuples(st.just("wait"), st.integers(min_value=1, max_value=400), st.none()),
)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ops=st.lists(_op, max_size=30))
def test_FR_CHN_03_property_bindings_match_reference_model(ops: list[tuple]) -> None:
    """The service agrees, after every step, with a small reference model of PRD 11.1 + BQ-89: a number
    is bound only by a correct, live, unexhausted code; one number to one user; one number per user."""
    rig = Rig()
    bound: dict[str, str] = {}  # number -> user
    pending: dict[str, list] = {}  # user -> [number, code, sent_at, wrong, uncertain]
    for op, a, b in ops:
        now = rig.clock()
        if op == "start":
            taken = bound.get(b) not in (None, a)
            result = rig.svc.start(a, b)
            assert result.ok is (not taken)
            if result.ok:
                pending[a] = [b, rig.last_code(b), now, 0, False]
        elif op == "confirm":
            p = pending.get(a)
            code = (p[1] if b else _wrong(p[1])) if p else "000000"
            result = rig.svc.confirm(a, code)
            live = p is not None and now < p[2] + CODE_TTL_S and p[3] < MAX_CODE_ATTEMPTS
            contested = p is not None and bound.get(p[0]) not in (None, a)
            if p is not None and (p[4] or contested):
                # The PRD does not say whether a refused "number_taken" keeps the pending code or how it
                # counts attempts, so after one the model follows the service instead of predicting it.
                assert not (contested and result.ok)
                assert not result.ok or (b and now < p[2] + CODE_TTL_S)  # never a wrong or stale code
                p[4] = True
                expect = result.ok
            else:
                expect = bool(live and b)
                assert result.ok is expect, (op, a, b, result)
                if live and not b:
                    p[3] += 1  # type: ignore[index]
            if expect:
                for n in [n for n, u in bound.items() if u == a]:
                    del bound[n]
                bound[p[0]] = a  # type: ignore[index]
                del pending[a]
        elif op == "unbind":
            rig.svc.unbind(a)
            for n in [n for n, u in bound.items() if u == a]:
                del bound[n]
            pending.pop(a, None)
        else:
            rig.clock.advance(a)
        for number in _NUMBERS:
            assert rig.svc.user_for(number) == bound.get(number)
        for user in _USERS:
            mine = [n for n, u in bound.items() if u == user]
            assert len(mine) <= 1
            assert rig.svc.number_for(user) == (mine[0] if mine else None)
