"""WORKSPACE_TOOLS hardening pass (WT-04): a unit taken from a checkpoint was made by an earlier run whose reads are not
known here, so its output counts as private for the units that rest on it (fail closed), like read_external's default.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from tilo_harness.branch import Checkpoint, FinishedUnit
from tilo_harness.executor import UnitOutcome, _Run


def test_WORKSPACE_TOOLS_HARDEN_a_reused_unit_hands_on_a_private_upstream_item() -> None:
    run = object.__new__(_Run)
    run.roster = SimpleNamespace(workers={"U1": "A_s0"})
    run.results = {}
    run.emit = lambda *a, **k: "ev1"  # type: ignore[method-assign]
    finished = FinishedUnit("U1", "d" * 64, (), 2.0, "01JHANDOFF")
    outcome: UnitOutcome = _Run.reuse(
        run, {"id": "U1", "title": "Read", "district": "D1"}, Checkpoint("r_parent", {"U1": finished})
    )
    assert outcome.read_private is True and outcome.read_external is True
    item: Any = run.results["U1"]
    assert item.private is True and item.tainted is True
