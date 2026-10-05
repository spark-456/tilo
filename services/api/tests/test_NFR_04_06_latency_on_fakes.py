"""NFR-04 and NFR-06 (PRD 17.1), measured on the scripted fakes (no model, no network): the part of each path
that tilo-api and the run machinery own. Written from the PRD text before any builder touches it (tests/NFR-batch-1).

- NFR-04 "Approval -> world visible: <= 6 s p95": from `POST /tasks/{id}/approve` until the world has started
  (`world.started` is on record) AND its layout is served (`GET /worlds/{id}/layout` is 200).
- NFR-06 "Card answered (any channel) -> agent resumes: <= 2 s p95": from `POST .../cards/{id}/answer` (the web
  channel; WhatsApp and email add their own hop) until the run records anything after `approval.resolved`.

These are a lower bound: the live Director, real queues and the network add to them, so the target is also
measured on tilo-dev after the deploy (docs/open-questions.md). A fake that is slow here is a bug in the path.
"""

from __future__ import annotations

import math
import time

from _clint2_lib import REPO_ROOT, build_run_flow
from tilo_api import app

RUNS = 20


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]


def _until(condition, *, within_s: float, what: str) -> float:
    start = time.perf_counter()
    while not condition():
        assert time.perf_counter() - start < within_s, f"{what}: not within {within_s} s"
        time.sleep(0.001)
    return time.perf_counter() - start


def test_NFR_04_approval_to_a_visible_world_is_within_6_s_at_p95():
    samples = []
    for _ in range(RUNS):
        rf = build_run_flow(REPO_ROOT)
        try:
            rf.start()
            started = time.perf_counter()
            assert rf.approve().status_code == 200
            _until(
                lambda rf=rf: (
                    rf.events("world.started")
                    and rf.flow.client.get(f"/worlds/{rf.world_id}/layout").status_code == 200
                ),
                within_s=30,
                what="the world is visible",
            )
            samples.append(time.perf_counter() - started)
        finally:
            rf.close()
            app.dependency_overrides.clear()
    assert _p95(samples) <= 6.0, f"p95 {_p95(samples):.2f} s over {RUNS} runs (max {max(samples):.2f} s)"


def test_NFR_06_a_card_answered_resumes_the_agent_within_2_s_at_p95():
    samples = []
    for _ in range(RUNS):
        rf = build_run_flow(REPO_ROOT)
        try:
            _, card = rf.run_to_gate()
            answered = time.perf_counter()
            assert rf.answer(card["id"], "approve").status_code == 200

            def resumed(rf=rf) -> bool:
                types = rf.types()
                return "approval.resolved" in types and len(types) > types.index("approval.resolved") + 1

            _until(resumed, within_s=30, what="the agent resumes")
            samples.append(time.perf_counter() - answered)
        finally:
            rf.close()
            app.dependency_overrides.clear()
    assert _p95(samples) <= 2.0, f"p95 {_p95(samples):.2f} s over {RUNS} runs (max {max(samples):.2f} s)"
