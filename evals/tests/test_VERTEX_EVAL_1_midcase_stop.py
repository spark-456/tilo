"""VERTEX-EVAL-1 (#722 follow-up): a provider failure in the middle of a case keeps that case's charged calls in the
report, as an error row, so the credits in the total are all accounted for."""

from __future__ import annotations

from pathlib import Path

from _vertex_eval_lib import (
    RecordingEvalProvider,
    ids_of,
    invoke,
    network_guard,  # noqa: F401  (autouse fixture)
    pair_row,
    run_argv,
    total_credits,
    write_pairs,
)
from tilo_providers.errors import QuotaError


def test_VERTEX_EVAL_1_a_case_cut_short_by_a_stop_is_an_error_row_with_its_charge(tmp_path: Path) -> None:
    pairs = write_pairs(tmp_path, [pair_row(i) for i in ids_of(3)])
    judge = RecordingEvalProvider(fail_at=2, error=QuotaError("quota"))  # the second call of case one fails
    result = invoke(run_argv(tmp_path, pairs), provider=judge)
    assert result.code == 1, (result.code, result.err)
    assert len(judge.requests) == 2
    assert total_credits(result) > 0  # the first call was charged
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    first = ids_of(3)[0]
    rows = [line for line in report.splitlines() if first in line and "error" in line.lower()]
    assert rows, "the case cut short is not listed as an error row"
