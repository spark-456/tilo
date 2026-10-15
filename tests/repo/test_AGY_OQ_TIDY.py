"""Tests for ticket AGY-OQ-TIDY: open-questions.md row formatting and missing BQ rows."""

from __future__ import annotations

import pathlib


def test_AGY_OQ_TIDY_file_has_no_crlf(repo_root: pathlib.Path) -> None:
    raw = (repo_root / "docs" / "open-questions.md").read_bytes()
    assert b"\r" not in raw, "docs/open-questions.md must use LF line endings, no CRLF"


def test_AGY_OQ_TIDY_all_recent_rows_have_five_columns_and_status(repo_root: pathlib.Path) -> None:
    text = (repo_root / "docs" / "open-questions.md").read_text(encoding="utf-8")
    lines = text.splitlines()

    start_idx = None
    for i, line in enumerate(lines):
        if "| BQ-PA06B-4 |" in line:
            start_idx = i
            break

    assert start_idx is not None, "BQ-PA06B-4 marker not found"

    checked = 0
    for idx in range(start_idx, len(lines)):
        line = lines[idx].strip()
        if not line.startswith("| BQ-"):
            continue
        cols = [c.strip() for c in line.split("|")][1:-1]
        assert len(cols) == 5, f"Line {idx + 1} ({cols[0]}) must have exactly 5 columns, got {len(cols)}"
        bq_id, question, default_cell, source, raised = cols
        assert len(question) > 0, f"{bq_id} question is empty"
        assert len(default_cell) > 0, f"{bq_id} default decision is empty"
        assert len(source) > 0, f"{bq_id} source is empty"
        assert raised.startswith("2026-10-"), f"{bq_id} invalid raised date: {raised}"
        checked += 1

    assert checked >= 150, f"Expected at least 150 recent BQ rows checked, got {checked}"


def test_AGY_OQ_TIDY_missing_bq_rows_appended_at_end(repo_root: pathlib.Path) -> None:
    text = (repo_root / "docs" / "open-questions.md").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("| BQ-")]

    expected_appended = [
        "BQ-INFRA-S2-1",
        "BQ-INFRA-S2-2",
        "BQ-INFRA-S2-3",
        "BQ-INFRA-S2-4",
        "BQ-INFRA-S2-5",
        "BQ-INFRA-S2-6",
        "BQ-INFRA-S2-7",
        "BQ-INFRA-S2-8",
        "BQ-INFRA-S2-9",
        "BQ-INFRA-S2-10",
        "BQ-INFRA-S2-11",
        "BQ-INFRA-S2-12",
        "BQ-INFRA-S2-13",
        "BQ-INFRA-S2-14",
        "BQ-UX17-1 / PREP-SLACK-1",
        "BQ-SST-1",
        "BQ-SST-2",
        "BQ-SST-3",
        "BQ-SST-4",
        "BQ-SST-5",
        "BQ-SST-6",
        "BQ-STUDIO-1",
    ]

    end_bqs = [ln.split("|")[1].strip() for ln in lines[-len(expected_appended) :]]
    assert end_bqs == expected_appended, f"Appended rows do not match expected: {end_bqs}"
