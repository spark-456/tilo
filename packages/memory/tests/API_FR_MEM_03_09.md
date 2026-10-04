# FR-MEM-03, FR-MEM-09 and FR-MTR-06: public API pinned by the tests (overridable)

Acceptance tests (PRD 13.5, 14.5): FR-MEM-03 "Replayed Pub/Sub messages produce no duplicate rows"; FR-MEM-09 "Deleting a
user removes their data from every store within 30 days, verified by a script"; FR-MTR-06 "Saved credits equal origin
cost minus lookup in every `memory.hit`". Sources: PRD 13.1, 13.2, 13.5, 14.3, 14.4, 15.1, 16.5, 22.2 D-11,
`contracts/event.rules.md` EV-09, `contracts/metering.rules.md` MT-05, `contracts/events/data/memory.hit.schema.json`,
`infra/modules/events/main.tf` (the ledger table's required columns).

These are the tests' assumptions, and the builder may override them. If a name or shape below changes, update the tests
in the same PR and say so in the review. The tests import only what is listed here. New events: none; `memory.hit` is
already registered and fixtured. No contract change is needed.

Where it goes: a new workspace package `packages/memory` (`tilo_memory`, stdlib only at runtime; add it to
`[tool.uv.workspace].members` in the root `pyproject.toml`, with its own `CLAUDE.md` of at most 40 lines) and one module
in `packages/metering`. Tests: `uv run pytest packages/memory/tests -q` and `uv run pytest packages/metering/tests -q`.
Fakes live in `packages/memory/tests/_memory_lib.py` and implement the duck-typed protocols below.

## `tilo_memory.ledger` (FR-MEM-03)

```python
class InMemoryLedgerTable:            # stands for BigQuery tilo_ledger.events; the only table the tests need
    def rows(self) -> list[dict]      # what the table physically holds: one dict per row, top-level TiloEvent columns;
                                      # item/vis/authz/data/trace may be JSON strings or decoded objects

class EventLedger:
    def __init__(self, table)         # several EventLedger on one table must not insert twice (scale-out)
    def ingest(self, message) -> IngestResult
        # message: duck-typed Pub/Sub message with .data (bytes, a JSON TiloEvent) and .message_id (str)
        # IngestResult.status in {"inserted", "duplicate", "conflict", "rejected"}; .event_id: str | None
        # Key = event `id` (PRD 13.2), never the message id. First write wins; a second message with the same id and
        # other content never rewrites the row (status "duplicate" or "conflict", BQ-194).
        # "rejected" (no row, no exception, content never echoed in the result): not JSON, not an object, or missing
        # one of v, id, seq, ts, world_id, type, severity.
        # Atomic under threads: concurrent deliveries of one id insert once.
    def events(self, world_id: str | None = None) -> list[dict]   # deduplicated, decoded, ordered by (world_id, seq)
    def count(self) -> int
    # No public method that updates or deletes a row (names containing update, delete, remove, truncate, upsert,
    # overwrite, replace, clear, pop are not allowed on EventLedger).

class LedgerRetentionStore:           # the one sanctioned path that removes ledger rows (BQ-195)
    def __init__(self, table, *, world_owner)   # world_owner(world_id) -> user id (u_...) or None
    def records(self)                 # entity "event_ledger", record_id = event id, created_at = event `ts` (aware UTC),
                                      # user_id = world_owner(world_id)
    def delete(self, record_id)       # idempotent
```

A real `BigQueryLedgerTable` is the builder's to add behind the same table protocol, tested against a mock client
only. Note: today's `infra/modules/events` subscription writes straight into the table, so duplicates would land there;
the builder decides (and records) whether dedup is an ingester in front of the table or a deduplicating view, but the
tests pin "no duplicate rows" on the physical table of the Python ingester.

## `tilo_memory.retention` (FR-MEM-09, retention)

```python
RETENTION_DAYS: Mapping[str, int | None]   # PRD 15.1 defaults; None = life of account / until unbound / disconnected
retention_days(entity: str) -> int | None  # ValueError for an unknown entity (never "keep forever" by accident)
purge_expired(registry: Mapping[str, RetentionStore], *, now: datetime) -> dict[str, int]  # store name -> removed
```

Entities and days: `org user channel_binding connection policy` None; `policy_history` 365; `task world run card
artifact` 90; `event_live` 30; `event_ledger` 365; `decision` 365; `archive_record` 30; `cache_entry` 7 to 30.
A record is expired only when strictly older than its window (age > days, BQ-196). Every store in the registry appears
in the result, with 0 when nothing was removed. The registry need not be complete for a purge.

```python
class RetentionStore(Protocol):            # duck-typed; the tests' FakeStore
    def records(self) -> Iterable[Record]  # a fresh read of everything the store holds
    def delete(self, record_id: str) -> None   # idempotent: deleting a missing id is not an error
# Record: .entity (str), .record_id (str, unique in the store), .created_at (aware datetime), .user_id (str | None)
```

## `tilo_memory.erasure` (FR-MEM-09, deletion and the verifying script)

```python
ERASURE_DEADLINE_DAYS = 30
REQUIRED_STORES: frozenset[str]   # names covering PRD 13.1/13.2: starting "firestore", "bigquery", "memory_bank", and at
                                  # least three starting "gcs" or "cloud_storage" (archive, artifacts, cache blobs)
class IncompleteRegistry(ValueError)   # a registry that lacks a required store; names the missing store(s)

request_erasure(user_id: str, *, requested_at: datetime) -> ErasureRequest   # .user_id .requested_at .deadline (+30 d)
    # ValueError: user_id not a str, blank, or not shaped like u_<alnum or _> (so "", " ", "*", "%", "u_*" fail);
    # requested_at naive.
erase_user(registry, request, *, now) -> ErasureReport
    # Registry must contain every REQUIRED_STORES name (extra stores are erased too), else IncompleteRegistry before
    # any delete. request.user_id None or blank -> ValueError before any delete (records with user_id None are
    # nobody's and are never deleted by a user erasure). Deletes every record whose user_id equals the request's, in
    # every store; one store raising does not stop the others. Completion is judged by re-reading each store.
    # ErasureReport: .complete (bool), .removed {store: int}, .remaining {store: int}, .failures {store: exception type
    # name or message without record content}, .late (bool: now > request.deadline; lateness never skips the work).
    # Idempotent; a re-run after a failure finishes the job. Reports hold names and counts only.
verify_erasure(registry, user_id) -> Verification   # .ok, .remaining {store: int}, .problems [str naming the store]
    # Read-only (never calls delete). Same IncompleteRegistry and user id rules as above.
main(argv: list[str], *, registry=None, stdout=None) -> int
    # `verify <user_id>`: prints JSON {"ok": bool, "stores": {name: remaining}, "problems": [..]}; exit 0 iff ok, 1 if
    # data remains, another non-zero code for bad input or an incomplete registry. Never prints record content.
    # `python -m tilo_memory.erasure --help` exits 0 and mentions `verify`, with no stores configured.
```

## `tilo_metering.savings` (FR-MTR-06)

```python
class InconsistentMemoryHit(ValueError)
hit_saving(event: Mapping) -> float
    # origin_cost - lookup_cost of one memory.hit. ValueError (InconsistentMemoryHit when data.saved disagrees, naming
    # the event id) if a cost is missing, not a finite non-negative int/float (bool, str, None, NaN, inf, negative are
    # refused), or the result is negative.
credits_saved(events: Iterable[Mapping], *, run_id: str | None = None) -> float
    # Sum of hit_saving over the memory.hit events (all other types ignored, even if their data has a `saved`), each
    # event id counted once, optionally for one run. Never trusts data.saved; a hit that breaks EV-09 raises.
```
