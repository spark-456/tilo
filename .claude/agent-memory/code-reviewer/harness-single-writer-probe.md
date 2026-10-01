---
name: harness-single-writer-probe
description: How to probe the harness single-writer lease (P0-09): same writer_id re-entry and missing last_seq CAS in the commit transaction
metadata:
  type: project
---

P0-09 review round 1 (2026-09-25): the lease check compared only writer_id, the skeleton derived writer_id from run_id (`skeleton_{run_id}`), and the commit transaction never compared head.last_seq with event.seq - 1 and used `transaction.set` (overwrite). Two runs with the same run id both held the "lease" and wrote duplicate seqs [1,2,3,2,3,4,4,...].

**Why:** D-11 / EV-10 single writer per world is the core invariant; writer-id identity plus in-memory seq is not enough.

Round 2 fixed it: lease keyed on a per-instance token, commit CASes head.last_seq and each view vseq, Firestore uses transaction.create. Remaining: ~1024 src lines, over the 400 cap. The ticket brief's scope made that unavoidable, so it was reported but did not fail the review.

**How to apply:** For any writer/lease code, run two writers concurrently with the same ids through MemoryStore (threads, small step_delay) and read the stream back. Done looks like: unique writer id per process, and the commit transaction checks head.last_seq == seq-1 (or uses create, not set). Also check expiry is re-checked or the lease is renewed on long runs.

FR-HIL-07 (2026-09-26, PR #53): `append` idempotent resend short-circuits on local `WorldState.seen` before `_write`, so a writer with an expired or taken-over lease still returns success for its own earlier events (truthful, writes nothing; judged non-blocking). A transact that raised after committing leaves local state behind: the resend gets WriterBusy ("head has moved") until reopen. Probe both cases for any later change to this path.
