---
name: se-session-size-overruns
description: Builders routinely blow the 400 hand-written line cap (P8 SE tickets, ST-2 outbox); unused helpers and prose-heavy docstrings are the usual padding
metadata:
  type: project
---

SE session spec tickets (P8-xx) bundle many public names per ticket; builders ship everything plus unused extras. P8-06 (2026-09-25) came in at ~890 source + ~720 test lines, with FakeExecutor, LiveNotBuiltError and register_autorater defined but never used, and evals/pyproject.toml declaring `dependencies = []` while importing jsonschema, yaml and tilo_contracts.

ST-2 outbox (FR-AGT-11, round 4, 2026-09-25): 543 source lines of which only ~336 are code; ~200 lines are docstrings/comments restating tests/API.md after each review round. Correctness was fine by round 4; size was the remaining defect. Round 5 cut it to 410 source lines (only inline comments, no prose headers) plus about 45 lines of docs and config; passed with the 10-line overrun noted. The builder's own count covers only source, so ask for docs and config lines too.

P0-06 router (PL-03, 2026-09-25): 448 non-test lines (router.py 280). Ranked below a logic defect: bare `raise` of RequestError dropped the attempt list (call record) after a paid fallback. Probe: primary Quota, fallback RequestError, then check `e.attempts`.

P8-01a (2026-09-25): the orchestrator's size count excludes the package CLAUDE.md, pyproject and test data fixtures (394 by that count, 443 with them). State both numbers in evidence.

P8-07 sandbox-web (2026-09-25): ~572 hand-written lines (src 173, tests 372: test-writer's 126-line testlib alone). Test-writer tests count against the builder's cap too. Also: the E-RED "hidden by CSS" test used a tag-stripping visible_text, so the builder put payloads in a `data-hidden` attribute of an empty styled div: the CSS hides nothing. Probe red pages for payload-as-text inside the hiding element.

P8-01b Treasury (2026-09-25): 533 insertions even after a "compact" commit (treasury.py 224, tests ~300). Also: overrun defined as committed > cap instead of actual > reservation (probe: reserve 10, commit 50 under a big cap -> overrun False), and no test for overrun/halted/replay_only Wait. Probe the spec's exact overrun trigger.

**Why:** root CLAUDE.md caps diffs at 400 hand-written lines; tests count (only generated, fixtures, lockfiles excluded).
**How to apply:** run `git diff --stat` first; count code vs docstring lines (ast-based count); grep each new public name for uses outside its definition; check the package pyproject declares what it imports. Review-round fixes tend to append prose to module headers — look there first for cuts.
