# PPL-11c-FS slice FS-1c: must-fix follow-ups of the FS-1 security review (addendum to `API_PPL_11c_FS.md`)

Issue #577 items 2-5 (item 1, the keyed hash of reservation ids and the founder marker `{}`, is a later ticket: not covered).
Tests: `test_PPL_11c_FS_{f,g,h,i}_*.py`; helper `_ppl11c_fs_fake.py` (an in-memory Firestore client in the optimistic mode, no read
locks). No contract change. `FS_PENDING` entries FS-16..FS-19 are strict xfails until the builder deletes them; `..._guard_...` tests pass today and stay.

## 1. FS-16 reservation writes (item 2)
`FirestorePersonStore` writes a reservation with `txn.create` (the read found none), never `set` or `update`; a reservation is deleted
only if its `person_id` is the person (`replace` moving an address, `delete`). Rival after our read, new address: `EmailTaken`, the
rival's reservation intact, nothing written (also for `create_founder`; a rival founder stays `OrgAlreadyFounded`). A reservation held by
someone else on `delete` or a move: a `PeopleError` that is none of the specific refusals (base class or a new subclass; no address, no
text), the whole transaction fails, nothing written. An absent reservation is no error. `MemoryStore` cannot reach this state: no test.

## 2. FS-17 last-person erase (item 3)
`erase_person`'s sole-person check is atomic with the person delete (`MemoryStore`: under its lock; Firestore: inside the delete
transaction), so a stale `list` cannot beat it. Racing erases of an unfounded org's N people (2 and 8 in memory, 3 on the emulator,
with a store whose `get`/`list` return a snapshot and then sleep) give N-1 successes, exactly one `LastPerson` and one person left.
A founded org may still be emptied by racing erases (BQ-PPL11C-16). Sequential behaviour is unchanged. A loser may already have erased
its work items before the refusal (erase is idempotent): not tested.

## 3. FS-18 build backoff (item 5)
`deps.PEOPLE_STORES_BACKOFF_S` (1 to 60 s, fixed) and `deps.people_stores_clock()` (monotonic seconds, replaceable by a test, read at call
time). After a failed build: inside the window every request is the 503 `not_configured` (the failure's own body, never the error text)
with no call to `google.cloud.firestore.Client` and no wait on the lock; eight first requests at a failing factory call it once; after
the window one request retries (eight at once: one call); a second failure opens a new window; a success builds once and is kept; `cache_clear`
clears the window. A configuration refusal (no switch) is unspecified. The existing `FS_13_a_failed_build..._not_cached` test now advances
the clock past the window before "the next request tries again" (its only change).

## 4. FS-19 `/first` session (item 4)
`Principal.full_session` and `Principal.channel` exist today (BQ-XWORLD-10, `deps.py`), so the tests are written. `/v1/people/first`
also requires `full_session` and `channel in {"web", "mobile_web"}` (an allow-list: email, a non-full session, `whatsapp`, `""` are
refused), checked in the route and independent of the gate predicate (its signature stays pinned by FS-12): 403 `forbidden`, the same body
as every refusal, before any store is read, after body validation. Nothing is consumed by a refusal. The `Rig` now signs in a full web
session (`rig.channel`, `rig.full_session`), and the three `Principal(...)` factories of the `/first` race tests set `full_session=True`.

## 5. Decisions
Rows BQ-PPL11C-18 and BQ-PPL11C-19 (`docs/open-questions.md`). Not covered: items 6-8 of #577 (total-time cap of `_transact`, address folding,
review leftovers), the keyed hash and erasure index (item 1).
