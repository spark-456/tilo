---
name: outbox-attack-patterns
description: Attacks that broke the ST-2 outbox (tilo_connectors); reuse on any outbox/connector/idempotency change
metadata:
  type: project
---

ST-2 outbox (branch feat/FR-AGT-11-outbox, 2026-09-25) failed on:
- Idempotency scope mismatch: Outbox dedupes on (world_id, key) but FakeGmail dedupes on key alone, so a second world reusing a key is marked "sent" and emits data.transfer with no email (honesty violation). Always test same key across two worlds.
- Grant was a public frozen dataclass, never checked against the send's key: `Grant("x","y")` bypasses SEC-03.
- BaseException (KeyboardInterrupt) or store.put failure after the adapter call leaves the entry "sending" forever (no retry, no event).
- emit() raising after "sent" loses the data.transfer permanently.
- enqueue of 5,000 entries took ~19 s (schema validation + deepcopy per call).

**Why:** tests only used one world and only tested passing grant=None.
**How to apply:** for any outbox/connector ticket, run these first; scripts drive `conftest.gate_case` with `evidence_from_case`.
