# FR-AGT-14e interface (Cloud Tasks hand-off for scheduled runs)

Names and behaviour the tests pin. Builds on `API_FR_AGT_14b.md` and `API_FR_AGT_14d.md`; overridable by the architect or
builder if the tests change in the same PR. No contract changes, no Terraform change, **no new route**.

Why: Cloud Run bills request-based CPU, so a run thread started by the Scheduler's tick is throttled the moment the tick
returns and is lost on scale-to-zero. Always-on CPU is rejected on cost (EFF). The tick therefore only HANDS each due slot
to Cloud Tasks; the run executes inside the task's own request (CPU allocated while it runs).

Tests: `test_FR_AGT_14e_fanout.py`, `test_FR_AGT_14e_task_run.py`, `test_FR_AGT_14e_run_wait.py`,
`test_FR_AGT_14e_no_new_route.py` (services/api/tests) and `tests/repo/test_FR_AGT_14e_tasks_handoff_guard.py`.
Support: `_fr_agt_14_lib.py` (`FakeTasksClient`, `task_body`, `task_payload`, `SchedApi.task_call`,
`SchedApi.deliver_new_tasks`) and `_fr_agt_14e_lib.py`. No test touches the network (a non-loopback `connect` raises).

## 1. One route, two authenticated callers

`POST /internal/schedules/tick` keeps its path, method and public status (`access.PUBLIC_ROUTES` and the SEC-15 pin are
UNCHANGED: five routes). The caller identity decides the mode. Both callers go through the 14d machinery unchanged
(503 first for an unset audience or `TILO_SCHEDULE_TICK_CALLER`; bearer; verifier asked for the configured audience; the
claims `iss`, `aud`, exact `email`, `email_verified is True`; store and seams built only after the token passed; one
logged line when the verifier raises).

| Caller | Request | Mode | Success |
| --- | --- | --- | --- |
| `TILO_SCHEDULE_TICK_CALLER` (Scheduler) | no body | FAN-OUT | 200 `{"fired": n}` (n = slots handed to Cloud Tasks) |
| `TILO_TASKS_CALLER` (Cloud Tasks) | the task body (section 3) | EXECUTE ONE RUN | 200 `{"ran": 1, "state": "done"\|"parked"\|"timeout"}` |

Cross-mode: the Scheduler identity with a body, the Tasks identity without a body (or with `{}`, a query only), any other
identity with either shape: 403 or 422 (401 for no or a refused token), a fixed body, no side effect (nothing claimed,
enqueued, created or started). If `TILO_TASKS_CALLER` equals `TILO_SCHEDULE_TICK_CALLER` the identity cannot pick a mode:
403 or 503 for every request, no side effect.

## 2. Config (read per request, never hard-coded)

```python
# tilo_api.schedules
ENV_QUEUE = "TILO_RUNS_QUEUE"  # projects/<p>/locations/<region>/queues/runs
ENV_TASKS_CALLER = "TILO_TASKS_CALLER"  # the Cloud Tasks OIDC identity (tilo-tasks-invoker@...); exact email
DISPATCH_DEADLINE_S = 1800  # the task's dispatchDeadline, as "1800s"
IN_REQUEST_DEADLINE_S = 25 * 60  # the run wait; 20 min <= it <= DISPATCH_DEADLINE_S - 60. The tests monkeypatch it
```

`TILO_RUNS_QUEUE` or `TILO_TASKS_CALLER` unset or empty: the Scheduler caller gets 503 AFTER its token and BEFORE anything
is claimed (fail closed; nothing runs inline any more); a Tasks-shaped request gets 503 or a refusal (an unset
`TILO_TASKS_CALLER` cannot identify it), 503 for an unset queue; no side effect either way. The slot is claimable the
moment it is configured.

## 3. FAN-OUT (the Scheduler caller)

```python
@dataclass(frozen=True)
class AlreadyExists: ...        # what a TasksClient returns for Cloud Tasks' ALREADY_EXISTS

class TasksClient(Protocol):
    def enqueue(self, task: Mapping[str, Any]) -> None | AlreadyExists: ...   # raises on any other failure

def get_tasks_client_factory(...) -> Callable[[], TasksClient]   # a dependency provider like get_schedule_store_factory

class TaskEnqueuer:                                             # the tick's RunStarter in fan-out
    def __init__(self, *, client: TasksClient, queue: str, audience: str, caller: str) -> None
    def start(self, run: RunStart) -> str                       # hands over ONE task; returns a non-empty str (a world id)
                                                                # it creates NO world; raises when the client raises
```

- The factory is called only after the token passed, once per request, never cached (the tests override the provider with a
  counting factory). A factory that raises: a 5xx with a fixed body. The default builds the real REST client (Cloud Tasks
  REST API through google-auth, `requests`-style transport injected for tests); no `google-cloud-tasks` dependency.
- For each due slot the Ticker claims it, `TaskEnqueuer.start(RunStart)` makes the task, the slot is `complete`d as
  before. The tick never calls `ScheduleStarter.start` and never `runs.start_run`: no world, no event, no run from it. It
  needs no run seams (an unwired seams factory does not stop the fan-out).
- The task is the Cloud Tasks REST resource; the tests allow only these keys:

```python
{
    "name": f"{TILO_RUNS_QUEUE}/tasks/{task_name(slot_key(schedule_id, slot))}",  # tilo_harness.schedule.task_name
    "dispatchDeadline": "1800s",
    "httpRequest": {
        "httpMethod": "POST",
        "url": TILO_SCHEDULE_TICK_AUDIENCE + "/internal/schedules/tick",
        "headers": {"Content-Type": "application/json"},  # never an Authorization header
        "body": base64(
            json.dumps(
                {"schedule_id": ..., "slot": slot_key, "due": due_iso, "skipped": n, "prior_world_id": id_or_null}
            )
        ),  # ONLY these five keys (BQ-AGT14-5 d)
        "oidcToken": {"serviceAccountEmail": TILO_TASKS_CALLER, "audience": TILO_SCHEDULE_TICK_AUDIENCE},
    },
}  # no retry config (the queue owns it), no brief, owner, approach, cap, title, token or secret anywhere
```

  `due` is the slot instant, UTC ISO as `slot_key` writes it: `slot == f"{schedule_id}:{due}"`. With missed slots
  collapsed the task is for the LATEST missed slot (as the Ticker already computes it).
- `ALREADY_EXISTS` (the client returns `AlreadyExists()`) is success: the slot completes, nothing is counted.
- Any other enqueue failure: the existing failure path (claim released, ONE counted failure under a fixed code
  `^[a-z][a-z0-9_]{0,63}$`, backoff, `next_due` unmoved, the same slot handed over after the backoff); one schedule's
  failure never stops the others. 200 `{"fired": <the ones that were handed over>}`; no exception text in the response.
- Replay-only: 200 `{"fired": 0}`, nothing enqueued, nothing moved. The rate limit stays `MAX_FIRES_PER_TICK` (20) per
  tick; one task per slot (the task name dedupes).

## 4. EXECUTE ONE RUN (the Tasks caller)

Body model (JSON only: another content type is 415 or 422; closed, so an unknown key is 422; no input is echoed):

```python
class TaskRunIn(BaseModel):  # extra="forbid"
    schedule_id: str  # ^sched_[0-9A-Za-z_]{1,64}$ fullmatch, else 422
    slot: str  # the slot key
    due: str  # ISO-8601, UTC-aware
    skipped: int  # 0..100000, default 0 (R1, untrusted, only drives the collapsed-slots alert)
    prior_world_id: str | None  # null or a world id (R1, untrusted, offered only if it is the owner's world)
```

- Wrong shape, wrong types, missing or unknown keys (`owner_user_id`, `brief`, `approach`, `budget_cap`, `cap`, `title`,
  `world_id`, ...), a malformed schedule id, a non-object body, invalid JSON: **422**.
  The owner, brief, approach and cap are NEVER read from the body; `skipped` and `prior_world_id` are data, never authority.
- A forged slot is refused without a run, by 422 or a 2xx `{"ran": 0, "skipped": "<fixed code>"}`: `slot` not exactly
  `slot_key(schedule_id, due)` (another schedule's slot, another instant, another spelling of the same instant, a naive
  instant), a `due` ahead of `get_clock()`, a `due` that is not an instant of the schedule's cadence.
- A valid body: the route re-reads the record by id and calls `ScheduleStarter.start` (so: owner from the record, snapshot
  from the record, budget only from the owner's own L3 `grant_budget` policy, ids deterministic from the slot key). Then it
  waits (section 5) with `IN_REQUEST_DEADLINE_S` and answers.
- Permanent refusals answer **200** (any 2xx is accepted by the tests) `{"ran": 0, "skipped": "<code>"}`, no world, no
  event, no run, the same answer on a repeat so Cloud Tasks does not retry; the codes are the starter's own:
  `schedule_missing` (gone or erased), `schedule_disabled` (disabled, or `disable_for_owner`), `owner_mismatch` (the slot's
  world belongs to someone else), `budget_not_granted`, `snapshot_missing`.
- A start that raises (anything from `runs.start_run` or the setup) and `run_seams_unwired` (the uncounted skip, a
  condition of the whole service): a **5xx** with a FIXED body (the same for any failure text, no text of it), nothing
  counted against the schedule. The ids are deterministic, so Cloud Tasks' retry meets the world the failed start made.
- A duplicate (or concurrent) delivery: one world, one run, one `world.requested`, `budget.granted`, `world.started`; 200.
- Replay-only blocks this mode too: nothing is created or started; the status is a refusal (`ran` 0) or 503 (the tests
  accept either; see the report); delivered again once the flag is clear, it runs.

## 5. The wait (`tilo_api.runs.Run`)

```python
def wait_until_parked_or_done(self, timeout_s: float, *, clock: Callable[[], float] = time.monotonic,
                              poll_s: float = 0.25) -> Literal["done", "parked", "timeout"]
```

- `"done"`: the run's thread has ended (completed, failed, paused, any way out); asking again returns at once.
- `"parked"`: the run is blocked on a person and nothing it can do goes on: its gate card waiting for an answer, or a
  question wait with the other units finished. It must NOT return `"parked"` while a unit is still working.
- `"timeout"`: `timeout_s` of `clock()` elapsed first. `poll_s` is how often the wait looks (a test passes a tiny one and
  a fake clock that jumps, so a 25 minute deadline costs no real time).
- The route answers `"state": <that value>`. The run thread keeps its normal behaviour after the request returns: a person
  still approves its gate over the cards route and T3 still needs a person. No behaviour change for interactive runs.

## 6. What changed in existing tests, deliberately

`SchedApi` (the rig) now sets `TILO_RUNS_QUEUE` and `TILO_TASKS_CALLER`, installs the fake Tasks client through
`get_tasks_client_factory` (when the name exists) and has `task_call` / `deliver_new_tasks`. In
`test_FR_AGT_14_scheduled_start.py` `fire()` ticks and delivers; the inline-start tests that cannot hold any more were
changed or retired (listed in the test-writer report and in the file's docstring). In `test_FR_AGT_14_tick_route.py` one
test delivers the enqueued task; in `test_FR_AGT_14_followups.py` the inline unwired-seams test moved to the delivery.
