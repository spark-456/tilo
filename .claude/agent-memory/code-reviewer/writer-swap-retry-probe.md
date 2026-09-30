---
name: writer-swap-retry-probe
description: Timeout-retry keyed on writer identity (FR-HIL-07 dispatch) duplicates writes; content-keyed "stable id" dedupe drops same-ms parts; per-part deadline treats slow as hung
metadata:
  type: project
---

ST-3a-3 (PR #39, 2026-09-26) dispatch.py redesign had three defects found by probes, all with the suite green (92 passed):
- Retry-on-timeout gated on `attempt_writer is writer`: two concurrent calls with different writer instances ping-pong re-arming the head (older call re-arms its own stale writer) -> one revoke written 3 times. Spec says retry only with the most recently arrived call's writer.
- "Stable id" field assigned but unused; dedupe actually keyed on JSON content, so two revokes of one policy in the same ms (now() is ms resolution) give 2 history entries, 1 event.
- `_PART_DEADLINE_S=0.3` tuned to tests; same-writer timeout returns immediately, so a healthy 350 ms writer writes 0 parts per call (spec: wait up to the call's shared budget).

**Why:** tests only use one writer instance per call and distinct content per part, so these paths never run.
**How to apply:** for any queue/retry writer, probe (1) two concurrent calls with two slow writer instances on one store, (2) frozen clock + duplicate-content parts, (3) a healthy writer slower than the per-attempt deadline. Run probes via `PYTHONPATH=services/api/tests uv run pytest <scratch>/test_x.py -p conftest`. FastAPI override deps need `request: Request` annotation or they 422. See [[timeout-then-late-commit-probe]], [[outbox-exactly-once-probes]].
