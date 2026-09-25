---
name: se-session-size-overruns
description: Builders routinely blow the 400 hand-written line cap (P8 SE tickets, ST-2 outbox); unused helpers and prose-heavy docstrings are the usual padding
metadata:
  type: project
---

SE session spec tickets (P8-xx) bundle many public names per ticket; builders ship everything plus unused extras. P8-06 (2026-09-25) came in at ~890 source + ~720 test lines, with FakeExecutor, LiveNotBuiltError and register_autorater defined but never used, and evals/pyproject.toml declaring `dependencies = []` while importing jsonschema, yaml and tilo_contracts.

ST-2 outbox (FR-AGT-11, round 4, 2026-09-25): 543 source lines of which only ~336 are code; ~200 lines are docstrings/comments restating tests/API.md after each review round. Correctness was fine by round 4; size was the remaining defect.

**Why:** root CLAUDE.md caps diffs at 400 hand-written lines; tests count (only generated, fixtures, lockfiles excluded).
**How to apply:** run `git diff --stat` first; count code vs docstring lines (ast-based count); grep each new public name for uses outside its definition; check the package pyproject declares what it imports. Review-round fixes tend to append prose to module headers — look there first for cuts.
