"""FR-MEM-05 / SEC-14 (PRD 13.2, 16.1 rule 4, 16.2): the shared secret redactor removes every kind of secret.

Pinned names (builder: make these exist). New leaf package `packages/redact`, import name `tilo_redact`, standard
library only, so providers, archive, memory, api, connectors, harness, evals and logging can all depend on it without
a cycle (`tilo_archive` has no business under a logger or a model call; nothing today is shared, see the report).
    redact(text: str) -> str          the `Callable[[str], str]` that `deps.get_redactor()` returns
    redact_value(obj) -> obj          the same over a JSON tree, new tree, keys and values; `RunArchive`'s redactor
    REDACTED == "[REDACTED]"          what a removed secret leaves behind (the stand-ins already use it)
Decisions where the PRD is silent: a removed secret leaves REDACTED (so a reader knows); a card keeps at most its
last four digits; a PEM block with no END line is removed to the end of the text; "secure fields" are keys named
exactly (case-insensitive) password, secret, token, access_token, refresh_token, client_secret, api_key,
authorization, cookie, and the whole value goes whatever it holds.
"""

from __future__ import annotations

import pytest
from _redact_samples_lib import FIXED_TAIL, KINDS, PROSE, SECRET_SCAN, TAIL, build, leaks, scan_hits
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_redact import REDACTED, redact, redact_value

SECURE_KEYS = [
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "api_key",
    "authorization",
    "cookie",
]


def test_FR_MEM_05_marker_is_the_pinned_constant():
    assert REDACTED == "[REDACTED]"


def test_FR_MEM_05_every_secret_scan_pattern_has_a_sample_and_none_survives():
    hit = {label for kind in KINDS for label in scan_hits(build(kind, FIXED_TAIL).text)}
    assert hit == {label for _, label in SECRET_SCAN.SECRET_PATTERNS}, "a scripts/secret_scan.py pattern has no sample"
    survivors = {kind: scan_hits(redact(build(kind, FIXED_TAIL).text)) for kind in KINDS}
    assert {k: v for k, v in survivors.items() if v} == {}


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_FR_MEM_05_each_kind_of_secret_is_removed(kind):
    sample = build(kind, FIXED_TAIL)
    out = redact(f"Please use this:\n{sample.text}\nand carry on.")
    assert leaks(out, sample) == [], out
    assert "Please use this:" in out
    assert kind == "pem_unterminated" or "and carry on." in out  # only the secret goes, not the text around it
    if sample.card is None:
        assert REDACTED in out


@pytest.mark.parametrize("key", SECURE_KEYS)
@pytest.mark.parametrize(
    "value", ["plain words", 12345, {"nested": "x", "n": [1, 2]}, ["a", "b"]], ids=["str", "int", "dict", "list"]
)
def test_SEC_14_secure_field_values_are_replaced_whatever_they_hold(key, value):
    assert redact_value({key: value}) == {key: REDACTED}
    assert redact_value({key.upper(): value}) == {key.upper(): REDACTED}


def test_SEC_14_secure_fields_are_found_deep_and_their_neighbours_are_kept():
    tree = {"calls": [{"headers": {"Authorization": "abc", "Accept": "json"}, "usage": {"input_tokens": 12}}], "n": 3}
    assert redact_value(tree) == {
        "calls": [{"headers": {"Authorization": REDACTED, "Accept": "json"}, "usage": {"input_tokens": 12}}],
        "n": 3,
    }


def test_SEC_14_a_secret_used_as_a_key_is_removed_too():
    sample = build("google_oauth_access", FIXED_TAIL)
    assert leaks(" ".join(redact_value({sample.text: 1})), sample) == []


@settings(max_examples=150, deadline=None)
@given(kind=st.sampled_from(sorted(KINDS)), tail=TAIL, before=PROSE, after=PROSE)
def test_FR_MEM_05_property_a_secret_embedded_in_random_text_never_survives(kind, tail, before, after):
    sample = build(kind, tail)
    tree = redact_value([before, {"k": sample.text}, after])
    for out in (redact(f"{before} {sample.text} {after}"), tree[1]["k"]):
        assert leaks(out, sample) == []
        assert scan_hits(out) == []
