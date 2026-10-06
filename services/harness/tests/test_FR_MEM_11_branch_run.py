"""FR-MEM-11 (PRD 13.4 "Runs: restart from any checkpoint as a new branch of the run", PRD 13.5): "The branch reuses
finished units and credits them as saved."

Given a run whose units finished (handed over and passed the Verifier) or did not (failed, skipped, reviewed as failed),
When a branch run starts from that run's checkpoint, Then every finished and unchanged unit is not executed, counts as a
success with the parent's artifact versions and is credited as saved through exactly one `memory.hit`
(`saved = origin_cost - lookup_cost`, EV-09), while every other unit runs normally and its dependents run after it.

THE INTERFACE THESE TESTS PIN is in `services/harness/tests/API_FR_MEM_11.md` (names are the tests' choice and the
builder may override them, updating the tests in the same PR). In short:

    tilo_harness.branch.checkpoint_from_events(events, plan, *, run_id=None) -> Checkpoint
    tilo_harness.branch.unit_digest(unit) -> str                    (sha256 hex of the canonical unit spec)
    run_plan(..., reuse=Checkpoint | None)                          the new run id is the writer's own `run_id`
    RunResult.reused: list[str]

No contract change and no API route. Fakes only: in-memory event store and artifact store, a scripted verifier model,
no network, no paid call. Like the other harness support modules, nothing from the new feature is imported at module
level, so each test fails on the missing feature (ModuleNotFoundError for `tilo_harness.branch`, a TypeError for
`run_plan(reuse=)`) and never on a typo here.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from agt_output_support import ORG, make_rig, outcome, unit_output
from agt_scripted import ScriptedProvider
from agt_support import (
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from agt_verifier_support import VERIFIER, build_manifest, claim, deliverable_of, make_verifier, note_for
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

WORLD = "w_branch"
PARENT, BRANCH = "r_parent", "r_branch"
ALL_UNITS = ["U1", "U2", "U3", "U4", "U5", "U6"]  # the layout has a worker for each; a plan uses a prefix or a subset
LENIENT = json.dumps({"verdict": "supported"})  # a verifier model that approves what rules 1-3 leave standing
NO_SHRINK = (Phase.explicit, Phase.reuse, Phase.generate)

# The standard plan: U1 -> U2 -> U3 -> U5, and U4 on its own. Credits are what each unit's runner reports (carried on
# the unit's first artifact event, ADR-0018 s6), so a unit's origin cost is exactly this number.
BASE = ["U1", "U2", "U3", "U4", "U5"]
DEPENDS = {"U2": ["U1"], "U3": ["U2"], "U5": ["U3"], "U6": ["U4"]}
CREDITS = {"U1": 7.0, "U2": 4.5, "U3": 3.0, "U4": 2.25, "U5": 1.0, "U6": 0.5}
OUTPUTS = {"U1": 2}  # U1 makes two artifacts: its credits still count once, on the first (origin cost 7, not 14)


# --- the world, the plan, the runner ---


@dataclass
class Env:
    layout: dict[str, Any]
    config: Any
    registry: Any
    store: Any  # the harness MemoryStore of events: the parent and every branch share it (one world)
    rig: Any  # the artifact store, scope and redactor
    workers: dict[str, str]  # unit -> the worker the layout gives it when the unit is in plan position of ALL_UNITS

    def events(self, run_id: str | None = None) -> list[dict[str, Any]]:
        stream = self.store.read_events(ORG, WORLD)
        return stream if run_id is None else [e for e in stream if e["run_id"] == run_id]

    def plan(
        self,
        *,
        drop: tuple[str, ...] = (),
        add: dict[str, list[str]] | None = None,
        titles: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        ids = [u for u in BASE if u not in drop] + list(add or {})
        deps = DEPENDS | (add or {})
        units = [
            build_unit(
                u, depends_on=[d for d in deps.get(u, []) if d in ids], district="D1", title=(titles or {}).get(u)
            )
            for u in ids
        ]
        return build_plan(units)


def make_env(tmp_path: Path) -> Env:
    from tilo_harness.store import MemoryStore

    specialists = [f"A_s{i}" for i in range(len(ALL_UNITS))]
    layout = build_layout(
        world_id=WORLD,
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": specialists, "unit_ids": ALL_UNITS}],
        extra_agents=[{"id": VERIFIER, "rank": "verifier"}],
    )
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    registry = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    return Env(
        layout, config, registry, MemoryStore(), make_rig(world_id=WORLD), dict(zip(BASE, specialists, strict=False))
    )


class Script:
    """A UnitRunner double. `kinds[unit]`: "ok" (default; a clean artifact), "bad" (an artifact with a planted wrong
    number: the Verifier fails it), "fail" (the unit fails) or "none" (it succeeds and hands over nothing). With
    `select`, a unit names the latest artifact each unit it depends on made, found in the world's stream, so a unit
    run in a branch can name a version made in the parent run (EV-15)."""

    def __init__(self, env: Env, kinds: dict[str, str] | None = None, *, select: bool = True) -> None:
        self.env, self.kinds, self.select = env, kinds or {}, select
        self.calls: list[str] = []

    def _selected(self, unit: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        refs = []
        for dep in unit["depends_on"]:
            made = [
                e for e in self.env.events() if e["type"] == "artifact.created" and e["actor"] == self.env.workers[dep]
            ]
            if made:
                refs.append(dict(made[-1]["data"]["artifact"]))
        return tuple(refs)

    async def run(self, unit: dict[str, Any], context: Any) -> Any:
        unit_id = unit["id"]
        self.calls.append(unit_id)
        await asyncio.sleep(0)
        kind = self.kinds.get(unit_id, "ok")
        if kind == "fail":
            return outcome((), success=False, summary=f"{unit_id} failed.")
        if kind == "none":
            return outcome((), credits=CREDITS[unit_id], summary=f"{unit_id} made nothing.")
        prefix = "bad" if kind == "bad" else "ok"
        outputs = [unit_output(f"{prefix}:{unit_id}:{i}".encode()) for i in range(OUTPUTS.get(unit_id, 1))]
        refs = self._selected(unit) if self.select else ()
        return outcome(outputs, refs=refs, credits=CREDITS[unit_id], summary=f"Finished {unit_id}.")


def _loader(env: Env):
    """The Verifier's deliverable loader: content that starts with "bad" claims a number no source holds."""

    def load(ref: dict[str, Any]) -> Any:
        text = WRONG_CLAIM if env.rig.store.read(env.rig.scope, ref).startswith(b"bad") else GOOD_CLAIM
        source = note_for(5)
        manifest = build_manifest(
            artifact_id=ref["artifact_id"], sources={"src_a": source}, claims=[claim("cl_1", text, ["src_a"])]
        )
        return deliverable_of(manifest, {"src_a": source})

    return load


GOOD_CLAIM = "Firm Faa reported revenue of 45 million."
WRONG_CLAIM = "Firm Faa reported revenue of 945 million."


def run(
    env: Env,
    run_id: str,
    script: Script,
    *,
    plan: dict[str, Any] | None = None,
    reuse: Any = None,
    verify: bool = True,
    model: ScriptedProvider | None = None,
) -> Any:
    """One `run_plan` of `plan` under `run_id` in the shared world (a fresh writer on the shared event store)."""
    from tilo_harness.executor import run_plan
    from tilo_harness.writer import WorldWriter

    writer = WorldWriter(
        env.store, org_id=ORG, world_id=WORLD, run_id=run_id, layout=env.layout, writer_id=f"w_{run_id}"
    )
    writer.open()
    kwargs: dict[str, Any] = {"artifacts": env.rig.store, "scope": env.rig.scope, "redact": env.rig.redactor}
    if verify:
        kwargs["verifier"], _ = make_verifier(model or ScriptedProvider(default=LENIENT), load=_loader(env))
    if reuse is not None:
        kwargs["reuse"] = reuse
    try:
        return asyncio.run(
            asyncio.wait_for(
                run_plan(
                    plan or env.plan(),
                    env.layout,
                    writer=writer,
                    config=env.config,
                    skills=env.registry,
                    runner=script,
                    **kwargs,
                ),
                30,
            )
        )
    finally:
        writer.close()


def checkpoint(env: Env, *, plan: dict[str, Any] | None = None, run_id: str | None = PARENT) -> Any:
    from tilo_harness.branch import checkpoint_from_events

    return checkpoint_from_events(env.events(), plan or env.plan(), run_id=run_id)


@dataclass
class Scenario:
    env: Env
    parent: Any  # RunResult
    parent_script: Script
    cp: Any  # Checkpoint
    branch: Any  # RunResult
    branch_script: Script
    branch_model: ScriptedProvider

    def hits(self) -> list[dict[str, Any]]:
        return [e for e in self.env.events(BRANCH) if e["type"] == "memory.hit"]

    def hit_of(self, unit_id: str) -> dict[str, Any]:
        worker = self.env.workers[unit_id]
        mine = [e for e in self.hits() if e["actor"] == worker]
        assert len(mine) == 1, f"{unit_id}: {len(mine)} memory.hit events (want exactly one)"
        return mine[0]


def make_scenario(tmp_path: Path, *, parent_kinds: dict[str, str] | None = None) -> Scenario:
    """The parent run: U1, U2, U4 finish and pass review, U3 fails (so U5 is skipped). The branch: every unit that
    runs now succeeds."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    env = make_env(tmp_path)
    parent_script = Script(env, parent_kinds if parent_kinds is not None else {"U3": "fail"})
    parent = run(env, PARENT, parent_script)
    cp = checkpoint(env)
    branch_script = Script(env)
    branch_model = ScriptedProvider(default=LENIENT)
    branch = run(env, BRANCH, branch_script, reuse=cp, model=branch_model)
    return Scenario(env, parent, parent_script, cp, branch, branch_script, branch_model)


def assert_world_valid(env: Env) -> None:
    """Every event of the world, parent and branch, in order, against the whole EV-01..EV-16 set (EV-10, 11, 15 too)."""
    from tilo_harness.validator import EventValidator, WorldState

    validator = EventValidator.from_repo()
    state = WorldState(env.layout)
    state.world_id = WORLD
    for event in env.events():
        assert validator.problems(event, state) == [], (event["seq"], event["type"])
        state.observe(event)


# --- the checkpoint: what "finished" means, read from events ---


def test_FR_MEM_11_checkpoint_lists_exactly_the_units_handed_over_and_passed_by_the_verifier(
    tmp_path: Path,
) -> None:
    """Finished = an `agent.handoff` from the unit's worker AND an `artifact.reviewed` result "passed" for every
    ref it handed over (FR-MEM-02: a Verifier pass before reuse). U3 failed (no handoff); U5 was skipped (no event)."""
    scenario = make_scenario(tmp_path)
    cp = scenario.cp
    assert cp.parent_run_id == PARENT
    assert set(cp.units) == {"U1", "U2", "U4"}
    for unit_id, finished in cp.units.items():
        assert finished.unit_id == unit_id
        assert list(finished.artifact_refs) == list(scenario.parent.outcomes[unit_id].artifact_refs) != []


def test_FR_MEM_11_checkpoint_origin_cost_is_the_credits_on_the_units_own_events(tmp_path: Path) -> None:
    """Origin cost = the sum of `credits` on the unit's events in the parent run. U1 made two artifacts and its credits
    ride on the first only, so it counts once (7, not 14); no unit's cost leaks into another's."""
    scenario = make_scenario(tmp_path)
    assert {u: f.origin_cost for u, f in scenario.cp.units.items()} == {"U1": 7.0, "U2": 4.5, "U4": 2.25}


def test_FR_MEM_11_checkpoint_names_the_parents_handoff_event_of_each_unit(tmp_path: Path) -> None:
    scenario = make_scenario(tmp_path)
    by_id = {e["id"]: e for e in scenario.env.events(PARENT)}
    for unit_id, finished in scenario.cp.units.items():
        handoff = by_id[finished.handoff_event_id]
        assert handoff["type"] == "agent.handoff" and handoff["actor"] == scenario.env.workers[unit_id]


def test_FR_MEM_11_checkpoint_digest_is_the_digest_of_the_plans_unit(tmp_path: Path) -> None:
    scenario = make_scenario(tmp_path)
    from tilo_harness.branch import unit_digest

    plan = scenario.env.plan()
    for unit in plan["units"]:
        if unit["id"] in scenario.cp.units:
            assert scenario.cp.units[unit["id"]].spec_digest == unit_digest(unit)


def test_FR_MEM_11_unit_digest_is_stable_and_changes_with_the_spec() -> None:
    from tilo_harness.branch import unit_digest

    unit = build_unit("U1", depends_on=["U0"], skills=[], district="D1")
    digest = unit_digest(unit)
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert unit_digest(json.loads(json.dumps(unit))) == digest, "a copy of the same spec"
    assert unit_digest(dict(reversed(list(unit.items())))) == digest, "key order is not part of the spec"
    for field, other in (("title", "Another title"), ("depends_on", []), ("role", "writer"), ("district", "D2")):
        assert unit_digest(dict(unit, **{field: other})) != digest, f"changing {field} changes the digest"


def test_FR_MEM_11_checkpoint_is_deterministic(tmp_path: Path) -> None:
    scenario = make_scenario(tmp_path)
    assert checkpoint(scenario.env) == scenario.cp


def test_FR_MEM_11_unit_failing_review_or_reviewed_as_unverified_is_not_finished(tmp_path: Path) -> None:
    """DECISION (PRD 13.4 silent on "finished"; FR-MEM-02): a unit whose Verifier result is not "passed" is not
    finished, even though it handed over and its dependents ran. U1 is "bad" (result failed)."""
    env = make_env(tmp_path)
    run(env, PARENT, Script(env, {"U1": "bad"}, select=False))
    assert set(checkpoint(env).units) == {"U2", "U3", "U4", "U5"}


def test_FR_MEM_11_checkpoint_of_a_run_nobody_verified_has_no_finished_unit(tmp_path: Path) -> None:
    """Without a Verifier there is no `artifact.reviewed`: nothing is verified, so nothing can be reused (FR-MEM-02)."""
    env = make_env(tmp_path)
    run(env, PARENT, Script(env), verify=False)
    cp = checkpoint(env)
    assert cp.parent_run_id == PARENT and dict(cp.units) == {}


def test_FR_MEM_11_checkpoint_ignores_a_unit_that_handed_over_nothing(tmp_path: Path) -> None:
    """DECISION: a unit that succeeded with no artifact has nothing a Verifier reviewed and nothing to reuse, so it is
    not finished (re-running it is the safe reading of "finished and verified")."""
    env = make_env(tmp_path)
    run(env, PARENT, Script(env, {"U4": "none"}))
    assert set(checkpoint(env).units) == {"U1", "U2", "U3", "U5"}


def test_FR_MEM_11_checkpoint_only_lists_units_of_the_given_plan(tmp_path: Path) -> None:
    scenario = make_scenario(tmp_path)
    cp = checkpoint(scenario.env, plan=scenario.env.plan(drop=("U4", "U5")))
    assert set(cp.units) == {"U1", "U2"}


def test_FR_MEM_11_checkpoint_run_id_picks_the_parent_in_a_world_with_two_runs(tmp_path: Path) -> None:
    scenario = make_scenario(tmp_path)
    from tilo_harness.branch import checkpoint_from_events

    events, plan = scenario.env.events(), scenario.env.plan()
    assert checkpoint_from_events(events, plan, run_id=PARENT) == scenario.cp
    assert checkpoint_from_events(scenario.env.events(PARENT), plan) == scenario.cp, "no run_id: the stream is one run"
    with pytest.raises(ValueError):
        checkpoint_from_events(events, plan)  # two runs and no run_id: ambiguous, refused
    with pytest.raises(ValueError):
        checkpoint_from_events(events, plan, run_id="r_nobody")  # a run the stream does not hold
    with pytest.raises(ValueError):
        checkpoint_from_events([], plan)


# --- the branch: reuse, credit, honesty ---


def test_FR_MEM_11_branch_reuses_finished_units_and_credits_them_as_saved(tmp_path: Path) -> None:
    """The acceptance test (PRD 13.5): U1, U2 and U4 finished in the parent and are not run again; U3 (failed) and U5
    (skipped) run. The branch credits exactly what the three reused units cost the first time."""
    scenario = make_scenario(tmp_path)
    assert scenario.branch_script.calls == ["U3", "U5"], "the runner is never called for a finished unit"
    assert sorted(scenario.branch.reused) == ["U1", "U2", "U4"]
    assert all(scenario.branch.outcomes[u].success for u in BASE), "a reused unit counts as a success"
    assert scenario.branch.failed == [] and scenario.branch.skipped == []

    assert len(scenario.hits()) == 3
    saved_by_unit = {u: scenario.hit_of(u)["data"]["saved"] for u in ("U1", "U2", "U4")}
    assert saved_by_unit == {"U1": 7.0, "U2": 4.5, "U4": 2.25}

    from tilo_metering.savings import credits_saved

    branch_events, all_events = scenario.env.events(BRANCH), scenario.env.events()
    assert credits_saved(branch_events) == pytest.approx(13.75)
    assert credits_saved(all_events, run_id=BRANCH) == pytest.approx(13.75)
    assert credits_saved(all_events, run_id=PARENT) == 0, "the parent run itself saved nothing"
    assert [e for e in scenario.env.events(PARENT) if e["type"] == "memory.hit"] == []


def test_FR_MEM_11_cost_report_credits_the_branch_run_with_the_sum_of_saved(tmp_path: Path) -> None:
    scenario = make_scenario(tmp_path)
    from tilo_metering.costs import cost_report

    report = cost_report([], scenario.env.events(), unit_types={}, credit_usd=0.005)
    assert report["totals"]["credits_saved"] == pytest.approx(13.75)
    assert report["totals"]["usd_saved"] == pytest.approx(13.75 * 0.005)
    assert {t["run_id"]: t["credits_saved"] for t in report["tasks"]} == {BRANCH: pytest.approx(13.75)}


def test_FR_MEM_11_reused_units_cost_nothing_in_the_branch(tmp_path: Path) -> None:
    """The meter (`credits` on events) of the branch is only what the units that ran spent: U3 (3) and U5 (1)."""
    scenario = make_scenario(tmp_path)
    assert sum(e["credits"] for e in scenario.env.events(BRANCH)) == pytest.approx(4.0)
    assert all(e["credits"] == 0 for e in scenario.hits()), "a reuse spends nothing; its figure is `data.saved`"


def test_FR_MEM_11_memory_hit_data_is_origin_cost_minus_a_zero_lookup_cost(tmp_path: Path) -> None:
    """lookup_cost is 0: a checkpoint lookup reads events already recorded and compares a digest, and the Verifier pass
    it relies on was paid for by the parent, so no metered call happens (see API_FR_MEM_11.md). EV-09 holds."""
    scenario = make_scenario(tmp_path)
    for unit_id, finished in scenario.cp.units.items():
        data = scenario.hit_of(unit_id)["data"]
        assert data == {"origin_cost": finished.origin_cost, "lookup_cost": 0, "saved": finished.origin_cost}
        assert math.isclose(data["saved"], data["origin_cost"] - data["lookup_cost"], abs_tol=1e-9)


def test_FR_MEM_11_memory_hit_is_valid_against_the_contracts_and_the_whole_world_replays_valid(
    tmp_path: Path,
) -> None:
    scenario = make_scenario(tmp_path)
    from tilo_contracts import EVENT_DATA_MODELS, Event
    from tilo_harness.validator import EventValidator

    validator = EventValidator.from_repo()
    for hit in scenario.hits():
        assert validator.problems(hit) == []
        EVENT_DATA_MODELS["memory.hit"].model_validate(hit["data"])  # additionalProperties false: no extra field
        Event.model_validate(hit)  # the envelope
        assert set(hit["data"]) == {"origin_cost", "lookup_cost", "saved"}
        assert hit["run_id"] == BRANCH and hit["world_id"] == WORLD
        assert hit["actor"] == hit["target"] and hit["district"] == "D1" and hit["level"] == "L1"
        assert hit["authz"] is None and hit["severity"] == "info" and hit["vis"] == "all" and hit["item"] is None
    assert_world_valid(scenario.env)
    assert [e["seq"] for e in scenario.env.events()] == list(range(1, len(scenario.env.events()) + 1))


def test_FR_MEM_11_memory_hit_is_caused_by_the_parents_handoff_of_that_unit(tmp_path: Path) -> None:
    """The Trace can link a reuse to the work it reuses: `cause` is the parent's `agent.handoff` of the unit (EV-11: an
    earlier event of the same world)."""
    scenario = make_scenario(tmp_path)
    for unit_id, finished in scenario.cp.units.items():
        assert scenario.hit_of(unit_id)["cause"] == finished.handoff_event_id


def test_FR_MEM_11_summary_says_it_reused_a_finished_unit_from_the_earlier_run(tmp_path: Path) -> None:
    scenario = make_scenario(tmp_path)
    for hit in scenario.hits():
        text = hit["summary"].lower()
        assert "reused" in text and "earlier run" in text and len(hit["summary"]) <= 140, hit["summary"]


def test_FR_MEM_11_a_reused_unit_is_recorded_only_by_its_memory_hit(tmp_path: Path) -> None:
    """HR-1: no animation without an event, and no event for work that did not happen. A reused unit has no
    agent.spawned, assigned, working, handoff or retired, no artifact event and no review in the branch: its only event
    is the `memory.hit` (its artifacts already exist; re-announcing them would break EV-15)."""
    scenario = make_scenario(tmp_path)
    for unit_id in ("U1", "U2", "U4"):
        worker = scenario.env.workers[unit_id]
        mine = [e for e in scenario.env.events(BRANCH) if worker in (e["actor"], e["target"])]
        assert [e["type"] for e in mine] == ["memory.hit"], (unit_id, [e["type"] for e in mine])
    reused_artifacts = {r["artifact_id"] for f in scenario.cp.units.values() for r in f.artifact_refs}
    announced = [e for e in scenario.env.events(BRANCH) if e["type"] in ("artifact.created", "artifact.versioned")]
    assert announced and not [e for e in announced if e["target"] in reused_artifacts], "nothing is announced twice"


def test_FR_MEM_11_reused_units_are_not_reviewed_or_modelled_again(tmp_path: Path) -> None:
    """The Verifier already passed them in the parent. In the branch it reviews only what the units that ran handed
    over (the usual FR-AGT-12 rule, one claim and so one model call per review); U1 and U4 are named by nobody that ran,
    so their artifacts are not reviewed at all, and no reused unit's own handoff exists to cause a review."""
    scenario = make_scenario(tmp_path)
    env = scenario.env
    handoffs = {e["id"] for e in env.events(BRANCH) if e["type"] == "agent.handoff"}
    reviewed = [e for e in env.events(BRANCH) if e["type"] == "artifact.reviewed"]
    assert reviewed and all(e["cause"] in handoffs for e in reviewed)
    untouched = {r["artifact_id"] for u in ("U1", "U4") for r in scenario.cp.units[u].artifact_refs}
    assert {e["target"] for e in reviewed}.isdisjoint(untouched)
    assert scenario.branch_model.call_count == len(reviewed)


def test_FR_MEM_11_dependent_of_a_reused_unit_runs_after_the_hit_and_names_the_parents_version(
    tmp_path: Path,
) -> None:
    """EV-15 (the branch shares the parent's world): U3 depends on reused U2 and selects U2's version made in the
    parent run. The world recorded it, so U3 succeeds and its handoff carries that exact ref."""
    scenario = make_scenario(tmp_path)
    env = scenario.env
    u2_ref = next(
        dict(e["data"]["artifact"])
        for e in env.events(PARENT)
        if e["type"] == "artifact.created" and e["actor"] == env.workers["U2"]
    )
    u3_handoff = next(e for e in env.events(BRANCH) if e["type"] == "agent.handoff" and e["actor"] == env.workers["U3"])
    assert u2_ref in u3_handoff["data"]["envelope"]["artifact_refs"]
    assert scenario.branch.outcomes["U3"].success and u2_ref in list(scenario.branch.outcomes["U3"].artifact_refs)
    u2_hit = scenario.hit_of("U2")
    u3_assigned = next(e for e in env.events(BRANCH) if e["type"] == "agent.assigned" and e["data"]["unit"] == "U3")
    assert u2_hit["seq"] < u3_assigned["seq"], "dependents start only after the reuse is recorded"


def test_FR_MEM_11_the_branch_shares_the_parents_world_and_its_events_continue_the_sequence(tmp_path: Path) -> None:
    """PINNED (EV-15 choice): one world, two runs. Same `world_id` throughout, `seq` continues from the parent's last
    (EV-10), the branch's run id differs from the parent's, and no artifact is imported or copied."""
    scenario = make_scenario(tmp_path)
    parent_events, branch_events = scenario.env.events(PARENT), scenario.env.events(BRANCH)
    assert {e["world_id"] for e in scenario.env.events()} == {WORLD}
    assert branch_events[0]["seq"] == parent_events[-1]["seq"] + 1
    assert {e["run_id"] for e in scenario.env.events()} == {PARENT, BRANCH}


def test_FR_MEM_11_failed_unit_of_the_parent_reruns_and_so_do_its_dependents(tmp_path: Path) -> None:
    scenario = make_scenario(tmp_path)
    ran = {e["data"]["unit"] for e in scenario.env.events(BRANCH) if e["type"] == "agent.working"}
    assert ran == {"U3", "U5"}
    assert sorted(scenario.parent_script.calls) == ["U1", "U2", "U3", "U4"], "U5 was skipped in the parent"


# --- edge cases ---


def test_FR_MEM_11_empty_checkpoint_reruns_everything_with_zero_hits(tmp_path: Path) -> None:
    from tilo_harness.branch import Checkpoint

    env = make_env(tmp_path)
    script = Script(env)
    result = run(env, BRANCH, script, reuse=Checkpoint(parent_run_id=PARENT, units={}))
    assert sorted(script.calls) == BASE and result.reused == []
    assert [e for e in env.events(BRANCH) if e["type"] == "memory.hit"] == []
    assert all(result.outcomes[u].success for u in BASE)


def test_FR_MEM_11_every_unit_finished_runs_nothing_and_every_unit_is_a_hit(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    run(env, PARENT, Script(env))
    cp = checkpoint(env)
    assert set(cp.units) == set(BASE)
    script = Script(env)
    model = ScriptedProvider(default=LENIENT)
    result = run(env, BRANCH, script, reuse=cp, model=model)
    assert script.calls == [] and model.call_count == 0, "no unit work and no verifier call"
    assert sorted(result.reused) == BASE and all(result.outcomes[u].success for u in BASE)
    hits = [e for e in env.events(BRANCH) if e["type"] == "memory.hit"]
    assert len(hits) == len(BASE)
    assert {e["type"] for e in env.events(BRANCH)} <= {"agent.spawned", "memory.hit"}, "only the team and the hits"
    assert sum(h["data"]["saved"] for h in hits) == pytest.approx(sum(CREDITS[u] for u in BASE))
    assert_world_valid(env)


def test_FR_MEM_11_a_unit_whose_spec_changed_reruns_and_so_does_everything_downstream_of_it(tmp_path: Path) -> None:
    """A unit whose plan definition changed since the checkpoint is never reused (the digest differs). DECISION:
    neither is a unit that depends on a unit that runs: its input is about to change, so reusing it would credit
    stale work. Here only U4 is independent of U1."""
    env = make_env(tmp_path)
    run(env, PARENT, Script(env))
    cp = checkpoint(env)
    assert set(cp.units) == set(BASE)
    script = Script(env)
    changed = env.plan(titles={"U1": "A changed title"})
    result = run(env, BRANCH, script, plan=changed, reuse=cp)
    assert sorted(script.calls) == ["U1", "U2", "U3", "U5"]
    assert result.reused == ["U4"]
    assert [e["data"]["saved"] for e in env.events(BRANCH) if e["type"] == "memory.hit"] == [CREDITS["U4"]]


def test_FR_MEM_11_units_not_in_the_plan_are_ignored_and_new_units_run(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    run(env, PARENT, Script(env))
    cp = checkpoint(env)
    script = Script(env)
    # U5 left the plan; U6 (depends on U4) is new: it is not in the checkpoint, so it runs.
    plan = env.plan(drop=("U5",), add={"U6": ["U4"]})
    result = run(env, BRANCH, script, plan=plan, reuse=cp)
    assert script.calls == ["U6"]
    assert sorted(result.reused) == ["U1", "U2", "U3", "U4"], "nothing is credited for U5, which is not in this plan"
    assert "U5" not in result.outcomes and result.outcomes["U6"].success
    assert len([e for e in env.events(BRANCH) if e["type"] == "memory.hit"]) == 4


def test_FR_MEM_11_a_finished_unit_whose_versions_the_world_never_recorded_is_not_reused(tmp_path: Path) -> None:
    """DECISION (fail closed, EV-15): a checkpoint entry naming an artifact version the branch's world has not recorded
    is not reused and not credited: it runs, so does everything downstream of it, and nothing dangles."""
    scenario = make_scenario(tmp_path)
    from tilo_harness.branch import Checkpoint

    env = scenario.env
    ghost = dataclasses.replace(scenario.cp.units["U1"], artifact_refs=({"artifact_id": "art_ghost", "version": 1},))
    cp = Checkpoint(parent_run_id=PARENT, units={**scenario.cp.units, "U1": ghost})
    script = Script(env)
    result = run(env, "r_branch2", script, reuse=cp)
    assert sorted(script.calls) == ["U1", "U2", "U3", "U5"]
    assert result.reused == ["U4"]


def test_FR_MEM_11_same_run_id_as_the_parent_raises_before_anything_is_written(tmp_path: Path) -> None:
    scenario = make_scenario(tmp_path)
    env = scenario.env
    script = Script(env)
    before = env.events()
    with pytest.raises(ValueError):
        run(env, PARENT, script, reuse=scenario.cp)
    assert script.calls == [] and env.events() == before, "refused up front: no event, no unit"


def test_FR_MEM_11_without_reuse_run_plan_is_unchanged(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    script = Script(env)
    result = run(env, PARENT, script)
    assert sorted(script.calls) == BASE and result.reused == []
    assert [e for e in env.events() if e["type"] == "memory.hit"] == []


def test_FR_MEM_11_event_order_is_deterministic(tmp_path: Path) -> None:
    def shape(scenario: Scenario) -> list[tuple[Any, ...]]:
        return [
            (e["type"], e["actor"], e["target"], e["summary"], e["data"] if e["type"] == "memory.hit" else None)
            for e in scenario.env.events(BRANCH)
        ]

    first, second = make_scenario(tmp_path / "a"), make_scenario(tmp_path / "b")
    assert shape(first) == shape(second) and first.branch.reused == second.branch.reused
    assert first.branch_script.calls == second.branch_script.calls


# --- property: the reuse set is exactly "finished, unchanged, and everything it needs reused" ---


unit_count = st.integers(2, 5)


@st.composite
def worlds(draw):
    n = draw(unit_count)
    ids = [f"U{i + 1}" for i in range(n)]
    edges = {u: [d for d in ids[:i] if draw(st.booleans())] for i, u in enumerate(ids)}
    kinds = {u: draw(st.sampled_from(["ok", "ok", "bad", "fail"])) for u in ids}
    changed = {u for u in ids if draw(st.integers(0, 4)) == 0}
    return ids, edges, kinds, changed


@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.too_slow], phases=NO_SHRINK)
@given(world=worlds())
def test_FR_MEM_11_property_reuse_is_exactly_the_finished_unchanged_closed_set(world) -> None:
    """Whatever failed, was reviewed as failed or changed: the units reused are exactly those finished in the parent
    (handed over, passed review), unchanged, with every dependency reused; the runner runs exactly the rest; hits equal
    reused; the credited total equals the reused units' origin costs; `seq` stays strictly increasing."""
    ids, edges, kinds, changed = world
    parent_ok: dict[str, bool] = {}
    finished: dict[str, bool] = {}
    for u in ids:
        parent_ok[u] = kinds[u] != "fail" and all(parent_ok[d] for d in edges[u])
        finished[u] = parent_ok[u] and kinds[u] == "ok"
    reused: dict[str, bool] = {}
    for u in ids:
        reused[u] = finished[u] and u not in changed and all(reused[d] for d in edges[u])
    expected = {u for u in ids if reused[u]}

    with tempfile.TemporaryDirectory() as tmp:
        env = make_env(Path(tmp))
        units = [build_unit(u, depends_on=edges[u], district="D1") for u in ids]
        parent_plan = build_plan(units)
        run(env, PARENT, Script(env, kinds, select=False), plan=parent_plan)
        cp = checkpoint(env, plan=parent_plan)
        assert set(cp.units) == {u for u in ids if finished[u]}

        branch_plan = build_plan(
            [
                build_unit(u, depends_on=edges[u], district="D1", title=("changed" if u in changed else None))
                for u in ids
            ]
        )
        script = Script(env, select=False)
        result = run(env, BRANCH, script, plan=branch_plan, reuse=cp)

        assert set(result.reused) == expected
        assert sorted(script.calls) == sorted(set(ids) - expected)
        hits = [e for e in env.events(BRANCH) if e["type"] == "memory.hit"]
        assert len(hits) == len(expected)
        assert sum(h["data"]["saved"] for h in hits) == pytest.approx(sum(CREDITS[u] for u in expected))
        assert all(result.outcomes[u].success for u in ids)
        assert [e["seq"] for e in env.events()] == list(range(1, len(env.events()) + 1))
        assert_world_valid(env)
