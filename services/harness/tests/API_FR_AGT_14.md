# FR-AGT-14: public API pinned by the scheduled-run tests (overridable)

FR-AGT-14 "Scheduled runs" (Clock Tower), PRD 8.6: "A weekly schedule fires on time and reuses memory." Sources: PRD 8.6, 6.3
(Cloud Scheduler starts schedules; start runs with rate limits), 13.1 (memory layers), `infra/ACCESS.md` route requirements,
NFR-24 (`replay_only`), contracts 1.4.0 (`schedule` channel, actor = the schedule's owner), and the design brief.

These are the tests' assumptions; the architect or builder may override them. If a name or shape changes, change the tests in the
same PR and say so in the review. Tests import only what is listed here. Doubles: `schedule_support.py`.

## `tilo_harness.schedule` (new module)

```python
MAX_FIRES_PER_TICK = 20          # runs one tick may start; the rest stay due (design rule 8)

@dataclass(frozen=True)
class Cadence:                   # weekly only (rule 9)
    weekday: int                 # 0..6, Monday = 0, the LOCAL weekday
    hour: int                    # 0..23, local
    minute: int                  # 0..59, local
    tz: str                      # IANA name; __post_init__ raises ValueError for any field out of range or an unknown/empty zone

def next_slot(cadence: Cadence, after: datetime) -> datetime
    # Pure. The first slot STRICTLY after `after` (so next_slot(c, due) is the following week), UTC-aware, seconds and
    # microseconds 0. `after` must be aware (ValueError if naive), any zone. Local wall time is kept across DST. A local time that
    # does not exist that day fires at the next valid instant; an ambiguous one fires once, at its first occurrence.

@dataclass(frozen=True, kw_only=True)   # keyword construction; defaults on the last three
class Schedule:
    schedule_id: str
    owner_user_id: str           # u_...
    title: str
    cadence: Cadence
    approved_brief_ref: str      # world id of the run the owner approved
    budget_cap: float
    enabled: bool = True
    next_due: datetime = ...     # UTC-aware (required in practice; the tests always pass it)
    last_slot: str | None = None         # slot_key of the last firing
    last_world_id: str | None = None

def slot_key(schedule_id: str, due: datetime) -> str
    # f"{schedule_id}:{due as UTC ISO-8601}". Starts with "<schedule_id>:", is a pure function of (schedule, instant), differs
    # per schedule and per slot, and is the same whatever zone `due` is expressed in.

@dataclass(frozen=True)
class RunStart:                  # what the starter is told to start; keyword construction
    idempotency_key: str         # == slot_key(schedule_id, slot); identical on every retry of the same slot
    schedule_id: str
    owner_user_id: str
    title: str                   # the schedule's title
    approved_brief_ref: str
    prior_world_id: str | None   # the schedule's last_world_id (artifact memory offered, never silently reused)
    budget_cap: float
    slot: datetime               # the slot being fired (UTC), the LATEST missed one when several were missed
    skipped: int                 # missed slots collapsed into this firing; 0 when on time
    cache_namespace: str         # == schedule_id (result cache namespace)

class ScheduleStore(Protocol):   # Firestore `schedules/{schedule_id}` in production, in-memory in tests
    def due(self, now: datetime, limit: int) -> list[Schedule]
        # enabled schedules with next_due <= now, oldest next_due first (ties by schedule_id), at most `limit`
    def claim(self, schedule_id: str, due: datetime) -> bool
        # atomic: True iff the schedule is enabled, its next_due == due and no claim is held; then a claim marker is held
    def release(self, schedule_id: str, due: datetime) -> None
        # drops the claim for `due`; next_due and every other field unchanged
    def complete(self, schedule_id: str, due: datetime, *, next_due: datetime, last_world_id: str) -> None
        # the only call that moves next_due; sets last_slot = slot_key(schedule_id, due), last_world_id, drops the claim

class RunStarter(Protocol):
    def start(self, run: RunStart) -> str     # returns the new run's world id; raises on failure

# FlagStore is the Protocol of tilo_metering.flags (get/set/history); the ticker reads only get("replay_only").

class Ticker:
    def __init__(self, *, store: ScheduleStore, starter: RunStarter, flags: FlagStore,
                 clock: Callable[[], datetime],                     # UTC-aware
                 alerts: Callable[[str, dict[str, Any]], None])     # (world_id, WorldWriter.emit kwargs)
    def tick(self) -> TickResult        # TickResult.fired: int = runs started in this tick
```

`tick()` behaviour the tests pin: reads the clock once; fires nothing while `flags.get("replay_only")` is true and moves nothing;
asks the store for at most `MAX_FIRES_PER_TICK` due schedules and skips any that is not `enabled`; for each: finds the LATEST slot
<= now (stepping `next_slot` from `next_due`), `claim(id, next_due)`, builds the `RunStart` (`skipped` = slots before the latest,
`prior_world_id = last_world_id`), `starter.start(...)`, then `complete(id, next_due=<first slot strictly after now>,
last_world_id=<returned id>)`. When `skipped > 0` it calls `alerts(world_id, skipped_alert_kwargs(world_id, skipped, new_ulid(now)))`
once, after the start. If `start` raises (any `Exception`) it calls `release(id, due)`, does not touch `next_due`, does not alert,
and carries on with the other schedules; `tick()` itself does not raise for one schedule's start failure. A tick never starts a
slot whose claim it did not win.

```python
def world_requested_kwargs(run: RunStart, world_id: str) -> dict[str, Any]
    # WorldWriter.emit kwargs: type "world.requested", actor run.owner_user_id (NOT "system"), target world_id, a summary, and
    # data == {"title": run.title, "channel": "schedule", "destination": None}. Shape of
    # contracts/fixtures/events/valid/world.requested--scheduled.json.
def skipped_alert_kwargs(world_id: str, skipped: int, alert_id: str) -> dict[str, Any]
    # emit kwargs: type "alert.raised", actor "system", target world_id, severity "info", a summary that states `skipped`,
    # data == {"alert_id": alert_id, "card_id": None}.

@dataclass(frozen=True)
class TickWiring:                # the route's dependencies
    verifier: OidcVerifier       # .verify(token, audience) -> claims mapping (same Protocol as tilo_channels.gmail_watch)
    audience: str                # harness URL: the `aud` the token must carry
    service_account: str         # the one allowed caller email: tilo-schedule-scheduler@<project>.iam.gserviceaccount.com
    ticker: Ticker
```

## `tilo_harness.app`

```python
def create_app(*, schedule_tick: TickWiring | None = None) -> FastAPI
app = create_app()               # the production module-level app: tick route present, nothing wired -> 503
```

`POST /internal/schedules/tick`, no parameters, no body used:
- no `Authorization: Bearer <token>` (missing, empty, other scheme): 401. Verifier raises: 401.
- not wired (`schedule_tick is None`): 503 for any request, before any token is looked at (fail closed).
- verifier accepted but not (`claims["aud"] == audience`, `claims["email"] == service_account` exactly, `claims["email_verified"] is
  True`): 403. `tilo-gmail-scheduler`, `tilo-tasks-invoker`, `tilo-api`, the same account name in another project: all 403.
- otherwise 200 `{"fired": n}`. Only POST; other methods 405.
- a body or query string is ignored or refused (4xx); it never selects a schedule or sets the time.
- bodies never contain the token, an address, or an exception text.
- `/health` and `/healthz` unchanged.

## Infra (Terraform; the user applies it)

Pinned by `tests/repo/test_FR_AGT_14_schedule_tick_terraform.py` (static) and `infra/envs/dev/tests/schedule_tick.tftest.hcl` (plan).
New service account `tilo-schedule-scheduler`; exactly one `google_cloud_scheduler_job` named `tilo-schedule-tick` (no for_each or
count), `* * * * *`, UTC, POST `<harness URL>/internal/schedules/tick`, OIDC as that account with the harness URL as audience,
`retry_count = 1`, no body, no query; `run.invoker` on harness only through `extra_invokers`, no project-level role. New dev output
`schedule_tick` (shape in the tftest header). `cloud_run.tftest.hcl`'s harness invoker list gains that one account on purpose.
`infra/ACCESS.md` gains the account, job and route rows. Security review required (new invoker and IAM).
