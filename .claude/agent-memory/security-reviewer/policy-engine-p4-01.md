---
name: policy-engine-p4-01
description: P4-01 tilo_policy engine (decide/open_gate/check_entry) security review history and still-open gaps; read before any policy-engine, kill-switch or harness-authz ticket
metadata:
  type: project
---

Branch feat/P4-01-policy-engine, worktree .claude/worktrees/agent-a8e8db588238c061e, ticket base 3413860. Rounds 1-2 notes also live in that worktree's copy of t3-invariant-gaps.md.

- r1 (79cf0b0) FAIL: engine never schema-validated inputs (per_day null unlimited, substring scope, non-ASCII digit timestamps, attachments=None).
- r2 (1b45e6c) FAIL: `now` and hand-built RiskTable unvalidated; last branch of _decide fail-open.
- r3 FAIL: decide read a policy back to an earlier level when `now` was behind a revocation/Stop all; dup ids checked only among covering policies; L2 instruction no age bound; check_entry trusted self-declared tier.
- r4 (a4e3693, 2026-09-25) FAIL: fixes landed (stamped_by drops a future-stamped policy; dup ids over all; level_since bound; check_entry(table=)). 750 tests green. New gap: dropping only the future-stamped policy lets a second overlapping policy decide, so with lowest-level-wins a recorded revocation of A (or a new L0/L1 narrowing policy) is read away when `now` is behind it: B L3 runs, while with `now` after it gates/draft_only. Fix: any owner policy for the action type with a stamp after `now` gates the whole decision (like dup ids). Probe: scratchpad probe_p4_r4.py pattern.
- Lower, r4: check_entry(table=) re-assesses tier but not table.max_level (T2 capped L2 + L3 case -> None while decide gates); table defaults to None (secure path is opt-in).

Filed elsewhere (not engine): #1 autonomy.yaml, #15 defaults, #21 (PI-11 fixtures, L2 instruction has no action type, WhatsApp card reply counts as instruction). approval.requested.approver trust moved to harness by contract text.

**Why:** each round closes the named probe but the same class resurfaces one step over (single policy -> overlapping policies; tier -> level cap).
**How to apply:** on the next round, re-run the two-policy variant (revoke A, B covers; new L0 A) and a max_level-capped table through check_entry. See [[t3-invariant-gaps]], [[redaction-and-kill-switch]].
