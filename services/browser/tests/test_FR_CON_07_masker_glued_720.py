"""FR-CON-07 / SEC-14, issue #720 (found by the Opus review of PR #718): the masker's holes.

1. A secret glued directly after a letter, digit or underscore (innerText joins a label and a following
   `<code>sk-...</code>` with no space) was returned unchanged, because every shape was anchored on a word boundary.
2. The egress check decides `sensitive_query` with `mask_text(q) != q`, so it let such a query through.
3. Masking was not idempotent for a userinfo that holds a secret ("https://Authorization: Bearer <key>@host").
4. `Authorization:` or `password:` followed by more than 8 whitespace characters left the value unmasked.

Every secret here is a runtime-assembled fake (tests/_browser_lib.fake_secrets); none is a real credential.
"""

from __future__ import annotations

import time

import pytest
from _browser_lib import fake_secrets
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_browser.egress import EgressPolicy
from tilo_browser.masking import mask_text

S = fake_secrets()
SHAPES = ["api_key", "github_token", "aws_key_id", "jwt", "google_oauth"]
WORD = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_é"


@given(
    glue=st.text(alphabet=WORD, min_size=1, max_size=8),
    shape=st.sampled_from(SHAPES),
    tail=st.sampled_from(["", " ok", "."]),
)
@settings(max_examples=120, deadline=None)
def test_FR_CON_07_720_a_secret_glued_after_a_word_character_never_survives(glue, shape, tail):
    secret = S[shape]
    out = mask_text(f"{glue}{secret}{tail}")
    assert secret not in out
    assert "[masked:secret]" in out
    assert mask_text(out) == out


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("glue", ["bearer", "Bearer", "x", "_", "1", "é", "key", "token", "Secret key"])
def test_FR_CON_07_720_named_glue_cases(glue, shape):
    out = mask_text(f"{glue}{S[shape]}")
    assert S[shape] not in out


def test_FR_CON_07_720_an_aws_key_id_followed_by_a_word_character_is_masked():
    assert S["aws_key_id"] not in mask_text(S["aws_key_id"] + "x")
    assert S["aws_key_id"] not in mask_text("x" + S["aws_key_id"])


def test_FR_CON_07_720_a_bearer_scheme_glued_to_a_word_is_masked():
    assert "abc12345xyz" not in mask_text("theBearer abc12345xyz")
    assert S["api_key"] not in mask_text("bearer" + S["api_key"])


@pytest.mark.parametrize(
    "text",
    [
        "risk-assessment-quarterly-review-notes",
        "task-force-planning-group-members-list",
        "the asking price was high",
        "ASIAPACIFICREGION",
        "ghost story about ghp",
        "a bearer of bad news",
        "eyes on the prize. yes.",
    ],
)
def test_FR_CON_07_720_prose_with_the_same_letters_is_left_alone(text):
    assert mask_text(text) == text


@pytest.mark.parametrize("gap", [9, 12, 64, 300])
def test_FR_CON_07_720_a_long_gap_before_the_value_does_not_hide_it(gap):
    pad = " " * gap
    assert "hunter2xyz" not in mask_text(f"password:{pad}hunter2xyz")
    assert "dXNlcjpwYXNzd29yZA" not in mask_text(f"Authorization:{pad}\nBasic dXNlcjpwYXNzd29yZA")
    assert "sid=abc123def" not in mask_text(f"Cookie:{pad}sid=abc123def")
    assert "sid=abc123def" not in mask_text(f"Set-Cookie:{pad}\nsid=abc123def")


def test_FR_CON_07_720_masking_a_userinfo_that_holds_a_secret_is_idempotent():
    text = f"see https://Authorization: Bearer {S['api_key']}@example.com"
    once = mask_text(text)
    assert S["api_key"] not in once
    assert mask_text(once) == once


PIECES = [
    *("https://", "http://", "@", ":", " ", "\n", "Authorization: ", "Cookie: "),
    *("Bearer ", "bearer ", "password=", "token: ", "example.com", "user", "/path?q="),
    *(S["api_key"], S["github_token"], S["jwt"], S["aws_key_id"], "x", "9", "_"),
]


@given(st.lists(st.sampled_from(PIECES), min_size=1, max_size=14))
@settings(max_examples=300, deadline=None)
def test_FR_CON_07_720_masking_is_idempotent_and_never_leaks_over_urls_headers_and_glue(parts):
    text = "".join(parts)
    out = mask_text(text)
    for shape in SHAPES:
        assert S[shape] not in out
    assert mask_text(out) == out


@pytest.mark.parametrize("prefix", ["x", "a+", "bearer+", "q1_"])
@pytest.mark.parametrize("shape", ["api_key", "github_token", "jwt"])
def test_FR_CON_07_720_a_secret_glued_in_a_query_is_blocked_by_the_egress_policy(prefix, shape):
    policy = EgressPolicy(["example.com"])
    decision = policy.check(f"https://example.com/search?q={prefix}{S[shape]}")
    assert decision.allowed is False
    assert decision.reason == "sensitive_query"
    assert S[shape] not in repr(policy.decisions)


HOSTILE = {
    "eyJ run": lambda: "eyJ" * 70_000,
    "glued sk run": lambda: "xsk-1" * 50_000,
    "sk- run": lambda: "sk-" * 80_000,
    "AKIA run": lambda: "AKIA" * 60_000,
    "long gap": lambda: "password:" + " " * 200_000,
    "userinfo run": lambda: "https://" + "a: " * 60_000,
}


@pytest.mark.parametrize("name", list(HOSTILE))
def test_FR_CON_07_720_hostile_input_stays_linear(name):
    text = HOSTILE[name]()
    start = time.perf_counter()
    mask_text(text)
    assert time.perf_counter() - start < 3.0, name
