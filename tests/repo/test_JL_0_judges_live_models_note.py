"""JL-0 (doc note, user decision of 2026-10-06): hackathon judges who sign in with Google may use live models, within
the SEC-16 caps. The decision is recorded on the BQ-SEC15-1 row of docs/open-questions.md, the row that explains how
a judge gets live models without loosening the `LIVE=1` gate, so the next reader finds the confirmation beside the
mechanism and not only in a chat.

stdlib only, like the other repo tests.
"""

from __future__ import annotations

import pathlib

SENTENCE = "user confirmed 2026-10-06: judges signed in with Google may use live models"
ROW_ID = "BQ-SEC15-1"


def _rows(repo_root: pathlib.Path) -> list[str]:
    text = (repo_root / "docs" / "open-questions.md").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.startswith(f"| {ROW_ID} |")]


def test_JL_0_the_bq_sec15_1_row_exists_exactly_once(repo_root: pathlib.Path):
    assert len(_rows(repo_root)) == 1, f"docs/open-questions.md must have exactly one `{ROW_ID}` row"


def test_JL_0_the_bq_sec15_1_row_records_that_the_user_confirmed_judges_may_use_live_models(
    repo_root: pathlib.Path,
):
    (row,) = _rows(repo_root)
    assert SENTENCE in row, f"the {ROW_ID} row must contain the sentence {SENTENCE!r}"


def test_JL_0_the_note_is_a_decision_not_a_loosening_the_live_gate_text_stays(repo_root: pathlib.Path):
    """The note must not replace the mechanism: the row still names the explicit `live_permitted` injection and
    the deployed-only `TILO_JUDGE_LIVE=1` permission (only the user sets live)."""
    (row,) = _rows(repo_root)
    assert "live_permitted" in row and "TILO_JUDGE_LIVE=1" in row
