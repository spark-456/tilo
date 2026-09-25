---
name: api-event-emit-patterns
description: Recurring defects when services (tilo-api etc.) build event.schema.json records themselves - derived ids, seq, run_id
metadata:
  type: project
---

ST-3a review (2026-09-25, branch feat/FR-HIL-07-kill-switch-redaction, stacked on P4-01): tilo_api/events.py filled the required, non-null `run_id` with `f"r_{world_id}"`. That is a run that never existed, and it is schema-invalid for legal world ids longer than 46 characters (the r_ pattern allows only 48 characters after the prefix). The tests validated events only with short fixture ids, so they passed.

**Why:** Contract fields that are required but not meaningful for the emitter get filled by string-deriving them from another id. That passes fixtures and breaks on edge-length ids, and it also misattributes the event in the Trace lens.

**How to apply:** For any service-built event, check how each required id is sourced (run_id, id/ulid, seq). Probe with a maximum-length world_id through the tests' validate_event helper (PYTHONPATH=services/api/tests, import _api_lib). Also note that seq = max+1 with no lock in sync FastAPI routes can race. The contract says the harness is the one writer per world.
