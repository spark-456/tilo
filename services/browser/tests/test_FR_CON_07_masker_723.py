"""FR-CON-07 / SEC-14: masker follow-ups from issue #723 (items 1 and 2).

Fake secrets only, assembled at runtime. A leak check compares a 12-character slice of the secret, so a
partly masked value still fails.
"""

from __future__ import annotations

import time

import pytest
from _browser_lib import PHONE, fake_card_numbers, fake_secrets

SECRETS = fake_secrets()
CARDS = fake_card_numbers()


def mask(text: str) -> str:
    from tilo_browser.masking import mask_text

    return mask_text(text)


@pytest.mark.parametrize("label", ["Card number", "Card:", "card_", "PAN"])
@pytest.mark.parametrize("form", ["plain", "spaced", "dashed"])
def test_FR_CON_07_723_a_card_glued_after_a_letter_is_masked(label, form):
    card = CARDS[form]
    out = mask(f"{label}{card} exp 12/30")
    assert card.replace(" ", "").replace("-", "")[:12] not in out.replace(" ", "").replace("-", "")
    assert "[masked:card]" in out


def test_FR_CON_07_723_a_phone_glued_after_a_letter_is_masked():
    out = mask(f"Phone{PHONE}")
    assert "9123" not in out
    assert "[masked:phone]" in out


def test_FR_CON_07_723_a_plus_or_digit_before_a_number_still_blocks_a_phone():
    assert mask("C++5 123 456 78") == "C++5 123 456 78"
    assert mask("12+65 9123 4567") == "12+65 9123 4567"


def test_FR_CON_07_723_a_digit_run_that_fails_luhn_after_a_letter_is_kept():
    bad = CARDS["invalid"]
    assert mask(f"Order{bad}") == f"Order{bad}"


def test_FR_CON_07_723_a_cookie_header_keeps_no_value_after_a_masked_first_value():
    jwt = SECRETS["jwt"]
    refresh = "r" + SECRETS["bearer"]
    out = mask(f"Cookie: {jwt}; refresh={refresh}")
    assert refresh[:12] not in out
    assert jwt[:12] not in out
    assert out.startswith("Cookie: ")


def test_FR_CON_07_723_set_cookie_with_a_masked_first_value_masks_the_rest_of_the_line():
    jwt = SECRETS["jwt"]
    tail = SECRETS["bearer"]
    out = mask(f"Set-Cookie: sid={jwt}; other={tail}; Path=/")
    assert tail[:12] not in out


def test_FR_CON_07_723_a_header_whose_value_is_only_placeholders_is_left_alone():
    for text in (
        "Cookie: [masked:secret]",
        "Cookie: [masked:secret]; [masked:secret]",
        "Authorization: Bearer [masked:secret]",
    ):
        assert mask(text) == text


def test_FR_CON_07_723_the_cookie_fix_is_idempotent():
    jwt = SECRETS["jwt"]
    once = mask(f"Cookie: {jwt}; refresh={SECRETS['bearer']}")
    assert mask(once) == once


def test_FR_CON_07_723_hostile_placeholder_runs_stay_linear():
    text = "Cookie: " + "[masked:secret];" * 20000 + "x"
    start = time.perf_counter()
    mask(text)
    assert time.perf_counter() - start < 0.6


def test_FR_CON_07_723_an_email_with_a_card_like_local_part_is_still_one_email():
    card = CARDS["plain"]
    assert mask(f"riya{card}@example.org") == "[masked:email]"
    assert mask(f"ops_team{card}@mail.example.com") == "[masked:email]"


def test_FR_CON_07_723_an_authorization_value_keeps_nothing_glued_after_its_token():
    app = SECRETS["bearer"]
    for text in (
        f"Authorization: Bearer {SECRETS['github_token']}|{app}",
        f"Authorization: AKIA{app[:16].upper()}:{app}",
    ):
        assert app[:12] not in mask(text)
