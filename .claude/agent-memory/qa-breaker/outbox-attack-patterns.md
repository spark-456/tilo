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

ST-2 round 5 (contract now at-least-once + writer dedupe on outbox_id; per-world order): r2-r4 repros all within contract; multi-world poison OK. New break: store hands emit() the *stored* pending transfer dict (no deepcopy, since round 3) so a writer that stamps id/seq or edits data in place and then fails poisons every retry. Script st2_r5.py. Follow-ups: send-lease expiry with two adapter instances = 2 sends (relies on adapter-global idempotency); adapter raising forever retried every dispatch with no backoff; flush is ~quadratic (3000+3000 pending = 4 s).
**How to apply:** always test "callback mutates its argument then raises" on any retry path.

ST-2 round 6: claim deepcopy fixed emit-side aliasing, but the *adapter* side still aliases: _finalize_claim stores the transfer uncopied and its artifact is the same `claimed["item"]` object passed to send_reply (FakeGmail keeps it in `sent`). Adapter-side mutation changes the pending transfer / emitted artifact. Script st2_r6.py.
**How to apply:** when a fix copies on one boundary, check every other boundary the same object crosses (in and out of the store, adapter args, event payloads).

ST-2 round 7 (367b493) PASSED: copy-in at adapter args, _transfer_event and _finalize_claim closed U/V/R; st2_r7.py vandalises every returned/passed object (enqueue/dispatch_due/cancel returns, emitted parts, adapter args, retained Grant) with no store change. Open perf note: 3000-pending flush ~6-7 s (filed in #30).
