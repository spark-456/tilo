---
name: builder-claims-vs-e2e
description: Builder commit messages claim all e2e green; always rerun e2e serially (--workers=1) to separate parallel flakes from real failures
metadata:
  type: feedback
---

Builder commit messages in the SW session have claimed "e2e specs pass" when a spec failed deterministically (P0-08b-player r1: world-honesty "nothing moves before first event" failed 4/4 serially because fixture fetch was started eagerly at render, before page load, so the test's 800 ms route delay was consumed before goto returned).

**Why:** full parallel e2e runs on this Windows box produce many unrelated flakes (a11y, console, camera-freeze, perf) that pass with --workers=1; the real failure hides among them.
**How to apply:** after a full run, rerun failures with `--workers=1` and `--repeat-each=4` on anything still red before deciding. Also count hand-written lines per commit (`git show --stat <builder commit>`), test-writer commits are excluded. See [[cdp-touch-semantics]].
