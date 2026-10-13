"""FR-MEM-05 / SEC-14, third security review (BQ-FRMEM05-1).

- A value under a quoted secure key ends only at a quote of its own JSON-in-JSON level. A deeper, escaped quote is
  text, so a secure field that holds a JSON document, a repr or an array loses all of it.
- After an unquoted password, passwd or passphrase label the value always goes: these labels fail closed even
  before prose.
- A one-word key that ends in password, passwd, pwd, secret or token is secure in both modes (`PGPASSWORD`,
  `csrftoken`); the paging cursors stay exempt.

Every fake secret is assembled at runtime.
"""

from __future__ import annotations

import json
import string

import pytest
from _redact_samples_lib import FIXED_TAIL
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_redact import REDACTED, redact, redact_value

PW = "hunter" + "2xyz"
CLIENT = "GOCSPX-" + FIXED_TAIL[:20]


@pytest.mark.parametrize(
    "text",
    [
        json.dumps({"token": json.dumps({"password": PW})}),
        json.dumps({"secret": json.dumps({"installed": {"client_id": "1.apps.example", "client_secret": CLIENT}})}),
        json.dumps({"api_key": json.dumps({"key": "x", "password": PW})}),
        json.dumps({"token": json.dumps([PW, {"a": CLIENT}])}),
        json.dumps({"body": json.dumps({"token": json.dumps({"password": PW, "client_secret": CLIENT})})}),
        str({"secret": json.dumps({"client_secret": CLIENT})}),
        str({"password": 'it\'s "x", ' + PW}),
    ],
)
def test_FR_MEM_05_a_secure_field_holding_json_a_repr_or_an_array_loses_all_of_it(text):
    out = redact(text)
    assert PW not in out and CLIENT not in out and CLIENT[7:15] not in out, out
    assert redact(out) == out
    if text.startswith('{"'):
        json.loads(out)


def test_FR_MEM_05_a_plain_field_holding_json_keeps_its_inner_json_valid_and_loses_the_inner_secret():
    inner = json.dumps({"user": "ann", "password": PW, "note": 'say "hi"'})
    out = json.loads(redact(json.dumps({"body": inner})))
    assert json.loads(out["body"]) == {"user": "ann", "password": REDACTED, "note": 'say "hi"'}


WORDS = st.text(alphabet=string.ascii_letters, min_size=4, max_size=8).map(lambda w: "Zq" + w)
GLUE = st.sampled_from([" ", '"', "'", "\\", '\\"', "\\n", ":", ",", "{", "}", "[", "]", "=", "&quot;", ": ", '", "'])
VALUE = st.lists(st.one_of(WORDS, GLUE), min_size=1, max_size=10).map("".join).filter(lambda v: "Zq" in v)
SECURE = st.sampled_from(["password", "token", "secret", "api_key", "client_secret", "accessToken", "Authorization"])


def _holders(key: str, value: str) -> list[str]:
    inner = json.dumps({key: value})
    return [
        json.dumps({key: value}),
        json.dumps({"a": [1, {key: value}]}, indent=2),
        json.dumps({"body": inner}),
        json.dumps({"body": json.dumps({"body": inner})}),
        json.dumps({key: inner}),
        str({key: value}),
        str({"a": [{key: value}]}),
        str({key: inner}),
    ]


@settings(max_examples=300, deadline=None)
@given(key=SECURE, value=VALUE)
def test_FR_MEM_05_property_no_word_of_a_value_under_a_quoted_secure_key_survives(key, value):
    words = [w for w in value.replace("\\n", " ").replace("&quot;", " ").split() if w.startswith("Zq")]
    for text in _holders(key, value):
        out = redact(text)
        for chunk in (w.strip("\"'\\:,{}[]=&") for w in words):
            if len(chunk) > 2:
                assert chunk not in out, (text, out)
        assert redact(out) == out
        if text.startswith(("{", "[")) and text[1] != "'":
            json.loads(out)


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        ("Username: ann  Password: changeme (temporary)", "changeme"),
        ("Wifi password: coffeeshop for guests", "coffeeshop"),
        ("Login: ann / Password: letmein - change it Monday", "letmein"),
        ("Your password: welcome then change it", "welcome"),
        ("passphrase: correct horse battery staple", "correct horse battery staple"),
        ("password: hunter2 please", "hunter2"),
        ("Password: reset link sent to Ann", "reset"),  # accepted false positive (BQ-FRMEM05-1)
        ("Password: minimum 8 characters", "minimum"),  # accepted false positive (BQ-FRMEM05-1)
        ("DB passwd: swordfish today", "swordfish"),
    ],
)
def test_FR_MEM_05_an_unquoted_password_label_fails_closed_even_before_prose(text, gone):
    out = redact(text)
    assert REDACTED in out and gone not in out, out
    assert redact(out) == out


@pytest.mark.parametrize(
    "text", ["The secret: ship small", "Token: of appreciation for the team", "Cookie: oatmeal raisin, 2 dozen"]
)
def test_FR_MEM_05_the_prose_rule_stays_for_secret_token_and_cookie(text):
    assert redact(text) == text


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        (f"PGPASSWORD={PW} psql -h db", PW),
        (f"MYSQL_PWD={PW} mysql", PW),
        (f"export CSRFTOKEN={PW}", PW),
        (json.dumps({"dbpassword": "plain words"}), "plain words"),
        (json.dumps({"csrftoken": PW}), PW),
    ],
)
def test_SEC_14_a_one_word_key_ending_in_a_secret_word_is_secure_in_text(text, gone):
    assert gone not in redact(text)


def test_SEC_14_a_one_word_key_ending_in_a_secret_word_is_secure_in_a_tree_and_cursors_stay():
    tree = {"dbpassword": "x", "PGPASSWORD": "y", "csrftoken": "z", "MYSQL_PWD": "w", "appsecret": "v"}
    assert redact_value(tree) == dict.fromkeys(tree, REDACTED)
    cursors = {"nextpagetoken": "c1", "next_page_token": "c2", "nextSyncToken": "c3", "pagetoken": "c4"}
    assert redact_value(cursors) == cursors
    assert redact(json.dumps(cursors)) == json.dumps(cursors)
