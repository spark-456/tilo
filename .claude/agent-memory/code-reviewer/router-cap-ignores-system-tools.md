---
name: router-cap-ignores-system-tools
description: EFF-03 cap and PL-03 price in router count only request.prompt; system and tools fields sent uncounted, over cap
metadata:
  type: project
---
P0-06 round 11 (2026-09-26): Router._prepare/_compact/_quote measure only `prompt` (+ tool outputs). GenerateRequest
also has `system` and `tools`; a 5000-word system with max_input_tokens=10 was sent as outcome ok. Chaos test only
ever builds `GenerateRequest(prompt=...)`, so it cannot see it.

**Why:** tests build requests with one field; the cap is implemented against the field the tests fill.

**How to apply:** for any cap/budget/redaction code, list every field of the request model and probe each one filled.
Related: [[router-per-profile-checks]], [[router-budget-selection-probe]].
