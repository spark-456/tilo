# FR-AGT-14b: public API pinned by the schedule store, schedule routes, scheduled-run start and tick tests (overridable)

FR-AGT-14 "Scheduled runs" (Clock Tower), PRD 8.6, second half: the production schedule store, owner-scoped schedule
routes, the scheduled-run start and the tick, all in tilo-api (option B of the supervisor's 6 Oct decision; PR 2 later
retargets the Scheduler job in `infra/`, which this ticket does not touch). Design: the 14b design brief
(decisions 1-9), BQ-AGT14-1/2, ADR-0003. Builds on PR #446: `tilo_harness.schedule` (Cadence, next_slot, Schedule,
RunStart, slot_key, task_name, Ticker, TickWiring, MAX_FIRES_PER_TICK, CLAIM_LEASE) and `services/harness/tests/
API_FR_AGT_14.md`, all of which stay.

These are the tests' assumptions; the architect or builder may override them. If a name or shape changes, change the
tests in the same PR and say so in the review. Tests import only what is listed here.
Doubles: `services/api/tests/_fr_agt_14_lib.py`, `services/harness/tests/fr_agt_14_store_support.py`.

## `tilo_harness.schedule` (additions; nothing existing changes)

```python
class Schedule:                    # frozen, kw_only; the snapshot fields are ADDITIVE with these defaults
    brief: dict[str, Any] | None = None       # copy of the brief the owner approved (task.brief)
    approach: dict[str, Any] | None = None    # copy of the approach the owner chose (one of task.approaches)
    failures: int = 0
    backoff_until: datetime | None = None     # UTC-aware
    last_error: str | None = None             # a short fixed code (^[a-z][a-z0-9_]{0,63}$), never exception text
    created_at: datetime | None = None
    # approved_brief_ref (existing) is the world id of the task the owner approved (design's `source_world_id`).
    # If the builder wraps the snapshot instead, only `make_record` / `SchedApi.record` change; the tests read
    # these names as attributes of what `store.get` returns.

class StartSkipped(Exception):     # a start that deliberately did nothing (RunStarter.start raises it)
    def __init__(self, code: str, *, advance: bool = False)   # .code, .advance
    # advance=True: next_due moves to the first slot after the one skipped (retry next week);
    # advance=False: the slot stays and is retried after the backoff.
```

`Ticker.tick()` changes, all behind a store that has `record_failure`:
- start raises (any `Exception`), or `StartSkipped`: after claiming, it calls
  `store.record_failure(schedule_id, due, error=<code>, next_due=<None | first slot after the skipped one>)`, then
  `store.release(schedule_id, due)`; it never calls `complete`, never alerts, carries on with the other schedules.
  `error` is `exc.code` for `StartSkipped`, a fixed code (`"start_failed"` suggested) for anything else; never `str(exc)`.
- everything after `claim` (slot arithmetic, `slot_key`, building `RunStart`, the start) is inside the try, so any
  exception releases the claim; `store.complete` and `store.record_failure` raising are logged per schedule and never
  abort the tick for the others (this replaces BQ-AGT14-2 (e) for `complete`: it no longer propagates).
- a `record_failure` missing on a #446 style fake store must not break the committed tests (those fakes keep their
  retry-every-tick behaviour); the builder adds it additively to `schedule_support.MemoryScheduleStore` or guards.
- `TickWiring` verification also requires `claims["iss"]` in `{"https://accounts.google.com", "accounts.google.com"}`
  (exact, case-sensitive; missing or any other value: 401 or 403), on the harness route as well.

## `tilo_harness.schedule_store` (new module)

```python
SCHEDULE_ID = re.compile(r"^sched_[0-9A-Za-z_]{1,64}$")   # an id can never reach a Firestore path
MAX_FAILURES = 8
def backoff_for(failures: int) -> timedelta     # min(60 s * 2**failures, 24 h); failures >= 1; no overflow for huge n
class ScheduleStoreNotConfigured(RuntimeError)

def schedule_to_doc(s: Schedule) -> dict[str, Any]       # the stored document, Firestore field names:
    # schedule_id, owner_user_id, title, cadence{weekday,hour,minute,tz}, approved_brief_ref, budget_cap, enabled,
    # next_due (datetime), last_slot, last_world_id, brief, approach, failures, backoff_until, last_error, created_at
def schedule_from_doc(doc: Mapping[str, Any]) -> Schedule
    # raises ValueError for anything that cannot be built: bad cadence, next_due missing/naive/not a datetime/not
    # ALIGNED to the cadence (next_slot(cadence, next_due - 1 microsecond) != next_due), bad cap (<=0, NaN, inf, bool,
    # string), wrong field types. schedule_from_doc(schedule_to_doc(s)) == s.

class InMemoryScheduleStore:                # same behaviour as Firestore, thread-safe (a lock = the transaction)
    def __init__(self, *, clock: Callable[[], datetime] | None = None)   # the STORE's clock (default: wall UTC)
class FirestoreScheduleStore:               # orgs/{org}/schedules/{schedule_id}; server time for leases and backoff
    def __init__(self, *, project_id: str, org_id: str = "org_tilo", client: Any = None)  # no client: firestore.Client(project=project_id)

def open_schedule_store(env: Mapping[str, str] | None = None, *, clock=None, firestore_client_factory=None) -> ScheduleStore
```

`open_schedule_store` is the one explicit-config door (ADR-0003 addendum): `TILO_SCHEDULES_STORE=memory` returns an
`InMemoryScheduleStore(clock=clock)`; `=firestore` plus a valid `TILO_FIRESTORE_PROJECT` (GCP project id shape
`^[a-z][a-z0-9-]{4,28}[a-z0-9]$`) returns a `FirestoreScheduleStore` whose client came from
`firestore_client_factory(project)` (default: the real `firestore.Client(project=project)`); anything else, including no
config, an unknown value, or the switch without a project: raises `ScheduleStoreNotConfigured`, builds no client.
`env=None` reads `os.environ`. Importing the module builds no client. `tilo_harness.store.FirestoreStore` and its
emulator/demo- guard are unchanged.

The store, in addition to the four `ScheduleStore` calls of #446 (same meaning):

```python
def create(self, schedule, *, max_per_owner: int) -> bool    # atomic per-owner cap; False stores nothing;
    # ValueError if schedule_id does not match SCHEDULE_ID
def get(self, schedule_id) -> Schedule | None                # None if absent, malformed id, or undecodable
def read_doc(self, schedule_id) -> dict | None               # the stored document as is (to see quarantine)
def insert_raw(self, doc: Mapping[str, Any]) -> None         # no validation; keyed by doc["schedule_id"] (tests, migrations)
def list_for_owner(self, owner_user_id) -> list[Schedule]
def update(self, schedule_id, *, enabled=None, title=None, cadence=None, next_due=None) -> Schedule | None  # None = unchanged
def delete(self, schedule_id) -> bool
def record_failure(self, schedule_id, due, *, error: str, next_due: datetime | None = None) -> None
    # for the claim held on `due`: failures += 1, last_error = error, backoff_until = store_now + backoff_for(failures),
    # drops the claim; next_due = <given> when given (a skipped slot); enabled = False once failures >= MAX_FAILURES
def due(self, now, limit) -> list[Schedule]
    # enabled, next_due <= now, backoff_until None or <= now; oldest next_due first, ties by schedule_id; at most
    # `limit`. A record that cannot be built is QUARANTINED in place (enabled=False, last_error="invalid_record") and
    # skipped; due() never raises for one, and a flood of them cannot hide a healthy schedule beyond one more call.
def claim / release / complete   # as #446; a claim is a lease of CLAIM_LEASE on the STORE's clock; release(wrong due)
    # is a no-op; claim on an unknown or malformed id is False
```

## `tilo_api.schedules` (new module)

```python
MAX_SCHEDULES_PER_OWNER = 10
router: APIRouter                        # included in tilo_api.app
def get_schedule_store() -> ScheduleStore    # a dependency seam; reads env on each call (cache a success only)
    # TILO_SCHEDULES_STORE unset: memory when tilo_api.dev.dev_enabled() and not deployed/live-refused, else
    # HTTPException(503, "not_configured"); never caches a refusal; "firestore" without a project: 503, no client built
def get_clock() -> Callable[[], datetime]    # UTC-aware; default wall clock
def get_oidc_verifier() -> OidcVerifier      # default: a google-auth id_token wrapper; a token that is not a JWT raises
    # before any certificate fetch (no network for a malformed token)
class ScheduleStarter:                       # the RunStarter of the tick
    def __init__(self, *, store: deps.Store, schedules: ScheduleStore, seams: runs.Seams | None,
                 clock: Callable[[], datetime])
    def start(self, run: RunStart) -> str    # the world id; raises StartSkipped / any Exception
```

Env names (read per request): `TILO_SCHEDULE_TICK_AUDIENCE` (the api URL = the `aud`), `TILO_SCHEDULE_TICK_CALLER` (the one
allowed service-account email), `TILO_SCHEDULES_STORE`, `TILO_FIRESTORE_PROJECT`. The module names no service-account
address.

`ScheduleStarter.start` behaviour (decisions 3, 4, 6):
- reads the schedule record (the snapshot) from `schedules`; `run.owner_user_id` and `run.budget_cap` are checked against
  it and never trusted over it (a wrong owner is refused; the cap granted is the record's);
- `seams is None`: raises `StartSkipped("run_seams_unwired", advance=False)`, no world created;
- the budget: `budget.request_budget_grant` for the record's cap with the owner's policies and the owner's earlier
  grants (as `approve` does); only an outcome with a `granted_event` (an L3 `grant_budget` policy of the owner that covers
  the cap and its daily limits) counts. Otherwise raises `StartSkipped("budget_not_granted", advance=True)`: nothing created.
  It never calls `grant_budget_by_person` and never reuses an earlier `budget.granted`;
- the world and run ids are deterministic from `run.idempotency_key` (sha256), matching `w_...` / `r_...` id patterns; a
  repeated or concurrent start of one key finds the world and returns it, writing no second `world.requested`, no second
  `budget.granted`, and starting no second run (also after a first start that raised after creating the world);
- the world: `store.worlds[w] = WorldRecord(owner=<record owner>)`, `world.requested` from
  `tilo_harness.schedule.world_requested_kwargs` is the first event (seq 1), then the policy-authorised `budget.granted`,
  then `tilo_api.runs.start_run(...)` (looked up on the module at call time so a test can replace it); events go through
  the single writer (`deps.get_event_writer`) or the store as `approve` does, and all pass the event schema;
- `start_run` raising propagates (the Ticker records a fixed failure code and releases the claim);
- the skipped-slot `alert.raised` (Ticker's `alerts`) is written to the new world's stream through the writer.

Routes (all need the signed-in principal; the owner is the principal's `user_id`, never the body; other users' schedules
and tasks answer the same 404 as unknown ones; JSON only, 415 otherwise; 422 bodies never echo input):

| Call | Route | Success | Errors |
| --- | --- | --- | --- |
| create | `POST /schedules` `{task_id, approach_id, title, cadence}` | 201 view | 401; 404 unknown or not your task; 409 task budget not granted, or 10 schedules already; 422 bad body or approach; 503 replay_only / no store |
| list | `GET /schedules` | 200 `{"schedules": [view]}` (own only) | 401; 503 no store |
| get | `GET /schedules/{id}` | 200 view | 401; 404 |
| update | `PATCH /schedules/{id}` any of `{enabled, title, cadence}` | 200 view | 401; 404; 422; 503 replay_only |
| delete | `DELETE /schedules/{id}` | 204 | 401; 404; 503 replay_only |

- `view`: `schedule_id` (`sched_...` server-generated), `title`, `cadence {weekday,hour,minute,tz}`, `enabled`, `next_due`
  (ISO-8601 UTC), `budget_cap`, `last_world_id`, `last_slot`, `failures`, `last_error`, `approved_brief_ref`, `created_at`.
- the server copies `task.brief`, the chosen approach and the cap of the task's `budget.granted` event; title 1..140
  characters; weekly cadence only (weekday 0..6, hour 0..23, minute 0..59, IANA tz; ints are strict; no extra keys);
  `next_due = next_slot(cadence, clock())` on create and when the cadence changes; the body never carries owner, brief,
  approach, cap, next_due, ids, counters (extra keys: 422, or ignored; never honoured).
- replay-only (`deps.refuse_if_replay_only`, after sign-in and the owner check) refuses create, update and delete with the
  global 503 `{"replay_only": true}`; reads still work.

`POST /internal/schedules/tick` (no principal; no body or query used):
- not configured (either `TILO_SCHEDULE_TICK_*` env missing or empty, or no schedule store): 503, before the token is looked at;
- no `Authorization: Bearer <token>` (missing, empty, other scheme): 401; the verifier raises: 401; the verifier is asked
  `verify(token, <TILO_SCHEDULE_TICK_AUDIENCE>)`;
- verified, but not (`iss` in the two Google values, `aud == audience` (a string), `email_verified is True`, `email ==
  TILO_SCHEDULE_TICK_CALLER` exactly): 403 (401 also accepted for `iss`); `tilo-gmail-scheduler`, `tilo-tasks-invoker`,
  `tilo-api` and another project's account are all 403;
- else 200 `{"fired": n}` from `Ticker(store=schedules, starter=ScheduleStarter(...), flags=deps.get_flag_store(),
  clock=get_clock(), alerts=<writes alert.raised into the new world>)`; replay-only: 200 `{"fired": 0}`, nothing moves;
  a store or flag read that raises: 5xx with a fixed body (no exception text);
- only POST (405 otherwise); responses never contain a token, an address or an exception text;
- the starter's seams come from `runs.run_seams` (mode replay unless the user's own `LIVE`), the same dependency approve uses.

## Decisions for the owner or architect (flagged, not made by the test-writer)

1. `POST /internal/schedules/tick` must be a public route of `access.AccessGate` (deployed, the Scheduler has no session or
   declaration). That changes `access.PUBLIC_ROUTES` and the pinned set in `_sec15_lib.PINNED_PUBLIC_ROUTES` (the SEC-15
   test says adding a public route is an owner decision) and makes `test_SEC_15_visitor_refused` count one more public route.
   `test_FR_AGT_14_deployed_the_tick_reaches_its_own_check...` pins the behaviour; the SEC-15 pin is not edited here.
2. ADR-0003 addendum (or a new ADR): `tests/repo/test_FR_AGT_14b_schedule_store_guard.py` expects the ADR text to name
   `TILO_SCHEDULES_STORE`, `TILO_FIRESTORE_PROJECT`, the emulator and `demo-`.

## System test (design item 8): not written, and why

`tests/system` talks to a real `uvicorn tilo_api:app` in dev mode (`TILO_API_DEV=1`, fixed port 8080). The tick needs
an injected OIDC verifier and a clock the test can move, and the owner needs an L3 `grant_budget` policy; the dev app has
none of the three and no route to create a policy, so a system case would need a new dev-only seam in an auth route (an env
that swaps the verifier) plus a dev policy fixture, well past the ~60 lines the design allows, and a dev-only way to
bypass the OIDC check is a hazard the tests should not invite. The same flow is covered in-process, through real HTTP
semantics on the real app, by `test_FR_AGT_14_scheduled_start.py` and `test_FR_AGT_14_tick_route.py`. Revisit when PR 2
gives the dev stack a real token path.
