"""FR-CON-07 / FR-CON-08 fix pass on PR #168 (issue #150, part 1; security and code review).

mask_data keys stay linear when many collide, shared tuples are copied once; the text cap masks a
window past the cut and then cuts, so no secret keeps a prefix at the cut and the result is
idempotent; Authorization values are masked to the end of the line; quoted values with an escaped
or missing closing quote, or over 512 characters, are masked whole.

Fake secrets are assembled at runtime; nothing here is a real credential.
"""

from __future__ import annotations

import time

import pytest
from _browser_lib import doc, fake_card_numbers, node

PW = "Q7v" + "Rk2" + "mZ9!x"
B64 = "dXNlcjpw" + "YXNzd29yZDEyMzQ="
SK = "s" + "k" + "-" + "A1b2C3d4" * 4
EMAIL = "riya.sharma" + "@" + "example.org"
CARD = fake_card_numbers()


# -- mask_data: colliding keys stay linear, shared tuples are memoised -------------------------------


def test_FR_CON_07_fifty_thousand_colliding_keys_mask_in_linear_time_and_keep_every_entry():
    from tilo_browser.masking import mask_data

    data = {f"user{i}@example.org": i for i in range(50_000)}
    start = time.process_time()
    out = mask_data(data)
    assert time.process_time() - start < 1.0
    assert len(out) == 50_000 and sorted(out.values()) == list(range(50_000))
    assert "[masked:email]" in out and "[masked:email]#2" in out and "[masked:email]#50000" in out
    assert max(map(len, out)) < 30


def test_FR_CON_07_a_literal_key_that_looks_like_a_collision_suffix_does_not_lose_entries():
    from tilo_browser.masking import mask_data

    data = {"a@example.org": 1, "[masked:email]#2": 2, "b@example.org": 3, "c@example.org": 4}
    out = mask_data(data)
    assert sorted(out.values()) == [1, 2, 3, 4]


def test_FR_CON_07_fifty_thousand_colliding_attrs_leave_the_worker_in_under_a_second(make_rig):
    rig = make_rig()
    attrs = {f"user{i}@example.org": "x" for i in range(50_000)}
    page = node("textbox", "Search", id="q", type="text")
    page["attrs"].update(attrs)
    rig.web.add("https://example.com/a", title="A", tree=doc(page))
    rig.worker.navigate("https://example.com/a")
    start = time.process_time()
    tree = rig.worker.read_accessibility_tree()
    assert time.process_time() - start < 1.0
    assert len(tree["children"][0]["attrs"]) == 50_002


def test_FR_CON_07_a_shared_tuple_dag_is_copied_once_and_stays_shared():
    from tilo_browser.masking import mask_data

    dag: object = (f"leaf-{SK}",)
    for _ in range(18):
        dag = (dag, dag)
    start = time.process_time()
    out = mask_data(dag)
    assert time.process_time() - start < 1.0
    node_ = out
    for _ in range(18):
        assert isinstance(node_, tuple) and node_[0] is node_[1]
        node_ = node_[0]
    assert isinstance(node_, tuple) and SK not in node_[0]


def test_FR_CON_07_a_tuple_shared_by_a_list_and_a_dict_is_a_tuple_in_both_places():
    from tilo_browser.masking import mask_data

    shared = (f"token={PW}", 1)
    out = mask_data({"a": [shared], "b": shared, "c": (shared, shared)})
    assert isinstance(out["a"][0], tuple) and out["a"][0] is out["b"]
    assert isinstance(out["c"][0], tuple) and out["c"][0] is out["c"][1]
    assert PW not in repr(out)


# -- the text cap: mask a window past the cut, then cut ----------------------------------------------

SHAPES = {
    "card": CARD["plain"],
    "card_spaced": CARD["spaced"],
    "email": EMAIL,
    "userinfo_url": f"https://user:{PW}@intranet.example.org/x",
    "sk_key": SK,
    "kv": f"password={PW}",
}


@pytest.mark.parametrize("name", list(SHAPES))
def test_FR_CON_07_a_secret_straddling_the_cut_keeps_no_prefix_at_any_offset(name, monkeypatch):
    from tilo_browser import masking

    monkeypatch.setattr(masking, "MAX_TEXT_CHARS", 3000)
    secret = SHAPES[name]
    needle = PW[:5] if name in ("userinfo_url", "kv") else secret[:5]  # the scheme or keyword may stay
    for start in range(3000 - 80 - len(secret), 3000 + 4):
        text = ("a " * 2000)[:start] + " " + secret + " tail " + "b " * 300
        out = masking.mask_text(text)
        assert needle not in out, (name, start)
        assert len(out) <= 3000 + len(masking.TRUNCATED_MARKER), (name, start)
        assert out.endswith(masking.TRUNCATED_MARKER), (name, start)
        assert masking.mask_text(out) == out, (name, start)


def test_FR_CON_07_masking_is_idempotent_for_text_over_the_real_cap():
    from tilo_browser.masking import MAX_TEXT_CHARS, mask_text

    filler = "Winter boots, size 42. "
    text = filler * (MAX_TEXT_CHARS // len(filler) - 3) + f"card {CARD['spaced']} mail {EMAIL} " + filler * 600
    once = mask_text(text)
    assert mask_text(once) == once
    assert CARD["plain"][:6] not in once and EMAIL not in once


def test_FR_CON_07_a_partial_placeholder_at_the_cut_is_stable_on_a_second_pass(monkeypatch):
    from tilo_browser import masking

    monkeypatch.setattr(masking, "MAX_TEXT_CHARS", 3000)
    for pad in range(3000 - 100, 3000 - 40):
        text = "a " * (pad // 2) + f"token={PW} " + "b " * 400
        out = masking.mask_text(text)
        assert PW not in out and masking.mask_text(out) == out, pad


# -- Authorization values run to the end of the line --------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        f"Authorization: Negotiate {B64}",
        f"Proxy-Authorization: NTLM {B64}",
        f'Authorization: Digest username="bob", realm="r", nonce="n", response="{PW}"',
        f"authorization = AWS4-HMAC-SHA256 Credential=abc/20261002, Signature={PW}",
        f"Authorization: {PW}",
    ],
)
def test_FR_CON_07_an_authorization_value_is_masked_to_the_end_of_the_line_for_any_scheme(line):
    from tilo_browser.masking import mask_text

    out = mask_text(line + "\nHost: example.com")
    assert PW not in out and B64 not in out and "bob" not in out and "Signature" not in out, out
    assert out.endswith("\nHost: example.com")
    assert mask_text(out) == out


def test_FR_CON_07_the_scheme_word_stays_and_the_credentials_go():
    from tilo_browser.masking import mask_text

    assert mask_text(f"Authorization: Negotiate {B64}") == "Authorization: Negotiate [masked:secret]"


# -- quoted values -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"password": "pa\\"ss tail ' + PW + '", "ok": 1}',
        "{'password': 'pa\\'ss tail " + PW + "', 'ok': 1}",
        'password="never closed tail ' + PW,
        '"secret": "' + "w " * 400 + PW + '", "ok": 1}',
        "token='" + "x" * 700 + " " + PW + "'",
    ],
)
def test_FR_CON_07_quoted_values_with_escapes_no_close_or_over_512_chars_are_masked_whole(text):
    from tilo_browser.masking import mask_text

    out = mask_text(text)
    assert PW not in out and "tail" not in out and "xxxx" not in out and "w w" not in out, out
    assert mask_text(out) == out


def test_FR_CON_07_an_unclosed_quote_masks_to_the_end_of_the_line_only():
    from tilo_browser.masking import mask_text

    assert mask_text('password="abc def\nnext line') == 'password="[masked:secret]\nnext line'


@pytest.mark.parametrize(
    "text",
    ["x://" + "@" * 20_000, "https://" + "u@" * 9_000, 'password="' + "a b " * 5_000, "Authorization:" * 3_000],
    ids=["at_soup", "userinfo_soup", "open_quote", "auth_soup"],
)
def test_FR_CON_07_masking_hostile_input_twice_changes_nothing(text):
    from tilo_browser.masking import mask_text

    once = mask_text(text)
    assert mask_text(once) == once


def test_FR_CON_07_an_escaped_quote_does_not_end_a_value_and_the_rest_of_the_json_is_kept():
    from tilo_browser.masking import mask_text

    out = mask_text('{"password": "a\\"b c", "name": "riya"}')
    assert out == '{"password": "[masked:secret]", "name": "riya"}'
