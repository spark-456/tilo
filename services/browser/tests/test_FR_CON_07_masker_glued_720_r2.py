"""FR-CON-07 / SEC-14, issue #720, round 2 (Opus review of PR #721): what the first fix left or broke.

- a glued `Authorization:`, `Cookie:` or `Set-Cookie:` header was still missed (its keyword needed a word boundary);
- the glued forms must not start inside a secret the left-anchored shapes mask whole and leave its body behind;
- the glued forms stay narrow enough not to eat ordinary words;
- the checks look at 12-character slices of each secret, so a leaked body cannot hide behind a masked prefix.

Every secret is a runtime-assembled fake (tests/_browser_lib.fake_secrets).
"""

from __future__ import annotations

import pytest
from _browser_lib import fake_secrets
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_browser.egress import EgressPolicy
from tilo_browser.masking import mask_text

S = fake_secrets()
SHAPES = ["api_key", "github_token", "aws_key_id", "jwt", "google_oauth"]
GLUE = ["a", "Z", "9", "_", "é", "Request headers", "keyJar.", "surveyJS."]
B64 = "dXNlcjpwYXNzd29yZA"


def leaked(out: str, secret: str, width: int = 12) -> bool:
    """True when any `width`-character slice of `secret` is still in `out`."""
    return any(secret[i : i + width] in out for i in range(len(secret) - width + 1))


@pytest.mark.parametrize("glue", GLUE)
@pytest.mark.parametrize("header", ["Authorization", "authorization", "Cookie", "Set-Cookie"])
def test_FR_CON_07_720_r2_a_header_glued_to_a_word_is_masked(glue, header):
    out = mask_text(f"{glue}{header}: Basic {B64}")
    assert B64 not in out
    assert mask_text(out) == out
    out = mask_text(f"{glue}{header}: sid=abc123def456")
    assert "abc123def456" not in out


@pytest.mark.parametrize("prefix", ["x", "9", "_", "é"])
def test_FR_CON_07_720_r2_a_glued_header_in_a_query_is_blocked_by_the_egress_policy(prefix):
    policy = EgressPolicy(["example.com"])
    decision = policy.check(f"https://example.com/search?q={prefix}Authorization:+Basic+{B64}")
    assert decision.allowed is False
    assert decision.reason == "sensitive_query"


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("glue", GLUE)
def test_FR_CON_07_720_r2_no_slice_of_a_glued_secret_survives(glue, shape):
    out = mask_text(f"{glue}{S[shape]}")
    assert not leaked(out, S[shape])
    assert mask_text(out) == out


def test_FR_CON_07_720_r2_a_glued_form_never_swallows_the_prefix_of_a_secret_the_first_pass_masks():
    cases = [
        ("surveyJS.config." + S["google_oauth"], S["google_oauth"]),
        ("keyJar.box." + S["jwt"], S["jwt"]),
        ("xsk-1abcdefghijklmnopqrstuvw-" + S["google_oauth"], S["google_oauth"]),
        ("monkeyJar." + S["jwt"], S["jwt"]),
    ]
    for text, secret in cases:
        out = mask_text(text)
        assert not leaked(out, secret), text
        assert mask_text(out) == out, text


@given(
    glue=st.text(alphabet="abcxyzXYZ019_é.-", min_size=0, max_size=10),
    first=st.sampled_from(SHAPES),
    second=st.sampled_from(SHAPES),
)
@settings(max_examples=200, deadline=None)
def test_FR_CON_07_720_r2_two_secrets_in_a_row_leave_no_slice_of_either(glue, first, second):
    out = mask_text(f"{glue}{S[first]} {S[second]}")
    assert not leaked(out, S[first])
    assert not leaked(out, S[second])
    assert mask_text(out) == out


@pytest.mark.parametrize(
    "text",
    [
        "surveyJSON.pages.length",
        "monkeyJar.open.now",
        "heyJude.Hey.Jude",
        "The pallbearer shouldered.",
        "isBearer abcdefghij",
        "risk-assessment-quarterly-review-notes",
    ],
)
def test_FR_CON_07_720_r2_ordinary_words_are_left_alone(text):
    assert mask_text(text) == text


@pytest.mark.parametrize("text", ["xbearer abc12345", "theBearer abc12345xyz", "isBearer abc12345"])
def test_FR_CON_07_720_r2_a_glued_bearer_with_a_digit_in_its_token_is_masked(text):
    assert "abc12345" not in mask_text(text)


def test_FR_CON_07_720_r2_the_look_aheads_reach_as_far_as_documented():
    body = "A" * 40 + "7" + "B" * 20  # the first digit is the 41st character: inside the 63-character reach
    assert "7" not in mask_text("key" + "sk-" + body).replace("[masked:secret]", "")
    aws = "A" * 15 + "7"  # the digit is the last of the 16 characters
    assert aws not in mask_text("x" + "AK" + "IA" + aws)
