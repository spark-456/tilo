# SEC-16 and FR-MTR-04: spend caps, rate limit and the durable replay-only switch (what the acceptance tests pin)

Sources: `docs/prd-supplement-2026-10-05.md` section 4, SEC-16 (Must, user, 5 Oct): "Per-uid rate limit and a lifetime
spend cap of 1,000 INR per uid (config). The caps are the real protection, since the declaration can be bypassed";
acceptance "Over the rate limit gets 429; over the cap new work is refused with a clear message". PRD FR-MTR-04 (14.5):
"Per-run, per-user and per-org caps; hard cap triggers the kill switch" / "Exceeding the demo hard cap switches the
link to replay-only". NFR-24: one flag switches the link to replay-only. PRD 17.3: US$25/day hard (triggers NFR-24).
ADR-0002 decision 13: caps come from config, only the per-org daily cap may be null. User, 2026-10-06: judges signed in
with Google may use live models, within caps (JL-0; BQ-SEC15-1). Builds on SEC-15 (`API_SEC_15.md`): the same
`provider_mode`, `AccessGate`, `GET /access` and `deps.router_for_mode`.

Tests: `services/api/tests/test_SEC_16_*.py`, `test_FR_MTR_04_api_replay_only_switch.py` (helpers `_sec16_lib.py`,
fixture `sec16_factory` in `conftest.py`) and `tests/repo/test_JL_0_judges_live_models_note.py`.

No frozen contract changes. One new config file (below) needs a shape: "needs contract change: a
`contracts/spend_caps.schema.json` and a `CONFIG_SHAPES` entry for `config/spend_caps.yaml` (architect, ADR-0002
decision 13 style)". `config/metering.yaml` is not extended: its schema is `additionalProperties: false` and credit and
USD based, and these caps are INR minor units.

## Money

Every amount is an `int` in minor units (paise; 1 INR = 100). No float, no bool, no string anywhere in the ledger,
the config or the guard (a malformed amount raises `TypeError` or `ValueError` and changes nothing; the guard turns it
into a replay plan). The 3,000 INR lifetime cap (the user, 8 Oct, BQ-SEC16-3) is `uid_lifetime_minor: 300000` in config, and no source file of tilo-api
contains the literal 100000 or 300000.

## Config: `config/spend_caps.yaml`, `tilo_api.spend.load_spend_caps(path=None) -> SpendCaps`

Keys, exactly these (an unknown key is refused), read through a YAML safe loader; anything unusable raises
`ValueError` (a `SpendConfigError` subclass), nothing is defaulted, a missing file raises:

| Key | Meaning |
| --- | --- |
| `currency` | `INR`, nothing else |
| `uid_lifetime_minor` | lifetime spend per uid, positive int, never null (shipped: 300000) |
| `run_minor` | per-run cap, positive int |
| `org_day_minor` | per-org per-UTC-day cap, positive int or null for none |
| `global_day_hard_minor` | the whole deployment's per-UTC-day hard cap (NFR-24's trigger), positive int |
| `unit_reserve_minor` | the flat amount each live unit and each Director call reserves and settles at until PL-06 prices exist (BQ-SEC16-1), positive int, never null (shipped: 1000) |
| `rate_limit_requests`, `rate_limit_window_s` | the per-uid rate limit: positive ints |

`SpendCaps` is a frozen dataclass with those seven fields as keyword-only arguments (no `currency` field).
`deps.get_spend_caps() -> SpendCaps` returns `load_spend_caps(None)`; tests override it.

## The ledger: `SpendLedger` protocol, `tilo_api.spend.InMemorySpendLedger(caps, *, shared=None)`

`shared` is the ledger's whole state (a dict); two ledgers over one dict are one store, which is how a test restarts a
process. A Firestore ledger replaces the class, not the protocol (transactional: see below).

| Call | Behaviour |
| --- | --- |
| `reserve(*, uid, run_id, org_id, amount_minor, at) -> Reservation \| Refused` | Atomic. Checks, all `<=` (exactly the cap passes, one over is refused): the durable switch (`reason "replay_only"`), uid lifetime (`"uid_lifetime"`), run (`"run"`), org day (`"org_day"`, UTC day of `at`, skipped when null), global day (`"global_hard"`: refused, and the switch is flipped). A `Refused` has `.reason` and nothing else changed (except the deliberate flip); a `Reservation` has `id, uid, run_id, org_id, amount_minor` and never a `.reason`. Settled plus outstanding both count. |
| `settle(reservation, actual_minor) -> result with .overrun` | Replaces the hold with the actual, recorded in full even above the hold (MT-03: `overrun` true; a later reserve is refused over the cap). Settling the global day to `>=` `global_day_hard_minor` flips the switch. A second `settle` or `release` of one reservation raises `KeyError`. Works after the switch flipped (a unit already done is still recorded). A bad `actual_minor` leaves the hold in place. |
| `release(reservation)` | Rolls the hold back completely. |
| `spent_minor(uid)`, `settled_minor(uid)` | ints: settled plus outstanding, and settled only. |
| `replay_only() -> bool` | The durable switch. |
| `trip_replay_only(reason) -> bool` | Sets it; `True` only for the one caller that flipped it (idempotent, atomic: 20 concurrent callers, one `True`). |
| `reset_replay_only(*, by)` | The only way back: a named human (`by` a non-empty string, else `TypeError`/`ValueError`). Not reachable from any route or the guard. |

Concurrent `reserve` calls cannot overspend (tests: 50 threads on one cap, 40 on a run and an org cap, a model-based
Hypothesis property). The switch lives in the same store as the totals, so it survives a restart and is read by every
instance. A Firestore implementation must do each of reserve, settle and the trip as one transaction.

## The rate limiter: `tilo_api.spend.RateLimiter(*, limit, window_s, clock)`

Sliding window per key, the key being the exact uid string given. `check(uid)` returns a decision with `.allowed` and
`.retry_after_s` (an `int`, rounded up, at least 1, at most `window_s`). A denied check is not recorded. `limit` and
`window_s` must be positive ints. `deps.get_rate_limiter()` returns one process-wide `RateLimiter` built from config
(the same object each call; per-instance on Cloud Run, a shared limiter is a later decision, listed in the report);
tests override it.

## The guard: `tilo_api.spend.SpendGuard(ledger, flags, caps)`

Never raises; every failure means live denied, not an error.

- `begin_unit(mode, *, uid, run_id, org_id, estimate_minor, at) -> UnitPlan(mode, reservation, reason)`: asked before
  every unit. `mode == "replay"` in: replay plan, the ledger is not touched. `"live"` in: if either switch store says
  replay, `("replay", None, "replay_only")` and no reservation; else `ledger.reserve`: a `Reservation` is a live plan
  (`reason None`), a `Refused` is a replay plan with its reason (`uid_lifetime`, `run`, `org_day`, `global_hard`),
  an exception from the ledger or the switch store, or a malformed estimate, is `("replay", None, "unavailable")`.
- `settle_unit(plan, actual_minor)` / `abort_unit(plan)`: settle or release a live plan's reservation; a replay plan is
  a no-op; a ledger error is swallowed and the hold stays counted (a failure can only under-spend).
- `live_allowed(uid) -> bool`: not `replay_only()`, not `uid_capped(uid)`, and no store error.
- `uid_capped(uid) -> bool`: `spent_minor(uid) >= caps.uid_lifetime_minor`; any store error answers `False` (unknown is
  not capped, so new work is not refused over an outage; `live_allowed` still says no).
- `replay_only() -> bool`: the NFR-24 flag store's `replay_only` OR the ledger's record; any store error answers `False`.
- The guard has no method that clears the switch.

`access.provider_mode(declaration, env, *, replay_only=False, capped=False)`: `capped=True` is replay exactly like
`replay_only=True` (outranks `TILO_JUDGE_LIVE` and the user's `LIVE=1`); `capped=False` changes nothing.

## HTTP behaviour (deployed only, like the SEC-15 gate; not deployed nothing here is read or counted)

1. **Order.** SEC-15's gate first (signed out 401, undeclared 403, visitor 403): those never reach the limiter or the
   ledger (spies assert no call). Then, for a judge on every non-public route, the rate limiter (before any body parsing,
   store, safety or router work); then the route.
2. **429.** `{"detail": <a sentence>, "code": "rate_limited"}` with `Retry-After: <whole seconds, 1..window>`. No side
   effect. Public routes (`/health`, `/healthz`, `GET /access`, `POST /access/declaration`) are not counted. The key is the
   verified `Principal.user_id` only.
3. **Capped new work.** `POST /intake`, `GET /tasks/{id}/approaches` and `POST /tasks/{id}/approve` for a judge whose
   request would be live (`provider_mode` is live before the cap) and whose `uid_capped` is true: 4xx (402, 403 or 409; the
   PRD fixes none) `{"detail": <a sentence naming the cap>, "code": "spend_cap_reached"}`, no side effect, no router built.
   Requests that would be replay are never refused for a cap and never write the ledger. Reads are never refused.
4. **`GET /access`** reports `models: "replay"` for a judge when capped, when either switch is set, or when live cannot be
   checked (ledger or switch store unreachable, ledger unwired). It reports `"live"` otherwise (SEC-15's rules).
5. **The switch.** Either store set: new work is refused 503 `{"detail": <says replay>, "replay_only": true}` (NFR-24's
   existing refusal, now also from the ledger's record), nothing live is built, and after a restart (new ledger over the
   same backing, fresh flag store) it is still on.
6. **Fail closed.** `deps.get_spend_cap_ledger()` raises 503 `not_configured` until wired (like `get_access_store`); with the
   ledger or the flag store unreachable, or the seam unwired, a judge's work runs as replay (201, router mode `replay`),
   never live and never a 5xx.
7. **No client control.** A header, query or body field cannot raise, reset or move a cap or the switch (every gated
   route probed as a capped judge; the ledger is not written); no route path or request schema property names the ledger, a cap
   or the switch.

## What is not pinned here (no test can settle it; needs the owner or the architect)

- **Per-unit wiring and pricing.** The guard is the seam; the tests do not run a unit through it because cost cannot be
  computed yet: `config/prices.yaml` is unset (PL-06), the price book is USD credits, and the cap is INR. Converting a
  model call's cost to INR minor units needs a rate in config that the PRD does not give. Decision needed: the USD to INR
  rate (a config key) or a direct INR price table. Until then (BQ-SEC16-1, a default the user may change) the builder
  wires `begin_unit` and `settle_unit` around each unit with `caps.unit_reserve_minor` as the estimate and the actual.
- **The Director's own call at intake, approaches and MustAsk** are model spend too. By the same default they reserve
  `caps.unit_reserve_minor` against the uid; the tests pin only that a capped uid's new live work is refused first.
- **Production backing.** Firestore ledger and switch store (and a shared rate limiter) are later tickets; BQ-238 stays open
  until one exists. `TILO_JUDGE_LIVE=1` stays the user's to set (BQ-SEC15-6), and now has its precondition: this ticket.

## Ambiguities resolved (PRD defaults, also in the report)

1. Config home: a new `config/spend_caps.yaml`, because the metering contract is frozen and USD/credits based.
2. Global hard cap is per UTC day (PRD 17.3 "daily"), in INR minor units; it reaches the switch at `>=` on settle and on a
   reserve that would exceed it, like the Treasury (hard cap reached).
3. Rate limit scope: every gated request of a judge counts (the supplement says "per-uid rate limit", no routes named);
   numbers come from config; sliding window.
4. HTTP code for a capped refusal: 4xx among 402/403/409 with the stable `code`; rate limit is 429 (stated by the PRD).
5. "Falls back to replay for already-running work": per unit through `begin_unit`; new work is refused.
6. Rate limit before cap: both are gate-level; a rate-limited request is 429 whatever else is true of the uid.
