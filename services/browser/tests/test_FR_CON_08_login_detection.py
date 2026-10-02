"""FR-CON-08 detection (PRD 12.3 "A site that needs a login raises a needs-you card", 16.1 rule 1):
`tilo_browser.login.detect_login(chain=, tree=, text=)` is a pure function that decides whether
what the browser landed on is a login wall. It returns a `LoginSignal` (`kind`, `refs`) or None.

kind is one of: "password_field", "otp_field", "sso_redirect", "credentials_in_text".

Heuristics pinned by these tests (the builder may be broader, never narrower, and must keep the
negative controls negative):
- password: any node with attrs.type == "password", or autocomplete current-password/new-password,
  anywhere in the tree at any depth;
- OTP: autocomplete "one-time-code", a name/label/id of otp/totp/mfa/2fa, or a label like
  "verification|security|authentication|authenticator|6-digit ... code";
- SSO: any URL in the redirect chain whose path has a segment equal to login, log-in, signin,
  sign-in, sign_in, sso, saml, oauth, oauth2, authorize or authenticate, or whose query carries
  SAMLRequest, or client_id together with redirect_uri;
- credentials in plain text: a text box whose label/placeholder/name asks for a password or
  passphrase even though it is type=text, or page text that tells the reader to enter, type,
  paste, send, share or reply with a password, passcode or credentials.

Tree shape and `chain` semantics: see API.md.
"""

from __future__ import annotations

import pytest
from _browser_lib import button, doc, link, node, password_box, textbox
from hypothesis import given, settings
from hypothesis import strategies as st

HOME = "https://portal.example.com/app"


def detect(tree=None, *, chain=(HOME,), text=""):
    from tilo_browser.login import detect_login

    return detect_login(chain=list(chain), tree=tree if tree is not None else doc(), text=text)


# -- password fields ---------------------------------------------------------


def test_FR_CON_08_a_password_input_is_a_login_page():
    sig = detect(doc(textbox("user", "Email"), password_box("pw"), button("go", "Sign in")))
    assert sig is not None and sig.kind == "password_field"
    assert "pw" in sig.refs


def test_FR_CON_08_a_password_input_buried_deep_in_the_tree_is_found():
    deep = node("group", "", node("group", "", node("form", "Login", node("group", "", password_box("deep_pw")))))
    sig = detect(doc(textbox("q", "Search"), deep))
    assert sig is not None and sig.kind == "password_field" and "deep_pw" in sig.refs


@pytest.mark.parametrize("autocomplete", ["current-password", "new-password"])
def test_FR_CON_08_a_text_input_that_autofills_as_a_password_is_a_password_field(autocomplete):
    sig = detect(doc(textbox("sneaky", "Account key", autocomplete=autocomplete)))
    assert sig is not None and sig.kind == "password_field" and "sneaky" in sig.refs


# -- OTP fields --------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        textbox("otp1", "Code", autocomplete="one-time-code"),
        textbox("otp2", "Enter code", name="otp"),
        textbox("otp3", "Code", name="totp_code"),
        textbox("otp4", "Enter the 6-digit code we texted you", inputmode="numeric", maxlength="6"),
        textbox("otp5", "Authenticator app code"),
        textbox("otp6", "Verification code"),
        textbox("otp7", "Two-factor", name="mfa"),
    ],
    ids=["autocomplete", "name-otp", "name-totp", "six-digit-label", "authenticator", "verification", "mfa"],
)
def test_FR_CON_08_a_one_time_code_field_is_a_login_page(field):
    sig = detect(doc(field))
    assert sig is not None and sig.kind == "otp_field"
    assert field["attrs"]["id"] in sig.refs


# -- SSO redirects -----------------------------------------------------------

SSO_CHAINS = {
    "google": "https://accounts.google.com/o/oauth2/v2/auth?client_id=abc123&redirect_uri=https%3A%2F%2Fportal.example.com%2Fcb&response_type=code",
    "microsoft": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=abc123&response_type=code",
    "okta-saml": "https://acme.okta.com/app/acme_portal_1/exk1/sso/saml?SAMLRequest=abc",
    "own-sso": "https://portal.example.com/sso/login?return_to=%2Fapp",
    "sign_in": "https://portal.example.com/users/sign_in",
    "client-and-redirect": "https://idp.example.net/x?client_id=abc&redirect_uri=https%3A%2F%2Fportal.example.com%2Fcb",
}


@pytest.mark.parametrize("target", list(SSO_CHAINS.values()), ids=list(SSO_CHAINS))
def test_FR_CON_08_a_redirect_to_an_sso_or_login_url_is_a_login_page(target):
    sig = detect(chain=[HOME, target])
    assert sig is not None and sig.kind == "sso_redirect"


def test_FR_CON_08_an_sso_hop_in_the_middle_of_a_chain_counts():
    sig = detect(chain=[HOME, SSO_CHAINS["own-sso"], "https://portal.example.com/app"])
    assert sig is not None and sig.kind == "sso_redirect"


# -- credentials asked for in plain text -------------------------------------


def test_FR_CON_08_a_text_input_labelled_as_a_password_is_a_credential_ask():
    sig = detect(doc(textbox("answer", "Your password", type="text")))
    assert sig is not None and sig.kind in {"credentials_in_text", "password_field"}
    assert "answer" in sig.refs


def test_FR_CON_08_a_placeholder_asking_for_a_password_is_a_credential_ask():
    sig = detect(doc(node("textbox", "", id="box", placeholder="Type your password here")))
    assert sig is not None and sig.kind == "credentials_in_text" and "box" in sig.refs


@pytest.mark.parametrize(
    "text",
    [
        "To continue, please type your password in the box below.",
        "Verification needed. Reply with your account password to continue.",
        "Please paste your API key or password into the chat so the assistant can log in for you.",
        "Enter your passcode to unlock this document.",
        "Send us your login credentials and we will fix it.",
    ],
)
def test_FR_CON_08_page_text_that_asks_for_a_password_is_a_login_page_even_without_a_field(text):
    sig = detect(doc(node("paragraph", text)), text=text)
    assert sig is not None and sig.kind == "credentials_in_text"


# -- precision: pages that are NOT login walls -------------------------------


@pytest.mark.parametrize(
    ("tree", "text", "chain"),
    [
        (doc(node("heading", "Winter boots"), node("paragraph", "Size 42")), "Winter boots. Size 42.", [HOME]),
        (doc(textbox("q", "Search", type="search"), button("go", "Search")), "", [HOME]),
        (doc(textbox("nl", "Email address for our newsletter", type="email"), button("s", "Subscribe")), "", [HOME]),
        (
            doc(
                textbox("name", "Your name"),
                textbox("mail", "Email", type="email"),
                node("textbox", "Message", id="msg", multiline="true"),
            ),
            "",
            [HOME],
        ),
        (doc(link("nav", "Sign in"), link("nav2", "Log in")), "Header has Sign in and Log in links.", [HOME]),
        (
            doc(textbox("zip", "Postal code", inputmode="numeric", maxlength="5"), textbox("promo", "Promo code")),
            "",
            [HOME],
        ),
        (
            doc(textbox("cc", "Card number", autocomplete="cc-number")),
            "Checkout",
            ["https://shop.example.com/checkout"],
        ),
        (doc(), "We hash passwords with Argon2 and never store them in plain text.", [HOME]),
        (doc(), "Read our password policy.", [HOME]),
        (doc(), "", ["http://example.com/", "https://example.com/"]),
        (doc(), "", ["https://example.com/pricing", "https://example.com/pricing/plans"]),
        (doc(), "", ["https://example.com/blog/author/jane"]),
    ],
    ids=[
        "article",
        "search-box",
        "newsletter-email",
        "contact-form",
        "nav-sign-in-links",
        "postal-and-promo-code",
        "card-field-is-not-login",
        "password-word-no-ask",
        "password-policy",
        "http-to-https-upgrade",
        "plain-redirect",
        "author-is-not-auth",
    ],
)
def test_FR_CON_08_ordinary_pages_are_not_login_pages(tree, text, chain):
    assert detect(tree, chain=chain, text=text) is None


def test_FR_CON_08_secure_field_refs_lists_password_otp_and_payment_fields_only():
    from tilo_browser.login import secure_field_refs

    tree = doc(
        textbox("q", "Search"),
        password_box("pw"),
        textbox("otp", "Code", autocomplete="one-time-code"),
        textbox("cc", "Card number", autocomplete="cc-number"),
        textbox("cvc", "CVC", autocomplete="cc-csc"),
        node("group", "", textbox("deep", "Pass", type="password")),
        textbox("zip", "Postal code"),
    )
    assert sorted(secure_field_refs(tree)) == ["cc", "cvc", "deep", "otp", "pw"]


# -- property: a password field is found wherever it sits --------------------

SAFE = [
    ("Search", {"type": "search"}),
    ("Email address for newsletter", {"type": "email"}),
    ("Your name", {}),
    ("Message", {}),
    ("Quantity", {"type": "number"}),
    ("Postal code", {"inputmode": "numeric", "maxlength": "5"}),
    ("Promo code", {}),
]


def _tree(safe_idx: list[int], depth: int, with_password_at: int | None):
    leaves = [textbox(f"f{i}", SAFE[k][0], **SAFE[k][1]) for i, k in enumerate(safe_idx)]
    if with_password_at is not None:
        leaves.insert(min(with_password_at, len(leaves)), password_box("the_pw"))
    tree = doc(*leaves)
    for _ in range(depth):
        tree = doc(node("group", "", *tree["children"]))
    return tree


@given(
    st.lists(st.integers(0, len(SAFE) - 1), max_size=6),
    st.integers(0, 4),
)
@settings(max_examples=60, deadline=None)
def test_FR_CON_08_a_tree_of_ordinary_fields_is_never_a_login_page(safe_idx, depth):
    assert detect(_tree(safe_idx, depth, None)) is None


@given(
    st.lists(st.integers(0, len(SAFE) - 1), max_size=6),
    st.integers(0, 4),
    st.integers(0, 6),
)
@settings(max_examples=60, deadline=None)
def test_FR_CON_08_a_password_field_is_found_at_any_position_and_depth(safe_idx, depth, pos):
    from tilo_browser.login import secure_field_refs

    tree = _tree(safe_idx, depth, pos)
    sig = detect(tree)
    assert sig is not None and sig.kind == "password_field" and "the_pw" in sig.refs
    assert "the_pw" in secure_field_refs(tree)
