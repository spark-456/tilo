# FR-MEM-11: restart a run from a checkpoint as a branch. Interface pinned by the tests (overridable)

Acceptance test (PRD 13.5): "The branch reuses finished units and credits them as saved" (Should). PRD 13.4: "Runs:
restart from any checkpoint as a new branch of the run (Should)". Related: PRD 8.5 / FR-AGT-10 (checkpoints after every
unit), FR-MEM-02 (a reuse needs a fit check and a Verifier pass), PRD 14.3 and FR-MTR-06 (credits saved = `memory.hit`
`origin_cost - lookup_cost`, EV-09), EV-15 (artifact events name versions the world recorded).

No contract change and no API route: it is a harness-level capability, like the FR-MEM-10 bundle. The `memory.hit` event
(`data` = `origin_cost`, `lookup_cost`, `saved`, additionalProperties false) is used exactly as registered; every other
fact (which unit, from which run) is carried by existing envelope fields (`actor`, `target`, `district`, `cause`,
`summary`). These are the tests' assumptions: the builder may override a name or shape and must update the tests in the
same PR and say so in the review.

Tests: `uv run pytest services/harness/tests/test_FR_MEM_11_branch_run.py -q` (harness suite only; its conftest collides
with the api suite's). Fakes only: in-memory event store (`MemoryStore`), in-memory `ArtifactStore`, a scripted verifier
model, no network, no paid call. The tests import `tilo_metering` (a workspace member, test-only use) to check the credit
chain; the harness itself needs only what it already depends on.

## New code

- `services/harness/src/tilo_harness/branch.py`: `Checkpoint`, `FinishedUnit`, `checkpoint_from_events`, `unit_digest`.
- `executor.run_plan(..., reuse: Checkpoint | None = None)` and `RunResult.reused: list[str]` (no change to any other
  default). The branch's run id is the writer's `run_id` (`WorldWriter(run_id=...)`), so there is no `new_run_id`
  parameter: a second one could disagree with the writer. (The scoping note suggested `branch_run(..., new_run_id=)`;
  a thin wrapper is allowed, but the tests pin the `run_plan(reuse=)` form because it reuses every existing run_plan
  keyword unchanged: `verifier`, `artifacts`, `scope`, `redact`, `must_ask`, ...)

```python
@dataclass(frozen=True)
class FinishedUnit:
    unit_id: str
    spec_digest: str                       # unit_digest(plan unit) at the time of the parent run
    artifact_refs: tuple[dict, ...]        # the refs the unit handed over, as in the parent's UnitOutcome.artifact_refs
    origin_cost: float                     # sum of `credits` on the unit's events in the parent run
    handoff_event_id: str                  # the parent's agent.handoff of this unit (becomes the hit's `cause`)

@dataclass(frozen=True)
class Checkpoint:
    parent_run_id: str
    units: Mapping[str, FinishedUnit]      # finished units only, keyed by unit id; may be empty

def unit_digest(unit: Mapping) -> str      # sha256 hex (64 chars) of the unit's canonical JSON (sorted keys, no spaces)

def checkpoint_from_events(events: Sequence[dict], plan: dict, *, run_id: str | None = None) -> Checkpoint
```

`checkpoint_from_events` is pure and deterministic (equal inputs give an equal `Checkpoint`). `run_id` picks the parent
out of a world stream that holds several runs; with `run_id=None` the stream must hold exactly one run. `ValueError` for
an empty stream, a `run_id` with no events, or a stream of several runs without `run_id`. Only units that are in `plan`
are listed.

`run_plan(plan, layout, ..., reuse=checkpoint)` returns the usual `RunResult` plus `reused` (unit ids reused, in the order
their hits were written).

## How "finished" is detected from events

The harness records a unit's success and verification with existing events (read `executor._Run.work` and `review`):

- unit -> worker: `agent.assigned` (actor Lead, `target` the worker, `data.unit` the unit id).
- succeeded: an `agent.handoff` whose actor is the worker (`data.envelope.artifact_refs` is what it handed over). A failed,
  parked or held unit writes no handoff (held and failed units only `agent.retired`); a skipped unit writes no event.
- verified: for every ref in that envelope, an `artifact.reviewed` with `data.result == "passed"` and `cause` equal to the
  handoff's id (the verifier writes it with the handoff as cause).

A unit is **finished** iff it succeeded and every ref it handed over was reviewed "passed" in the parent. Not finished:
failed, parked, held, skipped, reviewed "failed" or "unverified", **handed over no artifact** (DECISION: nothing a Verifier
reviewed and nothing to reuse), and every unit of a parent that ran **without a Verifier** (no `artifact.reviewed`, so
nothing is verified: FR-MEM-02).

## Reuse rules in `run_plan(reuse=)`

1. `writer.run_id == checkpoint.parent_run_id` raises `ValueError` before any event is written or unit started.
2. A unit is reused iff all of: it is in the checkpoint; its `spec_digest` equals `unit_digest` of the plan's unit now
   (a changed title, skills, role, district, dependencies, ... re-runs it); every version in its `artifact_refs` is one the
   branch's world recorded (`writer.recorded_version(artifact_id) >= version`; fail closed, EV-15, nothing dangles); and
   **every unit it depends on is reused too** (DECISION: a unit downstream of one that runs has an input that is about to
   change, so crediting it would credit stale work. The checkpoint is a prefix-closed cut of the DAG).
   Units in the checkpoint but not in the plan are ignored; units in the plan but not in the checkpoint run.
3. A reused unit is not executed: the runner is never called for it, no slot is taken, no skill loaded, no verifier call.
   It counts as a success: `result.outcomes[unit]` is `UnitOutcome(success=True, artifact_refs=<checkpoint refs>)`, so its
   dependents start normally and `result.failed`/`skipped` stay empty. Its worker still comes from the layout roster (the
   layout must still fit the whole plan).
4. Every other unit (unfinished, changed, new, downstream of one of those) runs exactly as in a plain `run_plan`.

## The one event of a reused unit

Exactly one `memory.hit` per reused unit, written before its dependents start, and nothing else for it in the branch
(no `agent.spawned/assigned/working/handoff/retired`, no `artifact.*`, no `artifact.reviewed`): HR-1, no animation
without an event, and no event for work that did not happen. Fields:

- `run_id` the branch's, `actor` = `target` = the unit's worker (the registry's story line is "{actor} reused an
  earlier result and saved N credits"), `level` and `district` the unit's, `item` null, `severity` info, `vis` "all",
  `authz` null, `credits` 0 (a reuse spends nothing; the figure is `data.saved`).
- `data` = `{"origin_cost": <the unit's original cost>, "lookup_cost": 0, "saved": <origin_cost>}`.
- `cause` = the parent's `agent.handoff` event id of that unit (`FinishedUnit.handoff_event_id`; EV-11 allows an earlier
  event of the same world), so the Trace links a reuse to the work it reuses.
- `summary` (free text, at most 140 characters) contains "reused" and "earlier run", for example "The agent reused a
  finished unit from the earlier run and saved 7 credits." No new field.

**lookup_cost = 0 (decision).** `tilo_memory.cache.ResultCache` takes `lookup_cost` as a constructor argument because a
cache lookup is a metered search. A checkpoint lookup is not: it reads events the parent already recorded and compares a
digest, and the Verifier pass it relies on was paid for by the parent (the branch makes no verifier call for a reused
unit; the tests count the model calls). A non-zero number would need a config value, and `config/agents.yaml` is shaped by
`contracts/agents.schema.json` (no free field; changing it is a contract change). So `saved = origin_cost`. The tests check
EV-09 generically (`saved == origin_cost - lookup_cost`) and pin `lookup_cost == 0`.

**Origin cost** = the sum of `credits` over the parent run's events whose `actor` or `target` is the unit's worker. Today
only the unit's first `artifact.created`/`versioned` carries credits (ADR-0018 s6), so a unit with two outputs counts once.

## Credits chain (checked in the tests)

`tilo_metering.savings.credits_saved(branch events)` equals the sum of the hits' `saved`; `credits_saved(world events,
run_id=branch)` too and `run_id=parent` is 0; `tilo_metering.costs.cost_report([], world events, unit_types={},
credit_usd=...)` shows `totals.credits_saved` = that sum and the branch run's task row carries it. The branch's own meter
(`credits` on its events) is only what the units that ran spent.

## EV-15 choice: the branch shares the parent's world (pinned)

One world, two runs: the branch is a new `WorldWriter(store, org_id, world_id, run_id=<new>, ...)` over the same event
store, opened after the parent's writer released its lease. Same `world_id`, `seq` continues from the parent's last event
(EV-10), run ids differ, the artifact store and scope are shared, nothing is imported or copied. The new writer's `open()`
loads the parent's events, so `recorded_version` already covers every parent version: a re-run dependent can select a
parent version in `UnitOutcome.artifact_refs` (EV-15: `existing(...)` and the handoff both pass), and the hit's `cause`
resolves. Branching into a different world would need the parent's versions imported first (as `import_run` does,
FR-MEM-10) and its handoff ids are not in that stream; out of scope here, and the "recorded in the world" check in rule 2
makes it fail closed (nothing reused) rather than dangle.

## Tests (each name carries FR_MEM_11)

Checkpoint: lists exactly the finished units; origin cost; handoff event id; digest equals the plan unit's; `unit_digest`
stable and sensitive; deterministic; failed review not finished; no verifier means none finished; a unit with no artifact
is not finished; only plan units; `run_id` selection and `ValueError`s.
Branch: the acceptance test (reused units not run, credited); `cost_report` credit; the meter holds only what ran; hit data
and `lookup_cost` 0; contract validity of every `memory.hit` (event validator, `EVENT_DATA_MODELS`, `Event`) and the whole
two-run world replayed through `EventValidator` with a `WorldState`; `cause`; summary text; one event per reused unit and no
re-announced artifact; no re-review or model call; dependents run after the hit and name the parent's version (EV-15);
shared world and `seq` continuity; failed parent unit re-runs with its dependents.
Edges: empty checkpoint (0 hits, all run); every unit finished (0 runner calls, 0 model calls, hits = units); changed spec
re-runs the unit and everything downstream; units outside the plan ignored and new units run; a checkpoint ref the world
never recorded is not reused; same run id raises and writes nothing; `run_plan` without `reuse` unchanged; deterministic event
order. Property (Hypothesis, random DAGs with random failed, failed-review and changed units): reused = finished, unchanged,
every dependency reused; the runner runs exactly the rest; hits = reused; credited total = reused origin costs; `seq`
strictly increasing; the world replays valid.

## Not pinned (follow-ups, listed in the report)

- Branching a branch: reused units appear in the first branch only as `memory.hit`, so `checkpoint_from_events` of a branch
  run lists them as unfinished (no handoff of their own). The user can branch from the original run; chaining is a later ticket.
- A Firestore checkpoint document (`orgs/{org}/worlds/{world}/checkpoints/{id}`, PRD 15.3) for a `Checkpoint`, and any
  route or card to trigger a branch (a person's choice, a side effect of nothing but compute; no policy decision).
- Units that have side effects: a reused unit performs none (its outbox entries already exist from the parent run).
