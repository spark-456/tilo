"""Renders the EV-01..EV-15 rows (PRD 3.5, 19.3): counts first, then percentages, then the method and the gaps.

Pure: the caller passes the build hash and the clock, so the same rows always give the same bytes.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any

from .latency import markdown_lines
from .metrics import MetricRow

CLAIM = (
    "scripted_fakes rows test pipeline mechanics, not model quality: the bank scripts the Director, so only "
    "recorded and live runs say anything about the model. A row never states that a target is reached."
)
_SHARES = ("EV-01", "EV-06", "EV-09", "EV-10")  # n of m (p%)
_STATUS = {"computed": "computed", "no_data": "no data", "needs_live_or_pilot": "needs live or pilot data"}
_HEADER = ("ID", "Metric", "Basis", "Status", "Value", "n", "Target")


def _value(row: MetricRow) -> str:
    if row.status != "computed" or row.value is None:
        return "-"
    if row.id in _SHARES:
        return f"{row.n} of {row.of} ({row.value:.0%})"
    if row.id == "EV-08":
        return f"{row.value:.0%}"
    if row.id == "EV-03":
        return f"{row.value:.2f}x"
    return f"{row.value:.2f}" + (" credits" if row.id == "EV-07" else " per run")


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_markdown(
    rows: Sequence[MetricRow], *, build_hash: str, now_utc: str, latency: Mapping[str, Any] | None = None
) -> str:
    lines = ["# Metrics report (EV-01 to EV-15)", "", CLAIM, "", f"Build `{build_hash}`, generated {now_utc}.", ""]
    lines += [f"| {' | '.join(_HEADER)} |", f"| {' | '.join('---' for _ in _HEADER)} |"]
    for row in rows:
        cells = (row.id, row.name, row.basis or "-", _STATUS[row.status], _value(row), str(row.n), row.target)
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    if latency:
        lines += ["", "## Latency (NFR-02, NFR-03, NFR-05)", "", *markdown_lines(dict(latency))]
    lines += ["", "## Method and gaps", ""]
    lines += [f"- **{row.id} {row.name}.** {row.method} {row.note}" for row in rows]
    return "\n".join(lines) + "\n"


def render_json(rows: Sequence[MetricRow]) -> dict[str, Any]:
    return {"rows": [dataclasses.asdict(row) for row in rows]}
