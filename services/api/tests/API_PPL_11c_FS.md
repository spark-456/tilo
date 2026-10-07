# PPL-11c-FS slice FS-1: Firestore stores for the people API (spec for the acceptance tests)

Issues #541 (items 1-3, 4b) and #549 (item 1, the stores half). Tests: `test_PPL_11c_FS_{a..e}_*.py`, helpers
`_ppl11c_fs_lib.py`. `contracts/` is unchanged: every record keeps its schema, so there is **no contract change**.
Production stays fail-closed; the live switch is the user's (ADR-0023, ADR-0003). No paid call, no credentials, no `LIVE`.

## 0. Pending markers
`_ppl11c_fs_lib.FS_PENDING` makes each requirement a strict xfail until its builder deletes the entry; `FS_EXEMPT` and
`FS_MEMORY_GREEN` are guards that pass today and stay. Emulator tests are `@pytest.mark.emulator` (not in `just check`; run
`uv run pytest services/api/tests -k PPL_11c_FS -m emulator`). The `Rig` (`_ppl11a_lib`) now forwards the person store's
`create_founder`/`founded` and overrides `get_founder_gate` to "yes" (the PPL-11c S3 tests assume any principal may found).

Emulator note: the Firestore emulator's cold start takes about 2.5 min; the first run on a cold cache needs the longer
timeout. `tilo_harness.emulator.running_emulator()` waits 240 s by default; `TILO_EMULATOR_READY_TIMEOUT_S` overrides it
(a value that is not a number above zero is ignored). Test: `services/harness/tests/test_PPL_11c_FS_emulator_ready_timeout.py`.

## 1. Layout (FS-01) and where the code lives
- The adapter is `tilo_api.people_firestore` (tilo-api): `tilo_people` is pure (its static test forbids `google`, `os`), so
  there is **no `PeopleStores.firestore` classmethod**; the factory is `firestore_people_stores(client) -> PeopleStores`.
  tilo-api needs a direct `google-cloud-firestore` dependency (today only through tilo-harness).
- Record: `orgs/{org}/people_{kind}/{id}` (kind in `INDEXES`; one collection per kind so erasure can collection-group by
  kind) holding exactly `{"version": n, "record": <record>}`. `version` is the compare-and-set counter, 1 on create, +1 per
  replace; it is never a record field. A delete removes the document (no tombstone copy).
- `orgs/{org}/people_directory/founder` = `{"uid": <founder id>}`; `orgs/{org}/people_directory/email_{hex}` =
  `{"person_id": id}` where `hex` = SHA-256 of the **lower-cased** address, UTF-8. The address is in the person record only.
- Nothing is written outside `orgs/{org}`. Ids reach a path only after the schema patterns; a malformed org or id reads as
  nothing (`get` None, `list` `()`, `delete` NotFound), never as a path (`/`, `..`, `.`, `__x__`).

## 2. The `RecordStore` contract on both stores (FS-02..FS-05)
Same behaviour as `MemoryStore` (`test_PPL_10d_stores.py`), one parametrised suite over `memory` and `firestore`:
get/create/replace/delete/list, `Stored(kind, record, version)`, deep copies, `PeopleInputError` for non-int versions, schema
failures and a foreign kind, `NotFound`, `VersionConflict`, `AlreadyExists` (a create is fail-if-exists), `list(org, field,
value)` by `INDEXES` only (anything else `PeopleInputError`), sorted by id, **every** record (no page), org isolation.
Replace, delete and create are atomic: racers on one version (8 in memory, 3 on the emulator) leave one winner, the rest
`VersionConflict` (or `NotFound`/`AlreadyExists`); contention is retried inside, never leaked as `Aborted`. Two adapter objects
over two clients race the same way (FS-04). Builder note, measured: on the emulator every read inside a transaction takes a lock, a
two-way race on one document costs about 15 s and eight racers stall for minutes, so do the single-document compare-and-set
and create with write preconditions (`exists=False`, `last_update_time`) rather than read-then-write transactions, and keep
transactions for the multi-document steps (founder + person + reservation); retry `Aborted` with jitter. Errors, reprs and logs name kind, id and versions, never record text, an address, or
a Firestore library exception (FS-05; an adapter error is a `tilo_people` error, its cause chain carries no text).

## 3. The person store's directory calls (FS-07..FS-11), `MemoryStore("person")` and Firestore alike
New errors in `tilo_people.errors`: `EmailTaken`, `OrgAlreadyFounded`, `LastPerson` (all `PeopleError`, no text).
- `create_founder(record)`: one transaction creates the founder document, the person and its address reservation.
  Refused `OrgAlreadyFounded` if the org has a founder document **or any person** (a seeded org is not foundable and is not
  "founded"); order of refusals: founder, then `AlreadyExists` (id), then `EmailTaken`; `PeopleInputError` for a record that
  is not a schema-valid `org_role: owner`; a refusal writes nothing. `founded(org) -> bool`, False for a malformed org.
- The founder document is never deleted: erasing the founder (or every person) keeps it, so `/first` can never re-found an org.
- `create`/`replace`/`delete` keep one reservation per person atomically with the record. A second person with the address
  (case-insensitive over the whole address) is `EmailTaken`; delete frees it; a replace that changes the address moves it
  (the old is free, the new is held) or, if the new one is taken, is `EmailTaken` and changes nothing; a case-only change is a
  no-op on the reservation; a refused create or replace (schema, id, version, not found) reserves nothing.
- **Last-person erase (decision, BQ-PPL11C-16):** `erase_person` raises `LastPerson`, before changing anything, when the user
  is the org's only person and `persons.founded(org)` is False (a bare protocol store counts as not founded). A founded org
  may be emptied person by person; the founder document is what remains. A person who is not the sole person erases as before.
  Reading of the brief: "refused unless a founder marker says otherwise" = refused unless the marker exists, because the marker
  is what blocks a re-found. Accepted gap: two concurrent erases of the last two people empty a founded org (still closed).
  Recovery of a dead org (no owner) is an operator action, deferred (FS-3).

## 4. Doors and wiring (FS-06, FS-13)
- `emulator_people_stores(project_id="demo-tilo")`: refuses (`RuntimeError`) without `FIRESTORE_EMULATOR_HOST` and for any
  id that does not `fullmatch` `demo-[0-9a-z-]+`, before a client is built (as `tilo_harness.store.FirestoreStore`, whose
  `$` also accepts a trailing newline: use `fullmatch`; the test sends `"demo-tilo\n"`).
- `open_people_stores(env=None, *, client_factory=None)`: the one live door (ADR-0023 decision 2): `TILO_PEOPLE_STORE=firestore`
  plus `TILO_FIRESTORE_PROJECT` matching `^[a-z][a-z0-9-]{4,28}[a-z0-9]$`; anything else raises `PeopleStoreNotConfigured`
  (names `TILO_PEOPLE_STORE`) with no client built. The schedules switch does not open it.
- Importing either module and `firestore_people_stores(client)` do no I/O.
- `deps.get_people_stores` (is the seam and carries `cache_clear`): unset or wrong config, locally or deployed, is 503
  `not_configured` and builds no client; explicit config builds **one** `PeopleStores` per process (single-flight: eight first
  requests build one client) from `firestore.Client(project=...)` called at call time; a failed build is 503 `not_configured`,
  not cached, message not echoed. The setting is read at the first successful build only. The write limiter and idempotency keys
  stay in memory on that object (FS-2 moves them).

## 5. Bootstrap uid (FS-12, issue #541 item 1)
`deps.get_founder_gate() -> Callable[[str], bool]` reads `TILO_PEOPLE_BOOTSTRAP_UID` on every call: true only for a value
equal to the uid, and the value must itself match `^u_[0-9A-Za-z_]{1,48}$` as written (no trimming, lists, wildcards).
`/v1/people/first` calls it **first** (before any store read and before the schema check): not the bootstrap uid, or none
configured (**the BQ default is refuse**, row BQ-PPL11C-15) is 403 `forbidden`, the same body as every other refusal of
`/first`. The uid then founds through `create_founder`. The bootstrap uid has no other power. Body parsing (closed 422) still
precedes it. `_DIRECTORY_LOCK` is no longer needed and must not be what makes the routes safe.

## 6. API over the stores (FS-14, FS-15)
`/v1/people` and `/v1/people/first` rely on the store's atomicity: with the process lock neutralised and a person store whose reads
return a stale snapshot, eight callers still leave one founder / one holder of an address (409 `email_taken`); the same on the
emulator; an emptied founded org answers `/first` 403; with explicit config the real wiring reaches the emulator and the
60-writes limit spans requests. FS-15 pins issue #541 item 4a (a member and a stranger get one 403 for a taken and a free address).

## 7. Deferred
FS-2: store-backed `Limits` and idempotency keys with TTL, eviction per principal (#549 items 1-3, 7), plate sources, Desk worlds,
meeting worlds in Firestore, a fixed 503 for a store outage. FS-3: Firestore rules and indexes (deny every client on `people_*`
and `people_directory`), IAM and the user's switch, FR-MEM-09 retention/erasure of the founder and reservation documents (an
unsalted address hash is personal data: consider a keyed hash), dead-org recovery, `time_zone` IANA check (#541 item 5).

## 8. Ambiguities settled (PRD defaults; also in the hand-back)
Document layout, the `version` envelope, hash input and collection names are the test-writer's choice (the brief said decide);
the last-person reading in section 3; the `get_founder_gate` seam name and the `TILO_PEOPLE_*` variable names (ADR-0023 names
the schedules ones only); `EmailTaken` is a new error, not a subtype of `AlreadyExists`.
