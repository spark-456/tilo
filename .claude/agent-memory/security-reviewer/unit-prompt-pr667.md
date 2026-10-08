---
name: unit-prompt-pr667
description: PR #667 UNIT-PROMPT (brief, answers, upstream into unit prompts) r1 FAIL at ef53fb0a. Used the weak neutralise_marker, against BQ-232's untrusted.neutralise. Follow-ups: raw title, unredacted upstream, superseded answers
metadata:
  type: project
---

PR #667 (fix/UNIT-PROMPT-brief-in-unit -> phase0-stack). `tilo_harness/unit_prompt.py` puts the brief, the intake Q/A and upstream unit output into the specialist, writer and verifier `unit.md` and the lead `review.md`. r1 FAIL at ef53fb0a on 2026-10-08.

**Blocker r1:** `unit_prompt.neutralise` loops `tilo_providers.prompts.neutralise_marker` over REQUEST/EARLIER/WORK/BEATS. That folds only ASCII case, whitespace and U+200B-200F/2060/FEFF. 10 of 12 closer forms survive in both REQUEST (person text) and EARLIER (model output, second-order): fullwidth and small-form `>`, fullwidth letters, soft hyphen, U+2063, U+034F, U+180E, U+FE0F, U+202D and U+E0020. BQ-232 (docs/open-questions.md) says untrusted text in harness prompts goes through `tilo_harness.untrusted.neutralise`, and must_ask.py already does. That helper leaves no `<` or `>` for all 12 forms.

**Held:** string.Template does a single pass, so `$answers` in person text stays literal. `_Run.results` is scoped to one run. Upstream comes only from the unit's own depends_on. Nothing is logged. Policy and outbox are untouched.

**Follow-ups:**
- The raw Director title sits between the blocks in DefaultUnitRunner (executor.py:139). A 59-char title forges both blocks.
- Upstream is built from the raw `outcome.outputs`, so it skips the store's redactor and the `flagged` screening verdict.
- Answers replaced by a chip edit (BQ-99) still reach the prompts (runs.py:166).
- REQUEST_CAP can starve the answers to "".
- The decoded upstream text is held whole for the run.

**Why:** "existing framing reused" claims bring the weak live_e2e `_safe` helper into production code.

**How to apply:**
- On any new harness prompt path, grep for `neutralise_marker` and require `untrusted.neutralise(text, limit=cap)`.
- Re-run scratch `probe_unitprompt.py`, a renderer with 12 closer forms counted on the NFKC/invisible-dropped view.
- `[firestore]` emulator-marked harness tests error locally (fixture start); they are environmental and not in this diff.
- Related: [[must-ask-verifier-agt-05-12]], [[plan-compiler-fr-int-09]], [[live-e2e-pl-live-e2e]].
