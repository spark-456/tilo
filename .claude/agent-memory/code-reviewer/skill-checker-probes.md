---
name: skill-checker-probes
description: FR-AGT-04 skill check.py review technique; checkers verify ids/refs exist but not that cited values match the source, nor that every input entity is covered, nor reject invented rows
metadata:
  type: project
---

Recurring gap in skills/*/check.py (FR-AGT-04 rounds 3-5, 2026-09-25): checkers validate the rows that ARE present but not that every input entity HAS a row (coverage), confirm a cited ref exists without comparing values, and silently ignore rows for ids NOT in the inputs. Fixes land one checker at a time; the same class survives in siblings.
- Round 3: table-extraction invented value/duplicate/cross-row ref.
- Round 4: quote-comparison `totals: []` passed; verification-checklist accepted unknown claim ids and a `false` verdict with unknown evidence.
- Round 5: quote-comparison coverage_matrix row for an invented quote passes (check only compares keys already in expected_pairs); invoice-po-matching accepts a non-matched row for an unknown invoice line and a status outside the enum; verification-checklist `unverified` with fabricated evidence ids passes; deck-writing chart_ref uses a key denylist (a `series` key passes); quote-comparison `_dec` lacks the magnitude/finite bound so inf*0 raises InvalidOperation.

**Why:** the Verifier (FR-AGT-12) runs these checkers; a pass on a bad output is a FAIL.
**How to apply:** probe each checker by loading examples/*.json, then (a) empty/drop one list entry, (b) add an extra unknown id, (c) mutate one value/ref, (d) duplicate a row, (e) an enum field set to garbage, (f) inf/NaN numbers in inputs; call check() via importlib from a scratchpad script with `uv run python`.
