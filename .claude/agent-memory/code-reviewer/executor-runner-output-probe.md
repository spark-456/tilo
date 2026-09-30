---
name: executor-runner-output-probe
description: P2 executor (run_plan) probes - malformed UnitRunner outcome aborts whole run and strands siblings in agent.working; self-cancel via current_task().cancel() hangs dependents; failed units still emit "finished and retired"
metadata:
  type: project
---

FR-AGT-01/02/03 review (PR #60, 2026-09-26): `run_plan` caught runner exceptions (unit fails closed) but built the agent.handoff envelope straight from the runner's `UnitOutcome`. A runner returning bad `provenance_ids`/`artifact_refs` made the writer raise EventRejected, the TaskGroup cancelled every sibling, and the stream ended with other agents' `agent.working` never retired (HR-2).

Final round (2026-10-01, 2278c99): the fix checked the envelope against envelope.schema.json only. Outcomes that pass the envelope schema but fail EventValidator's extra checks still abort the run: 30k artifact_refs (>100k values cap) and a lone surrogate in summary ("not UTF-8-round-trippable"). And the self-cancel fix used `current_task().cancelling()` to tell run-cancel from runner-cancel, so a runner calling `asyncio.current_task().cancel()` looks like an outer cancel: the unit task dies, its `finished` future is never set, dependents await forever (TaskGroup ignores cancelled children). Fix shape: run the runner in its own inner task; catch EventRejected on the handoff emit.

Re-check (2026-10-01, e58a815): fixed as suggested (ensure_future inner task + EventRejected catch on handoff); probes pass, outer cancel/wait_for still propagate, no leaked tasks. Remaining edge (pre-existing, non-blocking): a runner that swallows CancelledError on outer cancel makes the outer task resume normally.

Also seen: a failed unit (runner crash, tampered pinned skill, missing prompt for verifier/writer role) emits only `agent.retired`, whose registry story is "{target} finished and retired." - failure invisible in Trace (FR-AGT-13 territory).

**Why:** runner output is untrusted model-derived data; builders validate inputs (plan, layout) but not outputs, and validate against the contract schema while the writer enforces more (value cap, depth, UTF-8, finiteness).
**How to apply:** in any executor/harness review, write a scratch probe runner that returns contract-valid-but-writer-invalid output (huge arrays, lone surrogates), one that raises, and one that cancels its own current task; run under asyncio.wait_for to detect hangs; check siblings and the final stream. See [[timeout-then-late-commit-probe]].
