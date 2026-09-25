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
- r5 (1893765, 2026-09-25, final round) PASS: any owner+action_type policy with a stamp after `now` (or an unreadable stamp) gates the whole decision; check_entry(table=) enforces max_level. 753 tests green. Follow-ups handed over (not blocking): (a) an owner policy that fails schema or has level != last history level is still dropped, so an L0 or revoked A with `level` not updated lets overlapping B L3 run (bounded: B owner-granted, never T3, capped). Harden by gating on any unreadable owner/action policy, and tilo-api must write level+history atomically. (b) check_entry table still defaults to None. (c) check_entry sees one policy only, so lowest-wins is enforced by decide alone. (d) API.md "Live decisions" paragraph still says "covers nothing". Probe: scratchpad probe_p4_r5.py.

- r6 (907f765, 2026-09-25, delta for follow-up (a)) FAIL: new `may_cover` (coverage.py) gates on an invalid owner policy only if scope is non-list or matches; a schema-invalid scope ELEMENT (domain "Example.ORG", district "d1", connector "Gmail"/"gmail ", connectors [], dict items, extra scope key) is read as "clearly misses", so a narrowing L0/revoked A is dropped and B L3 runs (valid A -> draft_only). Fix: only a scope that conforms to policy.schema.json#/$defs/scope may "miss". Also still open: corrupt action_type/owner drops the record from `mine`. Probe: scratchpad probe_p4_r6.py. 153 policy tests green.

- r7 (48fe956, 2026-09-25, delta) FAIL: r6 cases closed (may_cover requires a conforming $defs/scope; readable() gates on bad action_type/owner). New bypass: `conforms` uses jsonschema `pattern` = Python `re.search`, where `$` matches before a trailing "\n" (ECMA-262 does not). So connectors ["gmail\n"], districts ["D1\n"], domains ["example.org\n"], recipients [...\n] "conform" and clearly miss; action_type/owner "...\n" pass readable() and drop out of `mine`. A L0 + B L3 -> run. Fix belongs in schemas.conforms (ECMA `$`), not per-field. Probe: scratchpad probe_p4_r7.py. 164 tests green.

Filed elsewhere (not engine): #1 autonomy.yaml, #15 defaults, #21 (PI-11 fixtures, L2 instruction has no action type, WhatsApp card reply counts as instruction). approval.requested.approver trust moved to harness by contract text.

**Why:** each round closes the named probe but the same class resurfaces one step over (single policy -> overlapping policies; tier -> level cap; invalid value -> value that only Python's regex calls valid).
**How to apply:** on the next round, re-run the two-policy variant (revoke A, B covers; new L0 A) and a max_level-capped table through check_entry. See [[t3-invariant-gaps]], [[redaction-and-kill-switch]].
