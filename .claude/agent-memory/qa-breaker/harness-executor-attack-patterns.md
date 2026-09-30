---
name: harness-executor-attack-patterns
description: FR-AGT-01/02/03 run_plan attacks that found bugs - runner self-CancelledError hangs dependents; bad outcome fields abort whole run; ValueError/RecursionError from skill YAML escape SkillError
metadata:
  type: project
---

PR #60 (2026-09-26, b50602b) harness executor `run_plan` in services/harness/src/tilo_harness/executor.py.

What broke (reproduced twice):
- A runner that raises `asyncio.CancelledError` itself (inner task cancelled) is not caught by `except Exception`; TaskGroup treats it as a quiet cancel, the unit's `finished` future is never set, and every dependent awaits forever -> run_plan hangs.
- Runner outcome fields (artifact_refs, provenance_ids duplicates or non-ULID) go straight into agent.handoff; EventRejected escapes and TaskGroup cancels healthy siblings, leaving agent.working with no agent.retired.
- yaml.safe_load raises ValueError (int over 4300 digits) and RecursionError (deep nesting), neither caught by `_read_skill` / `load_agents_config` -> registry constructor crashes, mid-run load_pinned aborts the whole run.

**Why:** executor wraps only `Exception` from runner.run, and only `SkillError` from load_pinned.
**How to apply:** on any later executor/runner ticket, retry these three first, plus cancel mid-run (stranded working agents, no retired) and WriterBusy mid-plan. Refusal preflight (cycles, PG-02, PG-11, roster) wrote nothing - held up well.
Scratch harness: build with agt_support.build_layout/build_plan + conftest.make_memory_writer; add services/harness/tests to sys.path.
