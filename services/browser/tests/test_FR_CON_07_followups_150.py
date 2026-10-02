"""FR-CON-07 / FR-CON-08 follow-ups from the PR #140 reviews (issue #150, part 1).

Masker: userinfo nested anywhere in text, quoted multi-word passwords, `Authorization` header
values, an iterative `mask_data` (tuples, secret-looking keys, no recursion), and a size cap on
text before masking. Login: `autocomplete` is a token list. Worker: `type()` refuses an empty or
ambiguous ref. Egress log: an IPv6 literal logs as its bracketed host, without userinfo.

Fake secrets are assembled at runtime; nothing here is a real credential.
"""

from __future__ import annotations

import time

import pytest
from _browser_lib import doc, node, textbox

PW = "Q7v" + "Rk2" + "mZ9" + "!x"
WORDS = ("alpha" + "Zq1", "bravo" + "Zq2", "charlie" + "Zq3")
B64 = "dXNlcjpw" + "YXNzd29yZDEyMzQ="
TOKEN = "T0k3" + "nValue" + "Zz9876"


def _policy():
    from tilo_browser.egress import EgressPolicy

    return EgressPolicy(allow=["example.com"])


# -- 1. masker: nested userinfo, quoted passwords, Authorization headers ----------------------------


@pytest.mark.parametrize(
    "text",
    [
        f"https://evil.net/https://user:{PW}@x.example/",
        f"see the mirror at ftp://admin:{PW}@files.example.org/pub for details",
        f"<a href='postgres://app:{PW}@db.internal:5432/main'>db</a>",
        f"redirect=https%3A%2F%2Fexample.com%2F&u=https://u:{PW}@a.b/c",
    ],
)
def test_FR_CON_07_userinfo_nested_in_text_or_a_path_is_masked(text):
    from tilo_browser.masking import mask_text

    out = mask_text(text)
    assert PW not in out and PW[:6] not in out
    assert "[masked:" in out
    assert mask_text(out) == out


def test_FR_CON_07_a_url_without_userinfo_in_text_is_kept():
    from tilo_browser.masking import mask_text

    text = "docs at https://example.com/a/b?x=1 and mailto-free ftp://files.example.org/pub"
    assert mask_text(text) == text


def test_FR_CON_07_nested_userinfo_in_an_allowlisted_path_never_reaches_the_decision():
    d = _policy().check(f"https://example.com/https://user:{PW}@x.example/")
    assert PW not in d.url and PW[:6] not in d.url


@pytest.mark.parametrize(
    "template",
    [
        '{{"password": "{v}"}}',
        "{{'password': '{v}'}}",
        'password = "{v}" and more text',
        '{{"api_key":"{v}","ok":true}}',
        "token: '{v}'",
    ],
)
def test_FR_CON_07_a_quoted_multi_word_secret_is_masked_whole(template):
    from tilo_browser.masking import mask_text

    text = template.format(v=" ".join(WORDS))
    out = mask_text(text)
    assert not any(w in out for w in WORDS), out
    assert "[masked:secret]" in out
    assert mask_text(out) == out


def test_FR_CON_07_a_quoted_value_keeps_the_text_after_its_closing_quote():
    from tilo_browser.masking import mask_text

    out = mask_text('{"password": "a b c", "name": "riya"}')
    assert out == '{"password": "[masked:secret]", "name": "riya"}'


@pytest.mark.parametrize(
    "text",
    [
        f"Authorization: Basic {B64}",
        f"authorization: basic {B64}",
        f"Authorization: Bearer {TOKEN}",
        f"authorization: bearer {TOKEN}",
        f'"Authorization": "Basic {B64}"',
        f"curl -H 'Authorization: Basic {B64}' https://example.com/",
        f"Authorization: {TOKEN}",
    ],
)
def test_FR_CON_07_authorization_header_values_are_masked(text):
    from tilo_browser.masking import mask_text

    out = mask_text(text)
    assert B64 not in out and TOKEN not in out, out
    assert "[masked:secret]" in out
    assert mask_text(out) == out


def test_FR_CON_07_prose_with_the_word_basic_or_authorization_is_kept():
    from tilo_browser.masking import mask_text

    text = "Basic understanding of the authorization process is required."
    assert mask_text(text) == text


# -- 2. mask_data: iterative, tuples, keys ----------------------------------------------------------


def test_FR_CON_07_mask_data_survives_a_3000_deep_dict_and_masks_the_leaf():
    from tilo_browser.masking import mask_data

    leaf = {"note": f"token={TOKEN}"}
    value: dict = leaf
    for _ in range(3000):
        value = {"k": value}
    out = mask_data(value)
    n = 0
    while "k" in out:
        out = out["k"]
        n += 1
    assert n == 3000
    assert TOKEN not in out["note"] and "[masked:secret]" in out["note"]


def test_FR_CON_07_mask_data_survives_a_3000_deep_list_and_a_cycle():
    from tilo_browser.masking import mask_data

    value: list = ["leaf"]
    for _ in range(3000):
        value = [value]
    out = mask_data(value)
    n = 0
    while isinstance(out[0], list):
        out = out[0]
        n += 1
    assert n == 3000 and out == ["leaf"]

    cyc: dict = {"a": f"token={TOKEN}"}
    cyc["self"] = cyc
    masked = mask_data(cyc)
    assert TOKEN not in masked["a"] and masked["self"] is masked


def test_FR_CON_07_mask_data_walks_tuples_and_keeps_them_tuples():
    from tilo_browser.masking import mask_data

    out = mask_data({"t": (f"token={TOKEN}", ("x", f"pwd={PW}"), 7), "l": [(f"token={TOKEN}",)]})
    assert isinstance(out["t"], tuple) and isinstance(out["t"][1], tuple)
    assert TOKEN not in repr(out) and PW not in repr(out)
    assert out["t"][2] == 7 and out["t"][1][0] == "x"
    assert isinstance(out["l"][0], tuple)


def test_FR_CON_07_mask_data_masks_secret_looking_dict_keys_and_keeps_ordinary_ones():
    from tilo_browser.masking import mask_data

    key = "s" + "k" + "-" + "A1b2C3d4" * 4
    out = mask_data({key: "v1", "Bearer " + "x" * 12: "v2", "plain": "v3", 5: "five"})
    assert key not in repr(out) and "x" * 12 not in repr(out)
    assert out["plain"] == "v3" and out[5] == "five"
    assert sorted(out.values(), key=str) == ["five", "v1", "v2", "v3"], "no entry is lost on a key collision"


def test_FR_CON_07_mask_data_leaves_numbers_and_other_scalars_as_they_are():
    from tilo_browser.masking import mask_data

    data = {"i": 4111, "f": 1.5, "b": True, "n": None}
    assert mask_data(data) == data


# -- 3. page text is capped before masking ----------------------------------------------------------


def test_FR_CON_07_text_over_the_cap_is_truncated_with_a_marker_and_masked():
    from tilo_browser.masking import MAX_TEXT_CHARS, TRUNCATED_MARKER, mask_text

    head = f"token={TOKEN} "
    out = mask_text(head + "word " * (MAX_TEXT_CHARS // 5 + 1000))
    assert out.endswith(TRUNCATED_MARKER)
    assert len(out) <= MAX_TEXT_CHARS + len(TRUNCATED_MARKER)
    assert TOKEN not in out and out.startswith("token=[masked:secret]")


def test_FR_CON_07_text_at_the_cap_is_not_truncated():
    from tilo_browser.masking import MAX_TEXT_CHARS, TRUNCATED_MARKER, mask_text

    text = "a " * (MAX_TEXT_CHARS // 2)
    assert len(text) == MAX_TEXT_CHARS
    assert mask_text(text) == text and TRUNCATED_MARKER not in text


@pytest.mark.parametrize("unit", ["1 ", "11 ", "a-", "a", "token ", "Bearer ", "https://u@"])
def test_FR_CON_07_masking_text_at_and_over_the_cap_is_fast(unit):
    from tilo_browser.masking import MAX_TEXT_CHARS, mask_text

    for size in (MAX_TEXT_CHARS, MAX_TEXT_CHARS * 2):
        text = unit * (size // len(unit) + 1)
        start = time.process_time()
        mask_text(text)
        assert time.process_time() - start < 2.0, (unit, size)


def test_FR_CON_07_capture_caps_page_text_before_masking(make_rig):
    from tilo_browser.masking import MAX_TEXT_CHARS, TRUNCATED_MARKER

    rig = make_rig()
    rig.web.add("https://example.com/big", title="Big", text="1 " * (MAX_TEXT_CHARS * 2), tree=doc(title="Big"))
    rig.worker.navigate("https://example.com/big")
    cap = rig.worker.capture()
    assert cap.text.endswith(TRUNCATED_MARKER)


# -- 4. login: autocomplete is a token list ---------------------------------------------------------


@pytest.mark.parametrize(
    "autocomplete",
    ["billing cc-number", "section-x one-time-code", "shipping section-b cc-csc", "section-login current-password"],
)
def test_FR_CON_08_autocomplete_is_a_token_list_so_these_are_secure_fields(autocomplete):
    from tilo_browser.login import secure_field_refs

    tree = doc(textbox("f1", "Field", autocomplete=autocomplete), textbox("q", "Search", autocomplete="off"))
    assert secure_field_refs(tree) == ["f1"]


def test_FR_CON_08_a_token_list_password_field_is_a_login_page():
    from tilo_browser.login import detect_login

    tree = doc(textbox("a", "Account", autocomplete="section-login new-password"))
    signal = detect_login(chain=["https://example.com/account"], tree=tree, text="")
    assert signal is not None and signal.kind == "password_field"


def test_FR_CON_08_autocomplete_tokens_that_only_contain_a_secure_word_are_not_secure():
    from tilo_browser.login import secure_field_refs

    tree = doc(textbox("a", "Nickname", autocomplete="nickname"), textbox("b", "Org", autocomplete="organization"))
    assert secure_field_refs(tree) == []


# -- 5. worker.type refuses an empty or ambiguous ref ------------------------------------------------


def test_FR_CON_08_type_refuses_an_empty_ref_even_if_an_idless_input_exists(make_rig):
    from tilo_browser.login import CredentialEntryRefused

    rig = make_rig()
    rig.web.add("https://example.com/a", title="A", tree=node("textbox", "Search", id="", type="text"))
    rig.worker.navigate("https://example.com/a")
    with pytest.raises(CredentialEntryRefused):
        rig.worker.type("", "boots")
    assert rig.driver.typed == []


def test_FR_CON_08_type_refuses_a_ref_shared_by_two_plain_inputs(make_rig):
    from tilo_browser.login import CredentialEntryRefused

    rig = make_rig()
    rig.web.add("https://example.com/a", title="A", tree=doc(textbox("dup", "Search"), textbox("dup", "Notes")))
    rig.worker.navigate("https://example.com/a")
    with pytest.raises(CredentialEntryRefused):
        rig.worker.type("dup", "boots")
    assert rig.driver.typed == []


def test_FR_CON_08_type_still_types_into_a_unique_plain_input(make_rig):
    rig = make_rig()
    rig.web.add("https://example.com/a", title="A", tree=doc(textbox("q", "Search"), textbox("n", "Notes")))
    rig.worker.navigate("https://example.com/a")
    rig.worker.type("q", "boots")
    assert rig.driver.typed == [("q", "boots")]


# -- 6. egress log: an IPv6 literal logs as its bracketed host ---------------------------------------


@pytest.mark.parametrize(
    ("raw", "logged"),
    [
        ("https://[::1]/", "https://[::1]/"),
        ("https://[2001:db8::1]:8443/a/b", "https://[2001:db8::1]:8443/a/b"),
        ("https://user:{pw}@[2001:db8::1]/x", "https://[2001:db8::1]/x"),
        ("https://user:{pw}@[::ffff:127.0.0.1]:80/", "https://[::ffff:127.0.0.1]:80/"),
        ("https://[::1]/p?q={pw}#f", "https://[::1]/p"),
    ],
)
def test_FR_CON_07_an_ipv6_literal_logs_as_its_bracketed_host_without_userinfo(raw, logged):
    d = _policy().check(raw.format(pw=PW))
    assert d.allowed is False
    assert d.url == logged
    assert PW not in d.url and "@" not in d.url


@pytest.mark.parametrize("raw", ["https://[::1]:80x/", "https://[::1]x/", "https://[::1/", "https://[<script>]/"])
def test_FR_CON_07_a_malformed_ipv6_authority_still_logs_scheme_only(raw):
    d = _policy().check(raw)
    assert d.allowed is False and d.url == "https:"


def test_FR_CON_07_the_blocked_ipv6_error_text_has_no_userinfo(make_rig):
    from tilo_browser.egress import EgressBlocked

    rig = make_rig()
    with pytest.raises(EgressBlocked) as exc:
        rig.worker.navigate(f"https://user:{PW}@[::1]/")
    assert PW not in str(exc.value) and "[::1]" in str(exc.value)
