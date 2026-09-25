---
name: outbox-review-patterns
description: Error-path defects to probe in tilo_connectors outbox reviews (ST-2 / FR-AGT-11) - stuck "sending", batch abort, forgeable Grant
metadata:
  type: project
---

ST-2 review (2026-09-25, branch feat/FR-AGT-11-outbox): Outbox._dispatch_one set state "sending" and put it before looking up the adapter outside the try, so an entry whose connector has no adapter (schema allows any connector_id pattern) raised KeyError out of dispatch_due, left the entry stuck in "sending" forever (not in _DUE_STATES), and skipped the rest of the batch. Tests only use gmail, so nothing caught it.

**Why:** Pinned tests cover the happy path and retry storms; error paths between "sending" and "sent/failed" are where exactly-once or liveness breaks.

**How to apply:** In outbox/dispatch reviews, probe with an inline `uv run python -c` against InMemoryOutboxStore: unknown connector, adapter raising, and process crash leaving "sending". Also check the Grant runtime check matches the send (idempotency_key) since API.md says "for this exact send"; FakeGmail only checked isinstance.
