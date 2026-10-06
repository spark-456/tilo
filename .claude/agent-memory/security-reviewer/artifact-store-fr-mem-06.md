---
name: artifact-store-fr-mem-06
description: PR #382 ADR-0018 T2 artifact store (tilo_memory.artifacts, FR-MEM-06) security review r1 result, open gaps, probe pattern; check on T3/T4/T6/T8 artifact tickets and any re-check of #382
metadata:
  type: project
---

PR #382 r1 (64bd1c1, 2026-10-05, base phase0-stack) FAIL, 2 blockers:
1. `_append` writes the blob before the record; retention/erasure enumerate records only, so a kill between the two writes (or record create failing while the cleanup blob delete also fails) leaves user bytes no purge or erasure ever finds (AR-08), and the orphan makes every later put(parent)/restore of that artifact fail forever (8 retries, AR-02). Asked for: no blob without a listed record (e.g. record first), interrupted write never blocks the next version.
2. `LocalDirBlobBackend.from_env` default `.tilo/artifacts/` is not in `.gitignore` (ADR-0018 s2 says gitignored).

r2 (6c59628) FAIL, 2 blockers in the repair path: (a) on a blob-create failure `_append` deletes the record even if the blob committed (GCS commit+timeout, local partial write) -> orphan blob again; (b) the idempotency repair purges another writer's in-flight record and the FileExistsError path deletes+rewrites a blob, so with two store instances over shared backends a put returns a version whose record is gone or whose bytes are another writer's (HR-1, AR-02). Single-instance paths were clean: 3 suite runs + 12 stress loops + 10-thread mixed stress, no hang, no orphan. Probes: probe382c.py (CommitThenRaise, LocalPartial, GatedBlobs two-instance race), stress382.py.
r3 (bc7ff3c) PASS, still flagged: GRACE (5 min, injected clock) + ArtifactBusy + exact-key `_blob_state`; failed blob create deletes the blob before the record. Residual only beyond GRACE (writer stalled >5 min or cross-instance clock skew): takeover makes the stalled writer return a recordless version / orphan blob, and `_settle` purge can delete a blob that just landed (probe382e/f sections 3, 4b). T8 must fence with backend preconditions and re-read the record after the blob create. One FR_MEM_06 run of 11 stalled after all tests (no summary, killed at 600 s); not reproduced with a hangdump plugin (scratchpad plug/hangdump.py), machine under load (tests/repo took 517 s).
Recurring pattern: "repair" logic that decides a write is dead from absence of the second half cannot tell it from a write in flight; ask for create-only completion with the same hash or a clock grace window.

What held (do not re-probe unless code changed): fullmatch on every id/ref/key/cause/archive_ref (ASCII ranges, no `\w`); cross-scope outcomes identical to never-existed for all read/write calls; redactor error stores nothing; screener non-dict/non-bool verdict -> unscreened; restore copies 8 fields exactly and takes no sources; JSON Schema validation via referencing registry (fail closed if unresolvable); single-instance races serialised by RLock.

Open follow-ups to carry: screened_at <= created_at only by clock order (unchecked); verdict not tied to bytes; caps trust a bytes subclass's `__len__` (executor must pass exact bytes); `new_id`/`record_validator` seams unchecked; add_manifest record check outside lock (orphan revision on concurrent erasure); `_plan` scans the whole world per put and idempotency is not atomic across instances (T8 needs a key doc); world cap reveals other owners' sizes; `from None` keeps redactor exception on `__context__`; LocalDir Windows aliasing (`b.`, `b `, `NUL`); alert flood on repeated corrupt reads.

**Why:** the store is the single source for deliverables, Verifier input and egress; T3-T8 build on it and T8 copies its write ordering to Firestore/GCS.
**How to apply:** on the #382 re-check verify write ordering with a probe that plants an orphan blob and fails meta create; on T8 check key-doc idempotency and every-generation delete; on T3 check exact bytes into put. Probe scripts: scratchpad probe382.py / probe382b.py (make_rig from packages/memory/tests/_artifact_testlib.py). Related: [[artifact-contract-adr0018-t1]], [[erasure-retention-fr-mem-09]].
