# tilo-api

The one door into Tilo. The web app, the meeting bot and the schedulers all call this service; it holds the sign-in
check, intake and planning, **the execution of runs**, approvals, the policy engine and outbox, the spend guard and
ledger, and every Firestore write. It is a single FastAPI app, `tilo_api:app`
(`services/api/src/tilo_api/__init__.py`), served by `uvicorn` on `$PORT`.

## Run it

```powershell
just setup      # once
just dev-api    # dev mode on 127.0.0.1:8080
```

```sh
just setup && just dev-api      # the same on Linux or macOS
```

Dev mode (`TILO_API_DEV=1`, set by `python -m tilo_api`) uses an in-memory store, a fixed owner `u_dev_owner`, a fake
Director and unit runner (`config/models.dev.yaml`), and serves `/docs`. It refuses to start on Cloud Run or with
`LIVE=1`. Deployed, `/docs` and the OpenAPI document are switched off.

## What it owns

| Area | Routes (examples) | Modules |
| --- | --- | --- |
| Intake and planning | `POST /intake`, `POST /tasks/{id}/answers`, `GET /tasks/{id}/approaches`, `POST /tasks/{id}/approve` | `intake.py`, `tasks.py`, `quick.py` |
| Runs and worlds | `GET /worlds`, `/worlds/{id}`, `/events`, `/layout`, `/delivery`, `/result`, `POST /worlds/{id}/rerun` | `runs.py`, `worlds_list.py`, `redaction.py`, `results.py` |
| Cards and approvals | `GET /cards`, `GET\|POST /worlds/{id}/cards/...`, Team Lead `console`, approver `share` links | `cards.py`, `cards_feed.py`, `console.py`, `sharing.py`, `dispatch.py` (pause, stop autopilot, revoke a policy) |
| People and teams | `/v1/people`, `/v1/work-items`, `/v1/pinboards`, `/v1/teams`, `/v1/team`, `/v1/plate` | `people*.py`, `team_*.py` |
| Skills | `/v1/skills`, `/v1/skills/catalog`, `/v1/skills/captures`, `/v1/learn` | `skills_*.py` |
| Meetings | `/v1/meetings/...` (attend, host, minutes, brief, follow-up), `/v1/worlds/{id}/rooms` | `meeting_*.py` |
| Schedules | `/schedules`, `POST /internal/schedules/tick` | `schedules.py` |
| Money | `GET /costs`, `GET /worlds/{id}/costs` | `spend.py`, `spend_units.py`, `costs.py`, `treasury_firestore.py` |
| Connectors, push, settings | `/v1/connectors`, `/v1/push`, `/v1/me/settings`, `/v1/me/brief`, `/v1/memory`, `/v1/assistant/ask` | `connect_routes.py`, `connector_rpc.py`, `push_*.py`, `user_settings.py`, `memory_routes.py`, `assistant/` |
| Health | `GET /health`, `/healthz`, `/health/deps` | `health_deps.py` (reports store kinds and the live flag, never values) |

## Auth and abuse controls

Middleware, outermost first: CORS, log context, rate limit, `no-store` on `/v1/*`, App Check, the access gate, run-id
logging. Deployed, the access gate refuses every route that is not public unless the request carries a verified Firebase
ID token. The public set is health, `/access`, `/preview/website`, three `/internal/*` routes (each checks its own Google
OIDC token) and `/l/<token>` (an HMAC single-use link). App Check is logged until `TILO_APPCHECK_ENFORCE=1`. Every
refused read of someone else's world is the same 404. See [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#security-model).

## How a run executes

`POST /tasks/{id}/approve` calls `runs.start_run`, which starts a daemon thread inside this process that compiles and
validates the plan, solves the layout, and calls `tilo_harness.executor.run_plan`. There is no call to a harness
service. Events go to Firestore through `world_writer.py` (the harness's single writer). Outbound calls to
`tilo-connectors`, `tilo-browser`, `tilo-render`, `tilo-channels` and the meet bot carry an OIDC ID token from the
metadata server; each target URL is an environment variable (`TILO_CONNECTORS_URL`, `TILO_BROWSER_URL`,
`TILO_RENDER_URL`, `TILO_CHANNELS_URL`, `TILO_MEET_BOT_URL`) and a call is made only when it is set.

## State

Deployed state is Firestore (default) under org `org_tilo` plus two Cloud Storage buckets (`TILO_ARTIFACTS_BUCKET`,
`TILO_ARCHIVE_BUCKET`); the full path list is in [ARCHITECTURE.md](../../docs/ARCHITECTURE.md#data-stores). The stores are
opened only through `store_door.py` and `prod.py`, and only when `TILO_API_STORE=firestore` (and the per-feature
`TILO_PEOPLE_STORE`, `TILO_SKILLS_STORE`, `TILO_TEAM_STORE`, `TILO_SCHEDULES_STORE`) and `TILO_FIRESTORE_PROJECT` are set.
The API is configured as a single instance: per-run card state, approver links, rate limiters and the meet-bot claims are
in process memory.

## Modes

| Switch | Effect |
| --- | --- |
| `LIVE=1` | live models for the global switch; the meet-bot gateway also needs it |
| `TILO_JUDGE_LIVE=1` | every signed-in Google person gets live models on a deployment; an anonymous demo is always replay |
| `TILO_APPCHECK_ENFORCE=1` | a missing App Check token becomes a 401 |
| `TILO_MEETING_MINUTES_ENABLED=1` | registers the minutes analysis and follow-up routes |
| `TILO_VOICE_METER=1`, `TILO_MEETING_ACTIONS=1` | open the bot's `/internal/meeting-voice/*` and `/internal/meeting-actions/run` routes (404 otherwise) |

`replay_only` (set by the daily deployment cap) and a person's spend cap override all of them. Only the owner sets `LIVE`.

## Tests

```sh
uv run --package tilo-api pytest services/api/tests -q -m "not emulator"
just test-outbox-emulator       # the Firestore outbox contract suite; needs Java and firebase-tools
```

About 470 files named `test_<requirement-id>_<slug>.py`, with `_*_lib.py` helpers, `API_*.md` notes pinning each
interface, and a `conftest.py` whose `client`, `store` and `writer` fixtures drive the real app with a fake principal.
See [CLAUDE.md](CLAUDE.md) for the long requirement list; where it disagrees with the code, the code wins.
