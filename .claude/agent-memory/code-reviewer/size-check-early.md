---
name: size-check-early
description: Count builder hand-written lines in round 1 and report the 400-line breach early; P0-08b-player reached round 4 at ~990 lines before it was flagged
metadata:
  type: feedback
---

Count hand-written lines in round 1, even when a functional defect is the biggest problem, and
put the count in EVIDENCE every round.

**Why:** P0-08b-player (split off specifically to stay under 400) came to ~990 builder source
lines (reducer, runWorld, choreographer, frame, renderer, store...). Rounds 1-3 only reported
functional problems, so the size breach came up in round 4, when a split costs the most.
**How to apply:** `git diff --numstat <base>...<branch>`, then subtract the tests/<ID> commit
(`git show --stat <test commit>`), fixtures, lockfiles and generated files. Also: in this
playwright config the timing project depends on chromium, so a single chromium flake
leaves the perf, toggle and freeze specs showing "did not run". Run them directly with
`--project=timing --no-deps`. See [[builder-claims-vs-e2e]].
