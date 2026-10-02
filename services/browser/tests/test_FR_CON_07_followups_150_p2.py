"""FR-CON-07 masking gaps, #150 part 2 (security re-check on PR #168; PRD 16.1 rule 4).

The cap cut after a large collapse, the Authorization scheme word, case-folded gating, growth of
text at or under the cap, and a few more secret shapes (Cookie, upper-case SK-/BEARER, a bare
bearer token, long or spaced userinfo). Fake secrets are assembled at runtime.
"""

from __future__ import annotations

import time

import pytest
from _browser_lib import fake_card_numbers

PW = "Q7v" + "Rk2" + "mZ9!x"
TOK = "AbCdEf" + "1234567890" + "wxyz"
CARD = fake_card_numbers()["plain"]
SHAPES = {
    "card": CARD,
    "card_spaced": fake_card_numbers()["spaced"],
    "email": "riya.sharma" + "@" + "example.org",
    "userinfo": f"https://u:{PW}@intranet.example.org/x",
}


# -- 1. the cut after a large collapse ------------------------------------------------------------


@pytest.mark.parametrize("name", list(SHAPES))
def test_FR_CON_07_a_secret_at_the_window_end_after_a_large_collapse_keeps_no_prefix(name, monkeypatch):
    from tilo_browser import masking

    monkeypatch.setattr(masking, "MAX_TEXT_CHARS", 20_000)
    window = 20_000 + masking._CUT_WINDOW
    secret = SHAPES[name]
    needle = PW[:5] if name == "userinfo" else secret[:8]
    head = 'token="' + "x" * 12_000 + '" '  # masking shrinks the window by 12 KB before the secret
    for k in range(1, len(secret)):
        filler = ("a " * window)[: window - k - len(head) - 1] + " "
        out = masking.mask_text(head + filler + secret + " tail " + "b " * 3000)
        assert needle not in out, (name, k)
        assert len(out) <= 20_000 + len(masking.TRUNCATED_MARKER)
        assert masking.mask_text(out) == out, (name, k)


# -- 2. Authorization: an unknown first word is the credential ------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        f"Authorization: {TOK} \nHost: x",
        f"authorization={TOK} &x=1",
        f"Authorization: {TOK}",
        f"Authorization:{TOK}\r\n",
    ],
)
def test_FR_CON_07_an_authorization_value_with_no_scheme_word_is_masked_whole(text):
    from tilo_browser.masking import mask_text

    out = mask_text(text)
    assert TOK not in out and "[masked:secret]" in out, out
    assert mask_text(out) == out
    assert "Host: x" in out or "Host" not in text


def test_FR_CON_07_a_known_scheme_word_stays_and_the_value_after_it_goes():
    from tilo_browser.masking import mask_text

    assert mask_text(f"Authorization: Bearer2 {TOK}") == "Authorization: [masked:secret]"
    assert mask_text(f"Authorization: Digest {TOK}") == "Authorization: Digest [masked:secret]"
    assert mask_text("Authorization: Basic [masked:secret]") == "Authorization: Basic [masked:secret]"


# -- 3. gating folds case and runs everything on non-ASCII text ------------------------------------


@pytest.mark.parametrize(
    "text",
    [f"paſſword={PW}", f"authorizatıon: Basic {TOK}", f"toKen={PW} café", f"secret: {PW} é"],
)
def test_FR_CON_07_case_folding_and_non_ascii_text_do_not_skip_a_pass(text):
    from tilo_browser.masking import mask_text

    out = mask_text(text)
    assert PW not in out and TOK not in out, out


# -- 4. text at or under the cap that grows when masked ---------------------------------------------


def test_FR_CON_07_text_under_the_cap_that_grows_when_masked_stays_bounded_and_idempotent():
    from tilo_browser.masking import MAX_TEXT_CHARS, TRUNCATED_MARKER, mask_text

    text = "a@b.co " * (MAX_TEXT_CHARS // 7)
    assert len(text) <= MAX_TEXT_CHARS
    start = time.process_time()
    out = mask_text(text)
    assert time.process_time() - start < 2.0
    assert len(out) <= MAX_TEXT_CHARS + len(TRUNCATED_MARKER) and out.endswith(TRUNCATED_MARKER)
    assert mask_text(out) == out


def test_FR_CON_07_raw_text_ending_in_the_marker_is_bounded_too_and_a_short_one_is_kept():
    from tilo_browser.masking import MAX_TEXT_CHARS, TRUNCATED_MARKER, mask_text

    text = "a@b.co " * 29_000 + TRUNCATED_MARKER
    out = mask_text(text)
    assert len(out) <= MAX_TEXT_CHARS + len(TRUNCATED_MARKER) and mask_text(out) == out
    assert mask_text("hello world" + TRUNCATED_MARKER) == "hello world" + TRUNCATED_MARKER


# -- 5. more shapes ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        f"Cookie: sessionid={PW}; theme=dark",
        f"Set-Cookie: sid={PW}; Path=/; HttpOnly",
        f"cookie={PW}",
        "S" + "K-" + "A1b2C3d4" * 4,
        f"BEARER {TOK}",
        f"bearer {TOK}",
        f"https://user:{PW}{'y' * 5000}@evil.net/",
        f"https://user:{PW} z@evil.net/",
        f"abcdefghijklmnopq://u:{PW}@h/",
    ],
)
def test_FR_CON_07_more_secret_shapes_are_masked(text):
    from tilo_browser.masking import mask_text

    out = mask_text(text)
    assert PW not in out and TOK not in out and "A1b2C3d4" not in out, out
    assert mask_text(out) == out


@pytest.mark.parametrize(
    "text",
    ["the bearer of this letter", "bearer instruments are fine", "visit http://example.com is up, mail bob@x.com"],
)
def test_FR_CON_07_prose_with_those_words_is_not_over_masked(text):
    from tilo_browser.masking import mask_text

    assert "[masked:secret]" not in mask_text(text)
