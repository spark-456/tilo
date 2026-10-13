"""COST-AUDIT (user rule: make credits last), from the Opus cost audit of a live run.

(a) The driver ran a Lead review at EVERY district's last unit (6 reviews for ~8 units). The rule now: a district
    with at least two units gets one review, at its last unit; a one-unit district has nothing to review beyond the
    unit itself (PRD 8.2: Leads review "at milestones, not every step, to bound cost"). One helper in `tilo_harness`
    states the rule; the e2e driver calls it. The review call goes on the cheap `lead_review` role (lite tier in
    `config/models*.yaml`; a model id never appears in code).
(b) The credit estimate no longer assumes every Director call fills its whole output cap: it uses the p90 output tokens
    per role in `evals/live_usage_p90.json` plus ONE repair attempt per call; the cap-based figure stays as the hard
    upper bound the estimate can never exceed.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from _live_e2e_lib import REAL_MODELS, REAL_PRICES, network_guard  # noqa: F401  (autouse fixture)
from tilo_evals import live_e2e
from tilo_providers.config import load_providers_config

REPO = Path(__file__).resolve().parents[2]


def _plan() -> list[dict[str, Any]]:
    """District D1 has one unit, D2 two (a chain), D3 three (a chain): 6 units, 3 districts with a unit chain each."""

    def unit(uid: str, district: str, after: list[str]) -> dict[str, Any]:
        return {
            "id": uid, "title": f"Title {uid}", "unit_type": "draft", "role": "writer",
            "district": district, "depends_on": after,
        }  # fmt: skip

    return [
        unit("U1", "D1", []),
        unit("U2", "D2", []), unit("U3", "D2", ["U2"]),
        unit("U4", "D3", []), unit("U5", "D3", ["U4"]), unit("U6", "D3", ["U5"]),
    ]  # fmt: skip


def test_COST_AUDIT_lead_reviews_only_districts_with_two_or_more_units() -> None:
    from tilo_harness.lead_review import review_milestones

    assert review_milestones(_plan()) == {"U3", "U6"}  # one each for D2 and D3; D1's lone unit gets none


def test_COST_AUDIT_a_district_with_parallel_ends_is_reviewed_once() -> None:
    from tilo_harness.lead_review import review_milestones

    units = [
        {"id": "A", "district": "D", "depends_on": []},
        {"id": "B", "district": "D", "depends_on": ["A"]},
        {"id": "C", "district": "D", "depends_on": ["A"]},  # B and C both end the district
    ]
    assert review_milestones(units) == {"C"}  # the last in plan order, once per district


def test_COST_AUDIT_the_driver_uses_the_shared_helper_and_the_lite_lead_review_role() -> None:
    from tilo_harness import lead_review

    assert live_e2e.review_milestones is lead_review.review_milestones
    assert live_e2e.REVIEW_ROLE == lead_review.REVIEW_ROLE == "lead_review"


@dataclasses.dataclass
class _Context:
    skills: list[Any] = dataclasses.field(default_factory=list)
    brief: Any = None
    intake_answers: Any = ()
    upstream: Any = ()


def test_COST_AUDIT_the_driver_makes_one_lead_review_per_multi_unit_district() -> None:
    asked: list[str] = []

    class Runner(live_e2e._UnitRunner):
        def _ask(self, role: str, prompt: str) -> tuple[str, float]:
            asked.append(role)
            return f"{role} text", 0.1

    runner = Runner(router=None, meter=None)  # type: ignore[arg-type]

    class _Shared:  # the unit's own call goes through the shared ToolUnitRunner (LW-07): count it as a role call
        async def run_unit(self, unit: Any, context: Any) -> Any:
            asked.append(unit["role"])
            item = SimpleNamespace(content=b"text")
            return SimpleNamespace(outcome=SimpleNamespace(success=True, outputs=(item,)), credits=0.1)

    runner._shared = _Shared()  # type: ignore[assignment]
    units = _plan()
    runner.capture({"goal": "g"}, {"units": units})
    context = _Context()
    for unit in units:
        asyncio.run(runner.run(unit, context))
    assert asked.count("lead_review") == 2 and "lead" not in asked
    assert asked.count("writer") == 6


def test_COST_AUDIT_every_models_file_puts_the_lead_review_on_the_lite_tier() -> None:
    for name in ("models.yaml", "models.gemini.yaml", "models.nim.yaml"):
        raw = yaml.safe_load((REPO / "config" / name).read_text(encoding="utf-8"))
        roles = raw["roles"]
        assert "lead_review" in roles, name
        assert roles["lead_review"]["primary"] == roles["narrator"]["primary"], f"{name}: the narrator's cheap tier"
        assert not roles["lead_review"].get("thinking"), name


def _estimate(chars: int = 1200, **kwargs: Any) -> live_e2e.Estimate:
    return live_e2e._estimate_chars(load_providers_config(REAL_MODELS, REAL_PRICES), chars, **kwargs)


def test_COST_AUDIT_the_estimate_is_below_the_old_cap_bound_and_above_the_p90_sum() -> None:
    bound = _estimate(at_cap=True)  # the old figure: every call fills its whole output cap
    now = _estimate()
    assert now.credits_low == pytest.approx(bound.credits_low)  # the low case never used the caps
    assert now.credits_low < now.credits_high < bound.credits_high
    # the p90 sum: one attempt per call, no repair, at the p90 output of each role
    once = _estimate(repairs=0)
    assert once.credits_high < now.credits_high, "one repair attempt per call is counted on top"
    assert once.credits_high > now.credits_low


def test_COST_AUDIT_the_p90_file_states_its_provenance_and_covers_every_estimated_role() -> None:
    data = json.loads((REPO / "evals" / "live_usage_p90.json").read_text(encoding="utf-8"))
    assert isinstance(data["provenance"], str) and len(data["provenance"]) > 40
    roles = data["output_tokens_p90"]
    assert {"director", "writer", "lead_review", "narrator"} <= set(roles)
    assert all(isinstance(v, int) and 0 < v for v in roles.values())


def test_COST_AUDIT_a_role_cap_below_its_p90_is_the_most_the_estimate_counts(tmp_path: Path) -> None:
    raw = yaml.safe_load(REAL_MODELS.read_text(encoding="utf-8"))
    raw["roles"]["director"]["max_output_tokens"] = 100  # far under the p90
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    config = load_providers_config(path, REAL_PRICES)
    low_cap = live_e2e._estimate_chars(config, 1200).credits_high
    assert low_cap < _estimate().credits_high  # the cap still bounds the estimate (min of p90 and cap)
