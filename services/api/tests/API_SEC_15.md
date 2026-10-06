# SEC-15: deployed access, visitor or judge (what the acceptance tests pin)

Source: `docs/prd-supplement-2026-10-05.md` section 4, SEC-15 (Must, user, 5 Oct): "Deployed access: sign-up asks
'visitor or Google AI Builder Cup judge?'. Visitors see 'still under construction, not open to the public' and get
no access; judges get live models (never forced to replay). Enforced server-side from the stored declaration."
Acceptance: "A visitor's API calls are refused server-side; a judge's run uses live models." Related: SEC-16 (per-uid
rate limit and lifetime cap: "the caps are the real protection, since the declaration can be bypassed"), NFR-24
(`replay_only`), EFF-01 (only the user sets `LIVE=1`; dev and CI make no paid call), PRD 16.1 (Tilo never handles
passwords). Tests: `services/api/tests/test_SEC_15_*.py` (helpers `_sec15_lib.py`, fixture `sec15_factory` in
`conftest.py`), `apps/web/src/access/access.SEC-15.test.tsx`, `apps/web/src/api/http.SEC-15.test.ts`.

No contract change is needed for any of this. (The declaration is a tilo-api record behind a store seam, like the
`Store`; no event is emitted and no schema in `contracts/` describes it. If the owner wants the declaration
audited as an event or the Firestore document shape fixed in `contracts/`, that is a later decision:
"needs contract change" is not claimed here.)

## Where it is enforced

A new module `tilo_api.access` and four small pieces of wiring.

| Piece | Shape |
| --- | --- |
| `access.Declaration` | `Literal["visitor", "judge"]`. Nothing else is ever stored. |
| `access.PUBLIC_ROUTES` | `frozenset[(METHOD, path template)]`, exactly `{GET /health, GET /healthz, GET /access, POST /access/declaration}`. Every other route is gated. The test pins this set as literals, so a new public route needs a test edit and an owner decision. |
| `access.InMemoryAccessStore` | `get(user_id) -> Declaration \| None`; `declare(user_id, declaration) -> Declaration`: atomic, first write wins, returns what is stored (so a second, different call returns the first value). The protocol is these two methods; a Firestore store replaces the in-memory one later. |
| `access.enforced(env=None) -> bool` | True iff `K_SERVICE` or `CLOUD_RUN_JOB` is present in the environment (presence, not truthiness; the same rule as `tilo_api.dev.refuse_if_unsafe`), read on every request. Not deployed, nothing is enforced: CI, the existing suite and `just dev-api` behave exactly as before (dev mode forbids itself when deployed, so the two never coexist). |
| `access.provider_mode(declaration, env, *, replay_only=False) -> "live" \| "replay"` | Pure, no I/O, never reads or writes `os.environ` (see "Judge: live models"). |
| `deps.get_access_store() -> AccessStore` | A dependency like `get_store`: the production default raises 503 `not_configured` until a store is wired; tests override it. |
| `deps.router_for_mode(mode) -> Router` | The one place a request's `Router` is built. `deps.get_router` calls it with the request's mode. The tests spy on this name (`monkeypatch.setattr(deps, "router_for_mode", ...)`), so `get_router` must look it up through the module at call time. `_worker_models`, `get_plan_compiler`, `get_unit_runner` and `get_must_ask_providers` all use `get_router`, so one change covers the Director, the units and MustAsk (the run seams currently call `get_router()` directly, not as a FastAPI dependency; they need the request's mode threaded through). |

### The gate (a deterministic check, never model-decided)

An application-wide dependency (or an equivalent first middleware) that runs on every route not in
`PUBLIC_ROUTES`, **before** body parsing, path or world lookups, the safety screen and any router or store work:

1. Not `enforced()`: pass (no store is read).
2. No signed-in person: the existing 401 (the access store is not read).
3. Store unwired (`get_access_store` raises): 503 `not_configured` (or 403). Fail closed; never an open route.
4. `declaration = store.get(principal.user_id)` (the verified `Principal` only; never a header, query, cookie or body
   field, whatever it claims).
5. `None`: 403 `{"detail": <a sentence asking which they are>, "code": "declaration_required"}`.
6. `"visitor"`: 403 `{"detail": "Tilo is still under construction and not open to the public.", "code": "under_construction"}`.
   The test asserts the `code` and that `detail` contains "still under construction" and "not open to the public"
   (lower-cased); nothing else about the sentence. The body is identical for every route and every state of the
   world: an unknown world or task id gets the same 403 as a real one (no membership oracle).
7. `"judge"`: pass; the route's own rules (ownership, roles, validation) apply as before.

A refused request has no side effect: no store write, no event, no safety call, no router built (the test compares
snapshots before and after, across five body shapes per route).

### Public routes

- `GET /access` (signed in; works for every declaration state, deployed or not): 200
  `{"declaration": "visitor" | "judge" | null, "allowed": bool, "models": "live" | "replay" | null}`. `allowed` is
  `declaration == "judge"`; `models` is `provider_mode(...)` for an allowed person and `null` otherwise (so the web can
  show an honest "live" or "replay" label, NFR-22). Needs the access store (503 without one when enforced).
- `POST /access/declaration` (signed in; the sign-up step): JSON `{"declaration": "visitor" | "judge"}` only.
  - 200 with the same shape as `GET /access`, when nothing was stored (it is stored now) or the same value was stored.
  - 409 `{"detail": ..., "code": "declaration_locked"}` when a different value is stored; the stored value is unchanged.
    Set once, in both directions: a visitor cannot become a judge and a judge cannot be downgraded by a request.
  - 422 for any other value (`"Judge"`, `""`, null, numbers, lists, a missing field): nothing stored, so no access.
  - 415 or 422 for a body that is not `application/json` (urlencoded, multipart, `text/plain`): a hostile page can post
    those cross-site without a preflight. Same rule as the task routes (415).
  - The declaration is for `principal.user_id` and nobody else: extra body fields (`user_id`, `owner`) are refused (422)
    or ignored, never obeyed; headers and the query string name nothing.
  - 401 when signed out. No route takes or stores a password.

No profile, account or settings update route may accept a `declaration` field: the only request schema in
`app.openapi()` that has that property is the one for `POST /access/declaration` (tested), and any future route whose
path says profile, account, settings, me or users is probed with a `declaration` in its body (tested).

## Judge: live models

`provider_mode(declaration, env, *, replay_only=False)`; `env` is a mapping (the caller passes `os.environ`):

| Condition | Mode |
| --- | --- |
| `replay_only` (NFR-24, the US$25/day kill switch) | `replay`, always |
| `env["LIVE"] == "1"` (the user's own global switch, unchanged meaning) | `live` |
| deployed (`K_SERVICE` or `CLOUD_RUN_JOB` present), `declaration == "judge"`, `env["TILO_JUDGE_LIVE"] == "1"` | `live` |
| anything else (a visitor or none; a judge where the deployment did not permit it; any judge in dev or CI) | `replay` |

Only the exact string `"1"` counts, for both variables. `TILO_JUDGE_LIVE=1` is the deployment config that permits a
judge's live models; like `LIVE=1`, only the user sets it, on the deployed service, never in dev or CI and never from
a request. The decision never sets any variable, so a judge declaration cannot flip `LIVE=1` in dev or CI; the live
paths are exercised in tests by the spy on `router_for_mode`, over a scripted provider: no paid call.

When not enforced (not deployed) the request's mode is `provider_mode(None, env)`: the access store is never consulted,
so CI keeps working with no store wired.

### Needs the architect (no tests can settle it)

`packages/providers` gates live on the process-wide `LIVE=1` inside `RecordReplayProvider._is_live()` and every adapter
("the `LIVE=1` gate lives in every adapter"). A per-request live decision needs an explicit, injected "live permitted"
parameter on the provider the router builds, or a second `Router` built under a deployed-only, user-set
`TILO_JUDGE_LIVE=1`, instead of loosening that gate. The tests do not constrain how; they pin only the decision
(`provider_mode`), the seam (`router_for_mode`) and that no request ever sets `LIVE`. A replay-only router is
unchanged. Ask before choosing the mechanism: it touches a hard rule.

## Ambiguities resolved (PRD defaults, also in the report)

1. "Never forced to replay" versus NFR-24: the kill switch wins. PRD FR-MTR-04 and 17.3 make the hard cap switch the
   link to replay-only, and the SEC-15 row itself says the caps are the real protection. A judge is never made replay
   by the deployment default; only the cost kill switch overrides.
2. How the deployment "permits" live for judges: `TILO_JUDGE_LIVE=1` (or the user's global `LIVE=1`). The PRD names no
   variable; this is the smallest option that keeps "only the user sets the live switch".
3. Missing declaration: fail closed with a distinct code (`declaration_required`) so the web can ask the question
   again; the supplement does not say.
4. Declaration changes: set once, both ways (no PRD text allows any change; an owner-side admin change is out of
   scope).
5. Enforcement only when deployed: the PRD is about the deployed link; dev and CI stay as they are.
6. A visitor still reaches `GET /access` and `POST /access/declaration` (signed in) and `/health`; nothing else.
