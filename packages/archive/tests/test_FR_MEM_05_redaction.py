"""Acceptance tests for FR-MEM-05 ("Secrets never reach the archive, logs or
prompts" -- acceptance test "Secret scanner over a full eval pass finds 0
tokens or passwords") and the redaction/encryption part of SEC-14 ("Raw
archive redaction and encryption" -- "Archive sample contains no tokens,
secure fields or full card numbers"). PRD 13.2, 16.1 rule 4, 16.4.

Every fake secret used here is assembled at runtime (random suffixes,
computed Luhn digits, base64-encoded fake JWT claims, string fragments
joined at call time) so no literal secret -- real or realistic-looking --
ever sits contiguously in this file's source text; root CLAUDE.md: "Fake
secrets for tests are assembled at runtime."

`tilo_archive` does not exist yet, so this file fails to collect with an
ImportError until the builder lands it.
"""

from __future__ import annotations

import json
import logging
import random
import sys
import time

import pytest
from conftest import (
    ORG_ID,
    RUN_ID,
    FakeClock,
    fake_bearer_header,
    fake_jwt,
    fake_luhn_card,
    fake_non_luhn_number,
    is_luhn_valid,
    load_secret_scan,
    rand_token,
    with_separator,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_archive import redact as redact_mod
from tilo_archive.archive import LocalDirStore, RunArchive

RNG = random.Random(20260925)  # fixed seed: deterministic, still not literal secret text

_URLSAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

SECRET_SCAN = load_secret_scan()


def _fake_private_key_marker() -> str:
    # Built from fragments so the contiguous matching text never appears in
    # this file's own source (the pre-commit secret scan would otherwise
    # flag this file, even though the value is synthetic).
    return "-----BEGIN " + "RSA " + "PRIVATE KEY" + "-----"


def _fake_service_account_marker() -> str:
    return '"' + "type" + '"' + ": " + '"' + "service_account" + '"'


# One fake-secret builder per scripts/secret_scan.py pattern, in the same
# order as SECRET_SCAN.SECRET_PATTERNS, built purely at runtime.
FAKE_SECRET_BUILDERS = {
    "a private key": _fake_private_key_marker,
    "a Google API key": lambda: "AIza" + rand_token(RNG, 35),
    "a Google OAuth access token": lambda: "ya29." + rand_token(RNG, 24, _URLSAFE),
    "a Google OAuth refresh token": lambda: "1//0" + rand_token(RNG, 34, _URLSAFE),
    "an API secret key": lambda: "sk-" + rand_token(RNG, 24),
    "a GitHub token": lambda: "ghp_" + rand_token(RNG, 36),
    "a Meta / WhatsApp access token": lambda: "EAA" + rand_token(RNG, 64),
    "an NVIDIA NIM API key": lambda: "nvapi-" + rand_token(RNG, 24, _URLSAFE),
    "a service account key": _fake_service_account_marker,
}

SECRET_SCAN_CASES = [(label, pattern, FAKE_SECRET_BUILDERS[label]) for pattern, label in SECRET_SCAN.COMPILED]


def test_FR_MEM_05_secret_scan_has_all_nine_patterns_covered():
    # Guards the parametrised test below against scripts/secret_scan.py
    # gaining or losing a pattern without this file noticing.
    assert len(SECRET_SCAN.SECRET_PATTERNS) == 9
    assert len(SECRET_SCAN_CASES) == 9


@pytest.mark.parametrize("label,pattern,build", SECRET_SCAN_CASES, ids=[c[0] for c in SECRET_SCAN_CASES])
def test_FR_MEM_05_redact_removes_each_secret_scan_pattern(label, pattern, build):
    secret = build()
    assert pattern.search(secret), f"builder for {label!r} does not match scripts/secret_scan.py's own pattern"

    payload = {"note": f"leaked value here: {secret} end of note"}
    redacted = redact_mod.redact(payload)
    text = json.dumps(redacted)

    assert secret not in text
    assert "[REDACTED:" in text


def test_FR_MEM_05_find_secrets_lists_kinds_found():
    key = "AIza" + rand_token(RNG, 35)
    kinds = redact_mod.find_secrets(f"config key={key}")
    assert isinstance(kinds, list)
    assert kinds


def test_FR_MEM_05_find_secrets_empty_for_clean_text():
    assert redact_mod.find_secrets("nothing sensitive here, just plain prose.") == []


def test_FR_MEM_05_redact_removes_bearer_token():
    header, token = fake_bearer_header(RNG)
    redacted = redact_mod.redact({"auth_header": header})
    text = json.dumps(redacted)
    assert token not in text
    assert "[REDACTED:" in text


def test_FR_MEM_05_redact_removes_jwt():
    jwt = fake_jwt(RNG)
    redacted = redact_mod.redact({"cookie_value": jwt})
    text = json.dumps(redacted)
    assert jwt not in text
    assert "[REDACTED:" in text


# ---------------------------------------------------------------------------
# Payment card numbers: 13-19 digits, spaces or dashes allowed, Luhn-valid,
# replaced so only the last 4 digits remain. A Luhn-invalid number the same
# shape as a card (e.g. an order number) is left alone.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("length", [13, 16, 19])
@pytest.mark.parametrize("separator", ["", " ", "-"])
def test_FR_MEM_05_redact_masks_luhn_valid_card_to_last_4(length, separator):
    card = fake_luhn_card(RNG, length=length)
    formatted = with_separator(card, separator) if separator else card
    last4 = card[-4:]

    redacted = redact_mod.redact({"card_number": formatted})
    text = json.dumps(redacted)

    assert card not in text
    assert f"[REDACTED:card ****{last4}]" in text


def test_FR_MEM_05_redact_leaves_luhn_invalid_order_number_alone():
    order_number = fake_non_luhn_number(RNG, length=16)
    assert not is_luhn_valid(order_number)

    payload = {"order_number": order_number}
    redacted = redact_mod.redact(payload)

    assert redacted == payload
    assert redacted["order_number"] == order_number


# ---------------------------------------------------------------------------
# Secret-named keys, several nesting depths and letter cases.
# ---------------------------------------------------------------------------


def test_FR_MEM_05_redact_secret_named_keys_various_depths_and_case():
    secret_value = rand_token(RNG, 24)
    payload = {
        "Password": secret_value,
        "level1": {
            "API_KEY": secret_value,
            "level2": {
                "Authorization": secret_value,
                "level3": [
                    {"cookie": secret_value, "PIN": secret_value, "refresh_token": secret_value},
                ],
            },
        },
    }

    redacted = redact_mod.redact(payload)
    text = json.dumps(redacted)

    assert secret_value not in text
    assert redacted["Password"] != secret_value
    assert redacted["level1"]["API_KEY"] != secret_value
    assert redacted["level1"]["level2"]["Authorization"] != secret_value
    inner = redacted["level1"]["level2"]["level3"][0]
    assert inner["cookie"] != secret_value
    assert inner["PIN"] != secret_value
    assert inner["refresh_token"] != secret_value


def test_FR_MEM_05_redact_does_not_touch_unrelated_keys():
    payload = {"username": "not-a-secret", "count": 3, "notes": "fine to keep"}
    assert redact_mod.redact(payload) == payload


# ---------------------------------------------------------------------------
# Scan caps: oversize text is replaced whole (fail closed); a long
# adversarial string stays linear-time.
# ---------------------------------------------------------------------------


def test_FR_MEM_05_max_scan_chars_constant_is_one_million():
    assert redact_mod.MAX_SCAN_CHARS == 1_000_000


def test_FR_MEM_05_oversize_text_replaced_whole():
    text = "a" * 2_000_000
    assert redact_mod.redact(text) == "[REDACTED:oversize]"


def test_FR_MEM_05_adversarial_text_redacted_under_two_seconds():
    charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@"
    text = "".join(RNG.choice(charset) for _ in range(900_000))

    start = time.perf_counter()
    redact_mod.redact(text)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"redact() took {elapsed:.2f}s on a 900,000-char adversarial string"


# ---------------------------------------------------------------------------
# Depth cap: nesting beyond 64 becomes a "too_deep" marker; redact never
# raises on odd JSON-like input (explicit cases plus a property test).
# ---------------------------------------------------------------------------


def test_FR_MEM_05_deep_nesting_becomes_too_deep_marker():
    value: object = "leaf"
    for _ in range(100):
        value = {"n": value}

    redacted = redact_mod.redact(value)

    node = redacted
    steps = 0
    while isinstance(node, dict) and "n" in node:
        node = node["n"]
        steps += 1
        assert steps <= 70, "never hit the too_deep marker"
    assert node == "[REDACTED:too_deep]"
    assert steps <= 65


def test_FR_MEM_05_redact_handles_nan_and_infinity_without_raising():
    # NaN/infinities are rejected by the archive writer, not the redactor
    # (brief REQUIRED BEHAVIOUR #2) -- redact() itself must not raise.
    redact_mod.redact(float("nan"))
    redact_mod.redact(float("inf"))
    redact_mod.redact({"x": float("nan"), "y": [float("inf"), float("-inf")]})


def test_FR_MEM_05_redact_handles_non_str_dict_keys_without_raising():
    redact_mod.redact({1: "one", None: "none", "flag": True})


_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**9), max_value=10**9),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=20),
)
_odd_keys = st.one_of(st.text(max_size=10), st.integers(), st.none(), st.booleans())
_odd_json_like = st.recursive(
    _json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(_odd_keys, children, max_size=4),
    ),
    max_leaves=25,
)


@given(_odd_json_like)
@settings(max_examples=60, deadline=None)
def test_FR_MEM_05_redact_never_raises_on_odd_json_like_input(value):
    redact_mod.redact(value)  # must not raise, whatever the shape


# ---------------------------------------------------------------------------
# redact_prompt and RedactingFilter.
# ---------------------------------------------------------------------------


def test_FR_MEM_05_redact_prompt_removes_secret_from_text():
    secret = "ghp_" + rand_token(RNG, 36)
    prompt = f"System: here is the token to use: {secret} -- call the tool with it."

    redacted_prompt = redact_mod.redact_prompt(prompt)

    assert secret not in redacted_prompt
    assert "[REDACTED:" in redacted_prompt
    assert isinstance(redacted_prompt, str)


def test_FR_MEM_05_redacting_filter_removes_secret_passed_as_log_arg():
    secret = "sk-" + rand_token(RNG, 24)
    record = logging.LogRecord(
        name="tilo.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="calling provider with token=%s",
        args=(secret,),
        exc_info=None,
    )

    f = redact_mod.RedactingFilter()
    kept = f.filter(record)

    assert kept  # RedactingFilter redacts in place, it does not drop the record
    message = record.getMessage()
    assert secret not in message
    assert "[REDACTED:" in message


def test_FR_MEM_05_redacting_filter_redacts_msg_without_args():
    secret = "nvapi-" + rand_token(RNG, 24, _URLSAFE)
    record = logging.LogRecord(
        name="tilo.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=f"provider key was {secret}",
        args=(),
        exc_info=None,
    )

    redact_mod.RedactingFilter().filter(record)

    assert secret not in record.getMessage()


# ---------------------------------------------------------------------------
# SEC-14: after RunArchive.append, no fake secret survives anywhere in the
# stored JSONL, and scripts/secret_scan.py's own scan logic finds nothing.
# ---------------------------------------------------------------------------


def test_FR_MEM_05_SEC_14_archive_append_redacts_every_secret_kind(tmp_path):
    secrets_used: list[str] = []
    payload: dict = {}

    for pattern, label in SECRET_SCAN.SECRET_PATTERNS:
        secret = FAKE_SECRET_BUILDERS[label]()
        secrets_used.append(secret)
        payload[label.replace(" ", "_").replace("/", "_")] = f"value: {secret}"

    bearer_header, bearer_token = fake_bearer_header(RNG)
    jwt = fake_jwt(RNG)
    card = fake_luhn_card(RNG)

    payload["auth_header"] = bearer_header
    payload["session_jwt"] = jwt
    payload["card_number"] = with_separator(card, " ")
    payload["nested"] = {"deep": {"password": rand_token(RNG, 16)}}

    secrets_used.append(bearer_token)
    secrets_used.append(jwt)
    secrets_used.append(card)
    secrets_used.append(payload["nested"]["deep"]["password"])

    store = LocalDirStore(tmp_path)
    archive = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())
    archive.append("model_call", payload)

    jsonl_path = tmp_path / ORG_ID / f"{RUN_ID}.jsonl"
    raw_text = jsonl_path.read_text(encoding="utf-8")

    for secret in secrets_used:
        assert secret not in raw_text, f"a fake secret survived in the stored archive: {secret!r}"

    findings = SECRET_SCAN.scan_file(str(jsonl_path))
    assert findings == []


# ---------------------------------------------------------------------------
# Fix-round-1 regression pins (code-reviewer, security-reviewer, qa-breaker).
# ---------------------------------------------------------------------------


def test_FR_MEM_05_tuple_payload_value_is_redacted(tmp_path):
    # code-reviewer: _redact_value walked only dict and list, so a tuple went
    # back unchanged and json.dumps serialised it as a JSON array in clear
    # text -- FR-MEM-05 / SEC-14. A tuple must be redacted the same as list.
    token = "ghp_" + rand_token(RNG, 36)
    header, bearer_token = fake_bearer_header(RNG)
    payload = {"t": (token, header)}

    store = LocalDirStore(tmp_path)
    archive = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())
    archive.append("tool_call", payload)

    jsonl_path = tmp_path / ORG_ID / f"{RUN_ID}.jsonl"
    stored_line = jsonl_path.read_text(encoding="utf-8")

    assert token not in stored_line
    assert bearer_token not in stored_line
    assert "[REDACTED:" in stored_line
    stored = json.loads(stored_line)
    assert stored["payload"]["t"] == ["[REDACTED:github_token]", "[REDACTED:bearer_token]"]


@pytest.mark.parametrize(
    "text",
    [
        "a-" * 500_000,
        "a." * 500_000,
        "".join(
            random.Random(1).choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._")
            for _ in range(1_000_000)
        ),
    ],
    ids=["hyphen-boundary", "dot-boundary", "mixed-1mb"],
)
def test_FR_MEM_05_jwt_pattern_is_linear_time_on_boundary_dense_input(text):
    # security-reviewer / qa-breaker: the old JWT pattern backtracked
    # quadratically on text with a word boundary at nearly every position.
    start = time.perf_counter()
    redact_mod.redact({"m": text})
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"redact() took {elapsed:.2f}s on a boundary-dense string"


def test_FR_MEM_05_dict_key_text_is_scanned_for_secret_patterns():
    # security-reviewer: dict keys were never scanned, only checked against
    # the secret-name markers -- a credential pattern embedded in a key with
    # no marker substring in its name (e.g. a trace id built from a leaked
    # JWT) survived untouched.
    jwt = fake_jwt(RNG)
    key = f"trace-{jwt}"
    assert not any(marker in key.lower() for marker in ("password", "secret", "token", "cookie", "pin"))
    payload = {key: "fine"}

    redacted = redact_mod.redact(payload)
    text = json.dumps(redacted)

    assert jwt not in text
    assert key not in redacted
    assert any("[REDACTED:" in str(k) for k in redacted)


def test_FR_MEM_05_redacting_filter_redacts_dict_arg_secret_keys():
    # security-reviewer: RedactingFilter only redacted str args; a dict arg's
    # secret-named keys (and nested values) leaked untouched. (A LogRecord
    # constructed with a single mapping arg stores it as `record.args`
    # directly, not wrapped in a tuple -- stdlib logging's %-dict support.)
    secret = rand_token(RNG, 24)
    record = logging.LogRecord(
        name="tilo.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="calling provider with %(api_key)s",
        args={"api_key": secret, "nested": {"password": secret}},
        exc_info=None,
    )
    assert isinstance(record.args, dict)  # confirms the stdlib collapsing above

    redact_mod.RedactingFilter().filter(record)

    assert record.args["api_key"] != secret
    assert record.args["nested"]["password"] != secret


def test_FR_MEM_05_redacting_filter_redacts_exc_info_traceback():
    # security-reviewer: RedactingFilter never looked at exc_info, so a
    # secret in an exception message survived in the rendered traceback.
    secret = "sk-" + rand_token(RNG, 24)
    try:
        raise ValueError(f"provider call failed, token={secret}")
    except ValueError:
        record = logging.LogRecord(
            name="tilo.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="provider error",
            args=(),
            exc_info=sys.exc_info(),
        )

    redact_mod.RedactingFilter().filter(record)

    formatter = logging.Formatter()
    rendered = formatter.format(record)
    assert secret not in rendered
    assert record.exc_info is None


@pytest.mark.parametrize(
    "build_text",
    [
        lambda card: f"{with_separator(card, ' ')} 123",  # trailing CVV
        lambda card: f"{with_separator(card, ' ')} 12/28",  # trailing expiry
        lambda card: f"2 {with_separator(card, ' ')}",  # leading stray digit
    ],
    ids=["trailing-cvv", "trailing-expiry", "leading-stray-digit"],
)
def test_FR_MEM_05_card_redacted_despite_adjacent_noise_digits(build_text):
    # security-reviewer / qa-breaker: the card regex greedily joined
    # adjacent digit groups, so a real card followed by a CVV/expiry, or
    # preceded by a stray digit, was left whole (Luhn failed on the joined
    # digit string) instead of being found and redacted.
    card = fake_luhn_card(RNG, length=16)
    text = build_text(card)

    redacted = redact_mod.redact({"note": text})["note"]

    assert card not in redacted
    assert f"[REDACTED:card ****{card[-4:]}]" in redacted


def test_FR_MEM_05_bearer_token_matches_json_quoted_header():
    # security-reviewer: a JSON-quoted "Authorization": "Bearer x" field was
    # not matched by a pattern anchored to the literal "Authorization:" form.
    token = rand_token(RNG, 40, _URLSAFE)
    payload = {"raw_request": f'{{"Authorization": "Bearer {token}"}}'}

    redacted = redact_mod.redact(payload)

    assert token not in json.dumps(redacted)
    assert "[REDACTED:bearer_token]" in redacted["raw_request"]


def test_FR_MEM_05_bearer_token_charset_includes_rfc6750_extras():
    # security-reviewer: the bearer charset omitted RFC 6750's + / ~, so part
    # of a token using them stayed in clear text.
    token = rand_token(RNG, 30, _URLSAFE) + "+/~" + rand_token(RNG, 10, _URLSAFE)
    header = f"Authorization: Bearer {token}"

    redacted = redact_mod.redact_prompt(header)

    assert token not in redacted
    assert "[REDACTED:bearer_token]" in redacted


def test_FR_MEM_05_find_secrets_fails_closed_on_oversize_text():
    # security-reviewer: find_secrets returned [] for oversize input, the
    # opposite of fail-closed (an empty list reads as "nothing found").
    kinds = redact_mod.find_secrets("a" * (redact_mod.MAX_SCAN_CHARS + 1))
    assert kinds == ["oversize"]
