---
name: eval-harness-recording-validation
description: tilo_evals replay recordings - builders validate the summary line but forget per-event fields and file decoding; attack every field and the read itself
metadata:
  type: project
---

P8-06 eval harness (evals/src/tilo_evals): round 1 fixed summary-line credits, round 2 crashed on bad
event trace/credits, round 3 fixed those but the whole pass still crashed (no results.md) on:
a non-UTF-8 / UTF-16-BOM recording (read_text UnicodeDecodeError, executors.py), 100k nested brackets
(RecursionError from json.loads), a 5000-digit credits int (plain ValueError, not JSONDecodeError).

Round 4 fixed those; new: the credit cap counts only the optional summary-line credits, never the required
per-event TiloEvent `credits`, so a summary-less recording costs 0 against EFF-07 (cap bypass).
Round 5 fixed the summary-less case, but a summary line without a `credits` key (or credits 0) still overrides
the event sum (missing credits -> 0.0), so the bypass persists. When suggesting "done", ask for max(summary, events).
Scratch config/evals.yaml must list all 8 groups or EvalsConfig refuses.

P8-06a split (2026-09-25): load_cases checked group vs dir and id prefix but never id vs filename stem
(E-PLAN/anything.yaml with id E-PLAN-01 loaded); also malformed YAML leaks raw yaml ParserError, and
EvalsConfig accepts negative/wrong-typed values (float() ValueError/TypeError escape as non-config errors).
P8-06a round 2: filename fix landed; the "other defects" were left unfixed (report them as the headline if
they matter). case.schema.json leaves `recording` any string (absolute, ../ traversal pass) and `measures`
any string, though spec says repo-relative path and EV-/FR-/EFF- ids.

**Why:** fixes tend to cover exactly the repro given, not the same class of input elsewhere.
**How to apply:** when re-reviewing a "bad input crashes the pass" fix, fuzz every field the consumer reads
AND the file read/parse itself (encoding, nesting depth, huge ints). Case fixtures need `args: {}` on every
check and non-null ground_truth to pass case.schema.json. Printing unicode on the Windows console crashes
the scratch script, not the product: don't mistake that for a finding.
