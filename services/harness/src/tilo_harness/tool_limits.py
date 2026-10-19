"""config/tool_loop.yaml: how far one unit's tool loop may go (RUN-COST-PROGRESS, EFF-03).

`ToolLimits` is plain data for `ToolUnitRunner(limits=...)`. A missing or bad file raises `ToolLimitsError` naming the
key, never a value, so the API's run runner refuses to start rather than run an unbounded loop.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = ["DEFAULT_TOOL_LOOP_CONFIG", "ToolLimits", "ToolLimitsError", "load_tool_limits"]

DEFAULT_TOOL_LOOP_CONFIG = Path(__file__).resolve().parents[4] / "config" / "tool_loop.yaml"


class ToolLimitsError(ValueError):
    """config/tool_loop.yaml is missing, unreadable or out of range."""


@dataclass(frozen=True)
class ToolLimits:
    rounds: int  # model calls per unit; the last one is offered no tools
    calls_per_round: int
    max_tool_calls: int
    calls_per_tool: Mapping[str, int]
    result_chars: int
    results_total_chars: int
    credit_share: float  # of the run's credit cap, spent by one unit before its tools are withheld
    progress_default: str
    progress: Mapping[str, str] = field(default_factory=dict)
    design_credit_share: float = 0.3

    def line(self, tool: str) -> str:
        """The plain sentence a running call of `tool` is recorded with."""
        return self.progress.get(tool, self.progress_default)


def _count(value: Any, low: int, high: int) -> int | None:
    return value if type(value) is int and low <= value <= high else None


def _int(doc: Mapping[str, Any], key: str, low: int, high: int) -> int:
    value = _count(doc.get(key), low, high)
    if value is None:
        raise ToolLimitsError(f"tool_loop.yaml: {key} must be an integer from {low} to {high}")
    return value


def _line(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 140:
        raise ToolLimitsError(f"tool_loop.yaml: {key} must be one sentence of at most 140 characters")
    return " ".join(value.split())


def load_tool_limits(path: Path | None = None) -> ToolLimits:
    try:
        doc = yaml.safe_load((path or DEFAULT_TOOL_LOOP_CONFIG).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, ValueError) as error:
        raise ToolLimitsError(f"tool_loop.yaml is unusable ({type(error).__name__})") from error
    if not isinstance(doc, dict):
        raise ToolLimitsError("tool_loop.yaml must be a mapping")
    share: Any = doc.get("credit_share")
    if type(share) not in (int, float) or not 0 < float(share) <= 1:
        raise ToolLimitsError("tool_loop.yaml: credit_share must be above 0 and at most 1")
    per_tool = doc.get("calls_per_tool")
    if not isinstance(per_tool, dict) or not all(
        isinstance(name, str) and _count(n, 1, 50) is not None for name, n in per_tool.items()
    ):
        raise ToolLimitsError("tool_loop.yaml: calls_per_tool must map tool names to counts from 1 to 50")
    progress = doc.get("progress")
    design_share = doc.get("design", {}).get("credit_share", 0.3)
    if type(design_share) not in (int, float) or not 0 < design_share < 1:
        raise ToolLimitsError("tool_loop.yaml: design.credit_share must be above zero and below one")
    if not isinstance(progress, dict) or not isinstance(progress.get("tools"), dict):
        raise ToolLimitsError("tool_loop.yaml: progress needs default and tools")
    return ToolLimits(
        rounds=_int(doc, "rounds", 1, 20),
        calls_per_round=_int(doc, "calls_per_round", 1, 20),
        max_tool_calls=_int(doc, "max_tool_calls", 1, 100),
        calls_per_tool=dict(per_tool),
        result_chars=_int(doc, "result_chars", 200, 100_000),
        results_total_chars=_int(doc, "results_total_chars", 200, 400_000),
        credit_share=float(share),
        progress_default=_line(progress.get("default"), "progress.default"),
        progress={str(k): _line(v, f"progress.tools.{k}") for k, v in progress["tools"].items()},
        design_credit_share=float(design_share),
    )
