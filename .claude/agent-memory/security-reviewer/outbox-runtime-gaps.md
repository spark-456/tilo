---
name: outbox-runtime-gaps
description: ST-2 / FR-AGT-11 outbox (services/connectors tilo_connectors) review findings and probes; check on every outbox, connector adapter, Firestore store or SEC-03 lint ticket
metadata:
  type: project
---

ST-2 round 1 (branch feat/FR-AGT-11-outbox, 2026-09-25) FAIL. All 49 pinned tests passed; every hole below is outside what the tests pin. Probes proved each one.
- Biggest: enqueue dedupes only on world_id+idempotency_key, then store.put keys by `id` and overwrites. The same id with a new key and the original real evidence passes check_entry (it never reads the key or the stored state). Result: a cancelled (Undo) entry goes back to scheduled and is sent; a sent entry is sent a second time with a second data.transfer. One approval or L2 instruction gives two sends, and PI-14 breaks.
- enqueue enforces state only for queued/scheduled. An L2 entry with state "failed" passes and dispatch_due sends it at once, before scheduled_at, with no cancel (PI-12). A "sent" entry arrives and emits nothing (open question #23).
- Grant is a public frozen dataclass. The adapter checks only isinstance (a subclass also passes) and never binds it to the call's idempotency_key or outbox_id.
- The SEC-03 AST scan flags only calls written as `send_reply(...)` or `x.send_reply(...)`. It misses getattr, a local alias, functools.partial and operator.methodcaller. It covers only services/ and packages/ and skips any file named test_*.py.
- dispatch_due trusts the store. store.put is public, so an entry put there without authorisation (a stranger as recipient) is sent. `evidence` is supplied by the caller, not read from the event log.
- The store has no compare-and-set. With two Outbox instances on one store, B.cancel returned "cancelled" while A sent the entry anyway. A crash after the "sending" put leaves the entry stuck. If emit raises after "sent", the data.transfer is lost.

**Why:** Root rule: every side effect goes through the outbox, exactly once. The tests pin the happy paths and the named cases, but not the adjacent identifier (id against key) or states other than queued/scheduled. This is the same pattern as [[t3-invariant-gaps]].

**How to apply:** On a re-review or a Firestore-store ticket, rerun the probes: same id with a new key after cancel and after sent; enqueue with state failed/sent/sending; Grant("a","b") and a Grant subclass sent straight to the adapter; getattr/alias/partial in a temp file given to scan_for_side_effect_calls; two Outbox instances sharing one store, cancelling from inside the adapter call. Run them with `uv run --package tilo-connectors python <scratch script> <worktree>`.
