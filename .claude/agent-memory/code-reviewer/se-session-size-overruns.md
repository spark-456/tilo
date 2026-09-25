---
name: se-session-size-overruns
description: SE (Evidence) session tickets tend to blow the 400 hand-written line cap and ship unused helpers; check size and dead code first
metadata:
  type: project
---

SE session spec tickets (P8-xx) bundle many public names per ticket; builders ship everything plus unused extras. P8-06 (2026-09-25) came in at ~890 source + ~720 test lines, with FakeExecutor, LiveNotBuiltError and register_autorater defined but never used, and evals/pyproject.toml declaring `dependencies = []` while importing jsonschema, yaml and tilo_contracts.

**Why:** root CLAUDE.md caps diffs at 400 hand-written lines; tests count (only generated, fixtures, lockfiles excluded).
**How to apply:** on SE tickets, run `git diff --stat` first, count src and tests, grep each new public name for uses outside its definition, and check that the package pyproject declares what it imports.
