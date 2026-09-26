---
name: harness-writer-gaps
description: P0-09 harness single-writer review; r1 lease/EV-14 gaps and r2 world_id path injection fixed; r3 PASS with head-doc count exposure flagged (PRD 10.1)
metadata:
  type: project
---

P0-09 (harness skeleton, session SH).

r1 FAIL (2026-09-25):
- Lease keyed on caller writer_id only; FirestoreStore used `transaction.set` on event docs; two processes of one run wrote seq [1,2,2].
- Validator dropped EV-14 stream half; append() accepted another world's world_id.

r2 FAIL (2026-09-25): r1 items fixed. New: org_id/world_id never validated; `world_id "w_victim/events/00000001"` let open()'s head `set()` overwrite another world's event doc.

r3 PASS (2026-09-25), flagged: ids.py + FirestoreStore now check org/world/run/scope patterns. Redaction probe clean again. Tests 199 passed (emulator included, ~140 s).
- Flagged residual: head (last_seq, per-district view_seq, lease token) is `transaction.set` on the world doc orgs/{org}/worlds/{world} (store.py _head/transact). Any client allowed to read the world doc sees hidden-district counts (PRD 10.1), and set() without merge would wipe any world metadata another service puts there. The brief itself put the lease on the world doc, so this is a design follow-up: rules must deny it to non-owners, or the head moves to a harness-only path.
- Minor: ids.py uses `re.match` with `$`, so "w_victim\n" is accepted (python-jsonschema has the same gap; ECMA/ajv would reject it). Use fullmatch or \Z.
- EV-04's policy.changed owner half and OB-01 L2 instruction checks are in neither the harness validator nor scripts/contracts_events.py (they belong to outbox policy records).

**Why:** builders fix the exact probe from the last round and miss adjacent bypasses (head doc set, unvalidated path ids).
**How to apply:** in later harness rounds (FR-AGT-10 checkpoints, FR-MEM ledger/archive), probe: same-writer-id double open; EV-14 with wrong cause; ids with "/" or a trailing "\n" into any Firestore path (org, world, scope, checkpoint id); which docs use `set`; where counters live and who can read them. When security rules are written, check the world doc is not readable by Viewers/Team Leads while the head sits there. Related: [[t3-invariant-gaps]].
