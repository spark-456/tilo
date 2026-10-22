# tilo-harness

The run engine: the code that turns an approved plan into agents doing units of work, with every step recorded as an
event. Read this first, because the name is misleading:

> **The harness is mostly a library.** `tilo-api` imports `tilo_harness` and runs the work in its own process, in a
> daemon thread per run. The separately deployed `tilo-harness` Cloud Run service is only a health check and a
> schedule-tick route that is not wired to anything yet.

## How a run executes

1. `POST /tasks/{id}/approve` in `tilo-api` (`services/api/src/tilo_api/tasks.py`) calls `runs.start_run`
   (`runs.py`), which starts a thread that runs `Run.main`.
2. The run compiles the Director's plan (`tilo_planning`), validates it (`plangraph.validate_plan`), builds the layout
   (`tilo_world.solve`), records `world.planned` and `world.started`, then calls `tilo_harness.executor.run_plan`.
3. `run_plan` refuses a bad plan without writing anything, pins every skill by hash, and runs the units as asyncio tasks
   bounded by `limits.max_specialists`. Per unit it records, in order: `agent.spawned`, `agent.assigned`, an optional
   must-ask chain, `skill.loaded`, `building.constructing`, `agent.moved`, `building.operational`, `agent.working`
   (again for each real tool call), the work itself, `artifact.created` or `artifact.versioned`, `agent.handoff`,
   `building.completed` and `agent.retired`.
4. A unit that fills its context window hands off to a spare agent through a validated note
   (`contracts/handoff.schema.json`, `context_handoff.py`); the successor re-checks before it continues.
5. A writer `deliver` unit produces the file: PDF, PPTX, DOCX, XLSX or CSV through `tilo_render`, a website HTML file
   (`website.py`) or a quiz app (`quiz.py`).
6. The run records `world.completed` or `world.failed`.

Scheduled runs are fanned out by `tilo-api` (`schedules.py`, Cloud Tasks queue named in `TILO_RUNS_QUEUE`) and then
take the same `start_run` path; this package supplies the `Ticker` and the schedule store.

## What lives where

| Module | Role |
| --- | --- |
| `executor.py` | `run_plan`: the unit scheduler and the per-unit event sequence |
| `writer.py`, `store.py`, `validator.py`, `views.py` | `WorldWriter`, the only writer per world: every event is validated (EV-01..16) before it is stored; a lease in `orgs/{org}/worlds/{world}/_head/state` enforces one writer; per-district views are redacted |
| `tool_runner.py`, `tools.py`, `tool_limits.py` | the tool loop: schema check, taint tracking, per-run cache, results neutralised and screened; side-effect tools are handed to the outbox and never run inline |
| `must_ask.py`, `question_wait.py` | rules in code decide when a unit must ask a person; a model reply can only add a question |
| `skills.py`, `skill_proposals.py` | skill registry pinned by hash; Team Lead skill proposals |
| `deliverable.py`, `outputs.py`, `website.py`, `quiz.py` | turn a writer unit's answer into stored files |
| `schedule.py`, `schedule_store.py`, `schedule_dates.py` | scheduled runs |
| `app.py` | the deployed ASGI app: `GET /health`, `GET /healthz`, `POST /internal/schedules/tick` (503 until wired) |
| `agents.py`, `skeleton.py` | the only users of Google ADK: a three-agent fixture run for `just harness-skeleton` |

Production tools (`web_search`, `fetch_url`, the five Gmail/Calendar/Drive reads, `browse_web`) are defined in
`tilo-api`, not here (`web_tools.py`, `workspace_tools.py`, `run_tools.py`). Every model call goes through
`packages/providers` by role; there is no live switch in this package, because providers are injected and `tilo-api`
chooses replay or live. `verifier.py`, `run_bundle.py`, `branch.py` and `lead_review.py` are built and tested but not
yet called by `tilo-api`.

## Events and storage

Events are written under `orgs/{org}/worlds/{world}/events/{seq}` with per-scope views at `.../views/{scope}/events/`.
`FirestoreStore` refuses to start without the emulator host and a `demo-` project id; the deployed API reaches
Firestore through its own `store_door.py`. Tests use `MemoryStore`.

## Tests

```sh
uv run pytest services/harness/tests -m "not emulator"     # fast suite
uv run pytest services/harness/tests -m emulator            # Firestore emulator: needs Java and firebase-tools
just harness-skeleton                                       # the ADK fixture run on the emulator
```

Test files are named `test_<requirement-id>_<slug>.py`. See [CLAUDE.md](CLAUDE.md) for the requirement IDs and local
rules.
