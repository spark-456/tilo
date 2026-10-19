"""NFR-26 (PRD 17.2): "Structured logs with run, world and trace ids", harness half.

A record emitted while `run_plan` works a unit (here from a `UnitRunner`, the one seam a unit's code runs in) comes
out as one JSON line carrying the run's `run_id` and `world_id`, the ones its `WorldWriter` was opened with. The line
shape, key names and the `tilo_logging.configure_logging` entry point are pinned in
tests/repo/test_NFR_26_structured_logs.py (defaults: `severity`, `message`, `run_id`, `world_id`; no id keys outside a
run). The harness has no inbound trace header, so no trace key is asserted here. Two runs at once (asyncio, one
thread) must not see each other's ids.

Fails today with ModuleNotFoundError: tilo_logging does not exist.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
from pathlib import Path
from typing import Any

from agt_support import (
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from conftest import make_memory_writer
from tilo_harness.executor import UnitOutcome, run_plan
from tilo_logging import configure_logging


class _LoggingRunner:
    async def run(self, unit: dict[str, Any], context: Any) -> UnitOutcome:
        log = logging.getLogger("nfr26.unit")
        log.warning("unit %s begins", unit["id"])
        await asyncio.sleep(0)  # let the other run interleave
        log.error("unit %s ends", unit["id"])
        return UnitOutcome(success=True, summary="ok")


def _run_args(tmp_path: Path, world: str, run: str, unit_id: str) -> tuple[Any, dict[str, Any]]:
    layout = build_layout(
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0"], "unit_ids": [unit_id]}], world_id=world
    )
    plan = build_plan([build_unit(unit_id)])
    writer, _ = make_memory_writer(layout, world_id=world, run_id=run)
    config = load_config_sync(write_agents_config(tmp_path / f"agents_{run}.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / f"skills_{run}"))
    return plan, {"layout": layout, "writer": writer, "config": config, "skills": skills, "runner": _LoggingRunner()}


async def _run(plan: dict[str, Any], kw: dict[str, Any]) -> Any:
    return await run_plan(plan, kw.pop("layout"), **kw)


@contextlib.contextmanager
def _captured():
    stream, root = io.StringIO(), logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        configure_logging(stream=stream)
        yield stream
    finally:
        root.handlers[:], root.level = handlers, level


def _records(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().split("\n") if line.strip()]  # every line must be JSON


def test_NFR_26_log_inside_a_harness_run_carries_run_id_and_world_id_and_none_outside(tmp_path: Path) -> None:
    plan, kw = _run_args(tmp_path, "w_nfr26_a", "r_nfr26_a", "U1")
    with _captured() as out:
        logging.getLogger("nfr26.outside").warning("before the run")
        asyncio.run(_run(plan, kw))
        logging.getLogger("nfr26.outside").warning("after the run")
    by_msg = {r["message"]: r for r in _records(out)}
    for message, severity in (("unit U1 begins", "WARNING"), ("unit U1 ends", "ERROR")):
        rec = by_msg[message]
        assert rec["severity"] == severity
        assert (rec["run_id"], rec["world_id"]) == ("r_nfr26_a", "w_nfr26_a")
    for message in ("before the run", "after the run"):
        assert "run_id" not in by_msg[message] and "world_id" not in by_msg[message]


def test_NFR_26_two_runs_at_once_never_share_ids(tmp_path: Path) -> None:
    plan_a, kw_a = _run_args(tmp_path, "w_nfr26_a", "r_nfr26_a", "U1")
    plan_b, kw_b = _run_args(tmp_path, "w_nfr26_b", "r_nfr26_b", "U2")

    async def both() -> None:
        await asyncio.gather(_run(plan_a, kw_a), _run(plan_b, kw_b))

    with _captured() as out:
        asyncio.run(both())
    unit_lines = [r for r in _records(out) if r["message"].startswith("unit U")]
    assert len(unit_lines) == 4
    for rec in unit_lines:
        side = "a" if rec["message"].startswith("unit U1") else "b"
        assert (rec["run_id"], rec["world_id"]) == (f"r_nfr26_{side}", f"w_nfr26_{side}"), rec
