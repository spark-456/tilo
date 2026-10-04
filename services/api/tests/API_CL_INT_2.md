# CL-INT-2: the CP2 thin slice after approve (what the acceptance tests pin)

PRD 5.4 CP2 ("intake -> plan -> world -> a gated action"), 8.5, 9.4 HR-1..HR-7, 10.3, 10.4, FR-AGT-11,
FR-HIL-01/03/04, FR-WLD-03/07; ADR-0008; web seam: issue #80 (`TiloClient`, `DeliveryResult`). Builds on
`API_CL_INT_1.md` (all of its routes and seams stay) and on the phase0-stack modules: the harness executor
(`tilo_harness.executor.run_plan`), `tilo_planning.plangraph.validate_plan`, `tilo_policy`, the outbox and mock
connector (`tilo_connectors`), the cards API (`tilo_api.cards`, #121) and the kill switches (`tilo_api.dispatch`, #120).
Every route needs the signed-in `deps.Principal`; the world routes also need `principal.world_id == world_id`
(any other caller gets the same 404 as an unknown world).

## What happens after `POST /tasks/{task_id}/approve`

`approve` keeps its CL-INT-1 contract (200 `{world_id}`, one `budget.granted`, 409 on a second call) and also
**starts one run** for the task. The run may execute inline or on a background thread; the tests poll the stream,
so both are fine. A run that cannot start never changes the approve response.

1. Compile: `plan = compiler(brief=task.brief, approach=<the chosen approach dict>, budget_cap=<the cap>, context=<PlanInputs: approaches, owner, skills, connectors, risk table, policies; FR-INT-09>)`.
2. Validate: `tilo_planning.plangraph.validate_plan(plan, risk_table=..., connectors={id: record}, skills=<set of
   skill ids>, policies=..., owner=<the world owner>)`. Any violation, or a compiler that raises: **no run starts**.
   Nothing is written except, at most, one `world.failed`; no agent, artifact or approval event; no outbox entry; no
   card. The approve response is still 200 (the budget grant is the person's decision, not the plan's).
3. Layout: `layout = layout_builder(plan, world_id=<world id>)` (a `layout.schema.json` record; the stream is
   validated against it).
4. `world.started` `{budget_cap: <the cap>}`, then the executor runs the plan with the injected unit runner: for each
   unit the executor's `agent.spawned`, `agent.assigned {unit}`, `skill.loaded` per pinned skill, `agent.working`,
   `agent.handoff`, `agent.retired`; a unit starts only after the units it depends on have retired. Each artifact
   ref in a unit's outcome becomes one `artifact.created {artifact: <ref>}` before anything refers to it.
5. **The gate.** A unit with `actions` does its work (the draft, via the unit runner); its side effect then goes
   through the policy engine, not the runner. The item to send is the **first artifact ref** of that unit's
   outcome. The resolver supplies the rest (see Seams). `tilo_policy.decide` is asked with the real risk table and
   the owner's `Store.policies`; a recipient not in `known_recipients` makes the action T3 (`new_recipients`). Any
   result other than `run`/`run_after_undo` (T3 always, or no covering policy) gates:
   - `approval.requested` `{gate_id: <plan gate id>, card_id, outbox_id (reserved, a ulid), action_type, risk_tier,
     irreversible: <the connector's declaration>, item: <the ref>, approver: null, team_lead: null}`;
   - a gate card (`card.schema.json`, kind `gate`, `gate.id` = the gate id, `gate.risk_tier`, `gate.action.type`,
     `gate.action.connector`, `gate.recipients`, `safe_default: "hold"`, options `approve`/`edit`/`hold`) submitted to
     the app's `CardStore` with that `outbox_id`, `card.id == approval.requested.data.card_id`;
   - the run then **waits**: nothing is enqueued, no connector is called, no `data.transfer`, `artifact.delivered`
     or `world.completed` is written.
6. **Answer.** The card is answered over the cards API (#121). `approve` by the owner: `approval.resolved`
   (`authz` = `{by: person, ref: <owner>, at}`, `option: approve`, `channel: web`, `pin_verified: false`, the same
   `gate_id`, `card_id`, `outbox_id`) written through the single writer by `CardStore`; then the run resumes:
   `Outbox.enqueue` with that authz (exactly one entry: `id` = the reserved `outbox_id`, `world_id`, `action_type`,
   `connector`, `recipients`, `destination`, `item`, `risk_tier`, `modifiers`, `authz`), `dispatch_due()`, the
   connector sends once, `data.transfer` (the outbox's own part: `direction: out`, same `outbox_id`, `artifact`,
   `risk_tier`; `authz` = the entry's), `artifact.delivered {artifact: <ref>, format: "email", outbox_id}` whose
   `cause` is that `data.transfer` event's id (EV-14), then `world.completed {credits_used, deliverable_count}`
   (`deliverable_count` = the number of `artifact.delivered`; `credits_used` <= the cap). `hold` (and `edit`) write
   nothing and leave the card open. Only `approve` opens the gate (CR-07).
7. **Retries.** A `send_reply` that raises is retried by the run (at least once, within a few seconds) until the
   entry is `sent`; the idempotency key keeps the connector to one send (FR-AGT-11). Two `approve` answers (even
   concurrent ones) write one `approval.resolved`, one entry, one send.
8. **Pause.** `POST /worlds/{id}/pause` (#120) sets `WorldRecord.paused` and writes `world.paused` through the
   writer. From then on the run writes nothing else (FR-WLD-07: no event after 2 s except `world.paused`; this
   suite checks "after the veil, none"), starts no unit, and sends nothing, even if the gate card is answered later.

All events of the run (executor, `world.started`, `artifact.*`, `approval.*`, `data.transfer`, `world.completed`)
reach `Store.events[world_id]` only through `deps.get_event_writer().append(world_id, event)` where `event` carries
its own `id` (ULID, idempotency key, as in #46). `seq` stays strictly increasing and gap-free from the CL-INT-1
events on. Every type is in `contracts/events/registry.yaml`, every event passes `event.schema.json`, its data
schema and the harness validator (EV-01..EV-14) against the layout. No model id appears in any event.

## Routes

| Call | Route | Success | Errors |
| --- | --- | --- | --- |
| listCards (exists, #121) | `GET /worlds/{world_id}/cards` | 200 `[card]`, served from the app's own `CardStore` | 404 not a member; 403 a Viewer or a non-owner |
| answerCard (exists, #121) | `POST /worlds/{world_id}/cards/{card_id}/answer` `{option}` | 200 `{outcome: "answered"}` | 404 unknown card or not yours; 403 Viewer; 400 already resolved |
| getDelivery (new) | `GET /worlds/{world_id}/delivery` | 200 `DeliveryResult` | 404 not a member of that world or not its owner; 409 until `world.completed` is written |

`DeliveryResult` is the issue #80 TiloClient shape: `{world_id, artifacts: [{id, title, kind, version}],
credits_used, time_saved: {low_min, high_min} | null}`. `artifacts` are the `artifact.delivered` artifacts in
order (`id` = artifact id, `version`, `kind` = that event's `format`, `title` a non-empty string);
`credits_used` equals `world.completed.data.credits_used`; `time_saved` is null until the metering ticket (FR-MTR-02
methods) and otherwise `low_min <= high_min`. The app owns its `CardStore` and outbox wiring: the tests do not
install either, so `get_card_store`-style seams are the builder's choice. The CardStore must know the world's owner
(`world_owners`) for the world the run raised the gate in.

## Injection seams the tests use (new, in `tilo_api.deps`; each defaults to the production wiring)

All callables are called with keyword arguments exactly as shown. Not set up in a CL-INT-1 test: approve must
still work there (the run just does not start or fails alone).

- `deps.get_plan_compiler()` -> `compile(*, brief: dict, approach: dict, budget_cap: float, context: PlanInputs) -> dict` (a PlanGraph,
  `plan.schema.json`). Default: the Director through `deps.get_router`.
- `deps.get_layout_builder()` -> `layout_for(plan: dict, *, world_id: str) -> dict`. Default: a deterministic
  builder (one Director, a Lead per district, workers by role, a workshop per district, an island per connector, a
  gate per plan gate).
- `deps.get_unit_runner()` -> a `tilo_harness.executor.UnitRunner` (`async run(unit, context) -> UnitOutcome`).
  Default: `DefaultUnitRunner` over `deps.get_router`.
- `deps.get_action_resolver()` -> `resolve(*, unit: dict, action_type: str, item: dict, brief: dict) -> dict` with
  `destination: str`, `recipients: list[str]`, and optional `known_recipients: list[str]` (default `[]`). It is the
  only source of the send's recipients and destination (a unit runner returns neither).
- `deps.get_skill_registry()` -> `tilo_harness.skills.SkillRegistry` (default: `skills/`).
- `deps.get_connector_registry()` -> `tilo_connectors.registry.ConnectorRegistry` (default: `config/connectors.yaml`).
  Its records are the `connectors` of `validate_plan`.
- `deps.get_connector_adapters()` -> `dict[str, adapter]` (connector id -> object with the outbox's `send_reply`).
- `deps.get_outbox_store()` -> `tilo_connectors.InMemoryOutboxStore`. The test reads `all_entries()`.
- `deps.get_event_writer()` (exists): the single writer. The run, the `CardStore` writer and the outbox's `emit`
  all end here; none writes `Store.events` itself.
- Pause and the world flag: `Store.worlds[world_id].paused` (exists).

## Defaults applied (PRD wording is silent)

- Recipients, destination and known contacts of a send come from the action resolver, not from the unit runner
  (PRD 10.3 shows them on the card; 12.1's mock has no addressbook). Item = the acting unit's first artifact ref.
- A failed plan validation does not fail `approve` (the grant is independent); it is `world.failed` at most.
  Delivery is 409 for a world that is not completed, failed or not.
- Delivery is 404 for a caller that is not a member of the world (the 404 convention of the world routes).
- Pause is final for the run in this ticket (no resume route yet): after `world.paused` the run writes nothing,
  and a later `approve` answer sends nothing.
- `world.started.data.budget_cap` is the confirmed cap; a run that spends nothing reports `credits_used` 0.
- Building events are not pinned (the executor emits none); `agent.*` and `artifact.created` are.
- A gate raised on a T1/T2 action covered by an owner's L2/L3 policy (the `policy.applied` path) is FR-HIL-05/06,
  not pinned here. Pinned: with no covering policy the send gates, and T3 gates even under an L3 policy.

## Follow-ups from #155 (safety subset)

- A unit that names an artifact another world already created fails the world (`world.failed`) before anything is recorded or sent.
- `gate.action.exact` is built from action, connector, destination and recipients; a send whose text would pass 500 characters fails closed (never cut).
- The run's Outbox is scoped to its world (`abandon` and `cancel` refuse another world's entry) and halts at each claim once the world is paused.
- A failed event write on a card answer is `503 {"outcome": "error", "reason": "event_write_failed"}`; the card stays open.
