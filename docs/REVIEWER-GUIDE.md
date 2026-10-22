# Reviewer guide

For a person or an AI reviewer opening this repository cold. It says where to start, where each service's entry point
is, how the tests are organised, which rules are enforced by tests, and what is known not to be finished. It was written
from the code on 22 October 2026; if something here disagrees with the code, the code wins.

## Where to start (30 minutes)

1. [README.md](../README.md): what Tilo is, the repository map, how to run it.
2. [docs/ARCHITECTURE.md](ARCHITECTURE.md): services, data stores, the run flow, the meeting bot, connectors, the
   security model. Read "Three things surprise readers" first.
3. [CLAUDE.md](../CLAUDE.md): the hard rules (models are configuration, side effects go through the outbox and policy
   engine, nothing animates without a recorded event, no secrets, no paid calls in dev or CI).
4. [contracts/README.md](../contracts/README.md) and `contracts/events/registry.yaml`: the schemas and the event
   registry. **Contracts win over prose.**
5. One service's `README.md` and `CLAUDE.md`, then its entry point (table below).

Order of authority when sources disagree: `contracts/` > the code > [the PRD](prd/tilo-prd-v2.md) (read-only, the spec;
requirement IDs such as `FR-*`, `NFR-*`, `SEC-*` are ticket ids) > [ADRs](adr/) > code comments. The `CLAUDE.md` files
carry requirement lists written ticket by ticket; they are dense and in places stale (see
[Stale statements](#stale-statements-in-older-docs)).

## Entry points

| Area | Start here | Then |
| --- | --- | --- |
| API app and middleware | `services/api/src/tilo_api/__init__.py` | `deps.py` (every store and client is built here), `access.py`, `firebase_auth.py`, `appcheck.py`, `rate_limit.py` |
| Intake, plan, approve | `tasks.py` (`approve` calls `runs.start_run`), `intake.py`, `quick.py` | `tilo_planning`: `compiler.py`, `plangraph.py` (`validate_plan`) |
| Run execution | `services/api/src/tilo_api/runs.py` (`start_run`, `Run`) | `services/harness/src/tilo_harness/executor.py` (`run_plan`), `writer.py` (`WorldWriter`), `validator.py`, `tool_runner.py`, `must_ask.py` |
| Side effects | `runs.py` (`tilo_policy.decide`, gate card, `open_gate`, `Outbox.enqueue`) | `packages/policy/src/tilo_policy/decide.py`, `gate.py`; `config/autonomy.yaml`; `services/connectors/src/tilo_connectors/outbox.py`, `side_effect_execute.py` |
| Approvals | `services/api/src/tilo_api/cards.py` | `sharing.py`, `console.py`, `dispatch.py` |
| Money | `spend.py`, `spend_units.py`, `config/spend_caps.yaml` | `costs.py`, `treasury_firestore.py`, `packages/metering` |
| Models and modes | `packages/providers/src/tilo_providers/router.py`, `replay.py` (`is_live_mode`) | `services/api/src/tilo_api/access.py` (`provider_mode`), `deps.py` (`router_for_mode`), `config/models.yaml` |
| Google connectors | `services/connectors/src/tilo_connectors/host_routes.py` | `host_broker.py`, `tokens.py`, `consent.py`, `adapters/` |
| Browser | `services/browser/src/tilo_browser/app.py` | `egress.py`, `playwright_engine.py`, `masking.py`, `fetch.py` |
| Render | `services/render/src/tilo_render/app.py` | `spec.py`, `pdf.py`, `pptx.py`, `docx.py`, `xlsx.py` |
| Meet bot | `meet-bot/bot/session.py`, `cloud_run.py` | `brain.py`, `wake.py`, `captions.py`, `meeting_actions.py`; API side `services/api/src/tilo_api/meeting_bot.py`, `meeting_bot_rpc.py` |
| Web app | `apps/web/src/Root.tsx`, `src/park/app/ParkApp` | `src/api/http.ts`, `src/world/` (reducer, choreographer), `src/stage/Stage.tsx`, `src/honesty/` |
| Layout solver | `packages/world/src/tilo_world/solver.py` | `services/api/src/tilo_api/layout.py` |
| Infrastructure | `infra/envs/dev/main.tf` | `infra/modules/`, `infra/ACCESS.md` (who can call whom), `cloudbuild.yaml`, `firebase.json` |

## How the tests are organised

Test files are named after the requirement they prove, for example `test_FR_WLD_02_generated_types_match_schemas`; the
requirement id is the definition of done. Python tests live beside what they test, not in one folder.

| Area | Location | About | How to run |
| --- | --- | --- | --- |
| Repository guards: Terraform, Dockerfiles, workflows, docs, CSP, justfile, the PRD 20.5 README sections, the 40-line `CLAUDE.md` cap, the meet bot's import rules, model-id and scenario-specific-code rules | `tests/repo/` | 67 files | `uv run pytest tests/repo -q` |
| Contracts: every schema, fixture and registry rule | `tests/contracts/` | 77 | `uv run pytest tests/contracts -q` |
| Services | `services/<name>/tests/` | api 470, harness 119, connectors 109, channels 100, browser 26, render 15, sandbox-web 5 | `uv run --package tilo-<name> pytest services/<name>` |
| Packages | `packages/<name>/tests/` | providers 83, planning 47, memory 32, policy 13, archive 13, people 11, metering 9, redact 9 | `uv run pytest packages/<name>` |
| Meet bot | `meet-bot/tests/` | 46 | `just meet-bot-test` (fakes only: no browser, network or key) |
| Skills | `skills/**/tests`, `skills/productivity/test_SKILL_LIBRARY_specs.py` | 8 | `just skills-test` |
| Evals harness | `evals/tests/` | 82 | `uv run pytest evals/tests -q` |
| Whole stack | `tests/system/` | 2 | `just system-test` (starts the real API and other services as processes; about 3 minutes, port 8080) |
| Web unit and component | `apps/web/src/**/*.test.ts(x)` beside the source | about 600 files | `pnpm --filter @tilo/web run test` |
| Web end to end | `apps/web/e2e/` | about 150 Playwright specs | `TILO_WEB_PORT=<own port> pnpm --filter @tilo/web run test:e2e` (run by hand; not in `just check`) |

Markers: `emulator` (needs the Firestore emulator, Java and firebase-tools; excluded by default, registered in the api and
harness `conftest.py`), `system`, `slow`. `just test` runs `pytest -m "not emulator and not system"` plus the web tests.
**`just check` is the full gate**: contract drift check, `ruff`/`biome` format and lint, the model-id lint, `mypy` and
`tsc`, then all tests. `just check-fast` skips the type checks. Provider and connector tests use fakes and recordings; an
autouse fixture in the providers tests blocks the network. Nothing in `just check` makes a paid call.

Known baseline when running `tests/repo` in a fresh checkout without `pnpm install`: the two `test_ROUTE_AUDIT_1` tests
fail, because `tests/repo/web_routes.cjs` loads `typescript` from `apps/web/node_modules`. Everything else in
`tests/repo` passes (671 passed, 2 failed, 2 skipped on 22 October).

## Rules that tests enforce

Useful when checking a change; each is a test you can run or grep.

- **Models are configuration:** `scripts/lint_model_ids.py` (part of `just lint`) fails on a model id outside `config/`
  and `packages/providers`.
- **No scenario-specific code:** `tests/repo/test_GEN_06_no_scenario_specific_code.py`.
- **Honesty rules (PRD 9.4):** `apps/web/src/honesty/*.test.ts` scan the web source for animation APIs outside
  `choreographer.ts`; world Playwright specs (`world-honesty`, `world-determinism`, `world-replay-banner`) check
  behaviour.
- **Events are registered and fixtured:** `just contracts-check` and `tests/contracts/`; the registry has 101 types and
  an unregistered one fails the build.
- **The meet bot holds no ledger code:** `tests/repo/test_FR_MTG_11_BQ_M2_4_MV_12_bot_holds_no_ledger_code.py` checks its
  imports.
- **Generated types do not drift:** `just contracts-check`.
- **Secrets:** `scripts/secret_scan.py` (pre-commit and CI); fake secrets in tests are assembled at runtime.
- **Firestore is closed to clients:** `firestore.rules` and `firestore.tokens.rules` are catch-all denies, pinned by
  `tests/repo/test_PROD_WIRE_3_access_rules.py` and `test_ADR32_T5b_token_database_rules.py`.
- **Single API instance:** `tests/repo/test_PROD_WIRE_3_api_single_instance_everywhere.py`.

## Known gaps

What is not finished or not wired, found by reading the code. The ledger of questions and the defaults taken is
[docs/open-questions.md](open-questions.md) (about 1,200 `BQ-` rows, newest at the end). "Unverified" means it could not
be established from the repository alone.

**Deployment and runtime**
- `tilo-harness` as a Cloud Run service is a health check plus a schedule-tick route that is never wired (it answers 503).
  All run execution is inside `tilo-api`. The harness `CLAUDE.md` still describes it as the run service.
- The live state of the deployed services (environment variables, which flags are on, `LIVE` on connectors) is set with
  `gcloud`, not Terraform, so it cannot be read from the repository.
- Terraform grants `run.invoker` on `browser` and `render` to `tilo-harness` (and connectors to harness and api), but the
  code's caller is `tilo-api`. Confirm the live bindings; `infra/ACCESS.md` documents the intent.
- `tilo-render` over HTTP fails closed: the shipped image installs no OIDC verifier, so `POST /render` answers 403. The
  API renders in its own process unless `TILO_RENDER_URL` is set.
- The `/internal/gmail/{push,renew,poll}` routes that the Gmail Pub/Sub topic and two Scheduler jobs point at do not
  exist, and `GmailPushEndpoint` is never mounted. Whether inbound mail triage is wired in production is unverified.
- Pub/Sub publishing and BigQuery ledger writes are provisioned but unused by any service; the Firestore Treasury ledger
  is the live ledger.
- CI: `.github/workflows/ci.yml` and `deploy-dev.yml` exist, but [docs/deploy-dev.md](deploy-dev.md) says GitHub Actions is
  unused under the current policy; Cloud Build and local runs gate merges. No automation runs the Playwright specs.
  `uv` is pinned to 0.5.11 in `ci.yml` and 0.12.18 elsewhere.

**Product**
- Connectors: only Gmail, Drive and Calendar have code. No free/busy, no event update or delete, no Docs, Sheets or
  Slides API calls. `config/mcp.yaml` is empty, so no MCP server can connect, and ADR-0031 (Tilo as an MCP server) has
  no implementation in `services/`. Lovable and Canva are held ([docs/connectors/README.md](connectors/README.md)).
  Slack, Teams and Outlook cards are prepared offline.
- Built and tested but not called from the API: `verifier.Verifier`, `run_bundle` (export/import), `branch` (reuse),
  `lead_review`, `meeting_proposals.py`. The "verifier" in a real run is a plan unit of role `verifier`.
- Switched off by default: minutes analysis and follow-up (`meeting.minutes.enabled`), the bot's voice meter and
  actions routes, Live voice, bring-your-own-model-key (`config/byok.yaml`), the proactive meeting nudges. `GET /v1/effort`
  always answers 503.
- The meet bot's live behaviour (admission selectors, microphone routing, captions) is tested only with fakes and saved
  caption pages; its own `docs/CLOUD_RUN.md` lists what is unverified. A crash can leave a meeting in `joining` until an
  operator recovers it.
- Email Autopilot and Google sign-in run in testing mode for listed test users until Google's app verification is
  complete.
- The evals have no committed pass record (`evals/results.md` is absent); do not read the case counts as results.

**API behaviour worth a second look** (inferred from code, not run): `GET /worlds/{id}/costs`, the approver share-link
routes and the Team Lead console require a world-bound or non-owner principal that a normal Google sign-in does not
produce, so the web app uses `GET /costs` and the owner paths instead; and `cards.get_channels_caller()` always returns
false, so answering a card by email is design only.

## Stale statements in older docs

These are known to disagree with the code; do not rely on them.

- `services/harness/CLAUDE.md` (run service, ADK, "Pub/Sub to BigQuery"), `apps/web/CLAUDE.md` ("reads Firestore docs
  under security rules", the retired `App.tsx` and `FlowShell`), `services/channels/CLAUDE.md` ("public ingress for
  signature-verified webhooks"), `services/browser/CLAUDE.md` ("proxy sidecar", missing `/sessions` routes),
  `services/render/CLAUDE.md` (omits `docx`; Slides and Docs are not made by render).
- `contracts/README.md` says the event data folder has 96 files; it has 101.
- `docs/demo.md` and `docs/deploy-dev.md` (and `apps/web/e2e/hosted-smoke.spec.ts`, pinned by
  `tests/repo/test_W22_hosted_smoke.py`) call the demo button "Explore a demo session"; the app's button says
  "Explore a demo town", so the hosted smoke spec would not find it.
- `docs/transcript-ingest.md` describes an upload path that is a library only; the live bot path returns the transcript
  directly. `docs/minutes.md` omits the self-pick, send-to-everyone, brief and retention behaviour.
- `docs/cloud-test-gate.md` gives a spend cap of INR 1000; `scripts/gate_cloud.py` enforces INR 4500.
- `infra/README.md` lists 8 of the 10 modules; `infra/ACCESS.md` says "eight secrets" where Terraform declares ten.
- Root `CLAUDE.md` says infrastructure is "not applied yet" and that development is local-first until billing exists;
  `just deploy dev` now deploys through Cloud Build to project `essential-wares-510320-f0`. Its "Layout" list also names
  only some of the packages.

## IDs and conventions

`FR-`/`NFR-`/`SEC-`/`PL-`/`EFF-` ids are PRD requirements; `BQ-` rows in `open-questions.md` are build-time questions and
the defaults taken; `ADR-` are decisions in [docs/adr/](adr/); `HR-1`..`HR-7` are the honesty rules; `T1`..`T3` are risk
tiers and `L0`..`L3` autonomy levels. One ticket is one requirement id, committed with a `Req: <ID>` trailer. English
everywhere; Windows is the primary development environment (native, no WSL; ADR-0001) with Linux used for CI and
containers.
