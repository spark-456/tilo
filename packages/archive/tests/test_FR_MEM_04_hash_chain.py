"""Acceptance tests for FR-MEM-04: "Raw archive with per-record hashes and a
per-run hash chain" -- acceptance test "Tampering with one record fails the
chain check" (PRD 13.5). Also covers 13.2 ("Raw archive ... SHA-256 per
record plus a per-run hash chain; any edit breaks the chain"), 15.1 (Archive
record entity: run, seq, kind, payload, hash, previous hash) and 22.2 D-09.

`tilo_archive` (packages/archive/src) does not exist yet, so every test here
fails to collect with an ImportError until the builder lands it -- the
expected "fail for the right reason" state for a test-writer ticket.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from conftest import (
    ARCHIVE_REF_RE,
    ORG_ID,
    OTHER_RUN_ID,
    RUN_ID,
    RUN_ID_RE,
    ZERO_HASH,
    FakeClock,
    canonical_hash,
    mentions_seq,
)
from hypothesis import given
from hypothesis import strategies as st
from tilo_archive.archive import LocalDirStore, RunArchive, verify_chain

# ---------------------------------------------------------------------------
# Record shape: hash / prev_hash match the canonical-JSON definition.
# ---------------------------------------------------------------------------


def test_FR_MEM_04_first_record_hash_and_prev_hash(archive):
    ref = archive.append("model_call", {"prompt": "hi"})
    records = archive.records()
    assert len(records) == 1
    rec = records[0]
    assert rec["v"] == "1.0"
    assert rec["run_id"] == RUN_ID
    assert rec["seq"] == 1
    assert rec["kind"] == "model_call"
    assert rec["prev_hash"] == ZERO_HASH
    assert rec["hash"] == canonical_hash(rec)
    assert ref == f"{RUN_ID}/1"
    assert ARCHIVE_REF_RE.match(ref)


def test_FR_MEM_04_chain_links_prev_hash_to_previous_hash(archive):
    archive.append("model_call", {"a": 1})
    archive.append("tool_call", {"b": 2})
    records = archive.records()
    assert records[1]["seq"] == 2
    assert records[1]["prev_hash"] == records[0]["hash"]
    assert records[1]["hash"] == canonical_hash(records[1])
    assert records[1]["hash"] != records[0]["hash"]


@pytest.mark.parametrize("kind", ["model_call", "tool_call", "channel_in", "channel_out"])
def test_FR_MEM_04_every_registered_kind_is_accepted(archive, kind):
    ref = archive.append(kind, {"k": kind})
    assert archive.records()[-1]["kind"] == kind
    assert ARCHIVE_REF_RE.match(ref)


def test_FR_MEM_04_archive_ref_and_run_id_match_contract_patterns(archive):
    assert RUN_ID_RE.match(RUN_ID)
    for _ in range(3):
        ref = archive.append("channel_in", {"text": "hello"})
        assert ARCHIVE_REF_RE.match(ref), ref


def test_FR_MEM_04_head_matches_last_record(archive):
    for i in range(3):
        archive.append("tool_call", {"i": i})
    seq, h = archive.head()
    last = archive.records()[-1]
    assert seq == last["seq"] == 3
    assert h == last["hash"]


def test_FR_MEM_04_local_dir_store_never_rewrites_existing_lines(tmp_path):
    store = LocalDirStore(tmp_path)
    arch = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())
    arch.append("model_call", {"i": 0})
    path = tmp_path / ORG_ID / f"{RUN_ID}.jsonl"
    assert path.exists()
    first_line = path.read_text(encoding="utf-8").splitlines()[0]

    arch.append("model_call", {"i": 1})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == first_line, "an existing line must never be rewritten"
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# verify_chain: intact run, then every tamper category from the brief.
# ---------------------------------------------------------------------------


def test_FR_MEM_04_verify_chain_accepts_intact_run(archive):
    for i in range(5):
        archive.append("model_call", {"i": i})
    assert verify_chain(archive.records()) == []


def test_FR_MEM_04_verify_chain_detects_payload_edit(archive):
    for i in range(3):
        archive.append("model_call", {"i": i})
    records = archive.records()
    records[1] = dict(records[1], payload={"i": "TAMPERED"})

    problems = verify_chain(records)

    assert problems
    assert mentions_seq(problems, 2)


def test_FR_MEM_04_verify_chain_detects_hash_recomputed_after_edit(archive):
    """Editing a record's payload *and* recomputing that record's own hash
    still breaks the next record's prev_hash link (brief: "a broken link
    (prev_hash)")."""
    for i in range(3):
        archive.append("model_call", {"i": i})
    records = archive.records()
    tampered = dict(records[1], payload={"i": "TAMPERED"})
    tampered["hash"] = canonical_hash(tampered)
    records[1] = tampered

    problems = verify_chain(records)

    assert problems
    assert mentions_seq(problems, 3)


def test_FR_MEM_04_verify_chain_detects_deleted_record(archive):
    for i in range(4):
        archive.append("model_call", {"i": i})
    records = archive.records()
    del records[1]  # remove seq 2

    problems = verify_chain(records)

    assert problems
    assert mentions_seq(problems, 2) or mentions_seq(problems, 3)


def test_FR_MEM_04_verify_chain_detects_inserted_record(archive):
    for i in range(3):
        archive.append("model_call", {"i": i})
    records = archive.records()
    injected = dict(records[1])
    injected["seq"] = 99
    records.insert(2, injected)

    problems = verify_chain(records)

    assert problems
    assert mentions_seq(problems, 3) or mentions_seq(problems, 99)


def test_FR_MEM_04_verify_chain_detects_swapped_records(archive):
    for i in range(3):
        archive.append("model_call", {"i": i})
    records = archive.records()
    records[0], records[1] = records[1], records[0]

    problems = verify_chain(records)

    assert problems
    assert mentions_seq(problems, 1) or mentions_seq(problems, 2)


def test_FR_MEM_04_verify_chain_detects_duplicate_seq(archive):
    for i in range(3):
        archive.append("model_call", {"i": i})
    records = archive.records()
    records[2] = dict(records[2], seq=records[1]["seq"])

    problems = verify_chain(records)

    assert problems


def test_FR_MEM_04_verify_chain_detects_record_from_another_run(archive, store):
    for i in range(2):
        archive.append("model_call", {"i": i})
    other = RunArchive(store, org_id=ORG_ID, run_id=OTHER_RUN_ID, clock=FakeClock())
    other.append("model_call", {"x": 1})

    records = archive.records() + other.records()
    problems = verify_chain(records)

    assert problems
    assert mentions_seq(problems, 3) or mentions_seq(problems, 1) or any(OTHER_RUN_ID in p for p in problems)


def test_FR_MEM_04_verify_chain_detects_truncated_tail_given_expected_head(archive):
    for i in range(5):
        archive.append("model_call", {"i": i})
    head = archive.head()
    truncated = archive.records()[:3]

    assert verify_chain(truncated) == [], "a valid prefix is indistinguishable without an expected head"
    problems = verify_chain(truncated, expected_head=head)
    assert problems


def test_FR_MEM_04_verify_chain_detects_appended_record_given_expected_head(archive):
    for i in range(3):
        archive.append("model_call", {"i": i})
    head = archive.head()
    archive.append("model_call", {"i": "extra"})

    problems = verify_chain(archive.records(), expected_head=head)

    assert problems


def test_FR_MEM_04_verify_chain_passes_when_records_match_expected_head(archive):
    for i in range(3):
        archive.append("model_call", {"i": i})
    head = archive.head()
    assert verify_chain(archive.records(), expected_head=head) == []


# ---------------------------------------------------------------------------
# Reopening continues the chain.
# ---------------------------------------------------------------------------


def test_FR_MEM_04_reopened_archive_continues_chain(store):
    first = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())
    first.append("model_call", {"i": 0})
    first.append("model_call", {"i": 1})
    head_after_first_session = first.head()

    reopened = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())
    assert reopened.head() == head_after_first_session

    reopened.append("tool_call", {"i": 2})
    records = reopened.records()
    assert len(records) == 3
    assert records[2]["seq"] == 3
    assert records[2]["prev_hash"] == head_after_first_session[1]
    assert verify_chain(records) == []


# ---------------------------------------------------------------------------
# Rejections: invalid kind, bad run id / org id, non-JSON and NaN payloads.
# Each must raise ValueError and write nothing.
# ---------------------------------------------------------------------------


def test_FR_MEM_04_invalid_kind_raises_and_writes_nothing(archive):
    with pytest.raises(ValueError):
        archive.append("not_a_real_kind", {"x": 1})
    assert archive.records() == []


@pytest.mark.parametrize("bad_run_id", ["not-valid", "r_", "R_bad", "", "r_" + "x" * 49])
def test_FR_MEM_04_bad_run_id_raises_and_writes_nothing(store, bad_run_id):
    with pytest.raises(ValueError):
        arch = RunArchive(store, org_id=ORG_ID, run_id=bad_run_id, clock=FakeClock())
        arch.append("model_call", {"x": 1})


@pytest.mark.parametrize("bad_org_id", ["bad org id", "org", "not_org_prefixed", ""])
def test_FR_MEM_04_bad_org_id_raises_and_writes_nothing(store, bad_org_id):
    with pytest.raises(ValueError):
        arch = RunArchive(store, org_id=bad_org_id, run_id=RUN_ID, clock=FakeClock())
        arch.append("model_call", {"x": 1})


def test_FR_MEM_04_non_json_payload_raises_and_writes_nothing(archive):
    class NotJSONSerialisable:
        pass

    with pytest.raises(ValueError):
        archive.append("model_call", {"x": NotJSONSerialisable()})
    assert archive.records() == []


def test_FR_MEM_04_nan_payload_raises_and_writes_nothing(archive):
    with pytest.raises(ValueError):
        archive.append("model_call", {"x": float("nan")})
    assert archive.records() == []


@pytest.mark.parametrize("bad_float", [float("inf"), float("-inf")])
def test_FR_MEM_04_infinite_payload_raises_and_writes_nothing(archive, bad_float):
    with pytest.raises(ValueError):
        archive.append("model_call", {"x": bad_float})
    assert archive.records() == []


# ---------------------------------------------------------------------------
# Property: seq is strictly increasing across any sequence of appends
# (property tests for invariants -- root CLAUDE.md / test-writer brief).
# ---------------------------------------------------------------------------


@given(
    st.lists(
        st.sampled_from(["model_call", "tool_call", "channel_in", "channel_out"]),
        min_size=1,
        max_size=15,
    )
)
def test_FR_MEM_04_seq_strictly_increasing(tmp_path_factory, kinds):
    store = LocalDirStore(tmp_path_factory.mktemp("prop"))
    arch = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())
    expected_next_seq = 1
    for kind in kinds:
        arch.append(kind, {"k": kind})
        rec = arch.records()[-1]
        assert rec["seq"] == expected_next_seq
        expected_next_seq += 1
    assert verify_chain(arch.records()) == []


# ---------------------------------------------------------------------------
# CLI: `python -m tilo_archive.verify <path>`.
# ---------------------------------------------------------------------------


def _run_cli(path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tilo_archive.verify", str(path)],
        capture_output=True,
        text=True,
    )


def test_FR_MEM_04_cli_exits_0_and_reports_ok_on_intact_chain(archive, tmp_path):
    for i in range(3):
        archive.append("model_call", {"i": i})
    jsonl_path = tmp_path / ORG_ID / f"{RUN_ID}.jsonl"

    result = _run_cli(jsonl_path)

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out == {"ok": True, "records": 3, "problems": []}


def test_FR_MEM_04_cli_exits_1_and_names_problem_on_tampered_chain(archive, tmp_path):
    for i in range(3):
        archive.append("model_call", {"i": i})
    jsonl_path = tmp_path / ORG_ID / f"{RUN_ID}.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["payload"] = {"i": "TAMPERED"}
    lines[1] = json.dumps(tampered)
    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = _run_cli(jsonl_path)

    assert result.returncode == 1
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["ok"] is False
    assert out["records"] == 3
    assert out["problems"]
