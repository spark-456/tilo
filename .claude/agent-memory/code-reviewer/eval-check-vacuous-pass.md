---
name: eval-check-vacuous-pass
description: Eval checks (tilo_evals) that look up args by check name or compare missing fields pass vacuously; probe duplicate check entries and absent fields
metadata:
  type: project
---

P8-06b (PR #52) first review, 2026-10-01: `_args(case, name)` took the first `checks[]` entry with that name, so a case with two `equals_ground_truth` entries checked the first field twice (the second field's mismatch passed). `equals_ground_truth` also passed when the field was missing from both ground_truth and outputs (None == None); `recipients_within` passed on a missing field.

**Why:** eval results feed deploy gates (PRD 19.4) and "honest reporting" (19.3); a false pass hides regressions.

**How to apply:** when reviewing eval checks/runner, probe (1) two entries of the same check with different args, (2) the field absent from outputs and/or ground truth, (3) a string where a list is expected, (4) bool vs number under tolerance. Related: [[skill-checker-probes]].
