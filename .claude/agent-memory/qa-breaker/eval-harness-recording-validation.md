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
P8-06a round 3: recording regex added, but the `..` lookahead uses `.*`, which stops at a newline, so
"x\n../../../etc/passwd" passes (normpath escapes the root). Always try an embedded newline against
JSON-Schema path patterns. The round-1 YAML, UTF-8 and EvalsConfig defects are still unfixed.
P8-06a round 4: newline fix held (control-char lookahead). Round-1 four defects STILL unfixed after 3 rounds;
builder fixes only the headline, so list the carried-over defects inside BIGGEST PROBLEM itself.
P8-06a round 5: all four fixed in cases.py, but EvalsConfig.load got the value checks only: malformed YAML /
non-UTF-8 config still raise raw ParserError/UnicodeDecodeError, 10**400 threshold -> OverflowError, .inf accepted.
A fix to one loader's read/parse must be checked against every sibling loader.
P8-06a round 6: all fixed via shared read_yaml/is_number, but merging unknown/missing key checks into
`sorted(set(raw) ^ set(_VALID))` crashes with raw TypeError on a non-string YAML key (`1: 2`, `null: x`)
plus a missing key. Refactors that "simplify" error paths add new crashes: always try non-str YAML keys.
Also: CaseError joins jsonschema e.message (repr of instance), so a 434-byte alias bomb as `id` builds a
100 MB message in 6s (exponential). Try YAML alias bombs against any loader that reprs values in errors.
P8-06a round 7: PASS. key=str sort, 500-char CappedError, and a no-alias SafeLoader (aliases rejected
outright, `<<:` with inline map still OK). Leftover non-blocker: cap truncates AFTER the full join, so
200k bad checks (2.6 MB file) take ~28s building a multi-MB message; ask for an error-count cap next time.

**Why:** fixes tend to cover exactly the repro given, not the same class of input elsewhere.
**How to apply:** when re-reviewing a "bad input crashes the pass" fix, fuzz every field the consumer reads
AND the file read/parse itself (encoding, nesting depth, huge ints). Case fixtures need `args: {}` on every
check and non-null ground_truth to pass case.schema.json. Printing unicode on the Windows console crashes
the scratch script, not the product: don't mistake that for a finding.
