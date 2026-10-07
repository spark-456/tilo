"""FR-AGT-09 (PRD 8.5, 8.6; EV-10): context handoff at 70% with a validated note. Acceptance: "Chaos test: forced
handoffs finish with no rework >= 95% (EV-10)".

THE SEAM THESE TESTS PIN (names chosen here; the builder may rename, then updates these tests in the same PR
and says so).
No contract changes: handoff.schema.json, agents.schema.json and the two registered events are used as they are.

    UnitOutcome (tilo_harness.executor) gains two fields, appended with defaults:
        context_share: float | None = None   # share 0..1 of THIS agent's context window used when run() returned
        handoff_note: dict | None = None     # a draft note (handoff.schema.json) when the agent stops UNFINISHED
    UnitContext gains two fields, appended with defaults:
        note: dict | None = None             # the validated note a successor starts from (None for the first agent)
        note_ref: dict | None = None         # that note's artifact_ref
    UnitRunner may define (optional):  async def verify(self, unit, context: UnitContext) -> bool
        the successor's re-run of the note's `verification_to_rerun`; context.agent_id is the successor, context.note
        the note. A runner with no `verify`, or one that raises or returns anything but True, did not verify.

run_plan is the Lead. When `runner.run` returns `handoff_note is not None` (the agent stopped, unfinished):
  1. The share must be a number >= `config.context.handoff_at` (read from config, never 0.70 in code); below it, or
     None, the unit fails closed. A runner that finishes (no note) at any share, e.g. 0.65 after compacting at
     `compact_at`, is NOT a handoff and writes no handoff event.
  2. The Lead validates the note against handoff.schema.json. Invalid: the unit fails closed (`RunResult.failed`,
     dependents skipped), the agent still retires, and nothing handoff-shaped is written (no stored note, no
     `agent.context_handoff_*`, no successor, no `agent.handoff`). Validation comes before the started event.
  3. The note is stored through `artifacts=` as application/json (its parsed bytes equal the note).
     No store: fail closed.
  4. `agent.context_handoff_started` (actor the old agent, data {note, context_pct: int(round(share*100))}).
  5. The successor is the first agent of the unit's rank, in layout order, that works no unit and was not yet used as a
     successor. None left: fail closed, before step 4 (nothing handoff-shaped written). The Lead writes `agent.spawned`
     (actor Lead, target successor) and `agent.assigned` (data {unit}).
  6. `runner.verify(unit, UnitContext(successor, skills, note=note, note_ref=ref))`.
  7. `agent.context_handoff_completed` (actor successor, data {predecessor, note, verification_passed}), then the Lead
     retires the old agent (`agent.retired`).
  8. Verified: `runner.run(unit, UnitContext(successor, skills, note=note, note_ref=ref))` continues the same unit (it
     may hand off again). Not verified: the unit fails closed, `runner.run` is not called for the successor, no
     `agent.handoff` and no artifact event for the unit; both agents retire.
  9. Only the last agent's finished outcome is the unit's outcome: outputs stored and one `agent.handoff` as today.

Everything is a fake: an in-memory store and artifact store, a scripted runner, no network, no model.
"""

from __future__ import annotations

import asyncio
import json
import random
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from agt_output_support import Ran, make_rig
from agt_support import (
    assert_valid_contract,
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from conftest import make_memory_writer
from hypothesis import Phase, given, settings
from hypothesis import strategies as st
from tilo_evals.metrics import RunRecord, compute_metrics
from tilo_harness.executor import UnitOutcome, UnitOutput, run_plan
from tilo_harness.validator import EventValidator

WORLD = "w_handoff"
HANDOFF = ("agent.context_handoff_started", "agent.context_handoff_completed")


class StepRunner:
    """Does `steps` steps per unit; one costs `cost` percent of context, an agent starts at `base` percent. At >= 70%
    with steps left it stops and writes a note. `ledger` holds each executed (unit, step), so a repeat is rework."""

    def __init__(
        self, steps=6, cost=20, base=10, lossy=False, verify_raises=False, share=None, note=None, finish_at=None
    ) -> None:
        self.steps, self.cost, self.base, self.lossy, self.verify_raises = steps, cost, base, lossy, verify_raises
        self.share, self.note, self.finish_at = (
            share,
            note,
            finish_at,
        )  # share/note: a forced report; finish_at: final pct
        self.ledger: list[tuple[str, int]] = []
        self.log: list[str] = []
        self.contexts: list[Any] = []
        self.sent: list[Any] = []  # outcomes built with the new fields (empty while the seam is missing)

    def good_note(self, uid: str, done: int, lossy: bool = False) -> dict[str, Any]:
        shown = done - 1 if lossy else done  # a lossy note forgets a finished step
        progress = [{"unit_id": uid, "summary": f"Step {i} done.", "artifact_refs": []} for i in range(shown)]
        return {
            "goal": f"Finish {uid}",
            "unit_ids": [uid],
            "done": progress,
            "in_progress": [],
            "decisions": ["Write the result as markdown."],
            "open_questions": [],
            "next_steps": [f"Do step {done}."],
            "verification_to_rerun": [{"step": "Count the finished steps.", "expected": f"{done} finished"}],
            "gotchas": ["A step is not safe to repeat."],
        }

    def sent_outcome(self, **fields: Any) -> Any:
        outcome = UnitOutcome(**fields)  # TypeError while UnitOutcome lacks the seam's fields
        self.sent.append(outcome)
        return outcome

    async def run(self, unit: dict[str, Any], context: Any) -> Any:
        uid = unit["id"]
        self.log.append(f"run:{context.agent_id}")
        self.contexts.append(context)
        await asyncio.sleep(0)
        start = len(context.note["done"]) if context.note else 0
        did = 0
        for step in range(start, self.steps):
            self.ledger.append((uid, step))
            did += 1
            if (self.note is not None and context.note is None) or (
                step + 1 < self.steps and min(100, self.base + self.cost * did) >= 70
            ):
                note = self.note if self.note is not None else self.good_note(uid, step + 1, self.lossy and not start)
                pct = min(100, self.base + self.cost * did)
                return self.sent_outcome(
                    success=True, summary="Stopped.", context_share=self.share or pct / 100, handoff_note=note
                )
        pct = self.finish_at if self.finish_at is not None else min(100, self.base + self.cost * did)
        out = UnitOutput(media_type="text/markdown", content=f"{uid}: steps 0-{self.steps - 1} done\n".encode())
        return self.sent_outcome(success=True, summary="Done.", outputs=(out,), context_share=pct / 100)

    async def verify(self, unit: dict[str, Any], context: Any) -> bool:
        self.log.append(f"verify:{context.agent_id}")
        if self.verify_raises:
            raise RuntimeError("the check crashed")
        return len(context.note["done"]) == sum(1 for u, _ in self.ledger if u == unit["id"])


def drive(tmp: Path, runner: Any, *, units=("U1",), spares=6, with_store=True, handoff_at=None) -> Ran:
    """A chain U1 -> U2 ... in D1; `spares` specialists beyond one per unit; the config's handoff_at may be lowered."""
    ids = list(units)
    layout = build_layout(
        world_id=WORLD,
        district_specs=[
            {
                "id": "D1",
                "lead": "A_lead",
                "specialists": [f"A_s{i}" for i in range(len(ids) + spares)],
                "unit_ids": ids,
            }
        ],
    )
    plan = build_plan([build_unit(u, depends_on=ids[i - 1 : i], district="D1") for i, u in enumerate(ids)])
    config = load_config_sync(write_agents_config(tmp / "agents.yaml"))
    if handoff_at is not None:  # the schema fixes 0.70, so a test lowers it on the loaded config
        config = config.model_copy(update={"context": config.context.model_copy(update={"handoff_at": handoff_at})})
    skills = make_skill_registry(copy_skills_fixture_tree(tmp / "skills"))
    writer, store = make_memory_writer(layout, world_id=WORLD)
    rig = make_rig(world_id=WORLD)
    store_kwargs = {"artifacts": rig.store, "scope": rig.scope, "redact": rig.redactor} if with_store else {}
    run = run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=runner, **store_kwargs)
    result = asyncio.run(asyncio.wait_for(run, 30))
    return Ran(WORLD, rig, writer, store, result, layout, {u: f"A_s{i}" for i, u in enumerate(ids)}, runner)


def drive_scratch(runner: Any, **kw: Any) -> Ran:
    with tempfile.TemporaryDirectory() as tmp:
        return drive(Path(tmp), runner, **kw)


def outputs_of(ran: Ran) -> list[bytes]:
    """The bytes of every markdown version the run announced (the unit outputs; the note is JSON)."""
    refs = [e["data"]["artifact"] for e in ran.of("artifact.created")]
    return [
        ran.rig.store.read(ran.rig.scope, r)
        for r in refs
        if ran.rig.store.head(ran.rig.scope, r).record["media_type"] == "text/markdown"
    ]


def note_of(ran: Ran, started: dict[str, Any]) -> dict[str, Any]:
    return json.loads(ran.rig.store.read(ran.rig.scope, started["data"]["note"]))


def types(ran: Ran) -> list[str]:
    return [e["type"] for e in ran.events]


# --- when a handoff happens ---


def test_FR_AGT_09_handoff_triggers_at_handoff_at(tmp_path) -> None:
    runner = StepRunner(steps=6, cost=20, base=10)  # 30, 50, 70 percent: stops after the third step
    ran = drive(tmp_path, runner)
    (started,) = ran.of("agent.context_handoff_started")
    assert started["actor"] == "A_s0" and started["data"]["context_pct"] == 70
    assert isinstance(started["data"]["context_pct"], int)
    assert runner.log == ["run:A_s0", "verify:A_s1", "run:A_s1"]
    assert ran.result.failed == [] and ran.result.outcomes["U1"].success is True


def test_FR_AGT_09_compaction_share_is_not_a_handoff(tmp_path) -> None:
    # 65% is past compact_at (0.60) and below handoff_at (0.70): the agent compacts and finishes; no handoff.
    runner = StepRunner(steps=3, cost=20, base=5, finish_at=65)
    ran = drive(tmp_path, runner)
    assert runner.log == ["run:A_s0"] and ran.result.failed == []
    assert [t for t in types(ran) if t in HANDOFF] == []


def test_FR_AGT_09_unfinished_below_handoff_at_fails_closed(tmp_path) -> None:
    runner = StepRunner(note=StepRunner().good_note("U1", 1), share=0.69)  # 69% < 70%: the Lead does not hand off
    ran = drive(tmp_path, runner)
    assert runner.sent, "the runner must be able to report an unfinished outcome (the seam)"
    assert ran.result.failed == ["U1"] and runner.log == ["run:A_s0"]
    assert [t for t in types(ran) if t in HANDOFF or t == "agent.handoff"] == []


def test_FR_AGT_09_threshold_is_read_from_config(tmp_path) -> None:
    runner = StepRunner(steps=2, note=StepRunner().good_note("U1", 1), share=0.55)
    ran = drive(tmp_path, runner, handoff_at=0.5)  # 55% >= 50%: with handoff_at 0.5 this is a handoff
    (started,) = ran.of("agent.context_handoff_started")
    assert started["data"]["context_pct"] == 55 and runner.log[:2] == ["run:A_s0", "verify:A_s1"]


# --- events ---


def test_FR_AGT_09_events_ordered_valid_registered_and_fixtured(tmp_path, repo_root) -> None:
    ran = drive(tmp_path, StepRunner())
    validator, events = EventValidator.from_repo(repo_root), ran.events
    assert {i: validator.problems(e) for i, e in enumerate(events) if validator.problems(e)} == {}
    seqs = [e["seq"] for e in ran.events]
    assert seqs == list(range(1, len(seqs) + 1))
    (started,) = ran.of("agent.context_handoff_started")
    (completed,) = ran.of("agent.context_handoff_completed")
    assert completed["actor"] == "A_s1" and started["actor"] == "A_s0"
    assert completed["data"] == {"predecessor": "A_s0", "note": started["data"]["note"], "verification_passed": True}
    at = {k: next(i for i, e in enumerate(events) if pred(e)) for k, pred in {
        "started": lambda e: e["id"] == started["id"],
        "spawned": lambda e: e["type"] == "agent.spawned" and e["actor"] == "A_lead" and e["target"] == "A_s1",
        "completed": lambda e: e["id"] == completed["id"],
        "retired": lambda e: e["type"] == "agent.retired" and e["target"] == "A_s0",
        "handoff": lambda e: e["type"] == "agent.handoff" and e["actor"] == "A_s1",
    }.items()}  # fmt: skip
    assert at["started"] < at["spawned"] < at["completed"] < at["retired"] < at["handoff"], at
    registry = yaml.safe_load((repo_root / "contracts/events/registry.yaml").read_text(encoding="utf-8"))["types"]
    for kind in sorted(set(types(ran))):
        assert kind in registry and (repo_root / "contracts" / registry[kind]["fixture"]).is_file(), kind
    assert all(kind in registry for kind in HANDOFF)


# --- the note ---


def test_FR_AGT_09_note_is_stored_valid_and_given_to_the_successor(tmp_path) -> None:
    runner = StepRunner()
    ran = drive(tmp_path, runner)
    (started,) = ran.of("agent.context_handoff_started")
    stored = note_of(ran, started)
    assert_valid_contract("handoff", stored)
    assert stored == runner.good_note("U1", 3)
    assert ran.rig.store.head(ran.rig.scope, started["data"]["note"]).record["media_type"] == "application/json"
    first, successor = runner.contexts
    assert (first.note, first.note_ref) == (None, None)
    assert (successor.agent_id, successor.note, successor.note_ref) == ("A_s1", stored, started["data"]["note"])


_REQUIRED = ("goal", "unit_ids", "done", "in_progress", "decisions", "open_questions", "next_steps")
_REQUIRED += ("verification_to_rerun", "gotchas")
_BROKEN = {f"missing {name}": (lambda n, name=name: n.pop(name)) for name in _REQUIRED}
_BROKEN |= {
    "no next step": lambda n: n.update(next_steps=[]),
    "no verification": lambda n: n.update(verification_to_rerun=[]),
    "no unit": lambda n: n.update(unit_ids=[]),
    "unknown field": lambda n: n.update(mood="tired"),
    "goal too long": lambda n: n.update(goal="x" * 501),
    "bad unit id": lambda n: n.update(unit_ids=["unit one"]),
    "done without refs": lambda n: n.update(done=[{"unit_id": "U1", "summary": "Did it."}]),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(_BROKEN))
def test_FR_AGT_09_invalid_note_fails_closed_with_no_successor(tmp_path, name) -> None:
    note = StepRunner().good_note("U1", 2)
    _BROKEN[name](note)
    runner = StepRunner(note=note, share=0.7)
    ran = drive(tmp_path, runner, units=("U1", "U2"))
    assert runner.sent, "the runner must be able to report an unfinished outcome (the seam)"
    assert ran.result.failed == ["U1"] and ran.result.skipped == ["U2"]
    assert runner.log == ["run:A_s0"], "no successor runs"
    assert [t for t in types(ran) if t in HANDOFF or t == "agent.handoff"] == []
    assert not [e for e in ran.events if e["type"] == "agent.spawned" and e["target"] == "A_s2"]
    assert [e["target"] for e in ran.of("agent.retired") if e["target"] == "A_s0"] == ["A_s0"]


def test_FR_AGT_09_note_that_is_not_an_object_fails_closed(tmp_path) -> None:
    runner = StepRunner(note="just carry on", share=0.7)
    ran = drive(tmp_path, runner)
    assert runner.sent, "the runner must be able to report an unfinished outcome (the seam)"
    assert ran.result.failed == ["U1"] and runner.log == ["run:A_s0"]
    assert [t for t in types(ran) if t in HANDOFF] == []


def test_FR_AGT_09_no_artifact_store_or_no_spare_agent_fails_closed(tmp_path) -> None:
    for sub, kw in (("a", {"with_store": False}), ("b", {"spares": 0})):
        (tmp_path / sub).mkdir()
        runner = StepRunner()
        ran = drive(tmp_path / sub, runner, **kw)
        assert runner.sent, "the runner must be able to report an unfinished outcome (the seam)"
        assert ran.result.failed == ["U1"] and runner.log == ["run:A_s0"], sub
        assert [t for t in types(ran) if t in HANDOFF or t == "agent.handoff"] == [], sub


# --- the successor verifies first ---


def test_FR_AGT_09_successor_reruns_verification_before_continuing(tmp_path) -> None:
    runner = StepRunner()
    ran = drive(tmp_path, runner)
    assert runner.log.index("verify:A_s1") < runner.log.index("run:A_s1")
    (completed,) = ran.of("agent.context_handoff_completed")
    assert completed["data"]["verification_passed"] is True


@pytest.mark.parametrize("mode", ["lossy note", "verify raises"])
def test_FR_AGT_09_failed_verification_does_not_continue(tmp_path, mode) -> None:
    runner = StepRunner(lossy=mode == "lossy note", verify_raises=mode == "verify raises")
    ran = drive(tmp_path, runner, units=("U1", "U2"))
    (completed,) = ran.of("agent.context_handoff_completed")
    assert completed["data"]["verification_passed"] is False
    assert runner.log == ["run:A_s0", "verify:A_s2"], "the successor never continues"
    assert ran.result.failed == ["U1"] and ran.result.skipped == ["U2"]
    assert not ran.of("agent.handoff") and outputs_of(ran) == [], "nothing handed over, no unit output"
    assert {e["target"] for e in ran.of("agent.retired")} >= {"A_s0", "A_s2"}


# --- no rework ---


def test_FR_AGT_09_no_rework_and_same_outputs_as_a_run_without_handoff(tmp_path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    runner, plain = StepRunner(steps=7), StepRunner(steps=7, cost=0)
    ran, base = drive(tmp_path / "a", runner, units=("U1", "U2")), drive(tmp_path / "b", plain, units=("U1", "U2"))
    want = [(u, i) for u in ("U1", "U2") for i in range(7)]
    assert sorted(runner.ledger) == want and sorted(plain.ledger) == want, "each step ran once, none repeated"
    assert ran.result.failed == [] and len(ran.of("agent.context_handoff_started")) >= 1
    assert outputs_of(ran) == outputs_of(base) and len(outputs_of(ran)) == 2
    assert len(ran.of("agent.handoff")) == 2, "one handoff envelope per unit, from the agent that finished it"


def test_FR_AGT_09_repeated_handoffs_chain_predecessors(tmp_path) -> None:
    runner = StepRunner(steps=12)  # three steps per agent: 4 agents, 3 handoffs
    ran = drive(tmp_path, runner)
    started, completed = ran.of("agent.context_handoff_started"), ran.of("agent.context_handoff_completed")
    assert [e["actor"] for e in started] == ["A_s0", "A_s1", "A_s2"]
    assert [(e["actor"], e["data"]["predecessor"]) for e in completed] == [
        ("A_s1", "A_s0"),
        ("A_s2", "A_s1"),
        ("A_s3", "A_s2"),
    ]
    assert [s["data"]["note"] for s in started] == [c["data"]["note"] for c in completed]
    assert len({s["data"]["note"]["artifact_id"] + str(s["data"]["note"]["version"]) for s in started}) == 3
    assert sorted(runner.ledger) == [("U1", i) for i in range(12)] and ran.result.failed == []


@settings(max_examples=30, deadline=None, derandomize=True, database=None, phases=[Phase.generate])
@given(steps=st.integers(1, 14), cost=st.integers(5, 35), base=st.integers(0, 40))
def test_FR_AGT_09_property_any_context_growth_finishes_with_no_rework(steps, cost, base) -> None:
    runner = StepRunner(steps=steps, cost=cost, base=base)
    ran = drive_scratch(runner, spares=14)
    assert ran.result.failed == [] and runner.ledger == [("U1", i) for i in range(steps)]
    started, completed = ran.of("agent.context_handoff_started"), ran.of("agent.context_handoff_completed")
    assert len(started) == len(completed) == len(runner.contexts) - 1
    assert all(c["data"]["verification_passed"] for c in completed)
    assert all(s["data"]["context_pct"] >= 70 for s in started), "never before 70%"
    seqs = [e["seq"] for e in ran.events]
    assert all(a < b for a, b in zip(seqs, seqs[1:], strict=False))


# --- chaos: EV-10 ---


def test_FR_AGT_09_chaos_forced_handoffs_finish_with_no_rework_share_at_least_95_percent() -> None:
    runs, clean, handoffs, bad_seed = [], 0, 0, 17
    for seed in range(40):
        rnd = random.Random(seed)
        runner = StepRunner(
            steps=rnd.randint(6, 14),
            cost=rnd.choice([15, 20, 25, 30]),
            base=rnd.choice([10, 20, 30]),
            lossy=seed == bad_seed,
        )
        ran = drive_scratch(runner, spares=12)
        assert ran.of("agent.context_handoff_started"), f"seed {seed}: the handoff was forced"
        handoffs += len(ran.of("agent.context_handoff_completed"))
        full = [("U1", i) for i in range(runner.steps)]
        clean += ran.result.failed == [] and runner.ledger == full  # finished, every step once and none lost
        runs.append(
            RunRecord(f"r{seed}", "bank", "scripted_fakes", "E-HAND", None, (), tuple(ran.events), {}, None, True)
        )
    assert clean / 40 >= 0.95 and clean == 39, f"{clean} of 40 forced-handoff runs finished with no rework"
    rows = [r for r in compute_metrics(runs, credit_usd=0.01, coverage={}) if r.id == "EV-10"]
    (row,) = rows
    assert row.status == "computed" and (row.n, row.of) == (handoffs - 1, handoffs)
    assert row.value == pytest.approx((handoffs - 1) / handoffs) and row.value >= 0.95
