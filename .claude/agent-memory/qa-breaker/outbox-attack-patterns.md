---
name: outbox-attack-patterns
description: tilo_connectors outbox (ST-2) - in-memory pending state, per-instance adapter maps and emit failures are where "exactly once" breaks
metadata:
  type: project
---
ST-2 round 2 (2026-09-25) FAILED again. Fixes addressed round-1 repros; new breaks:

- Pending data.transfer kept in Outbox instance memory (`_pending_transfers`): emit raises -> entry is "sent"; restart (new Outbox on same store) never emits it. Honesty-rule break.
- emit raising inside `_dispatch_one` propagates out of dispatch_due, stopping the batch (API says never).
- A second Outbox on the same store whose connector map lacks "gmail" marks another instance's entries permanently "failed" ("missing adapter" is per instance).
- "sending" is in the claimable states, so concurrent dispatchers both call the adapter; two adapter instances (two processes) = two real sends.
- undo_window_s has no schema max: huge value or year-9999 created_at raises uncaught OverflowError (add_seconds catches only ValueError/TypeError).

ST-2 round 4 FAILED: leases fixed races but lease *expiry while the holder is alive* still double-acts. Transfer lease 30 s by the injected clock; slow emit + clock.advance(31) -> second instance emits same data.transfer; also cross-instance clock skew does it with no delay. A poison transfer at the head blocks all later transfers in every world forever. Script: st2_r4.py (run from services/connectors with PYTHONPATH=tests).

**Why:** state that must survive a crash was put in process memory; per-instance config was treated as global truth.
**How to apply:** for any outbox/queue, always test: new instance after injected failure, two instances with different config on one store, slow adapter + 2 threads. Script pattern: scratchpad st2_r2.py. Related: [[api-kill-switch-attack-patterns]].
