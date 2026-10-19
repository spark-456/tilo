# FR-MTR-10 Cost dashboards: the data and API these tests pin

PRD 14.1, 14.3, 14.4, 14.5, 3.5 EV-07, 6.6; FR-MTR-01, FR-MTR-06; PL-01. Acceptance: "Dashboard shows cost per task by
tier and profile." This is the data and API half only: no screen, no visual work (the web client waits for the
redesign). Tests: `packages/metering/tests/test_FR_MTR_10_cost_report.py` (the computation) and
`services/api/tests/test_FR_MTR_10_costs_routes.py` (the routes). No contract schema changes, no new event types.

## `tilo_metering.costs` (new module in `packages/metering`)

```python
def cost_report(
    ledger: Iterable[LedgerEntry],            # Treasury.ledger; only kind == "commit" is spend
    events: Iterable[Mapping[str, Any]],      # event.schema.json records, any worlds
    *,
    unit_types: Mapping[str, Mapping[str, str]],   # run_id -> plan unit id -> unit_type
    credit_usd: float = 0.005,
) -> dict
```

Pure: no I/O, no clock, no model, inputs untouched. Spend comes from the ledger's `commit` entries alone, at the
credits each entry recorded (the price in effect on its date, FR-MTR-01; the report never re-prices). Reservations,
releases, grants and `usage` records are not spend. From events it reads `world.planned` (`data.tier`),
`world.completed` and `memory.hit`. Anything else is ignored. Sums use `math.fsum` (so order never changes a sum).

### Shape

```json
{
  "credit_usd": 0.005,
  "totals": {"tasks": 2, "completed_tasks": 2, "credits": 242.0, "usd": 1.21, "credits_saved": 5.5, "usd_saved": 0.0275},
  "tasks":           [{"run_id", "tier", "completed", "credits", "usd", "credits_saved"}],
  "by_tier":         [{"tier", "tasks", "credits", "usd", "credits_per_task", "credits_saved"}],
  "by_profile":      [{"profile", "tasks", "credits", "usd", "credits_per_task"}],
  "by_task_type":    [{"task_type", "tasks", "credits", "usd", "credits_per_task"}],
  "by_tier_profile": [{"tier", "profile", "tasks", "credits", "usd", "credits_per_task"}]
}
```

- A **task is a run** (EV-07, PRD 14.4 "ledger `runs` table"). A task is in the report when it has a ledger commit or
  an event. `completed` is true once the run has a `world.completed`.
- **tier** is the world tier of PRD 9.1 (`outpost`, `village`, `town`, `city`), from the run's `world.planned`
  `data.tier`; `null` when the run was never planned. It is the "tier" of PRD 14.5 and EV-07 ("by tier"), not the T1-T3
  risk tier (see Gaps).
- **profile** is `usage.profile` of the commit; `null` for a commit with no usage, and also for a `profile` that is
  not a `providers.schema.json` `profile_id` (`^[a-z][a-z0-9-]{0,31}$`), so a model id written there by mistake never
  reaches the output (PL-01). Its credits stay in every sum.
- **task_type** is `unit_types[run_id][entry.step]`; `null` when the step is not a unit of that run's plan.
- `tasks` in a group counts the distinct runs in it: runs with spend in it, and in `by_tier` also planned runs with no
  spend (so a tier can show `credits_per_task` 0); `credits_per_task = credits / tasks`. `credits_saved` is FR-MTR-06: the sum over `memory.hit` events of `origin_cost - lookup_cost`,
  each event id once (a redelivery counts once), per run, never netted off spend and never added to it. A hit whose
  `saved` disagrees raises `tilo_metering.savings.InconsistentMemoryHit`, as the meter does (the routes answer 422
  `inconsistent_ledger`, BQ-MTR10-5).
- **Order**: `tasks` by `run_id`; `by_tier` and the tier of `by_tier_profile` by world size (outpost, village, town,
  city), then `null`; profiles and task types alphabetically, then `null`. The same inputs in any order give the same
  report, byte for byte once serialised.
- Empty input gives `totals` all `0`, every list `[]`. No NaN.

## `tilo_api` (new routes, new seam)

```python
# tilo_api.deps
def get_ledger() -> Sequence[LedgerEntry]     # production default: HTTPException 503 "not_configured"
```

The Treasury is not wired into tilo-api yet and its ledger is in memory only, so the ledger is one injected seam, like
`get_store`: tests override it with `treasury.ledger`; the real wiring is the Treasury ticket's. Everything else is
read from the existing `Store` (`worlds[w].owner`, `worlds[w].run_id`, `events[w]`, `runs[w].plan["units"]`).

| Route | Success | Errors |
| --- | --- | --- |
| `GET /worlds/{world_id}/costs` | 200 `{"world_id": ..., **report}` for that world's run(s) | 401, 403, 404, 422, 503 |
| `GET /costs` | 200 `report` over every world whose `owner` is the principal's `user_id` | 401, 403, 422, 503 |

422 `inconsistent_ledger` is only `InconsistentMemoryHit` (any other `ValueError` surfaces); 503 `not_configured` is a
missing ledger seam or an unreadable `config/prices.yaml` (read once, only a good read kept, retried otherwise).

- **Scope of a world's runs**: `WorldRecord.run_id` plus every `run_id` on that world's events. A ledger entry of any
  other run is never counted. Task types come from the world's `store.runs[world_id].plan["units"]` (`id`,
  `unit_type`) keyed under the world's run id; a missing or malformed run or plan gives no task types (`null`), not an
  error.
- **Who**: the owner only (`principal.role == "owner"` and `principal.user_id == world.owner`). A principal that is not
  a member of the world (`principal.world_id != world_id`) or an unknown world gets the same bare 404 (identical
  bytes); a member who is not the owner (viewer, approver, team_lead, or another owner's id) gets 403 with no figures.
  `GET /costs` needs role `owner` (else 403) and lists only that user's own worlds, whatever `principal.world_id` says;
  another owner's world ids, run ids and user id never appear. No principal: 401 (the existing default).
- **Read-only**: any other method is 405; a GET writes no event, changes no store field and no ledger entry. The
  routes are reads, so `replay_only` (NFR-24) does not close them.
- The body is allowlisted: only the shape above. No model id, `price_source`, event summary or plan title appears.

## Ambiguities resolved (apply the PRD default, also log in `docs/open-questions.md`)

1. "Cost per task ... by tier" (PRD 14.5) vs EV-07 "credits per **successful** run, by tier": the rows count every
   run with spend and carry `completed_tasks` in `totals`; the dashboard can divide by completed runs later. Default
   pinned to FR-MTR-10's own wording ("per task").
2. "Tier": the world tier (PRD 9.1), since EV-07 and PRD 3.5 line 235 use it for cost per task. See risk tier below.
3. Non-owner of a world you belong to: 403 (cards pattern); everyone else 404 (layout and events pattern).

## Gaps (needs contract change or a decision; no test written for these)

- **needs contract change: risk tier.** The ticket asks for risk tier as a grouping. A risk tier (T1-T3) exists per
  action (`plan.gates[].risk_tier`, `approval.requested`/`policy.applied`/`data.transfer` `data.risk_tier`), but no
  cost is recorded against it: no ledger entry, no event with `credits`, and no unit carries one, and a task spans
  several tiers. Grouping by it needs a rule (for example "the highest tier among a unit's gates") written into a
  contract or ADR first. Not tested.
- **needs contract change: step id = plan unit id.** `LedgerEntry.step` is a free string (`Treasury.reserve(run_id,
  step_id, ...)`); nothing says it is the plan unit id, and `contracts/metering.rules.md` MT-03 calls it a "step". The
  task-type grouping and its tests assume `step == plan.units[].id`. Without that rule, `by_task_type` is all `null`.
  Events cannot stand in: a cost-carrying event (`artifact.created`, `world.planned`) names no unit and, from tilo-api
  runs today, a `null` `trace.profile`, which is why spend is read from the ledger.
- **A task has no type of its own.** Runs record no task or scenario type (`world.requested` has title, channel,
  destination); only plan units have `unit_type`. "By task type" is therefore by unit type (`by_task_type`).
- **No ledger source in tilo-api.** `deps.get_ledger` is new and unwired; the ledger has no `world_id` (runs map to worlds
  through `WorldRecord.run_id` and the events), no persistence, and the credits ledger table of PRD 14.4 is not defined
  in `contracts/` or `infra/`.
