"""SEC-16 beta caps and the lifetime-cap feedback pop-up (docs/open-questions.md build log; ticket SPEND-CAPS-FEEDBACK).

Two decisions are not in the PRD and must be findable where the next reader looks:

* `BQ-SEC16-3`: the user approved new caps on 8 Oct 2026 (run 50000, uid lifetime 300000, global day 500000 paise;
  INR 500, 3,000 and 5,000). It supersedes the shipped values stated in `BQ-SEC16-1` and notes that INR 5,000 a day is
  above PRD 17.3's US$25 at the 80 INR per US$ default.
* `BQ-FEEDBACK-1`: a user request of 8 Oct 2026 (not in the PRD): the lifetime-cap pop-up and `POST /v1/feedback`.

Rows are appended at the end of the table, one line each (the file merges with `merge=union`). stdlib only, like the
other repo tests.
"""

from __future__ import annotations

import pathlib

import pytest

LAST_ROW_BEFORE = "BQ-MTG17-3"  # the last row when this ticket was written; new rows go after it


def _lines(repo_root: pathlib.Path) -> list[str]:
    return (repo_root / "docs" / "open-questions.md").read_text(encoding="utf-8").splitlines()


def _row(repo_root: pathlib.Path, row_id: str) -> tuple[int, str]:
    found = [(n, line) for n, line in enumerate(_lines(repo_root)) if line.startswith(f"| {row_id} |")]
    assert len(found) == 1, f"docs/open-questions.md must have exactly one `{row_id}` row, found {len(found)}"
    return found[0]


@pytest.mark.parametrize("row_id", ["BQ-SEC16-3", "BQ-FEEDBACK-1"])
def test_SEC_16_FEEDBACK_the_row_exists_once_is_one_table_line_and_sits_after_the_older_rows(
    repo_root: pathlib.Path, row_id: str
):
    number, line = _row(repo_root, row_id)
    anchor, _ = _row(repo_root, LAST_ROW_BEFORE)

    assert number > anchor, f"{row_id} must be appended at the end of the table, after {LAST_ROW_BEFORE}"
    assert line.rstrip().endswith("|")
    assert line.count(" | ") == 4, "five columns: ID, question, default, source, raised (a `|` in a cell is escaped)"
    assert line.rstrip().endswith("| 2026-10-08 |"), "raised 2026-10-08"


def test_SEC_16_FEEDBACK_bq_sec16_3_records_the_approved_caps_and_what_it_supersedes(repo_root: pathlib.Path):
    _, row = _row(repo_root, "BQ-SEC16-3")

    assert "user approved 8 Oct" in row
    for number in ("50000", "300000", "500000"):
        assert number in row, f"the row states {number}"
    for amount in ("INR 500", "INR 3,000", "INR 5,000"):
        assert amount in row, f"the row states {amount}"
    assert "config/spend_caps.yaml" in row
    assert "BQ-SEC16-1" in row and "supersede" in row.lower(), "it says it replaces BQ-SEC16-1's shipped values"
    assert "PRD 17.3" in row, "it notes the daily cap is now above PRD 17.3's US$25"
    assert "replay-only" in row and "unchanged" in row, "the replay-only fallback at the daily cap is unchanged"


def test_SEC_16_FEEDBACK_bq_feedback_1_records_the_request_the_code_and_the_deferred_admin_read(
    repo_root: pathlib.Path,
):
    _, row = _row(repo_root, "BQ-FEEDBACK-1")

    assert "user request 8 Oct" in row
    assert "not in the PRD" in row
    for token in ("spend_cap_reached", "POST /v1/feedback", "lifetime_cap", "2000"):
        assert token in row, f"the row names `{token}`"
    assert "beta" in row.lower() and "feedback" in row.lower()
    assert "deferred" in row.lower() and "admin" in row.lower(), "the owner/admin read path is explicitly deferred"
    assert "no read route" in row.lower(), "ordinary users have no read route"


def test_SEC_16_FEEDBACK_bq_sec16_4_records_the_lowered_caps_with_the_users_words(repo_root: pathlib.Path):
    number, row = _row(repo_root, "BQ-SEC16-4")
    anchor, _ = _row(repo_root, "BQ-SEC16-3")

    assert number > anchor and row.rstrip().endswith("| 2026-10-09 |")
    assert row.count(" | ") == 4, "five columns: ID, question, default, source, raised"
    assert "Cut the lifetime cap to 500 rupees per person. 3000 seems excessive for a free service." in row
    assert "Yeah go ahead with your cost analysis and new spend limits. I think it's fair" in row
    for token in ("50000", "INR 500", "15000", "INR 150", "500000", "INR 5,000", "BQ-SEC16-3", "supersede"):
        assert token in row, f"the row names `{token}`"
    assert "user-approved" in row and "overridable" not in row and "supervisor's decision" not in row
