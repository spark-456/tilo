"""FR-CHN-07: email notifications and digests carry signed single-use links (PRD 11.6; 10.3 "Email:
Summary with signed, single-use action links, valid 24 h. Questions only; gates need sign-in"; 16.2
"Forwarded email action links: signed, single-use, 24-hour links; gates need sign-in"; 16.4 SEC-08
"Forged or replayed requests rejected"; services/channels/CLAUDE.md "signed, single-use and expire in
24 h"; docs/security/p4-policy-invariants.md PI-04 "a gate is answered only where the person is
known ... never email").

Acceptance (PRD 11.6): a reused or expired link is refused; gates require sign-in. A link can open a
card, but approving a gate always needs an authenticated person; a link alone never authorises a T3 or
gate action.

These tests DEFINE the API of `tilo_channels.links` (package `tilo_channels` does not exist yet):

    class LinkRefused(Exception):
        reason: str   # one of the stable codes below; str(exc) never contains the token, nonce or a key

    class KeyRing:
        def __init__(self, keys: Mapping[str, bytes], active: str) -> None
        active_kid: str                                   # the key new links are signed with
        def add(self, kid: str, key: bytes, *, activate: bool = False) -> None
        def retire(self, kid: str) -> None                # ValueError if kid is the active key
        # Verification accepts every key in the ring (active or not) until it is retired. The service
        # consults the ring on every issue and redeem; it does not snapshot it.

    @dataclass(frozen=True) class CardState:
        card: Mapping[str, Any]    # a contracts/card.schema.json card
        answered: bool             # answered on any channel, or closed by its timeout

    class NonceStore(Protocol):
        def consume(self, nonce: str, expires_at: datetime) -> bool   # atomic; True only the first time

    class LinkService:
        def __init__(self, *, keys: KeyRing, nonces: NonceStore, clock: Callable[[], datetime],
                     cards: Callable[[str], CardState | None], base_url: str) -> None
        def issue(self, *, card_id: str, user_id: str, action: str, option: str | None = None) -> IssuedLink
        def redeem(self, token: str, *, card_id: str, action: str, viewer: str | None = None,
                   option: str | None = None) -> Redemption

    @dataclass(frozen=True) class IssuedLink:
        token: str; url: str; nonce: str; key_id: str; card_id: str; user_id: str
        action: str; option: str | None; issued_at: datetime; expires_at: datetime
    @dataclass(frozen=True) class Redemption:
        card_id: str; user_id: str; action: str; option: str | None; nonce: str
        authn: str                  # "session" if `viewer` was the bound user, else "link"
        requires_sign_in: bool      # the caller must send the person through sign-in before anything
                                    # else; the link itself never authorises a gate or consent action

Actions are "open" (show the card) and "answer" (answer a question card with one option; the option is
bound into the token). `viewer` is the id of the authenticated person on the request, or None.

Stable refusal reasons: malformed, bad_signature, unknown_key, expired, used, wrong_card, wrong_user,
wrong_action, wrong_option, card_answered, unknown_card, unknown_action, unknown_option, not_allowed.

PRD defaults and choices made where the PRD is silent (listed in the test-writer report too):
  D1 (PRD 10.3 "valid 24 h"): expires_at = issued_at + exactly 24 h. The boundary instant itself is not
     asserted; 23:59:59 is accepted and 24:00:01 refused.
  D2 (PRD 10.3 "Questions only; gates need sign-in"): an answer link is issued only for a card whose
     answer_channels contain "email" and whose kind is needs_you. gate and consent are refused outright
     even if a malformed card lists email; meeting follows its answer_channels (the schema excludes email).
  D3 (PRD 16.2): a possessed link alone is enough to answer a question card (authn "link"); a different
     signed-in viewer than the bound user is refused. For gate, consent and meeting cards, "open" with no
     signed-in viewer succeeds only as `requires_sign_in=True`.
  D4: a refusal never consumes the nonce (an attacker holding a forwarded link cannot burn it for the
     owner by presenting it wrongly). Only a fully valid redeem consumes it.
  D5: an unknown or retired key id are both "unknown_key" (no oracle between them).
  D6: a card already answered (or timed out) refuses answer links with "card_answered".
"""

from __future__ import annotations

import copy
import hmac
import inspect
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from _chn_links_lib import (
    ALICE,
    BOB,
    CONSENT,
    GATE,
    GATE_REV,
    MEETING,
    NOT_ANSWERABLE_BY_EMAIL,
    Q1,
    Q2,
    T0,
    TTL,
    FakeNonceStore,
    fresh_key,
    links,
    make_rig,
)
from hypothesis import given, settings
from hypothesis import strategies as st

SIGNATURE_FAILURES = {"malformed", "bad_signature", "unknown_key"}


def _refusal(L: Any, fn: Any, *args: Any, **kwargs: Any) -> str:
    """Call `fn`, require LinkRefused, return its reason code."""
    with pytest.raises(L.LinkRefused) as info:
        fn(*args, **kwargs)
    reason = info.value.reason
    assert isinstance(reason, str)
    return reason


# ---------------------------------------------------------------------------------------------------
# Issuing
# ---------------------------------------------------------------------------------------------------


def test_FR_CHN_07_issue_binds_card_user_action_option_and_expires_in_24h():
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    assert (link.card_id, link.user_id, link.action, link.option) == (Q1, ALICE, "answer", "per_kwh")
    assert link.issued_at == T0
    assert link.expires_at == T0 + timedelta(hours=24) == T0 + TTL
    assert link.key_id == "k1"
    assert isinstance(link.token, str) and link.token
    assert isinstance(link.nonce, str) and link.nonce


def test_FR_CHN_07_issue_returns_an_https_url_carrying_the_token():
    link = make_rig().issue(Q1, ALICE, "answer", "per_kwh")
    assert link.url.startswith("https://app.tilo.test/")
    assert link.token in link.url


def test_FR_CHN_07_issued_tokens_are_unique_with_long_random_nonces():
    """Same claims, 300 issues: every token and nonce differs (nonce is random, not derived from the claims)
    and carries at least 128 bits (22+ base64url chars)."""
    rig = make_rig()
    links_ = [rig.issue(Q1, ALICE, "answer", "per_kwh") for _ in range(300)]
    assert len({lk.token for lk in links_}) == 300
    assert len({lk.nonce for lk in links_}) == 300
    assert all(len(lk.nonce) >= 22 for lk in links_)


def test_FR_CHN_07_issue_for_unknown_card_is_refused():
    L = links()
    rig = make_rig()
    assert _refusal(L, rig.issue, "01J8Z3K4M5N6P7Q8R9S0T1V2ZZ", ALICE, "open", None) == "unknown_card"


@pytest.mark.parametrize("option", [None, "", "nope", "approve", "hold"])
def test_FR_CHN_07_issue_answer_needs_an_option_on_the_card(option):
    L = links()
    rig = make_rig()
    assert _refusal(L, rig.issue, Q1, ALICE, "answer", option) == "unknown_option"


@pytest.mark.parametrize("action", ["approve", "delete", "send", "", "OPEN", "Answer"])
def test_FR_CHN_07_issue_unknown_action_is_refused(action):
    L = links()
    rig = make_rig()
    assert _refusal(L, rig.issue, Q1, ALICE, action, None) == "unknown_action"


@pytest.mark.parametrize("card_id", NOT_ANSWERABLE_BY_EMAIL)
def test_FR_CHN_07_issue_answer_link_refused_for_cards_email_cannot_answer(card_id):
    """Gate, consent and meeting cards: no email answer link for any of their options, including approve
    (PRD 10.3 "Questions only; gates need sign-in"; PI-04)."""
    L = links()
    rig = make_rig()
    for opt in rig.book.cards[card_id]["options"]:
        assert _refusal(L, rig.issue, card_id, ALICE, "answer", opt["id"]) == "not_allowed"


@pytest.mark.parametrize("card_id", [GATE, GATE_REV, CONSENT])
def test_FR_CHN_07_issue_answer_link_refused_for_gate_even_if_card_lists_email(card_id):
    """Defence in depth: a gate or consent card that wrongly lists "email" still gets no answer link,
    so a link alone can never carry an approve (T3 or otherwise)."""
    L = links()
    rig = make_rig()
    rig.book.cards[card_id]["answer_channels"] = [*rig.book.cards[card_id]["answer_channels"], "email"]
    for opt in rig.book.cards[card_id]["options"]:
        assert _refusal(L, rig.issue, card_id, ALICE, "answer", opt["id"]) == "not_allowed"


@pytest.mark.parametrize("card_id", [Q1, Q2, GATE, GATE_REV, CONSENT, MEETING])
def test_FR_CHN_07_issue_open_link_allowed_for_every_card_kind(card_id):
    link = make_rig().issue(card_id, ALICE, "open", None)
    assert (link.card_id, link.action, link.option) == (card_id, "open", None)


# ---------------------------------------------------------------------------------------------------
# Redeeming: the happy paths
# ---------------------------------------------------------------------------------------------------


def test_FR_CHN_07_answer_link_for_a_question_card_redeems_once_from_the_link_alone():
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_pack")
    r = rig.redeem(link)
    assert (r.card_id, r.user_id, r.action, r.option) == (Q1, ALICE, "answer", "per_pack")
    assert r.nonce == link.nonce
    assert r.authn == "link"
    assert r.requires_sign_in is False
    # the nonce was consumed exactly once, with a retention that covers the link's life
    assert list(rig.store.consumed) == [link.nonce]
    assert len(rig.store.calls) == 1
    assert rig.store.consumed[link.nonce] >= link.expires_at


def test_FR_CHN_07_answer_link_with_the_bound_user_signed_in_reports_session_authn():
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    r = rig.redeem(link, viewer=ALICE)
    assert (r.user_id, r.authn, r.requires_sign_in) == (ALICE, "session", False)


def test_FR_CHN_07_open_link_for_a_question_card_needs_no_sign_in():
    rig = make_rig()
    r = rig.redeem(rig.issue(Q1, ALICE, "open", None))
    assert (r.action, r.option, r.requires_sign_in, r.authn) == ("open", None, False, "link")


@pytest.mark.parametrize("card_id", NOT_ANSWERABLE_BY_EMAIL)
def test_FR_CHN_07_gate_open_link_requires_sign_in_and_carries_no_answer(card_id):
    """A link can open a gate card, but with no signed-in person it only yields `requires_sign_in`; it
    carries no option and no authority (PRD 10.3, 16.2: gates need sign-in)."""
    rig = make_rig()
    r = rig.redeem(rig.issue(card_id, ALICE, "open", None))
    assert r.action == "open"
    assert r.option is None
    assert r.requires_sign_in is True
    assert r.authn == "link"


@pytest.mark.parametrize("card_id", [GATE, GATE_REV])
def test_FR_CHN_07_gate_open_link_with_the_signed_in_person_opens_but_never_answers(card_id):
    rig = make_rig()
    r = rig.redeem(rig.issue(card_id, ALICE, "open", None), viewer=ALICE)
    assert (r.action, r.option, r.requires_sign_in, r.authn) == ("open", None, False, "session")


def test_FR_CHN_07_digest_links_each_open_one_card_and_are_independent():
    """A digest carries one link per card (PRD 11.6 "notifications and digests"): redeeming one neither
    burns nor opens another."""
    L = links()
    rig = make_rig()
    cards = [Q1, Q2, GATE, MEETING]
    digest = [rig.issue(c, ALICE, "open", None) for c in cards]
    assert len({lk.nonce for lk in digest}) == len(cards)
    for lk in reversed(digest):
        assert rig.redeem(lk).card_id == lk.card_id
    for lk in digest:
        assert _refusal(L, rig.redeem, lk) == "used"


# ---------------------------------------------------------------------------------------------------
# Reuse and expiry (the PRD acceptance sentence)
# ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "card_id,action,option",
    [(Q1, "answer", "per_kwh"), (Q1, "open", None), (GATE, "open", None), (CONSENT, "open", None)],
)
def test_FR_CHN_07_reused_link_is_refused(card_id, action, option):
    L = links()
    rig = make_rig()
    link = rig.issue(card_id, ALICE, action, option)
    rig.redeem(link)
    assert _refusal(L, rig.redeem, link) == "used"
    assert _refusal(L, rig.redeem, link) == "used"
    assert len(rig.store.consumed) == 1


def test_FR_CHN_07_reused_link_is_refused_on_another_service_instance_sharing_the_store():
    """Two Cloud Run instances, one nonce store: single-use holds across instances."""
    L = links()
    rig = make_rig()
    other = rig.new_service()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    rig.redeem(link, service=other)
    assert _refusal(L, rig.redeem, link) == "used"
    assert _refusal(L, rig.redeem, link, service=other) == "used"


def test_FR_CHN_07_expired_link_is_refused():
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    rig.clock.advance(hours=24, seconds=1)
    assert _refusal(L, rig.redeem, link) == "expired"
    rig.clock.advance(days=30)
    assert _refusal(L, rig.redeem, link) == "expired"


def test_FR_CHN_07_expired_gate_open_link_is_refused():
    L = links()
    rig = make_rig()
    link = rig.issue(GATE, ALICE, "open", None)
    rig.clock.advance(hours=24, seconds=1)
    assert _refusal(L, rig.redeem, link, viewer=ALICE) == "expired"


def test_FR_CHN_07_link_is_valid_until_just_before_24h():
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    rig.clock.advance(hours=23, minutes=59, seconds=59)
    assert rig.redeem(link).card_id == Q1


def test_FR_CHN_07_refused_links_do_not_consume_the_nonce():
    """Signature, key, expiry and malformed refusals happen before the nonce store is touched, so garbage
    carrying a copied nonce cannot burn a real link."""
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")

    foreign = L.LinkService(
        keys=L.KeyRing(keys={"k1": fresh_key()}, active="k1"),
        nonces=FakeNonceStore(),
        clock=rig.clock,
        cards=rig.book,
        base_url="https://app.tilo.test",
    )
    forged = rig.issue(Q1, ALICE, "answer", "per_kwh", service=foreign)
    assert _refusal(L, rig.redeem, forged) == "bad_signature"
    assert _refusal(L, rig.redeem, link, token="") == "malformed"
    assert rig.store.consumed == {} and rig.store.calls == []

    rig.clock.advance(hours=25)
    assert _refusal(L, rig.redeem, link) == "expired"
    assert rig.store.consumed == {} and rig.store.calls == []


# ---------------------------------------------------------------------------------------------------
# Tampering and forgery
# ---------------------------------------------------------------------------------------------------


def _mutate(token: str, i: int) -> str:
    repl = "A" if token[i] != "A" else "B"
    return token[:i] + repl + token[i + 1 :]


def test_FR_CHN_07_tampered_token_is_refused_at_every_position():
    """Change any one character of a valid token. The mutation is refused (malformed, bad signature or
    unknown key) and burns nothing. The only tolerated exception is a non-canonical spelling of the SAME
    token (e.g. base64 padding bits): then the claims are identical and the original is now `used`, so it
    still cannot be redeemed twice."""
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    base = rig.redeem(link, service=rig.new_service(nonces=FakeNonceStore()))
    refused = 0
    for i in range(len(link.token)):
        store = FakeNonceStore()
        svc = rig.new_service(nonces=store)
        mutated = _mutate(link.token, i)
        try:
            got = svc.redeem(mutated, card_id=Q1, action="answer")
        except L.LinkRefused as exc:
            assert exc.reason in SIGNATURE_FAILURES, (i, exc.reason)
            assert store.consumed == {}, i
            refused += 1
        else:
            assert (got.card_id, got.user_id, got.action, got.option, got.nonce) == (
                base.card_id,
                base.user_id,
                base.action,
                base.option,
                base.nonce,
            ), i
            assert _refusal(L, svc.redeem, link.token, card_id=Q1, action="answer") == "used", i
    assert refused >= len(link.token) - 4  # at most a couple of padding-bit positions are equivalent


def test_FR_CHN_07_token_signed_with_another_secret_is_refused_as_bad_signature():
    L = links()
    rig = make_rig()
    foreign = rig.new_service(
        nonces=FakeNonceStore(), keys=L.KeyRing(keys={"k1": fresh_key()}, active="k1")
    )  # same key id, different secret
    forged = rig.issue(Q1, ALICE, "answer", "per_kwh", service=foreign)
    assert _refusal(L, rig.redeem, forged) == "bad_signature"


def test_FR_CHN_07_token_with_an_unknown_key_id_is_refused():
    L = links()
    rig = make_rig()
    foreign = rig.new_service(nonces=FakeNonceStore(), keys=L.KeyRing(keys={"zz9": fresh_key()}, active="zz9"))
    forged = rig.issue(Q1, ALICE, "answer", "per_kwh", service=foreign)
    assert forged.key_id == "zz9"
    assert _refusal(L, rig.redeem, forged) == "unknown_key"
    assert rig.store.consumed == {}


def test_FR_CHN_07_truncated_extended_or_garbage_tokens_are_refused():
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    t = link.token
    for bad in ["", " ", "x", "a.b.c", "....", "%%%%", t[:-10], t[: len(t) // 2], t + "AAAA", t + ".", t * 2, "." + t]:
        assert _refusal(L, rig.redeem, link, token=bad) in SIGNATURE_FAILURES, bad
    assert rig.store.consumed == {}
    assert rig.redeem(link).card_id == Q1  # the genuine link is unharmed


# ---------------------------------------------------------------------------------------------------
# Binding: card, user, action, option
# ---------------------------------------------------------------------------------------------------


def test_FR_CHN_07_link_for_another_card_is_refused():
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    assert _refusal(L, rig.redeem, link, card_id=Q2) == "wrong_card"
    assert _refusal(L, rig.redeem, link, card_id=GATE) == "wrong_card"


@pytest.mark.parametrize("card_id,action,option", [(Q1, "answer", "per_kwh"), (Q1, "open", None), (GATE, "open", None)])
def test_FR_CHN_07_link_presented_by_another_signed_in_user_is_refused(card_id, action, option):
    """A forwarded link used by someone else who is signed in (PRD 16.2 forwarded email action links)."""
    L = links()
    rig = make_rig()
    link = rig.issue(card_id, ALICE, action, option)
    assert _refusal(L, rig.redeem, link, viewer=BOB) == "wrong_user"


def test_FR_CHN_07_link_for_another_action_is_refused():
    L = links()
    rig = make_rig()
    answer = rig.issue(Q1, ALICE, "answer", "per_kwh")
    assert _refusal(L, rig.redeem, answer, action="open") == "wrong_action"
    assert _refusal(L, rig.redeem, answer, action="approve") == "wrong_action"
    opener = rig.issue(Q1, ALICE, "open", None)
    assert _refusal(L, rig.redeem, opener, action="answer") == "wrong_action"
    gate_opener = rig.issue(GATE, ALICE, "open", None)
    assert _refusal(L, rig.redeem, gate_opener, action="answer") == "wrong_action"
    assert _refusal(L, rig.redeem, gate_opener, action="approve") == "wrong_action"


def test_FR_CHN_07_link_for_another_option_is_refused():
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    assert _refusal(L, rig.redeem, link, option="per_pack") == "wrong_option"
    assert rig.redeem(link, option="per_kwh").option == "per_kwh"  # repeating the bound option is fine


@pytest.mark.parametrize(
    "over",
    [{"card_id": Q2}, {"viewer": BOB}, {"action": "open"}, {"option": "per_pack"}],
    ids=["card", "user", "action", "option"],
)
def test_FR_CHN_07_binding_mismatch_leaves_the_link_usable_by_the_right_person(over):
    """D4: a mismatch refuses the request and consumes nothing; the intended user's click still works."""
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    _refusal(L, rig.redeem, link, **over)
    assert rig.store.consumed == {}
    assert rig.redeem(link, viewer=ALICE).option == "per_kwh"


# ---------------------------------------------------------------------------------------------------
# Card state: answered elsewhere, gone, or no longer answerable by email
# ---------------------------------------------------------------------------------------------------


def test_FR_CHN_07_link_for_a_card_already_answered_on_another_channel_is_refused():
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    rig.book.answered.add(Q1)  # answered on WhatsApp or the web in the meantime
    assert _refusal(L, rig.redeem, link) == "card_answered"
    assert rig.store.consumed == {}


def test_FR_CHN_07_sibling_option_link_is_refused_once_the_card_is_answered():
    """Each option of a question card has its own email link. After one is used and the API marks the
    card answered, the others die even though they are unused and unexpired."""
    L = links()
    rig = make_rig()
    a = rig.issue(Q1, ALICE, "answer", "per_kwh")
    b = rig.issue(Q1, ALICE, "answer", "per_pack")
    assert rig.redeem(a).option == "per_kwh"
    rig.book.answered.add(Q1)
    assert _refusal(L, rig.redeem, b) == "card_answered"


def test_FR_CHN_07_link_for_a_card_that_no_longer_exists_is_refused():
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    del rig.book.cards[Q1]
    assert _refusal(L, rig.redeem, link) == "unknown_card"


def test_FR_CHN_07_answer_redeem_is_refused_when_the_card_is_not_answerable_by_email_any_more():
    """Defence in depth at redeem time: the card is now a gate, or no longer lists email."""
    L = links()
    rig = make_rig()
    a = rig.issue(Q1, ALICE, "answer", "per_kwh")
    b = rig.issue(Q2, ALICE, "answer", "per_kwh")
    rig.book.cards[Q1] = {**copy.deepcopy(rig.book.cards[GATE]), "id": Q1}
    rig.book.cards[Q2]["answer_channels"] = ["web", "mobile_web", "whatsapp"]
    assert _refusal(L, rig.redeem, a) == "not_allowed"
    assert _refusal(L, rig.redeem, b) == "not_allowed"
    assert rig.store.consumed == {}


# ---------------------------------------------------------------------------------------------------
# Constant-time signature comparison (asserted through the comparison helper used)
# ---------------------------------------------------------------------------------------------------


def _spy_compare_digest(monkeypatch: pytest.MonkeyPatch, L: Any) -> list[tuple[Any, Any]]:
    calls: list[tuple[Any, Any]] = []
    real = hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    if hasattr(L, "compare_digest"):  # `from hmac import compare_digest` style
        monkeypatch.setattr(L, "compare_digest", spy)
    return calls


def test_FR_CHN_07_signature_is_compared_with_hmac_compare_digest(monkeypatch):
    L = links()
    assert "compare_digest" in inspect.getsource(L)
    calls = _spy_compare_digest(monkeypatch, L)
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    rig.redeem(link)
    assert len(calls) >= 1, "a valid redeem must verify its signature with hmac.compare_digest"
    a, b = calls[-1]
    assert type(a) is type(b) and len(a) == len(b) > 0, "compares two equal-length MACs"

    # a forged signature (right key id, wrong secret) goes through the same comparison and is refused
    before = len(calls)
    foreign = rig.new_service(nonces=FakeNonceStore(), keys=L.KeyRing(keys={"k1": fresh_key()}, active="k1"))
    forged = rig.issue(Q2, ALICE, "answer", "per_kwh", service=foreign)
    assert _refusal(L, rig.redeem, forged) == "bad_signature"
    assert len(calls) > before


def test_FR_CHN_07_every_signature_rejection_goes_through_compare_digest_with_no_early_exit(monkeypatch):
    """Whichever character of the token is changed, a rejection for a bad signature has run
    hmac.compare_digest first: there is no `==` or prefix check that exits early on the first mismatching
    byte."""
    L = links()
    calls = _spy_compare_digest(monkeypatch, L)
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    bad_signature = 0
    for i in range(len(link.token)):
        before = len(calls)
        try:
            rig.new_service(nonces=FakeNonceStore()).redeem(_mutate(link.token, i), card_id=Q1, action="answer")
        except L.LinkRefused as exc:
            if exc.reason == "bad_signature":
                bad_signature += 1
                assert len(calls) > before, f"position {i}: refused as bad_signature without compare_digest"
    assert bad_signature >= 1, "no mutation reached the signature check; the test proves nothing"


# ---------------------------------------------------------------------------------------------------
# Key rotation
# ---------------------------------------------------------------------------------------------------


def test_FR_CHN_07_key_rotation_old_key_verifies_until_retired_then_is_refused():
    L = links()
    rig = make_rig("k1")
    old_a = rig.issue(Q1, ALICE, "answer", "per_kwh")
    old_b = rig.issue(Q1, ALICE, "answer", "per_pack")
    assert old_a.key_id == old_b.key_id == "k1"

    rig.ring.add("k2", fresh_key(), activate=True)
    assert rig.ring.active_kid == "k2"
    new = rig.issue(Q2, ALICE, "answer", "per_kwh")
    assert new.key_id == "k2", "after rotation new links are signed with the new key"

    # both generations verify while k1 is merely rotated out
    assert rig.redeem(old_a).option == "per_kwh"
    assert rig.redeem(new).card_id == Q2

    rig.ring.retire("k1")
    assert _refusal(L, rig.redeem, old_b) == "unknown_key"
    assert old_b.nonce not in rig.store.consumed
    # the new key is unaffected, and new links keep working
    again = rig.issue(Q2, ALICE, "open", None)
    assert again.key_id == "k2"
    assert rig.redeem(again).card_id == Q2


def test_FR_CHN_07_the_active_key_cannot_be_retired():
    rig = make_rig("k1")
    with pytest.raises(ValueError):
        rig.ring.retire("k1")
    assert rig.redeem(rig.issue(Q1, ALICE, "answer", "per_kwh")).card_id == Q1


# ---------------------------------------------------------------------------------------------------
# No secrets in errors (root CLAUDE.md: no secrets in logs)
# ---------------------------------------------------------------------------------------------------


def test_FR_CHN_07_refusals_do_not_echo_the_token_nonce_or_key():
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    rig.redeem(link)
    leaks = [link.token, link.nonce, rig.key.hex()]
    attempts = [
        lambda: rig.redeem(link),  # used
        lambda: rig.redeem(link, viewer=BOB),
        lambda: rig.redeem(link, token=link.token[:-5]),
    ]
    for attempt in attempts:
        with pytest.raises(L.LinkRefused) as info:
            attempt()
        text = f"{info.value!s} {info.value!r}"
        assert not any(s in text for s in leaks)


# ---------------------------------------------------------------------------------------------------
# Properties and concurrency
# ---------------------------------------------------------------------------------------------------

_VARIANTS = ["ok", "wrong_card", "wrong_user", "wrong_action", "wait_59m", "wait_9h07m"]


@settings(max_examples=150, deadline=None)
@given(ops=st.lists(st.tuples(st.integers(0, 3), st.sampled_from(_VARIANTS)), max_size=40))
def test_FR_CHN_07_property_no_token_is_accepted_twice_under_any_interleaving(ops):
    """Any order of redeem attempts (right facts, wrong card, wrong user, wrong action) over four tokens
    on a moving clock: each token is accepted at most once, never after 24 h, and only by a request with
    the right facts. (Whether a wrong-facts attempt also burns the nonce is pinned elsewhere, D4.)"""
    L = links()
    rig = make_rig()
    tokens = [
        rig.issue(Q1, ALICE, "answer", "per_kwh"),
        rig.issue(Q1, ALICE, "answer", "per_pack"),
        rig.issue(Q2, ALICE, "answer", "per_kwh"),
        rig.issue(GATE, ALICE, "open", None),
    ]
    accepted = [0] * len(tokens)
    for idx, variant in ops:
        lk = tokens[idx]
        if variant == "wait_59m":
            rig.clock.advance(minutes=59)
            continue
        if variant == "wait_9h07m":
            rig.clock.advance(hours=9, minutes=7)
            continue
        over: dict[str, Any] = {}
        if variant == "wrong_card":
            over["card_id"] = Q2 if lk.card_id == Q1 else Q1
        elif variant == "wrong_user":
            over["viewer"] = BOB
        elif variant == "wrong_action":
            over["action"] = "open" if lk.action == "answer" else "answer"
        try:
            rig.redeem(lk, **over)
        except L.LinkRefused:
            continue
        assert variant == "ok", f"{variant} request was accepted"
        assert rig.clock() < lk.expires_at, "accepted after expiry"
        accepted[idx] += 1
        assert accepted[idx] == 1, "token accepted twice"
    assert all(n <= 1 for n in accepted)
    assert len(rig.store.consumed) == sum(accepted)


@pytest.mark.parametrize("two_instances", [False, True], ids=["one_instance", "two_instances_one_store"])
def test_FR_CHN_07_concurrent_redeems_of_one_link_succeed_exactly_once(two_instances):
    """32 simultaneous clicks on one link (a mail client prefetch plus the person, a forwarded copy):
    exactly one is accepted, all others are refused as used."""
    L = links()
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # make thread switches frequent so a check-then-set race would show
    try:
        for _ in range(25):
            rig = make_rig()
            services = [rig.service, rig.new_service()] if two_instances else [rig.service]
            link = rig.issue(Q1, ALICE, "answer", "per_kwh")
            n = 32
            barrier = threading.Barrier(n)

            def click(i: int, link: Any = link, barrier: threading.Barrier = barrier, services: Any = services) -> str:
                barrier.wait()
                try:
                    services[i % len(services)].redeem(link.token, card_id=Q1, action="answer")
                except L.LinkRefused as exc:
                    return exc.reason
                return "accepted"

            with ThreadPoolExecutor(max_workers=n) as pool:
                results = list(pool.map(click, range(n)))
            assert results.count("accepted") == 1, results
            assert all(r == "used" for r in results if r != "accepted"), results
            assert len(rig.store.consumed) == 1
    finally:
        sys.setswitchinterval(old_interval)


_OPTIONS = ["approve", "edit", "hold", "connect", "per_kwh", "per_pack", "research", "even", None]


@settings(max_examples=250, deadline=None)
@given(
    card_id=st.sampled_from([Q1, Q2, GATE, GATE_REV, CONSENT, MEETING]),
    lists_email=st.booleans(),
    action=st.sampled_from(["open", "answer", "approve", "delete"]),
    option=st.sampled_from(_OPTIONS),
    viewer=st.sampled_from([None, ALICE, BOB]),
)
def test_FR_CHN_07_property_a_link_alone_never_answers_or_approves_a_gate(card_id, lists_email, action, option, viewer):
    """Whatever is issued and however it is presented: a gate or consent card is never answered, and
    never opened without sign-in; no redemption of a non-question card carries an option (so no T3 or gate
    approve rides on a link); a viewer other than the bound user is always refused."""
    L = links()
    rig = make_rig()
    card = rig.book.cards[card_id]
    if lists_email and card["kind"] in ("gate", "consent"):
        card["answer_channels"] = [*card["answer_channels"], "email"]  # a malformed card
    if action != "answer":
        option = None
    try:
        link = rig.issue(card_id, ALICE, action, option)
    except L.LinkRefused:
        return
    try:
        r = rig.redeem(link, viewer=viewer)
    except L.LinkRefused:
        return
    assert viewer in (None, ALICE), "a different signed-in user was accepted"
    assert r.user_id == ALICE
    assert r.action in ("open", "answer")
    if card["kind"] in ("gate", "consent", "meeting"):
        assert r.action == "open" and r.option is None, "answer or approval carried by a link"
        assert r.requires_sign_in is (viewer is None), "gate opened without sign-in"
    else:
        assert "email" in card["answer_channels"] or r.action == "open"
