"""FR-MEM-04: RunArchive takes a required, injected redactor. What gets
written and hashed is the redactor's output; a raising redactor writes
nothing (fail closed). The real redactor is FR-MEM-05's, not tested here."""

from __future__ import annotations

import json

import pytest
from conftest import ORG_ID, RUN_ID, FakeClock, canonical_hash
from tilo_archive.archive import RunArchive, verify_chain

RAW_MARKER = "raw-" + "payload-marker"


def test_FR_MEM_04_redactor_is_required(store):
    with pytest.raises(TypeError):
        RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())  # type: ignore[call-arg]


def test_FR_MEM_04_redactor_output_is_what_gets_written_and_hashed(store):
    seen: list[object] = []

    def redactor(payload):
        seen.append(payload)
        return {"redacted": True}

    arch = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=redactor)
    arch.append("model_call", {"text": RAW_MARKER})

    assert seen == [{"text": RAW_MARKER}]
    lines = store.read_lines(ORG_ID, RUN_ID)
    assert len(lines) == 1 and RAW_MARKER not in lines[0]
    stored = json.loads(lines[0])
    assert stored["payload"] == {"redacted": True}
    assert stored["hash"] == canonical_hash(stored)
    assert verify_chain([stored]) == []


def test_FR_MEM_04_raising_redactor_writes_nothing(store):
    fail = {"now": False}

    def redactor(payload):
        if fail["now"]:
            raise RuntimeError(f"cannot redact {payload!r}")
        return payload

    arch = RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=redactor)
    arch.append("tool_call", {"n": 1})
    head_before = arch.head()
    lines_before = store.read_lines(ORG_ID, RUN_ID)

    fail["now"] = True
    with pytest.raises(ValueError) as info:
        arch.append("tool_call", {"text": RAW_MARKER})

    assert RAW_MARKER not in str(info.value)
    assert store.read_lines(ORG_ID, RUN_ID) == lines_before
    assert arch.head() == head_before
    assert len(arch.records()) == 1

    fail["now"] = False
    assert arch.append("tool_call", {"n": 2}) == f"{RUN_ID}/2"
    assert verify_chain(arch.records()) == []
