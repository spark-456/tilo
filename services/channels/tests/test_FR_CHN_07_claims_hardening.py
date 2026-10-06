"""FR-CHN-07 claims hardening (issue #144, library items): a MAC-valid token is still refused unless its
claims obey the issue rules, the body is bounded, crafted option lists and blank ids never crash.

A separate file: the pinned tests in the other FR-CHN-07 files stay as written."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from _chn_links_lib import ALICE, GATE, Q1, links, make_rig


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _sign_body(rig, raw: bytes) -> str:
    """A validly signed token over an arbitrary raw body (what a key holder, or an issuer bug, could emit)."""
    signed = f"{rig.kid}.{_b64e(raw)}"
    mac = hmac.new(rig.key, b"tilo-link-v1|" + signed.encode(), hashlib.sha256).digest()
    return f"{signed}.{_b64e(mac)}"


def _claims(rig, action="answer", option="per_kwh", card=Q1):
    link = rig.issue(card, ALICE, action, option)
    return json.loads(base64.urlsafe_b64decode(link.token.split(".")[1] + "=="))


def _signed(rig, claims) -> str:
    return _sign_body(rig, json.dumps(claims, separators=(",", ":")).encode())


def _refused(rig, token, card=Q1, action="answer") -> str:
    L = links()
    with pytest.raises(L.LinkRefused) as info:
        rig.service.redeem(token, card_id=card, action=action)
    assert rig.store.consumed == {} and rig.store.calls == []
    return info.value.reason


@pytest.mark.parametrize("a", ["approve", "OPEN", "", "answer ", "send"])
def test_FR_CHN_07_a_signed_claim_with_an_unknown_action_is_malformed(a):
    rig = make_rig()
    claims = _claims(rig)
    claims["a"] = a
    assert _refused(rig, _signed(rig, claims), action=a) == "malformed"


def test_FR_CHN_07_a_signed_claim_without_an_option_key_is_malformed_not_a_keyerror():
    rig = make_rig()
    claims = _claims(rig, "open", None, GATE)
    del claims["o"]
    assert _refused(rig, _signed(rig, claims), card=GATE, action="open") == "malformed"


def test_FR_CHN_07_an_answer_claim_without_an_option_is_malformed():
    rig = make_rig()
    claims = _claims(rig)
    claims["o"] = None
    assert _refused(rig, _signed(rig, claims)) == "malformed"


def test_FR_CHN_07_an_open_claim_carrying_an_option_is_malformed():
    rig = make_rig()
    claims = _claims(rig, "open", None, GATE)
    claims["o"] = "approve"
    assert _refused(rig, _signed(rig, claims), card=GATE, action="open") == "malformed"


def test_FR_CHN_07_well_formed_claims_for_both_actions_still_redeem():
    rig = make_rig()
    answer = rig.service.redeem(_signed(rig, _claims(rig)), card_id=Q1, action="answer")
    assert (answer.action, answer.option) == ("answer", "per_kwh")
    opened = rig.service.redeem(_signed(rig, _claims(rig, "open", None, GATE)), card_id=GATE, action="open")
    assert (opened.action, opened.option) == ("open", None)


def test_FR_CHN_07_an_oversized_signed_body_is_refused_before_parsing(monkeypatch):
    rig = make_rig()
    claims = _claims(rig)
    claims["pad"] = "x" * 2000
    calls = []
    real = links().json.loads
    monkeypatch.setattr(links().json, "loads", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert _refused(rig, _signed(rig, claims)) == "malformed"
    assert calls == []


def test_FR_CHN_07_a_deeply_nested_signed_body_is_refused_cleanly():
    rig = make_rig()
    deep = b"[" * 100_000 + b"]" * 100_000
    assert _refused(rig, _sign_body(rig, deep)) == "malformed"


def test_FR_CHN_07_a_recursion_error_in_json_parsing_is_malformed(monkeypatch):
    rig = make_rig()
    token = _signed(rig, _claims(rig))

    def boom(*args, **kwargs):
        raise RecursionError

    monkeypatch.setattr(links().json, "loads", boom)
    assert _refused(rig, token) == "malformed"


def test_FR_CHN_07_the_mac_is_still_checked_before_any_claim_parsing(monkeypatch):
    """A forged body (bad MAC) is bad_signature, and json is never touched."""
    rig = make_rig()
    kid, body, sig = rig.issue(Q1, ALICE, "answer", "per_kwh").token.split(".")
    calls = []
    monkeypatch.setattr(links().json, "loads", lambda *a, **k: calls.append(1))
    assert _refused(rig, f"{kid}.{_b64e(b'[' * 100_000)}.{sig}") == "bad_signature"
    assert calls == []


@pytest.mark.parametrize("options", [5, "per_kwh", {"id": "per_kwh"}, True, [{"id": 5}], [{"id": "per_kwh"}, 7]])
def test_FR_CHN_07_a_card_whose_options_are_not_a_list_of_str_ids_is_refused_not_a_typeerror(options):
    L = links()
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")
    rig.book.cards[Q1]["options"] = options
    with pytest.raises(L.LinkRefused) as info:
        rig.issue(Q1, ALICE, "answer", "per_kwh")
    assert info.value.reason == "unknown_option"
    with pytest.raises(L.LinkRefused) as info:
        rig.redeem(link)
    assert info.value.reason == "unknown_option"
    assert rig.store.consumed == {}


@pytest.mark.parametrize("bad", [5, None, 1.5, b"u", ["u"], "", " ", "\t\n"])
def test_FR_CHN_07_issue_requires_non_blank_str_user_and_card_ids(bad):
    rig = make_rig()
    with pytest.raises(ValueError):
        rig.service.issue(card_id=Q1, user_id=bad, action="open")
    with pytest.raises(ValueError):
        rig.service.issue(card_id=bad, user_id=ALICE, action="open")
