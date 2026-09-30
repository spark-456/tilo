---
name: executor-runner-output-probe
description: P2 executor (run_plan) probes - malformed UnitRunner outcome aborts whole run and strands siblings in agent.working; failed units still emit "finished and retired"
metadata:
  type: project
---

FR-AGT-01/02/03 review (PR #60, 2026-09-26): `run_plan` caught runner exceptions (unit fails closed) but built the agent.handoff envelope straight from the runner's `UnitOutcome`. A runner returning bad `provenance_ids`/`artifact_refs` made the writer raise EventRejected, the TaskGroup cancelled every sibling, and the stream ended with other agents' `agent.working` never retired (HR-2).

Also seen: a failed unit (runner crash, tampered pinned skill, missing prompt for verifier/writer role) emits only `agent.retired`, whose registry story is "{target} finished and retired." - failure invisible in Trace (FR-AGT-13 territory).

**Why:** runner output is untrusted model-derived data; builders validate inputs (plan, layout) but not outputs.
**How to apply:** in any executor/harness review, write a scratch probe runner that returns contract-invalid output and one that raises; check sibling units and the final stream. Also run the default runner on every role the executor accepts, not just the tested one. See [[timeout-then-late-commit-probe]].
