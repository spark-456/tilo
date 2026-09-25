---
name: idempotency-resubmit-probe
description: In-memory stores keyed by id (cards, outbox) overwrite on duplicate submit, reopening resolved authorisations; probe it with a tiny uv run python script
metadata:
  type: project
---

ST-3b (FR-HIL-01/02, 2026-09-25): `CardStore.submit` used `dict[id] = new record` with no existing-id check, so a redelivered gate card reopened an already approved gate and a second `approval.resolved` went out for the same outbox_id. The pinned API doc and tests did not cover duplicate ids, so the tests passed anyway.

**Why:** harness delivery is at-least-once (Pub/Sub). A duplicate that reopens a gate breaks the rule that each authorisation is used once.

**How to apply:** when a store keys records by a caller-supplied id, submit the same payload again after resolving it and check the resolved status holds. A 10-line `uv run python -c` probe against valid fixtures is enough. Related: [[test-vs-api-doc-conflicts]].
