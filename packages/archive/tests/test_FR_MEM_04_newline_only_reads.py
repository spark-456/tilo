"""Acceptance tests pinning ticket FR-MEM-04/05 review round 2, change 2:
every reader of stored JSONL must split lines on "\\n" only, never
`str.splitlines()` -- which also breaks on U+2028 (LINE SEPARATOR), U+2029
(PARAGRAPH SEPARATOR), U+0085 (NEL), \\x0b (VERTICAL TAB), \\x0c (FORM FEED),
and \\x1c-\\x1e (FILE/GROUP/RECORD SEPARATOR). PRD 13.2 ("Raw archive ...
JSONL per run ... SHA-256 per record plus a per-run hash chain") and 15.1
(archive record entity) depend on each stored line being exactly one JSON
record; a reader that splits on any of those extra characters would shred a
payload containing one into multiple bogus "lines" and desync seq/hash
across every record after it.

These tests go through the public interfaces already established by
test_FR_MEM_04_hash_chain.py: `RunArchive.append` / `.records()` / `.head()`,
`verify_chain`, and the `python -m tilo_archive.verify` CLI -- not a private
reader method, per root CLAUDE.md's test-writer rule ("through the public
interface a user or service would use").

`tilo_archive` does not exist yet, so this file fails to collect with an
ImportError until the builder lands it -- the expected "fail for the right
reason" state for a test-writer ticket.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from conftest import ORG_ID, RUN_ID, FakeClock, identity_redactor
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_archive.archive import LocalDirStore, RunArchive, verify_chain

# Every character str.splitlines() treats as a line boundary beyond plain
# "\n" (per Python's str.splitlines() docs): U+000B, U+000C, U+001C-U+001E,
# U+0085, U+2028, U+2029. "\r" and "\r\n" are deliberately excluded here --
# JSONL readers already have to handle CRLF sanely and the brief calls out
# exactly these eight as the extra characters str.splitlines() adds beyond
# a plain "\n" split.
SPECIAL_LINE_BREAKS = [
    ("U+2028_LINE_SEPARATOR", " "),
    ("U+2029_PARAGRAPH_SEPARATOR", " "),
    ("U+0085_NEL", "\u0085"),
    ("VERTICAL_TAB_x0b", "\x0b"),
    ("FORM_FEED_x0c", "\x0c"),
    ("FILE_SEPARATOR_x1c", "\x1c"),
    ("GROUP_SEPARATOR_x1d", "\x1d"),
    ("RECORD_SEPARATOR_x1e", "\x1e"),
]


def _run_cli(path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tilo_archive.verify", str(path)],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("name,ch", SPECIAL_LINE_BREAKS, ids=[n for n, _ in SPECIAL_LINE_BREAKS])
def test_FR_MEM_04_payload_with_str_splitlines_only_char_round_trips(tmp_path, name, ch):
    store = LocalDirStore(tmp_path)
    archive = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=identity_redactor)
    n = 4
    texts = [f"before-{i}{ch}middle-{i}{ch}after-{i}" for i in range(n)]
    for text in texts:
        archive.append("model_call", {"text": text})

    head_before = archive.head()

    # Reopen: a from-scratch RunArchive over the same store must read back
    # the exact same head, proving the reader did not shred any stored line
    # on this character.
    reopened = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=identity_redactor)
    assert reopened.head() == head_before, (
        f"{name}: reopening the archive changed its head -- a reader split a stored line on this character"
    )

    records = reopened.records()
    assert len(records) == n, f"{name}: record count changed on reopen"
    for i, rec in enumerate(records):
        assert rec["seq"] == i + 1, f"{name}: seq desynced on reopen"
        assert rec["payload"]["text"] == texts[i], f"{name}: payload text was altered by line splitting on reopen"

    assert verify_chain(records) == [], f"{name}: verify_chain found problems after a clean reopen"


@pytest.mark.parametrize("name,ch", SPECIAL_LINE_BREAKS, ids=[n for n, _ in SPECIAL_LINE_BREAKS])
def test_FR_MEM_04_verify_cli_exits_0_with_correct_record_count(tmp_path, name, ch):
    store = LocalDirStore(tmp_path)
    archive = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=identity_redactor)
    n = 5
    for i in range(n):
        archive.append("model_call", {"text": f"line{ch}break-{i}", "i": i})
    jsonl_path = tmp_path / ORG_ID / f"{RUN_ID}.jsonl"

    result = _run_cli(jsonl_path)

    assert result.returncode == 0, (
        f"{name}: verify CLI exited {result.returncode} (stderr: {result.stderr!r}) -- "
        "a reader likely split a stored line on this character and desynced the chain"
    )
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out == {"ok": True, "records": n, "problems": []}, f"{name}: {out}"


def test_FR_MEM_04_char_at_start_and_end_of_payload_value_round_trips(tmp_path):
    store = LocalDirStore(tmp_path)
    archive = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=identity_redactor)
    for name, ch in SPECIAL_LINE_BREAKS:
        archive.append("model_call", {"kind": name, "text": f"{ch}payload-wrapped{ch}"})

    reopened = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=identity_redactor)
    records = reopened.records()

    assert len(records) == len(SPECIAL_LINE_BREAKS)
    for (name, ch), rec in zip(SPECIAL_LINE_BREAKS, records, strict=True):
        assert rec["payload"]["kind"] == name
        assert rec["payload"]["text"] == f"{ch}payload-wrapped{ch}", name
    assert verify_chain(records) == []


def test_FR_MEM_04_all_special_chars_combined_in_one_payload_round_trips(tmp_path):
    store = LocalDirStore(tmp_path)
    archive = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=identity_redactor)
    combined = "".join(ch for _, ch in SPECIAL_LINE_BREAKS)
    text = f"start{combined}mid{combined}end"
    archive.append("model_call", {"text": text})
    archive.append("model_call", {"text": "plain-second-record"})

    head_before = archive.head()
    reopened = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=identity_redactor)

    assert reopened.head() == head_before
    records = reopened.records()
    assert len(records) == 2
    assert records[0]["payload"]["text"] == text
    assert records[1]["seq"] == 2
    assert records[1]["payload"]["text"] == "plain-second-record"
    assert verify_chain(records) == []

    jsonl_path = tmp_path / ORG_ID / f"{RUN_ID}.jsonl"
    result = _run_cli(jsonl_path)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out == {"ok": True, "records": 2, "problems": []}


# ---------------------------------------------------------------------------
# Property: for any payload text built from the plain-"\n"-only-safe
# characters (i.e. no real "\n", which JSON already escapes, plus any mix of
# the eight str.splitlines()-only separators), the record count and payload
# text always round-trip exactly through append -> reopen -> records().
# ---------------------------------------------------------------------------

_SPECIAL_CHARS_ONLY = st.text(alphabet=[ch for _, ch in SPECIAL_LINE_BREAKS] + list("abcXYZ012 -_"), max_size=40)


@given(st.lists(_SPECIAL_CHARS_ONLY, min_size=1, max_size=8))
@settings(max_examples=25, deadline=None)
def test_FR_MEM_04_property_round_trip_for_any_mix_of_special_separators(tmp_path_factory, texts):
    store = LocalDirStore(tmp_path_factory.mktemp("prop"))
    archive = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=identity_redactor)
    for text in texts:
        archive.append("model_call", {"text": text})

    head_before = archive.head()
    reopened = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=identity_redactor)

    assert reopened.head() == head_before
    records = reopened.records()
    assert len(records) == len(texts)
    for expected_text, rec in zip(texts, records, strict=True):
        assert rec["payload"]["text"] == expected_text
    assert verify_chain(records) == []
