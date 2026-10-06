# FR-AGT-14d interface (rollout follow-ups of the scheduled-runs reviews)

Names the tests pin. Builds on `API_FR_AGT_14b.md`. No contract changes. Tests: `services/api/tests/test_FR_AGT_14_followups.py`,
`services/harness/tests/test_FR_AGT_14_followup_{skip_count,reenable,owner_erasure}.py`, the two changed 14b tests (below) and
`tests/repo/test_FR_AGT_14b_schedule_store_guard.py` (BQ-AGT14-4 is now the last table row).

## 1. Lazy seams after auth (`tilo_api.schedules`)

Two new dependency providers, overridable through `app.dependency_overrides` like the other seams of the module:

```python
def get_seams_factory(...) -> Callable[[], runs.Seams | None]          # the factory builds runs.run_seams the way it is wired
def get_schedule_store_factory(...) -> Callable[[], ScheduleRepository] # the factory builds the store (503 not_configured on refusal)
```

- `tick` depends on these two providers (cheap: they return a callable, build nothing) and CALLS each factory only after the
  token has passed `tick_caller_ok`, exactly once per request, never cached across requests. The tests inject counters by
  overriding the providers: `dependency_overrides[get_seams_factory] = lambda: counting_seams_factory`, same for the store.
- The 503 for an unset `TILO_SCHEDULE_TICK_AUDIENCE` or `TILO_SCHEDULE_TICK_CALLER` stays first (before the token, before any
  factory call). Every other status code and body is unchanged. A factory that raises after auth: a 5xx with a fixed body.
- The DEFAULT factories must keep honouring the existing overrides: `get_schedule_store` (the rig overrides it, and the
  "no schedule store is 503" test deletes that override) and the run-seam overrides the CL-INT rigs install (`deps.get_*`,
  resolved the way `runs.run_seams` does). `SchedApi` still overrides only those; it does not override the new providers.
- Not pinned: where `deps.get_store`, `get_clock`, flags and the verifier are resolved (they stay cheap).

## 2. Disable and erase by owner (`tilo_harness.schedule_store`)

```python
class InMemoryScheduleStore / FirestoreScheduleStore:
    def disable_for_owner(self, owner_user_id: str) -> int
        # every schedule of that one owner: enabled=False, last_error="owner_disabled"; returns how many changed;
        # a second call returns 0; another owner's records untouched; a held claim does not stop it; an invalid owner id
        # (not u_<[0-9A-Za-z_]{1,48}>: blank, "*", "u_", path-like, trailing newline, non-str) changes nothing
        # (a ValueError or 0 are both accepted: "refused like the other methods")

class ScheduleRetention:                       # structural tilo_memory.retention.RetentionStore
    def __init__(self, store: ScheduleRepository) -> None      # positional
    def records(self) -> Iterable[Record]      # a FRESH read of EVERY document of the store, enabled or not
        # record_id == schedule_id; user_id == the document's owner_user_id (None if it has none);
        # entity: a non-empty str; created_at: an aware datetime
    def delete(self, record_id: str) -> None   # deletes the document; idempotent; an id that is no schedule id is a no-op
```

- Placement: `ScheduleRetention` lives in `tilo_harness.schedule_store`. `tilo-harness` already depends on `tilo-memory`
  (`services/harness/pyproject.toml`), so no new package dependency; the adapter may import `tilo_memory.retention` types or
  only match the Protocol structurally.
- `records()` must also yield documents that cannot be decoded into a `Schedule` (quarantined or malformed), by their raw
  `owner_user_id`, so an erasure removes them; a document with no owner is yielded with `user_id=None` and is never deleted by
  an erasure. How the stores enumerate every document is the builder's choice (the tests only go through `ScheduleRetention`).
- Tests: erasing owner A through `tilo_memory.erasure.erase_user` over a registry whose `firestore` entry is the adapter
  removes only A's schedules; `verify_erasure` then reports 0 remaining; a failing delete is reported by exception type name.

## 3. `StartSkipped(count=False)` (`tilo_harness.schedule`)

```python
class StartSkipped(Exception):
    def __init__(self, code: str, *, advance: bool = False, count: bool = True) -> None   # .code .advance .count
```

- `count=False` (wins over `advance`): the Ticker releases the claim and records NO failure and NO backoff (`failures`,
  `last_error`, `backoff_until`, `next_due` unchanged, schedule stays enabled; no `record_failure` call), so the same slot is
  claimable on the very next tick. It logs the fixed code ONCE per tick (at any level of the `tilo_harness.schedule` logger or
  its parents, the message holds the code and no schedule id), however many schedules were skipped. `count=True` is as before.
- `ScheduleStarter.start` with `seams is None` raises `StartSkipped("run_seams_unwired", count=False)`.
- Changed deliberately (they pinned `failures == 1` and a backoff): `test_FR_AGT_14_with_the_run_seams_unwired_the_firing_is_skipped_without_a_failure_and_retried_next_tick`
  in `services/api/tests/test_FR_AGT_14_scheduled_start.py` (renamed) and
  `test_FR_AGT_14_a_skipped_start_that_does_not_advance_keeps_the_slot_for_a_retry` in
  `services/harness/tests/test_FR_AGT_14_ticker_hardening.py` (now uses a counted code, `snapshot_missing`, so that counted
  behaviour stays pinned) plus the new `..._does_not_count_...` test next to it asserting `failures == 0`, no backoff.
- Test helper change: `SchedApi.starter(seams=None)` no longer needs wired seams to be built.

## 4. Re-enable moves `next_due` (shared store transition, both stores)

`update(schedule_id, enabled=True, ...)` and so `PATCH /schedules/{id} {"enabled": true}`: if the resulting `next_due` is at or
before the STORE's now, it becomes `next_slot(cadence, now)` (strictly after now); a `next_due` still in the future is left;
failures, backoff and error are cleared as before. `enabled=False`, a title-only update and a cadence change (which already sets
its own `next_due`) do not use this rule. Memory store: its injected clock; Firestore: the transaction's read time.

## 5. The default Google verifier: bounded, cached certificate fetch (`tilo_api.schedules`)

Tests: `services/api/tests/test_FR_AGT_14_followup_verifier.py` (real RS256 tokens signed with a throwaway key made at run
time, a counting fake transport and a fake clock; nothing leaves the process).

```python
CERT_TTL_S: float          # module constant, 300 <= CERT_TTL_S <= 3600
CERT_FETCH_TIMEOUT_S: float  # module constant, 0 < CERT_FETCH_TIMEOUT_S <= 5

class GoogleOidcVerifier:
    def __init__(self, *, transport: Callable[..., Any] | None = None, clock: Callable[[], float] = time.monotonic) -> None
    def verify(self, token: str, audience: str) -> Mapping[str, Any]      # unchanged contract
def get_oidc_verifier() -> OidcVerifier    # returns ONE shared GoogleOidcVerifier (same object every call)
```

- `transport` has the shape of `google.auth.transport.Request`: `(url, method="GET", body=None, headers=None, timeout=...,
  **kwargs) -> response` with `response.status` (int) and `response.data` (bytes of the Google v1 cert JSON
  `{kid: x509 PEM}`). The default is google-auth's `requests` transport. The verifier must call it (through
  `id_token.verify_oauth2_token` or its own fetch) so that the call carries `timeout=` with a value `<= CERT_FETCH_TIMEOUT_S`
  (google-auth's own call passes none, so wrap or pre-fetch). The test fake defaults `timeout` to 120, google-auth's default,
  so a missing timeout is visible.
- `clock` is `Callable[[], float]` in seconds and is used ONLY to age the certificate cache.
- Cache: a successful fetch is reused for any later verification until `CERT_TTL_S` seconds after that fetch (aged from the
  fetch, not from the last use); after it, the next verification fetches once. A failed fetch (an HTTP error status or the
  transport raising) is never stored as a success, caches nothing, and the next call may fetch again and succeed. The
  token pre-checks (shape, RS256 `kid`, Google issuer, our audience) still run BEFORE any fetch: a token that is plainly not
  ours causes no fetch. A forged signature raises and leaves the cache usable.
- Not pinned (builder's choice, say which in the report): what an unknown `kid` does inside the TTL (refetch or refuse; a
  refetch must not let an unauthenticated caller force one fetch per request), whether stale certificates may be served when
  a refresh fails, and where the shared instance lives (module global or `functools.cache`).

## 6. The route logs one fixed line when the verifier raises (`tilo_api.schedules.tick`)

When `verifier.verify` raises ANY exception the route still answers 401 `{"detail": "Unauthorized"}` with
`WWW-Authenticate: Bearer` and logs exactly ONE record on the `tilo_api.schedules` logger holding `type(exc).__name__` and
nothing else of the failure: not the token, not the exception text, no `exc_info` (a traceback carries the text). A call
with no verifier error logs nothing at WARNING or above from that logger. Logged level is the builder's choice.
