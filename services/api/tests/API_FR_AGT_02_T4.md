# FR-AGT-02 / FR-MEM-06 T4: tilo-api runs on the artifact store (ADR-0018 section 5 ticket 4)

The interface the T4 acceptance tests pin. The ADR names the pieces; these exact names are chosen by the test-writer
and the builder may change one if it says so and updates the tests in the same PR. Fakes only: an in-memory
`ArtifactStore`, a fake redactor, a RunArchive over a temp dir (`_clint2_lib.ArtifactRig`).

## Seams (`tilo_api.deps`, run seams like `get_unit_runner`; `runs.run_seams` builds them; a seam that raises means no run starts)
- `ORG_ID: str`: a well-formed org id (`org_...`). tilo-api has no org concept until sign-in; every run's Scope is
  `Scope(org_id=deps.ORG_ID, world_id=<the run's world>, owner=<the world's owner>)`. Never taken from a request.
- `get_artifact_store() -> tilo_memory.artifacts.ArtifactStore`
- `get_redactor() -> Callable[[str], str]`: the shared secret redactor (the same one the store was given).
- `get_run_archive() -> Callable[..., tilo_archive.RunArchive]`: called as `open_archive(org_id=..., run_id=...)`, once
  per run, for the run's raw archive.
- Dev mode (`dev_run.overrides()`): `get_artifact_store` is one in-memory store per `dev.install` (the same object on
  every call, so the run and a reader share it), and refuses (`DevModeRefused`) when deployed or live, like every
  dev stand-in. The production default of the three seams is the builder's choice (ADR-0018 s5 T4 names only dev:
  "memory backend in dev mode"); it must be a real store or raise, never a half-wired value.

## The run
- `runs.Run` is the writer `run_plan` is given: it has `org_id` (= `deps.ORG_ID`) and `world_id`, which `run_plan`
  compares with the Scope (a mismatch is `PlanRefused`, nothing written; harness `WorldWriter` gets a public `org_id`).
- `run_plan(plan, layout, writer=run, ..., artifacts=<store>, scope=<Scope above>, archive=<opened archive>,
  redact=<redactor>)`. The stopgap in `_GatedRunner.run` that drops `outputs` is gone; `_GatedRunner` neither mints nor
  emits artifact events: the executor stores each output and announces it from the store's record.
- `Run.emit` forwards `item` and `credits` to the writer (`Run.put` writes them on the event). The unit's credits are
  still clamped to what the approved budget has left (`Run.metered`, HR-1) and ride on the unit's first announced item.
- `Run.foreign` is removed: a ref held only in another Scope (another world, or another owner) is rejected by the
  store's scope check, so the unit fails and the world fails closed as before.
- The gate and `deliver_in_app` use the announced refs; the send's item is the unit's first announced version.

## Dev
- `DevUnitRunner.run(unit, context)` returns a `MeteredOutcome` with one synthetic `text/markdown` `UnitOutput` and no
  `artifact_refs`; it must still work for `unit == {"title": "T"}` and `context is None` (CL-INT-5d calls it so), and
  keeps its delay, its refusal when deployed or live, and `credits == unit_credits()`.

## Ambiguity resolved by default (logged in the report)
- No requirement names the api's org: a module constant is the least that works (PRD 15.1 keys artifacts by org).
- A unit that returns invalid credits (NaN, negative) fails in the executor (T3); the API's old "treat as 0" is not pinned.
