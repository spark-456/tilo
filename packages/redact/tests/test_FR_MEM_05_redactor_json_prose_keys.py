"""FR-MEM-05 / SEC-14, second security review (BQ-FRMEM05-1). The artifact store (AR-07, MF-06), connectors and the run
bundle refuse or store what `redact` returns, so: JSON stays JSON (a broken document is a corrupted artifact), output is
a fixed point (a second pass that changes it refuses an export), prose that only looks labelled is kept (a false
positive is lost work), and the tree and text modes agree on which keys are secure. Fake secrets are built at runtime.
"""

from __future__ import annotations

import io
import json
import logging
import random

import pytest
from _redact_samples_lib import FIXED_TAIL, build
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_redact import REDACTED, RedactingFilter, redact, redact_value

SECRET = "Zq" + FIXED_TAIL[:14]  # credential-shaped (16 characters) and no known token shape
CARD = "4" + "1" * 15  # the Luhn-valid test card, built at runtime
SECURE = [
    "password",
    "token",
    "secret",
    "api_key",
    "accessToken",
    "x-api-key",
    "Authorization",
    "cookie",
    "pass",
    "pwd",
]
CURSORS = ["page_token", "next_page_token", "start_page_token", "new_start_page_token", "sync_token", "next_sync_token"]
CURSORS += ["continuation_token", "nextPageToken", "syncToken", "pageToken", "nextSyncToken", "startPageToken"]
CURSORS += ["newStartPageToken"]
PLAIN = ["note", "user", "type", "properties", "minLength", "tokens", "max_output_tokens", "code", "key", "items"]
FRAGMENTS = [*SECURE, "=", ": ", ":", " ", "\n", '"', "'", "\\", "\\n", '\\"', "&quot;", "&", "?", "@", "://", "{", "}"]
FRAGMENTS += ["[", "]", ",", "Bearer ", "Basic ", SECRET, CARD, REDACTED, "#2", "sid=", "?code=", "&state=", "/cb", "x"]
FRAGMENTS += ["none", "ship small", "5", "null", "-----BEGIN " + "PRIV" + "ATE KEY-----", "QUJDREVGR0hJSktMTU5PUFFS"]
TEXT = st.lists(st.sampled_from(FRAGMENTS), max_size=8).map("".join) | st.text(max_size=12)
KEY = st.sampled_from(SECURE + CURSORS + PLAIN) | TEXT
NODE = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | TEXT,
    lambda kids: st.lists(kids, max_size=4) | st.dictionaries(KEY, kids, max_size=4),
    max_leaves=12,
)
DOC = st.dictionaries(KEY, NODE, max_size=5) | st.lists(NODE, max_size=5)  # a document is an object or an array


@pytest.mark.parametrize(
    "doc",
    [
        {"token": 5, "secret": False, "password": None},
        {"token": -1.5e3, "api_key": True, "cookie": None, "user": "ann"},
        {"properties": {"password": {"type": "string", "minLength": 8}}},
        {"auth": {"token": ["a", "b"]}, "password": [1, {"secret": "x"}]},
        {"pan": int(CARD), "cards": [int(CARD), 5], "token": int(CARD)},
    ],
)
def test_FR_MEM_05_secure_keys_holding_json_values_leave_valid_json(doc):
    for text in (json.dumps(doc), json.dumps(doc, separators=(",", ":")), json.dumps({"body": json.dumps(doc)})):
        out = redact(text)
        assert redact(out) == out and json.loads(out) is not None, (text, out)
        assert CARD not in out
    out = json.loads(redact(json.dumps(doc)))
    if "properties" in doc:
        assert out == doc  # a JSON schema keeps its shape: `{` and `[` values are left to the rules inside them
    if "token" in doc and not isinstance(doc["token"], dict | list):
        assert out["token"] == REDACTED == redact_value(doc)["token"]  # a number becomes the string, as in a tree
    for key in ("secret", "password", "api_key", "cookie"):
        if doc.get(key, 0) is None or isinstance(doc.get(key), bool):
            assert out[key] == doc[key] == redact_value(doc)[key]  # a bool or null holds no secret, in both modes


@settings(max_examples=300, deadline=None)
@given(doc=DOC, indent=st.sampled_from([None, 2]), compact=st.booleans(), nest=st.booleans())
def test_FR_MEM_05_property_any_json_document_stays_valid_json_and_is_a_fixed_point(doc, indent, compact, nest):
    nest = nest and isinstance(doc, dict | list)
    if nest:
        doc = {"body": json.dumps(doc)}
    text = json.dumps(doc, indent=indent, separators=(",", ":") if compact else None)
    out = redact(text)
    assert redact(out) == out
    loaded = json.loads(out)
    if nest:
        json.loads(loaded["body"])  # the JSON-in-JSON layer is valid too


@settings(max_examples=500, deadline=None)
@given(st.lists(st.sampled_from(FRAGMENTS), min_size=1, max_size=16).map("".join))
def test_FR_MEM_05_property_any_text_is_a_fixed_point(text):
    once = redact(text)
    assert redact(once) == once


def test_FR_MEM_05_twenty_thousand_random_fragment_texts_are_fixed_points():
    rng = random.Random(7)  # the review's 60 000-case idem.py fuzz at a third of its size (it stays clean at full size)
    for _ in range(20_000):
        once = redact("".join(rng.choice(FRAGMENTS) for _ in range(rng.randint(1, 14))))
        assert redact(once) == once, once


KEEPS = [
    "Payment Authorization: approved by finance on 3 Oct",
    "Prior Authorization: required for the MRI referral",
    "Subject: Travel Authorization: Singapore trip, 12-14 Nov",
    "Authorization: pending",
    "Cookie: oatmeal raisin, 2 dozen",
    "The secret: ship small, ship often.",
    "Secret: minimum 8 characters",
    "Token: of appreciation for the team",
    "Bearer securities are exempt.",
    "Bearer authentication is used by the API, and Bearer instruments too.",
    "Love you, xoxo-mum-and-dad",
    "Use https://shop.example/sale?code=SUMMER20 today",
    "Boarding pass: gate 12",
]


@pytest.mark.parametrize("text", KEEPS)
def test_FR_MEM_05_prose_that_only_looks_labelled_is_kept_in_text_and_inside_json(text):
    assert redact(text) == text
    assert redact(json.dumps({"note": text})) == json.dumps({"note": text})


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        (f"The secret: {SECRET} ship small", SECRET),
        (f"Password: {SECRET[:7]}!", SECRET[:7]),  # 8 characters with a symbol
        ('Password: "ship small"', "ship small"),  # quoted
        ("password: none", "none"),  # a lone word fails closed
        (f"token: {SECRET}", SECRET),
        ("Authorization: Bearer x y z", "x y z"),
        (f"Payment Authorization: {SECRET} ok", SECRET),
        ("Cookie: sid=abc; theme=dark", "sid=abc"),
        (f"pass: {SECRET}", SECRET),
        (f"Bearer {SECRET[2:8]}9x", SECRET[2:8]),
        (f"https://example.com/oauth/callback?code={SECRET}", SECRET),
        (f"https://example.com/x?code={SECRET}&state=1", SECRET),
        (f"https://example.com/x?scope=a&code={SECRET}", SECRET),
        (f"grant_type=authorization_code&code={SECRET}", SECRET),
    ],
)
def test_FR_MEM_05_credential_shaped_quoted_or_lone_values_still_go(text, gone):
    out = redact(text)
    assert REDACTED in out and gone not in out, out


KEYS_SECURE = [*SECURE, "Password", "PASSWORD", "passwd", "passphrase", "client_secret", "clientSecret", "access_token"]
KEYS_SECURE += ["ACCESS_TOKEN", "refresh_token", "id_token", "apiKey", "apikey", "APIKey", "X-Goog-Api-Key"]
KEYS_SECURE += ["x-auth-token", "Proxy-Authorization", "payment_authorization", "Set-Cookie", "db_password"]
KEYS_SECURE += ["dbPassword", "aws_secret_access_key", "private_key", "push_token", "sessionToken", "secret_key"]
KEYS_SECURE += ["dbpassword", "PGPASSWORD", "MYSQL_PWD", "csrftoken", "clientsecret"]  # one unbroken word, a suffix
KEYS_PLAIN = [*CURSORS, "max_output_tokens", "input_tokens", "tokens", "token_count", "authz", "bypass", "keyboard"]
KEYS_PLAIN += ["code", "key", "signature", "session", "user", "passport", "password_hint", "secretary", "pagetoken"]
KEYS_PLAIN += ["nextpagetoken", "synctoken"]


@pytest.mark.parametrize("mode", ["tree", "text_eq", "text_colon", "json", "json_compact", "json_in_json"])
@pytest.mark.parametrize("key", KEYS_SECURE + KEYS_PLAIN)
def test_SEC_14_tree_and_text_modes_agree_on_every_key(key, mode):
    form = {
        "tree": lambda: json.dumps(redact_value({key: SECRET})),
        "text_eq": lambda: redact(f"{key}={SECRET}"),
        "text_colon": lambda: redact(f"{key}: {SECRET}"),
        "json": lambda: redact(json.dumps({key: SECRET})),
        "json_compact": lambda: redact(json.dumps({key: SECRET}, separators=(",", ":"))),
        "json_in_json": lambda: redact(json.dumps({"body": json.dumps({key: SECRET})})),
    }[mode]
    assert (SECRET not in form()) is (key in KEYS_SECURE), (key, mode, form())


def test_SEC_14_pass_true_and_payment_authorization_under_the_agreed_rule():
    """`pass` is a secure key only as the whole key, and a bool holds no secret, so `{"pass": true}` is kept in both
    modes. `payment_authorization` ends in `authorization`, so a tree (structured data, not prose) fails closed on it;
    the prose line "Payment Authorization: approved" is kept because its value is not credential-shaped."""
    assert redact_value({"pass": True}) == {"pass": True} and redact('{"pass": true}') == '{"pass": true}'
    assert redact_value({"pass": "x"}) == {"pass": REDACTED} == json.loads(redact('{"pass": "x"}'))
    assert redact_value({"payment_authorization": "approved"}) == {"payment_authorization": REDACTED}
    assert json.loads(redact('{"payment_authorization": "approved"}')) == {"payment_authorization": REDACTED}


@pytest.mark.parametrize("key", ["password", "Authorization", "token", "pass"])
def test_FR_MEM_05_a_collision_key_is_a_fixed_point(key):
    for text in (f"{key}=[REDACTED]#2", f"{key}: [REDACTED]#2", f"{key}: {REDACTED} (ends 1111)#3"):
        assert redact(text) == text
    first, second = f"{key}={SECRET}", f"{key}={SECRET[::-1]}"
    tree = redact_value({first: 1, second: 2})
    assert len(tree) == 2 and redact_value(tree) == tree


def test_FR_MEM_05_a_card_typed_as_a_json_number_becomes_a_string_and_the_json_stays_valid():
    out = redact(json.dumps({"pan": int(CARD), "n": 1}))
    assert json.loads(out) == {"pan": f"{REDACTED} (ends 1111)", "n": 1}
    assert redact(f"paid with {CARD} today") == f"paid with {REDACTED} (ends 1111) today"


def test_FR_MEM_05_a_log_record_extra_field_named_like_a_secret_loses_its_value():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s %(password)s %(apiKey)s %(user)s"))
    handler.addFilter(RedactingFilter())
    logger = logging.Logger("fr_mem_05_extra_names", logging.DEBUG)
    logger.addHandler(handler)
    logger.info("login", extra={"password": "hunter2plain", "apiKey": "plainwords", "user": "ann"})
    assert stream.getvalue() == f"login {REDACTED} {REDACTED} ann\n"


def test_FR_MEM_05_known_shapes_still_go_inside_json_strings():
    token = build("google_oauth_access", FIXED_TAIL).text
    out = redact(json.dumps({"headers": f"Authorization: Bearer {token}\r\nAccept: x", "n": 1}))
    assert token not in out and json.loads(out)["n"] == 1 and "Accept: x" in json.loads(out)["headers"]
