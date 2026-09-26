"""FR-INT-01 (PRD 7.1): "Intake accepts text up to 4,000 characters and up to 10 files (PDF,
DOCX, PPTX, XLSX, CSV, PNG, JPG; 50 MB total)." Acceptance test: "Given text and 3 files, when
submitted, then a task appears with brief chips in <= 4 s p50 and each file shows an extraction
status." Brief-chip *content* is FR-INT-03 (next ticket, per the brief) -- not asserted here,
only that a task/world/run is created and each file gets a status.

Public interface under test: `tilo_planning.intake.submit_intake` (see conftest.py's module
docstring for how this ticket's interface was designed and which ambiguities it resolves).
"""

from __future__ import annotations

import statistics
import time

import pytest
from _planning_contracts_lib import (
    assert_valid_event,
    make_csv_bytes,
    make_docx_bytes,
    make_jpg_bytes,
    make_pdf_bytes,
    make_png_bytes,
)
from tilo_planning.artifacts import InMemoryArtifactStore
from tilo_planning.intake import (
    MAX_FILES,
    MAX_TEXT_CHARS,
    MAX_TOTAL_BYTES,
    IntakeFile,
    IntakeRejected,
    IntakeRequest,
    submit_intake,
)


def _three_small_files() -> list[IntakeFile]:
    return [
        IntakeFile(filename="brief.docx", content=make_docx_bytes("The quarterly numbers are strong.")),
        IntakeFile(filename="photo.jpg", content=make_jpg_bytes()),
        IntakeFile(filename="data.csv", content=make_csv_bytes([["a", "b"], ["1", "2"]])),
    ]


def test_FR_INT_01_text_and_three_files_creates_task_with_event_and_statuses(repo_root, registry, safety_provider):
    request = IntakeRequest(text="Prepare the weekly supplier summary.", files=_three_small_files())
    store = InMemoryArtifactStore()

    result = submit_intake(request, safety=safety_provider, store=store)

    assert result.task_id
    assert result.world_id.startswith("w_")
    assert result.run_id.startswith("r_")
    assert result.event["type"] == "world.requested"
    assert_valid_event(repo_root, registry, result.event)

    assert len(result.files) == 3
    filenames = {f.filename for f in result.files}
    assert filenames == {"brief.docx", "photo.jpg", "data.csv"}
    for file_result in result.files:
        assert file_result.status == "ok"
        assert file_result.artifact["version"] == 1


def test_FR_INT_01_text_over_4000_chars_is_rejected_nothing_stored(safety_provider):
    request = IntakeRequest(text="x" * (MAX_TEXT_CHARS + 1), files=[])
    store = InMemoryArtifactStore()

    with pytest.raises(IntakeRejected) as excinfo:
        submit_intake(request, safety=safety_provider, store=store)

    reason = excinfo.value.reason
    assert str(MAX_TEXT_CHARS) in reason or "4000" in reason or "text" in reason.lower()
    assert store.list_ids() == []


def test_FR_INT_01_more_than_10_files_is_rejected_nothing_stored(safety_provider):
    files = [IntakeFile(filename=f"f{i}.png", content=make_png_bytes()) for i in range(MAX_FILES + 1)]
    request = IntakeRequest(text="Some task.", files=files)
    store = InMemoryArtifactStore()

    with pytest.raises(IntakeRejected) as excinfo:
        submit_intake(request, safety=safety_provider, store=store)

    assert excinfo.value.reason
    assert store.list_ids() == []


def test_FR_INT_01_total_size_over_50mb_is_rejected_nothing_stored(safety_provider):
    big = make_pdf_bytes(size=MAX_TOTAL_BYTES + 1)
    request = IntakeRequest(text="Some task.", files=[IntakeFile(filename="huge.pdf", content=big)])
    store = InMemoryArtifactStore()

    with pytest.raises(IntakeRejected) as excinfo:
        submit_intake(request, safety=safety_provider, store=store)

    assert excinfo.value.reason
    assert store.list_ids() == []


@pytest.mark.parametrize("filename", ["macro.exe", "archive.zip", "notes.txt"])
def test_FR_INT_01_disallowed_file_type_is_rejected_nothing_stored(safety_provider, filename):
    request = IntakeRequest(text="Some task.", files=[IntakeFile(filename=filename, content=b"whatever")])
    store = InMemoryArtifactStore()

    with pytest.raises(IntakeRejected) as excinfo:
        submit_intake(request, safety=safety_provider, store=store)

    assert excinfo.value.reason
    assert store.list_ids() == []


def test_FR_INT_01_submit_p50_under_4s(safety_provider):
    """PRD 7.1 FR-INT-01: "brief chips in <= 4 s p50" for text + 3 small files with fake
    providers. Runs several submissions (fresh store each time, since a real submission is not
    idempotent) and asserts the median wall time."""
    samples = []
    for _ in range(7):
        store = InMemoryArtifactStore()
        request = IntakeRequest(text="Prepare the weekly supplier summary.", files=_three_small_files())
        start = time.perf_counter()
        submit_intake(request, safety=safety_provider, store=store)
        samples.append(time.perf_counter() - start)

    p50 = statistics.median(samples)
    assert p50 < 4.0, f"FR-INT-01: p50 submit time {p50:.3f}s exceeds the 4s budget ({samples})"
