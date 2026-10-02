"""FR-CHN-07 hardening (PR #138 review round 1): every input ends in LinkRefused, crafted cards fail
closed, nothing secret in a repr, naive clocks refused, bounded expiry, domain-separated MAC.

A separate file: the pinned tests in test_FR_CHN_07_signed_links.py stay as written."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest
from _chn_links_lib import ALICE, GATE, Q1, links, make_rig

BAD_TEXT = ["é", "­", "\ud800", "A­B", "٣"]  # e-acute, soft hyphen, lone surrogate


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _redeem(rig, token):
    return rig.service.redeem(token, card_id=Q1, action="answer")


@pytest.mark.parametrize("segment", [0, 1, 2], ids=["kid", "claims", "signature"])
@pytest.mark.parametrize("bad", BAD_TEXT)
@pytest.mark.parametrize("mode", ["replace", "insert"])
def test_FR_CHN_07_non_ascii_in_any_segment_is_a_refusal_with_nothing_consumed(segment, bad, mode):
    L = links()
    rig = make_rig()
    parts = rig.issue(Q1, ALICE, "answer", "per_kwh").token.split(".")
    parts[segment] = bad if mode == "replace" else parts[segment][:3] + bad + parts[segment][3:]
    with pytest.raises(L.LinkRefused) as info:
        _redeem(rig, ".".join(parts))
    assert info.value.reason in {"malformed", "bad_signature", "unknown_key"}
    assert rig.store.consumed == {} and rig.store.calls == []


@pytest.mark.parametrize("token", [None, 5, b"k1.a.b", ["k1", "a", "b"]])
def test_FR_CHN_07_non_string_token_is_malformed(token):
    L = links()
    with pytest.raises(L.LinkRefused) as info:
        _redeem(make_rig(), token)
    assert info.value.reason == "malformed"


def _crafted(rig, **changes):
    card = {**rig.book.cards[Q1], **changes}
    rig.book.cards[Q1] = card
    return card


@pytest.mark.parametrize(
    "changes",
    [
        {"gate": {"tier": "T3"}},
        {"consent": {"scope": "x"}},
        {"rung": "gate"},
        {"rung": "consent"},
        {"rung": None},
        {"answer_channels": "web,email"},
        {"answer_channels": ("email",)},
        {"kind": "Needs_you"},
    ],
    ids=["gate_obj", "consent_obj", "rung_gate", "rung_consent", "no_rung", "str_channels", "tuple_channels", "kind"],
)
def test_FR_CHN_07_crafted_cards_never_get_or_keep_an_answer_link(changes):
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    _crafted(rig, **changes)
    with pytest.raises(L.LinkRefused) as info:
        rig.issue(Q1, ALICE, "answer", "per_kwh")
    assert info.value.reason == "not_allowed"
    with pytest.raises(L.LinkRefused) as info:
        rig.redeem(link)
    assert info.value.reason == "not_allowed"


@pytest.mark.parametrize("kind", [None, "Gate", "GATE", "approval", "needs_you "])
def test_FR_CHN_07_open_needs_sign_in_unless_the_card_is_a_plain_question(kind):
    rig = make_rig()
    link = rig.issue(GATE, ALICE, "open", None)
    rig.book.cards[GATE]["kind"] = kind
    assert rig.redeem(link).requires_sign_in is True


def test_FR_CHN_07_an_option_without_an_id_never_matches():
    L = links()
    rig = make_rig()
    rig.book.cards[Q1]["options"] = [{"label": "no id"}, {"id": None}]
    for option in ("None", "", None):
        with pytest.raises(L.LinkRefused) as info:
            rig.issue(Q1, ALICE, "answer", option)
        assert info.value.reason == "unknown_option"


def test_FR_CHN_07_reprs_never_show_the_token_url_or_nonce():
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    done = rig.redeem(link)
    text = f"{link!r} {done!r}"
    assert not any(secret in text for secret in (link.token, link.url, link.nonce))


def test_FR_CHN_07_a_naive_clock_is_refused_at_issue_and_redeem():
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    rig.clock.t = rig.clock.t.replace(tzinfo=None)
    with pytest.raises(L.LinkRefused) as info:
        rig.issue(Q1, ALICE, "answer", "per_kwh")
    assert info.value.reason == "bad_clock"
    with pytest.raises(L.LinkRefused) as info:
        rig.redeem(link)
    assert info.value.reason == "bad_clock"
    assert rig.store.consumed == {}


def _signed(rig, claims):
    """A validly signed token over arbitrary claims (what a key holder, or a bug, could produce)."""
    body = _b64e(json.dumps(claims, separators=(",", ":")).encode())
    signed = f"{rig.kid}.{body}"
    mac = hmac.new(rig.key, b"tilo-link-v1|" + signed.encode(), hashlib.sha256).digest()
    return f"{signed}.{_b64e(mac)}"


def _claims(rig, **over):
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    claims = json.loads(base64.urlsafe_b64decode(link.token.split(".")[1] + "=="))
    claims.update(over)
    return claims


def test_FR_CHN_07_the_mac_input_is_domain_separated():
    """A token MACed without the `tilo-link-v1|` prefix does not verify; with it, it does."""
    L = links()
    rig = make_rig()
    claims = _claims(rig, e=int(datetime(2026, 10, 3, 9, tzinfo=UTC).timestamp()))
    assert _redeem(rig, _signed(rig, claims)).card_id == Q1
    body = _b64e(json.dumps(claims, separators=(",", ":")).encode())
    plain = f"{rig.kid}.{body}"
    unprefixed = f"{plain}.{_b64e(hmac.new(rig.key, plain.encode(), hashlib.sha256).digest())}"
    with pytest.raises(L.LinkRefused) as info:
        _redeem(rig, unprefixed)
    assert info.value.reason == "bad_signature"


@pytest.mark.parametrize("e", [-1, 0, 2**32, 2**63, 10**30, 1.5, "9", None, True])
def test_FR_CHN_07_an_absurd_expiry_claim_is_malformed_not_a_crash(e):
    L = links()
    rig = make_rig()
    with pytest.raises(L.LinkRefused) as info:
        _redeem(rig, _signed(rig, _claims(rig, e=e)))
    assert info.value.reason == "malformed"
    assert rig.store.consumed == {}


@pytest.mark.parametrize("card_id,user_id", [("", ALICE), (Q1, "")])
def test_FR_CHN_07_issue_refuses_an_empty_card_or_user_id(card_id, user_id):
    L = links()
    rig = make_rig()
    with pytest.raises(L.LinkRefused):
        rig.service.issue(card_id=card_id, user_id=user_id, action="open")
