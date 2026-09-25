"""Acceptance tests pinning ticket FR-MEM-04/05 review round 2, change 1:
"the private-key redaction covers the whole PEM block, not just the header"
(PRD 13.2 "with secrets removed", 16.1 rule 4 "Secrets never enter prompts,
logs, traces, the raw archive", 16.4 SEC-14 "Raw archive redaction and
encryption -- Archive sample contains no tokens, secure fields or full card
numbers").

Before this round, `redact()` only needed to make `scripts/secret_scan.py`'s
header-only pattern (`-----BEGIN [A-Z ]*PRIVATE KEY-----`) stop matching --
see `test_FR_MEM_05_redact_removes_each_secret_scan_pattern` in
test_FR_MEM_05_redaction.py, which never inspects the base64 body or the END
line. These tests close that gap: the full block (header through the
matching END line, or to the end of the string value when there is no END
line) must be gone from every place redaction runs -- archive payloads,
RedactingFilter log lines and redact_prompt -- including a PEM quoted inside
a JSON string with literal "\\n" escapes (a service-account key file's
private_key field), and private_key_id must be treated as a secret-named key.

Every fake key here is built at runtime from fragments (conftest.py's
build_pem_block / build_service_account_payload) so no PEM-shaped text is
ever contiguous in this file's own source -- root CLAUDE.md: "Fake secrets
for tests are assembled at runtime."

`tilo_archive` does not exist yet, so this file fails to collect with an
ImportError until the builder lands it -- the expected "fail for the right
reason" state for a test-writer ticket (root CLAUDE.md ticket loop).
"""

from __future__ import annotations

import json
import logging
import random
import time

import pytest
from conftest import (
    ORG_ID,
    PEM_TYPE_WORDS,
    RUN_ID,
    FakeClock,
    build_pem_block,
    build_service_account_payload,
    load_secret_scan,
    rand_token,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_archive import redact as redact_mod
from tilo_archive.archive import LocalDirStore, RunArchive

RNG = random.Random(20260925)  # fixed seed: deterministic, still not literal secret text

SECRET_SCAN = load_secret_scan()

# ---------------------------------------------------------------------------
# Full block redaction, every PEM type word, through RunArchive.append.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("type_word", PEM_TYPE_WORDS, ids=[w or "generic" for w in PEM_TYPE_WORDS])
def test_FR_MEM_05_archive_append_strips_whole_pem_block_body_and_end(tmp_path, type_word):
    block, body_lines = build_pem_block(RNG, type_word, n_lines=6, include_end=True)
    before = "call started, credentials attached below:"
    after = "end of credentials, nothing else follows."
    payload = {"config_text": f"{before}\n{block}\n{after}"}

    store = LocalDirStore(tmp_path)
    archive = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())
    archive.append("model_call", payload)

    jsonl_path = tmp_path / ORG_ID / f"{RUN_ID}.jsonl"
    raw_text = jsonl_path.read_text(encoding="utf-8")

    for line in body_lines:
        assert line not in raw_text, f"PEM body line survived in the archive for type={type_word!r}"
    end_dashes_label = "-" * 5 + "END"
    assert end_dashes_label not in raw_text, f"PEM END line survived in the archive for type={type_word!r}"
    assert before in raw_text, "text before the PEM block must survive"
    assert after in raw_text, "text after the PEM block's END line must survive"
    assert "[REDACTED:" in raw_text


@pytest.mark.parametrize("type_word", PEM_TYPE_WORDS, ids=[w or "generic" for w in PEM_TYPE_WORDS])
def test_FR_MEM_05_redact_strips_whole_pem_block_body_and_end(type_word):
    block, body_lines = build_pem_block(RNG, type_word, n_lines=6, include_end=True)
    before = "keep this prefix"
    after = "keep this suffix"
    payload = {"note": f"{before} {block} {after}"}

    redacted = redact_mod.redact(payload)
    text = json.dumps(redacted)

    for line in body_lines:
        assert line not in text
    assert ("-" * 5 + "END") not in text
    assert before in text
    assert after in text
    assert "[REDACTED:" in text


# ---------------------------------------------------------------------------
# No END line: redact from BEGIN to the end of the string value (fail closed).
# ---------------------------------------------------------------------------


def test_FR_MEM_05_truncated_pem_with_no_end_line_redacts_to_end_of_value():
    block, body_lines = build_pem_block(RNG, "RSA", n_lines=6, include_end=False)
    before = "prefix text stays"
    trailing = "this text has nothing to do with the key but sits after it in the same string"
    payload = {"leaked": f"{before} {block} {trailing}"}

    redacted = redact_mod.redact(payload)
    text = json.dumps(redacted)

    assert before in text
    for line in body_lines:
        assert line not in text
    assert trailing not in text, "everything after a truncated BEGIN, in the same value, must fail closed"
    assert "[REDACTED:" in text


def test_FR_MEM_05_truncated_pem_at_very_end_of_value_redacts_cleanly():
    block, body_lines = build_pem_block(RNG, "EC", n_lines=4, include_end=False)
    before = "prefix text stays"
    payload = {"leaked": f"{before} {block}"}

    redacted = redact_mod.redact(payload)
    text = json.dumps(redacted)

    assert before in text
    for line in body_lines:
        assert line not in text
    assert "[REDACTED:" in text


# ---------------------------------------------------------------------------
# PEM quoted inside a JSON string with literal "\n" escapes -- a
# service-account key file's private_key field. private_key_id is a
# secret-named key too.
# ---------------------------------------------------------------------------


def test_FR_MEM_05_service_account_private_key_with_escaped_newlines_is_redacted():
    payload, body_lines, key_id = build_service_account_payload(RNG)

    redacted = redact_mod.redact(payload)
    text = json.dumps(redacted)

    for line in body_lines:
        assert line not in text, "an escaped-newline PEM body line survived redaction"
    assert key_id not in text, "private_key_id must be treated as a secret-named key"
    assert redacted["private_key"] != payload["private_key"]
    assert redacted["private_key_id"] != payload["private_key_id"]
    # Non-secret fields of the service-account-shaped payload are untouched.
    assert redacted["project_id"] == payload["project_id"]
    assert redacted["client_email"] == payload["client_email"]


def test_FR_MEM_05_service_account_key_survives_nowhere_in_stored_archive(tmp_path):
    payload, body_lines, key_id = build_service_account_payload(RNG)

    store = LocalDirStore(tmp_path)
    archive = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())
    archive.append("model_call", {"credentials": payload})

    jsonl_path = tmp_path / ORG_ID / f"{RUN_ID}.jsonl"
    raw_text = jsonl_path.read_text(encoding="utf-8")

    for line in body_lines:
        assert line not in raw_text
    assert key_id not in raw_text

    findings = SECRET_SCAN.scan_file(str(jsonl_path))
    assert findings == []


# ---------------------------------------------------------------------------
# private_key_id joins the secret-named keys, independent of any PEM value.
# ---------------------------------------------------------------------------


def test_FR_MEM_05_private_key_id_redacted_as_secret_named_key():
    key_id = rand_token(RNG, 40, "0123456789abcdef")
    payload = {"private_key_id": key_id, "count": 3}

    redacted = redact_mod.redact(payload)

    assert redacted["private_key_id"] != key_id
    assert redacted["count"] == 3
    text = json.dumps(redacted)
    assert key_id not in text


# ---------------------------------------------------------------------------
# RedactingFilter (formatted log line) and redact_prompt also strip the
# whole block, not just the header.
# ---------------------------------------------------------------------------


def test_FR_MEM_05_redacting_filter_strips_whole_pem_block_from_log_line():
    block, body_lines = build_pem_block(RNG, "OPENSSH", n_lines=5, include_end=True)
    record = logging.LogRecord(
        name="tilo.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="provider auth failed, key was: %s",
        args=(block,),
        exc_info=None,
    )

    kept = redact_mod.RedactingFilter().filter(record)

    assert kept
    message = record.getMessage()
    for line in body_lines:
        assert line not in message
    assert ("-" * 5 + "END") not in message
    assert "[REDACTED:" in message


def test_FR_MEM_05_redact_prompt_strips_whole_pem_block():
    block, body_lines = build_pem_block(RNG, "DSA", n_lines=5, include_end=True)
    prompt = f"System: here is the signing key to use: {block} -- call the tool with it."

    redacted_prompt = redact_mod.redact_prompt(prompt)

    for line in body_lines:
        assert line not in redacted_prompt
    assert ("-" * 5 + "END") not in redacted_prompt
    assert "[REDACTED:" in redacted_prompt


# ---------------------------------------------------------------------------
# Linear-time and bounded: a 1,000,000-char adversarial string of repeated
# "-----BEGIN " fragments and base64-like runs redacts in under 2 seconds.
# ---------------------------------------------------------------------------


def test_SEC_14_adversarial_pem_like_one_million_chars_redacted_under_two_seconds():
    charset = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    begin_fragment = "-" * 5 + "BEGIN "  # never followed by a literal type word + "PRIVATE KEY" + dashes here
    chunk = begin_fragment + "".join(RNG.choice(charset) for _ in range(39))
    repeats = (1_000_000 // len(chunk)) + 1
    text = (chunk * repeats)[:1_000_000]
    assert len(text) == 1_000_000

    start = time.perf_counter()
    redact_mod.redact(text)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"redact() took {elapsed:.2f}s on a 1,000,000-char PEM-like adversarial string"


def test_SEC_14_adversarial_full_pem_blocks_repeated_redacted_under_two_seconds():
    block, _ = build_pem_block(RNG, "RSA", n_lines=6, include_end=True)
    repeats = (1_000_000 // (len(block) + 1)) + 1
    text = (block + "\n") * repeats
    text = text[:1_000_000]
    assert len(text) == 1_000_000

    start = time.perf_counter()
    redact_mod.redact({"blob": text})
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"redact() took {elapsed:.2f}s on 1,000,000 chars of repeated full PEM blocks"


@given(st.integers(min_value=1, max_value=50))
@settings(max_examples=10, deadline=None)
def test_SEC_14_redact_time_does_not_blow_up_with_pem_type_word_length(n_words):
    # Guards against a nested/backtracking regex on the "[A-Z ]*"-shaped type
    # word: a long run of upper-case words before "PRIVATE KEY" must not
    # cause catastrophic backtracking when no END line follows.
    dashes = "-" * 5
    key_word = "PRIVATE" + " " + "KEY"
    long_type = " ".join(["WORD"] * n_words)
    begin = f"{dashes}BEGIN {long_type} {key_word}{dashes}"
    text = begin + "A" * 500 + "!" * 500  # never terminates with a valid END line

    start = time.perf_counter()
    redact_mod.redact(text)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"redact() took {elapsed:.2f}s for a {n_words}-word PEM type label with no END line"


# ---------------------------------------------------------------------------
# scripts/secret_scan.py's own scan over the stored JSONL, for every PEM
# type, finds nothing once the redaction covers the whole block.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("type_word", PEM_TYPE_WORDS, ids=[w or "generic" for w in PEM_TYPE_WORDS])
def test_SEC_14_secret_scan_finds_nothing_in_stored_archive_for_each_pem_type(tmp_path, type_word):
    block, _ = build_pem_block(RNG, type_word, n_lines=6, include_end=True)
    store = LocalDirStore(tmp_path)
    archive = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())
    archive.append("model_call", {"prompt": f"use this key:\n{block}\nthanks"})

    jsonl_path = tmp_path / ORG_ID / f"{RUN_ID}.jsonl"
    findings = SECRET_SCAN.scan_file(str(jsonl_path))

    assert findings == [], f"secret_scan.py still found something for type={type_word!r}: {findings}"


# ---------------------------------------------------------------------------
# A PEM whose body sits in a different value from its BEGIN line.
# ---------------------------------------------------------------------------


def _log_line(msg: str, *args: object) -> str:
    record = logging.LogRecord("tilo.test", logging.ERROR, __file__, 1, msg, args, None)
    assert redact_mod.RedactingFilter().filter(record)
    return record.getMessage()


def _split_block(type_word: str) -> tuple[str, list[str], str, list[str]]:
    block, body_lines = build_pem_block(RNG, type_word, n_lines=4, include_end=True)
    lines = block.split("\n")
    return lines[0], lines[1:-1], lines[-1], body_lines


@pytest.mark.parametrize("type_word", PEM_TYPE_WORDS, ids=[w or "generic" for w in PEM_TYPE_WORDS])
def test_FR_MEM_05_pem_split_across_log_args_leaves_no_body(type_word):
    header, middle, end_line, body_lines = _split_block(type_word)
    message = _log_line("%s\n%s\n%s", header, "\n".join(middle), end_line)
    for line in body_lines:
        assert line not in message
    assert ("-" * 5 + "END") not in message


def test_FR_MEM_05_pem_header_in_arg_body_in_msg_leaves_no_body():
    header, middle, end_line, body_lines = _split_block("RSA")
    message = _log_line("%s\n" + "\n".join(middle) + "\n" + end_line, header)
    for line in body_lines:
        assert line not in message
    assert ("-" * 5 + "END") not in message


@pytest.mark.parametrize("type_word", PEM_TYPE_WORDS, ids=[w or "generic" for w in PEM_TYPE_WORDS])
def test_FR_MEM_05_pem_stored_as_a_list_of_lines_leaves_no_body(tmp_path, type_word):
    block, body_lines = build_pem_block(RNG, type_word, n_lines=4, include_end=True)
    payload = {"pem_lines": ["before the key", *block.split("\n"), "after the key"]}

    archive = RunArchive(LocalDirStore(tmp_path), org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())
    archive.append("tool_call", payload)
    raw_text = (tmp_path / ORG_ID / f"{RUN_ID}.jsonl").read_text(encoding="utf-8")

    for line in body_lines:
        assert line not in raw_text
    assert ("-" * 5 + "END") not in raw_text
    assert "[REDACTED:private_key]" in raw_text  # a split key withholds the whole payload


def test_FR_MEM_05_pem_list_with_no_end_line_redacts_every_later_string():
    block, body_lines = build_pem_block(RNG, "EC", n_lines=4, include_end=False)
    redacted = redact_mod.redact({"lines": [*block.split("\n"), "trailing text"]})
    text = json.dumps(redacted)
    for line in body_lines:
        assert line not in text
    assert "trailing text" not in text


def test_FR_MEM_05_pem_begin_line_as_a_key_redacts_its_value():
    header, middle, end_line, body_lines = _split_block("RSA")
    text = json.dumps(redact_mod.redact({header: "\n".join([*middle, end_line])}))
    for line in body_lines:
        assert line not in text


# A key split across values in any arrangement: the whole value (or log line) is withheld.
SPLIT_SHAPES = {
    "reversed_list": lambda h, b, e: [b, e, h],
    "nested_lists": lambda h, b, e: [[h], [b], [e]],
    "list_in_the_middle": lambda h, b, e: [h, [b], e],
    "dict_in_the_middle": lambda h, b, e: [h, {"b": b}, e],
    "dict_siblings": lambda h, b, e: {"k": h, "v": b},
    "split_across_keys": lambda h, b, e: {"lines": [h], "more": [b, e]},
    "end_then_new_block": lambda h, b, e: [h, b, e + "\n" + h, b, e],
    "body_and_end_only": lambda h, b, e: {"a": "unrelated", "tail": b + "\n" + e},
}


@pytest.mark.parametrize("shape", sorted(SPLIT_SHAPES))
def test_FR_MEM_05_a_key_split_across_values_leaves_no_body(shape):
    header, middle, end_line, body_lines = _split_block("RSA")
    value = SPLIT_SHAPES[shape](header, "\n".join(middle), end_line)
    text = json.dumps(redact_mod.redact(value))
    for line in body_lines:
        assert line not in text
    assert ("-" * 5 + "END") not in text


def _all_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "".join(_all_text(k) + _all_text(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return "".join(_all_text(v) for v in value)
    return ""


def test_FR_MEM_05_a_key_cut_into_chunks_of_any_size_leaves_no_body():
    block, body_lines = build_pem_block(RNG, "RSA", n_lines=4, include_end=True)
    body = "".join(body_lines)
    for size in range(1, 201):
        chunks = [block[i : i + size] for i in range(0, len(block), size)]
        text = _all_text(redact_mod.redact({"stdout_chunks": chunks}))
        assert body[:16] not in text.replace("\n", ""), f"chunk size {size} leaked the body"


def test_FR_MEM_05_markers_cut_mid_word_or_oversize_pieces_leave_no_body():
    block, body_lines = build_pem_block(RNG, "RSA", n_lines=4, include_end=True)
    cut_a, cut_b = block.index("PRI") + 3, block.rindex("PRI") + 3
    three_way = [block[:cut_a], block[cut_a:cut_b], block[cut_b:]]
    head, rest = block.split("\n", 1)
    body_part, end_line = rest.rsplit("\n", 1)
    pad = "x" * (redact_mod.MAX_SCAN_CHARS + 1)
    oversize = [head + pad, body_part, pad + end_line]
    for value in (three_way, oversize):
        text = _all_text(redact_mod.redact({"parts": value}))
        for line in body_lines:
            assert line not in text


def test_FR_MEM_05_a_lone_end_line_redacts_from_the_start_of_its_value():
    header, middle, end_line, body_lines = _split_block("EC")
    text = redact_mod.redact_prompt("\n".join([*middle, end_line]) + " after")
    for line in body_lines:
        assert line not in text
    assert text.endswith(" after")


@pytest.mark.parametrize("order", ["body_end_header", "end_header_body"])
def test_FR_MEM_05_log_args_in_any_order_leave_no_body(order):
    header, middle, end_line, body_lines = _split_block("RSA")
    body = "\n".join(middle)
    args = (body, end_line, header) if order == "body_end_header" else (end_line, header, body)
    message = _log_line("%s %s %s", *args)
    for line in body_lines:
        assert line not in message


def test_FR_MEM_05_log_record_that_cannot_compose_keeps_no_raw_arg(capsys):
    block, body_lines = build_pem_block(RNG, "RSA", n_lines=4, include_end=True)
    api_key = "sk-" + rand_token(RNG, 30)
    logger = logging.getLogger("tilo.test.compose")
    logger.propagate = False  # pytest's own capture handler re-raises formatting errors
    handler = logging.StreamHandler()
    handler.addFilter(redact_mod.RedactingFilter())
    logger.addHandler(handler)
    try:
        logger.error("loaded config", block)  # an unused arg: getMessage() raises
        logger.error("user %d", api_key)  # a bad %-conversion
    finally:
        logger.removeHandler(handler)
        logger.propagate = True
    err = capsys.readouterr().err
    assert "[REDACTED:" in err  # the handler did print the failed record, redacted
    for line in body_lines:
        assert line not in err
    assert api_key not in err
