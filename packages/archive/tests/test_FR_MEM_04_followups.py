"""FR-MEM-04 follow-ups from issue #57 (security-reviewer and code-reviewer
non-blocking findings on the #37 split): no payload or stored content in an
error message, no chained redactor exception, a CLI `--head` check, and a
CLI problem message that names a line, not a seq."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from conftest import ORG_ID, RUN_ID, FakeClock, identity_redactor
from tilo_archive.archive import LocalDirStore, RunArchive
from tilo_archive.record import VALID_KINDS

RAW_MARKER = "raw-" + "payload-marker"


def _run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tilo_archive.verify", *map(str, args)],
        capture_output=True,
        text=True,
    )


def test_FR_MEM_04_invalid_kind_error_never_echoes_the_kind(archive):
    # Swapped arguments put the payload in the kind slot: the error must
    # name the allowed kinds only, never what was passed.
    with pytest.raises(ValueError) as info:
        archive.append({"text": RAW_MARKER}, "model_call")  # type: ignore[arg-type]
    message = str(info.value)
    assert RAW_MARKER not in message
    assert all(kind in message for kind in VALID_KINDS)

    with pytest.raises(ValueError) as info:
        archive.append(RAW_MARKER, {"x": 1})
    assert RAW_MARKER not in str(info.value)


@pytest.mark.parametrize("bad_line", ["[1,2]", '"' + RAW_MARKER + '"', "null"], ids=["list", "string", "null"])
def test_FR_MEM_04_reopen_error_for_non_object_line_names_only_the_json_type(tmp_path, bad_line):
    store = LocalDirStore(tmp_path)
    arch = RunArchive(store, org_id="org_a", run_id="r_1", clock=FakeClock(), redactor=identity_redactor)
    arch.append("model_call", {"i": 0})
    path = tmp_path / "org_a" / "r_1.jsonl"
    path.write_text(bad_line + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 1") as info:
        RunArchive(store, org_id="org_a", run_id="r_1", clock=FakeClock(), redactor=identity_redactor)
    assert RAW_MARKER not in str(info.value)


def test_FR_MEM_04_redactor_failure_leaves_no_chained_exception(store):
    def redactor(payload):
        raise RuntimeError(f"cannot redact {payload!r}")

    arch = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=redactor)
    with pytest.raises(ValueError) as info:
        arch.append("tool_call", {"text": RAW_MARKER})

    assert info.value.__cause__ is None
    assert info.value.__context__ is None
    assert RAW_MARKER not in str(info.value)
    assert store.read_lines(ORG_ID, RUN_ID) == []


def test_FR_MEM_04_redactor_base_exception_writes_nothing(store):
    class Stop(BaseException):
        pass

    def redactor(payload):
        raise Stop

    arch = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=redactor)
    with pytest.raises(Stop):
        arch.append("tool_call", {"x": 1})
    assert store.read_lines(ORG_ID, RUN_ID) == []
    assert arch.records() == []


def _three_record_run(archive, tmp_path):
    for i in range(3):
        archive.append("model_call", {"i": i})
    return tmp_path / ORG_ID / f"{RUN_ID}.jsonl"


def test_FR_MEM_04_cli_head_flag_accepts_the_true_head(archive, tmp_path):
    path = _three_record_run(archive, tmp_path)
    seq, digest = archive.head()

    result = _run_cli(path, "--head", f"{seq}:{digest}")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"ok": True, "records": 3, "problems": []}


def test_FR_MEM_04_cli_head_flag_detects_a_truncated_tail(archive, tmp_path):
    path = _three_record_run(archive, tmp_path)
    seq, digest = archive.head()
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")

    assert _run_cli(path).returncode == 0  # the chain alone cannot see the cut
    result = _run_cli(path, "--head", f"{seq}:{digest}")

    assert result.returncode == 1
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["ok"] is False and any("tail does not match expected head" in p for p in out["problems"])


@pytest.mark.parametrize("bad", ["3", "x:abc", "3:", ":" + "0" * 64, "0:" + "g" * 64, "3:abc"])
def test_FR_MEM_04_cli_head_flag_rejects_a_malformed_value(archive, tmp_path, bad):
    path = _three_record_run(archive, tmp_path)

    result = _run_cli(path, "--head", bad)

    assert result.returncode == 1
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["ok"] is False and out["problems"] and "--head" in out["problems"][0]


def test_FR_MEM_04_cli_truncated_line_message_names_a_line_not_a_seq(tmp_path):
    store = LocalDirStore(tmp_path)
    arch = RunArchive(store, org_id="org_a", run_id="r_1", clock=FakeClock(), redactor=identity_redactor)
    for i in range(2):
        arch.append("model_call", {"i": i})
    path = tmp_path / "org_a" / "r_1.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + '{"v":"1.0","ru', encoding="utf-8")

    out = json.loads(_run_cli(path).stdout.strip().splitlines()[-1])

    assert out["problems"] == ["line 3: unparseable or truncated record"]
