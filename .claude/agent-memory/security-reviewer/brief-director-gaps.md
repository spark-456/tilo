---
name: brief-director-gaps
description: FR-INT-03/04/05 Director brief r1 PASS flagged (2546a94). Brief fields are model output shaped by injection; the repair prompt echoes model output outside the delimiters; the memory seam has no scope or expiry; task text is never safety-screened
metadata:
  type: project
---

FR-INT-03/04/05 (`packages/planning` brief.py, questions.py, memory.py, `prompts/director/`). r1 PASS, flagged, at 2546a94. It stacks on FR-INT-01/02.

What holds:
- The Director request has no tools. The system prompt is a static file.
- `output_schema()` keeps `additionalProperties: false`, so the model cannot forge `applied_preferences` or `assumptions`. The router rejects them.
- `json.loads` in the router and pydantic in planning both keep the last duplicate key, so the two parsers agree.

Open follow-ups (not in spark-456/tilo#59 at r1):
1. `prompts/router/schema_repair.md` puts `$error` after the TASK block. The jsonschema message quotes the model's output (up to 300 chars), so injected text reaches the prompt outside the data block. This is router-wide.
2. `extract_brief` has no length cap. A 120k-char task goes straight through, because the `director` role has no `max_input_tokens` and `budget` defaults to None. Only intake's 4000-char limit protects it.
3. The task text is never screened by the SafetyProvider (PRD 16.3 item 2, SEC-04). Intake screens files only. The Director's output is not screened either.
4. `MemoryLookup.lookup(brief, fields)` takes no user, org, scope or expiry. PRD 13.1 says decisions carry scope and expiry.
5. Stored preferences apply only to fields the model flags as ambiguous. Injected text can therefore suppress an org constraint or sensitivity preference.

**Why:** `brief.sensitivity`, `constraints` and `sources[].ref` (file, memory and connector ids, URLs) are all model output that injected text can shape. The comment in questions.py says "sensitivity changes tiers and gates".

**How to apply:**
- On P4 and plan tickets (FR-INT-09), fail any code that lowers a tier based on `brief.sensitivity` or `constraints`. Tiers must come from connector `data_class` and similar sources, never from the brief.
- Fail any code that dereferences `sources[].ref` without an ownership check against the requesting user.
- On FR-INT-13 (channel intake), check that task text is screened before it reaches the Director.
- Related: [[intake-extraction-gaps]], [[t3-invariant-gaps]].
