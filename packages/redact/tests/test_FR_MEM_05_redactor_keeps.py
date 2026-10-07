"""FR-MEM-05 / SEC-14: the shared redactor keeps what is not a secret, and is deterministic and idempotent.

It is also the scanner behind MF-06, the `label` rule (ADR-0018) and handoff excerpts: "the redactor would change
this" means "refuse", so over-redaction breaks real runs. Decisions where PRD 13.2 and 16.2 are silent:
  - Emails and phone numbers are kept. PRD 16.1 rule 4 is about secrets (tokens, passwords, credentials, card
    numbers); recipients and message bodies are the data the archive exists to hold (13.2). The live-e2e scrub of
    emails and phones is about publishing a recording, a different threat, and stays its own.
  - A digit run is a card only when it is 13 to 19 digits, passes Luhn and is not touching a letter or digit
    (so sha256 digests, ids and ULIDs are safe); a Luhn-failing 16-digit number (order, tracking, epoch-ms ids)
    is kept. Numbers typed as JSON numbers are kept; only text is scanned.
  - Added by the builder (BQ-FRMEM05-1): a plain 13-digit number from 1500000000000 to 1999999999999 is an
    epoch-millisecond timestamp and is kept even when it passes Luhn (about 10% do); a run starting with 0 is no card.
"""

from __future__ import annotations

import copy
import hashlib

from _redact_samples_lib import FIXED_TAIL, KINDS, TAIL, build, card_number, luhn_complete
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_redact import REDACTED, redact, redact_value

WORDS = [
    "Summarise",
    "the",
    "quarter",
    "report",
    "for",
    "Harrier",
    "Logistics",
    "then",
    "send",
    "a",
    "draft",
    "to",
    "us",
]
ULID = st.text(alphabet="0123456789ABCDEFGHJKMNPQRSTVWXYZ", min_size=26, max_size=26)
BENIGN = st.one_of(
    st.sampled_from(WORDS),
    st.builds("{}_{}".format, st.sampled_from(["w", "r", "u", "org", "art", "gate"]), ULID),  # ids
    ULID,
    st.binary(min_size=32, max_size=32).map(lambda b: hashlib.sha256(b).hexdigest()),  # content_sha256
    st.dates().map(lambda d: d.isoformat()),
    st.integers(0, 10**12 - 1).map(str),  # up to 12 digits
    st.builds("${:,}.{:02d}".format, st.integers(0, 10**6), st.integers(0, 99)),
    st.sampled_from(
        ["ops@harrier-logistics.example", "+65 6123 4567", "https://example.com/a/b?page=2", "max_output_tokens: 1024"]
    ),
)


@settings(max_examples=200, deadline=None)
@given(st.lists(BENIGN, min_size=1, max_size=12))
def test_FR_MEM_05_property_text_with_no_secret_is_unchanged(pieces):
    text = " ; ".join(pieces)  # not a space: "1234 5678 9012 3456" side by side would be a card
    assert redact(text) == text


def test_FR_MEM_05_a_16_digit_number_that_fails_luhn_is_kept():
    _, digits = card_number(FIXED_TAIL)
    bad = digits[:-1] + str((int(digits[-1]) + 1) % 10)
    assert redact(f"order {bad} shipped") == f"order {bad} shipped"


def test_FR_MEM_05_a_luhn_valid_epoch_ms_timestamp_is_kept():
    ms = luhn_complete("178123456789")  # 13 digits from 17...: an epoch-millisecond timestamp that happens to pass Luhn
    assert len(ms) == 13 and ms.startswith("17")
    for text in (ms, f"created_at {ms} by u_01HZ", f'{{"ts": {ms}, "note": "ts={ms}"}}'):
        assert redact(text) == text


def test_FR_MEM_05_a_zero_led_luhn_run_and_a_long_decimal_are_kept():
    zeros, fraction = "0" * 16, luhn_complete("411111111111111")  # Luhn-valid, but after a decimal point
    assert redact(f"id {zeros} and 0.{fraction} done") == f"id {zeros} and 0.{fraction} done"


def test_SEC_14_usage_and_authorisation_records_are_not_secure_fields():
    tree = {
        "usage": {"input_tokens": 12, "output_tokens": 3, "cached_tokens": 1, "max_output_tokens": 50},
        "authz": {"by": "u_01HZ", "tier": "T3", "at": "2026-10-07T09:30:00.000Z"},
        "ok": True,
        "none": None,
        "to": "ops@harrier-logistics.example",
    }
    before = copy.deepcopy(tree)
    assert redact_value(tree) == before
    assert tree == before  # the input is not changed


def test_FR_MEM_05_redact_value_redacts_every_string_of_a_tree_and_keeps_its_shape():
    secret = build("google_oauth_access", FIXED_TAIL).text
    out = redact_value({"a": [f"x {secret}", {"b": f"y {secret}"}], "n": 1.5})
    assert set(out) == {"a", "n"} and out["n"] == 1.5 and isinstance(out["a"][1], dict)
    assert secret not in repr(out) and out["a"][0].startswith("x ") and REDACTED in out["a"][0]


@settings(max_examples=100, deadline=None)
@given(kind=st.sampled_from(sorted(KINDS)), tail=TAIL, before=st.lists(st.sampled_from(WORDS), max_size=5))
def test_FR_MEM_05_property_redaction_is_deterministic_and_idempotent(kind, tail, before):
    text = " ".join([*before, build(kind, tail).text, "done"])
    once = redact(text)
    assert redact(text) == once
    assert redact(once) == once
    tree = {"k": [text, {"password": text}]}
    assert redact_value(redact_value(tree)) == redact_value(tree) == redact_value(copy.deepcopy(tree))
