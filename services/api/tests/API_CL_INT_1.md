# CL-INT-1: the CP2 thin-slice API flow (what the acceptance tests pin)

PRD 5.4 CP2, 7.1 FR-INT-01..08, 10.1, 16.3; ADR-0008; web seam: issue #80 (`TiloClient`).
Every route needs the signed-in `deps.Principal` (`deps.get_current_principal`). Tasks are held in memory.

## Routes

| Call | Route | Success | Errors |
| --- | --- | --- | --- |
| submitIntake | `POST /intake` (multipart `text`, `files`) | 201 `{task_id, world_id, run_id, event, brief, questions, files, gaps}` (`gaps`: FR-INT-15, `[]` when none); the existing FR-INT-01/02 keys stay | 422 `{"error"}` limits (as today); 422 `{"error", "gaps"}` when no part is possible (FR-INT-15); 503 no or refused safety provider |
| answerQuestions | `POST /tasks/{task_id}/answers` JSON `{answers: [{field, answer\|null}], brief_edits: {}}` | 200 `{brief}` | 404 unknown task; 403/404 not the owner; 422 unknown field, invalid edit |
| getApproaches | `GET /tasks/{task_id}/approaches` | 200 `{task_id, approaches, recommended, credit_usd, budget_ceiling}` (`budget_ceiling`: SIMPLE-RUN-2, the most one approval grants) | 404; 403/404 owner; 409 questions not yet answered |
| approve | `POST /tasks/{task_id}/approve` JSON `{approach_id, budget_cap}` | 200 `{world_id}` | 404; 403/404 owner; 409 no approaches yet; 422 bad cap or approach |

`questions[]` is `{field, text, suggested_answers}`. `questions` and `brief` are never taken from the
client. An unauthenticated caller gets the 401 the auth dependency raises, before anything else.

SEC-10: the complete JSON body on task answers and approval is capped at 32,768 bytes (413
`body_too_large` above the cap). This includes `brief_edits`: the brief schema can describe more
sources than fit in one edit request. Typical short briefs fit; shorten an oversized edit before
resubmitting. The schema's source limits do not raise the request-body cap.

## Injection seams the tests use

- `deps.get_current_principal`, `deps.get_store` (exist). `Store.events[world_id]` receives the events the
  API writes on approve (`budget.granted`).
- `tilo_api.intake.get_safety` (exists). Its default builds `tilo_providers.build_safety_provider` from the
  providers config, read when the dependency is called (not at import): `TILO_MODELS_FILE` picks the models
  file (`tilo_providers.config.resolve_models_path`), `config/prices.yaml` the prices. No `safety` role,
  or a build error, is 503.
- `deps.get_router` (new, in `tilo_api.deps`): returns a `tilo_providers.router.Router`. Default builds it
  from config. Every model call (brief, approaches) goes through it.
- Budget: `tilo_planning.budget.request_budget_grant` then, if it does not run, `grant_budget_by_person`.
  The tests spy on those module attributes.

## Defaults applied (PRD wording is silent)

- Partial answers: every asked question must be answered or skipped (`answer: null`) before approaches.
- "The person's confirmed cap" is the `budget_cap` in the approve request; the grant equals it exactly.
- A second approve never writes a second `budget.granted` (409, or 200 with the same `world_id`).
- Follow-ups (#139, BQ-99): the last action on a chip wins (an answer drops the field earlier edit; in one request the edit wins); the goal answer "Something else, which I will describe" is 422 (describe it in the goal chip); a flagged file stays out of `brief.sources`; the Director runs before any file is stored (502 stores nothing); `budget_cap` above `caps.run_credits` in `config/metering.yaml` (300) is 422; a 422 or a log never quotes the input or the model error text.
