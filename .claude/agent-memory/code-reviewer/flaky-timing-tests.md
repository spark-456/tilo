---
name: flaky-timing-tests
description: Wall-clock "linear time" regex tests with tight bounds flake under full-suite load; run the suite 2-3 times and check --durations
metadata:
  type: feedback
---

Wall-clock bounds in ReDoS/linear-time tests (e.g. `elapsed < 1.0`) flake when the whole suite runs on Windows: FR-MEM-04 round 4 had a 0.46s case fail its 1.0s bound once in four full runs.

**Why:** a flaky test is a failing test (automatic FAIL) and will break CI randomly.
**How to apply:** for any perf-bound test, run the full suite more than once and compare `--durations` to the bound; want at least ~10x headroom or a size-ratio (scaling) check instead of an absolute time. Also check hand-written size: packages with redaction + chain logic tend to exceed 400 lines of source alone.
