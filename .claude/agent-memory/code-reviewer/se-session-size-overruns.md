---
name: se-session-size-overruns
description: Builders routinely blow the 400 hand-written line cap (P8 SE tickets, ST-2 outbox); unused helpers and prose-heavy docstrings are the usual padding
metadata:
  type: project
---

SE session spec tickets (P8-xx) bundle many public names per ticket; builders ship everything plus unused extras. P8-06 (2026-09-25) came in at ~890 source + ~720 test lines, with FakeExecutor, LiveNotBuiltError and register_autorater defined but never used, and evals/pyproject.toml declaring `dependencies = []` while importing jsonschema, yaml and tilo_contracts.

ST-2 outbox (FR-AGT-11, round 4, 2026-09-25): 543 source lines of which only ~336 are code; ~200 lines are docstrings/comments restating tests/API.md after each review round. Correctness was fine by round 4; size was the remaining defect. Round 5 cut it to 410 source lines (only inline comments, no prose headers) plus about 45 lines of docs and config; passed with the 10-line overrun noted. The builder's own count covers only source, so ask for docs and config lines too.

P0-06 router (PL-03, 2026-09-25): 448 non-test lines (router.py 280). Ranked below a logic defect: bare `raise` of RequestError dropped the attempt list (call record) after a paid fallback. Probe: primary Quota, fallback RequestError, then check `e.attempts`.

**Why:** root CLAUDE.md caps diffs at 400 hand-written lines; tests count (only generated, fixtures, lockfiles excluded).
**How to apply:** run `git diff --stat` first; count code vs docstring lines (ast-based count); grep each new public name for uses outside its definition; check the package pyproject declares what it imports. Review-round fixes tend to append prose to module headers — look there first for cuts.
