# services/api — `tilo-api`

## Purpose
Cloud Run service (PRD 6.2): sessions, tasks, cards, approvals, policies, downloads, sharing, RBAC. The only service the web client and channels write through; the client reads live state from Firestore under rules.

## Commands
- `uv run --package tilo-api pytest` — tests; `just check` — gate; `just dev-api` — dev mode on 127.0.0.1:8080 (fake Director); `Dockerfile` runs `tilo_api:app`, deploy `docs/deploy-dev.md`
## Requirement IDs
- PRD 6.2 row; SEC-05..12, SEC-15; FR-INT-11/12, FR-HIL-10/12 (API half); FR-MTR-10 (`tilo_api.costs`: owner-only `GET /worlds/{id}/costs`, `GET /costs`; `deps.get_ledger` 503 until the Treasury is wired, BQ-MTR10-4); PPL-11a. FR-AGT-14b (`tilo_api.schedules`, `tests/API_FR_AGT_14b.md`, ADR-0023): `/schedules` routes snapshot a task the owner approved (404 for others); `POST /internal/schedules/tick` (own OIDC check: `TILO_SCHEDULE_TICK_AUDIENCE`, `TILO_SCHEDULE_TICK_CALLER`, 503 unset) starts runs only on the owner's L3 `grant_budget` policy; store `TILO_SCHEDULES_STORE`=memory (dev default) or firestore + `TILO_FIRESTORE_PROJECT`.

## Contracts and config
- Reads/writes `packages/contracts-py` types; Firestore (worlds, events, cards, policies, grants); Cloud Tasks. Config:
  `autonomy.yaml`, `flags/`, `connectors.yaml` (RBAC and routing only), `teams.yaml`, `scenarios/`, `out_of_policy.yaml`, `capability_gaps.yaml`.
- Env: `TILO_API_DEV=1`; `TILO_API_DEV_ORIGINS` (default `http://localhost:5173`); `TILO_DEV_UNIT_DELAY_S` (1.5, 0..10); `TILO_JUDGE_LIVE=1`.
## Local rules
- Side effects go through the outbox and the deterministic policy engine, T3 only with a person. `/health` (Cloud Run smoke check, #397) and `/healthz` (in-container): ok. Task routes read only `application/json` (415).
  SEC-15 (`tilo_api.access`, `tests/API_SEC_15.md`): deployed (`K_SERVICE`/`CLOUD_RUN_JOB`) the `AccessGate` middleware refuses every route not in `PUBLIC_ROUTES` (`/health`, `/healthz`, `GET /access`, `POST /access/declaration`, `POST /internal/schedules/tick`) from the stored visitor/judge declaration (403 `under_construction`/`declaration_required`; 503 with no `deps.get_access_store`; set once, 409 `declaration_locked`). Live models only via `provider_mode` -> `deps.router_for_mode` (replay_only wins; `TILO_JUDGE_LIVE=1` is the user's, never set in code).
- Dev mode (CL-INT-4, `tilo_api.dev`): fixed owner `u_dev_owner`, in-memory `Store`, a writer that refuses an event with no
  `vis`, CORS for `TILO_API_DEV_ORIGINS` only, Host loopback:8080; no cloud, no paid call; refuses when `K_SERVICE`,
  `CLOUD_RUN_JOB` or live is set. `dev_run` (CL-INT-5c/5d): a paced unit runner (`config/prices.dev.yaml`), a fake recipient.
- `GET /worlds/{id}/layout` (FR-WLD-05): the run's layout, 404 until built; owner gets `tilo_world` geometry (CL-INT-6); others an allowlisted view.
- `POST /intake` (FR-INT-01/02/11/12): multipart `text`, `files`, optional `scenario` -> 201 task, per-file status; or 422
  `{"error": reason}`, nothing stored (a refusal adds `alternative`, `category`; nothing possible, FR-INT-15, adds `gaps`; a bad scenario id is 422); 201 has `gaps`.
  Approve builds the scenario's policies and events first, then stores: the owner's own, one `policy.changed` each.
- Team Lead console (FR-HIL-10, `tilo_api.console`): `GET /worlds/{id}/console`, `POST .../console/cards/{id}/answer`;
  role `team_lead` + an owner-assigned, schema-valid `config/teams.yaml` record; only its domain's questions (never on the
  cards routes); same Pause-all guard as cards. Skill proposals (FR-AGT-15, `tilo_api.skill_proposals`, `tests/API_FR_AGT_15.md`): `/worlds/{id}/skill-proposals[/{pid}[/approve|reject]]`; the answering Lead promotes, another current Team Lead of the domain decides; never the owner as such.
- CP2 flow (CL-INT-1, `tilo_api.tasks`): intake also returns the `brief` and `questions`; then `POST /tasks/{id}/answers`,
  `GET .../approaches`, `POST .../approve`. Principal required; another user's task is 404. `deps.get_safety` (the
  `safety` role, 503 without one) screens every typed string; models only via `deps.get_router`; one budget grant per
  owner at a time. `tests/API_CL_INT_1.md`, BQ-83.
- Cards (FR-HIL-01/02, `tilo_api.cards`): `GET /worlds/{id}/cards`, `POST .../answer`. Identity is the verified
  `deps.Principal` only; channel class = the session's (web or mobile_web, either); email only from tilo-channels, needs_you only; WhatsApp removed (SD-01), no PIN (CH-RM). Viewer 403; PRD 10.1 scope. First
  answer wins (400 `already_resolved`, 409 `busy`); one derived `event_id` each. `tests/API_ST3b.md` (Round 2), BQ-69..73. Share links (FR-HIL-12, `tilo_api.sharing`, `config/sharing.yaml`): the owner re-raises a gate as a new proposal for a named Approver, who opens and answers `/share/{token}` after sign-in; a gate and its re-raises are one wait, one live share per gate; token hashed, in no event, card or log; `tests/API_FR_HIL_12.md`, BQ-HIL12-1..4.
- Run (CL-INT-2, `tilo_api.runs`): approve starts a run if the Director's plan (`deps.get_plan_compiler`, FR-INT-09)
  passes `validate_plan`; a unit may ask first (`MustAsk`, `deps.get_must_ask_providers`; `QuestionWait` holds it, no
  `world.completed` while one waits, BQ-235..237; its card is never merged, #338); a send waits at a gate card, then the outbox after the owner approves.
  Events via `deps.get_event_writer`; paused gets none. A `deliver` unit delivers in_app, ungated. `replay_only` (NFR-24, process-wide flag, BQ-238) closes intake, answers, approaches, approve: 503 `replay_only: true`. `GET .../delivery`: 409 until `world.completed`. `tests/API_CL_INT_2.md`.
  Outputs (ADR-0018 T4): `run_plan` puts them on `deps.get_artifact_store` in Scope (`deps.ORG_ID`, world, owner) and announces them; the gate runs in `Run.before_handoff` on the first announced item. The store, redactor and archive seams refuse in production (no run starts) until T8 and FR-MEM-05; dev mode wires an in-memory store. `tests/API_FR_AGT_02_T4.md`.
- People API (PPL-11a, `tilo_api.people`, `tests/API_PPL_11a.md`): `GET /v1/meetings/{id}/quotes?ids=`, `GET /v1/work-items/{id}/quote` (ADR-0020), `GET /v1/plate` (ADR-0021, `people_plate.py`: own six sources, a failing source is 503, never partial); writes (`people_writes.py`): `POST /v1/meetings|people|work-items`, `/v1/meetings|work-items/{id}/confirm` (JSON only 415, closed bodies 422, redact then schema, `check_write`, CAS 409, refused create 403); one org (`deps.ORG_ID`), person = `Principal.user_id`, one 404 body, 422 shape, 503 `not_configured` (`get_people_stores`, `get_plate_sources`, `get_source_owners`, `get_clock`, T4 store/redactor); no model, no `LIVE`.
