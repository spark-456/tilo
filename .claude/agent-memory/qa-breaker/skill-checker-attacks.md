---
name: skill-checker-attacks
description: FR-AGT-04 skill check.py fuzzing - input-side crashes, overflow, weak injection/commitment regexes; fuzz recipe
metadata:
  type: project
---

FR-AGT-04 round 1 (2026-09-25) FAILED: 9 of 10 skills/*/*/check.py raised TypeError when an id/category field was a list or dict, and email-triage's injection regex missed "ignore the previous instructions".

Round 2 (2026-09-25) FAILED: output-side fixed, but builders only hardened `output`, not `inputs`. Still raising: unhashable input ids (price/quote/invoice/verification/deck), NaN in deck material text, and invoice-po-matching OverflowError on a schema-valid 400-digit quantity (float division at check.py ~107). Semantic misses: triage regex misses singular "instruction", "you are now", "System: new instructions"; reply-drafting commitment regex misses "5,000 dollars", "3 March", "tomorrow"; `to: []`, `subject: None`, `flags: [1]` pass.

Round 3 (2026-09-25) FAILED: no raises left (fuzz.py leaf fuzzer clean), but semantic pass-garbage: price-comparison computes cheapest only from output-declared unit_prices, so omitting the cheap offer's row lets a dearer pick pass (check.py:143-145). Also pass: pick.source_id unchecked, invoice reason_code any type, table-extraction value/row_ref garbage, web-research claim None.

Round 4 (2026-09-25) FAILED: leaf fuzzer (16 bad values x every leaf, inputs+outputs) found no raises. Still pass-garbage: email-reply-drafting `to: []` (or sender moved to cc) passes; checker only rejects unknown addresses, never requires to == [reply_to_sender] (check.py ~157). Also schema-valid omissions pass: quote-comparison missing totals rows, table-extraction dropped records/fields, exec-summary dropped claims.

Round 5 (2026-09-25) FAILED: reply-drafting `to` fixed; fuzz.py (scratchpad) no raises. table-extraction check.py only compares value when it is numeric-cell or str-vs-str, so text cell "Widget" -> 42/False/null, "$3.50" -> 999999 all pass; float() parse also makes exact big ints fail. Also omissions: dropped records/claims/slides still pass.

**Why:** Verifier (FR-AGT-12) runs these checkers; they must fail closed, never raise.
**How to apply:** Fuzz BOTH inputs and outputs leaf by leaf (list/dict/None/NaN/10**400/huge strings); prove schema-validity with jsonschema + skill.yaml so the crash is not dismissable; paraphrase injection and commitment text. Then try OMISSION attacks: drop rows from output arrays (unit_prices, totals, records) and see if pick/recommendation checks still pass.

Re-scope round 1 (2026-09-25, skills/_lib/guard.py) FAILED: no raises, but parse_decimal returns None for float repr with exponent (1e16, 1e+300) and for >40-digit ints; table-extraction compares None==None so text cell -> 1e16 passes; invoice sums unparseable amounts as 0. number_tokens truncates at MAX_STR so exec-summary numbers after 20k chars pass; check_bounds is never called by any check.py; bcc never checked (schema bans it).
Re-scope round 2 (2026-09-26, d9aae2d) FAILED: 161 tests green, no raises, but Decimal arithmetic uses default context prec=28 while parse_decimal admits 40 digits; invoice amounts [10**28, 1] sum rounds to 10**28, so the wrong total passes and the correct one fails (schema-valid). Same risk in quote/price totals. Also seen: price-comparison non-dict pick (string) yields no finding; deck non-str title/bullets skip number checks; triage numbers adjacent to letters ("500k") are not tokens.
How to apply next time: attack "None == None" comparisons and `or Decimal(0)` defaults; try exponent floats and text past the truncation cap.
