---
name: contracts-review-patterns
description: How to review Tilo contract tickets (P0-02 style) - probing cross-reference rules, drift check, invalid fixtures
metadata:
  type: project
---

Contract rules that JSON Schema cannot express (id cross-references inside one document) must be numbered in a contracts/<name>.rules.md (PG-xx in plan.rules.md, WE-xx in layout.rules.md) so the deterministic validators enforce them. In the P0-02 review (2026-09-25) card.schema.json described "safe_default must be one of the options" only in prose, and it also allowed an irreversible option as the timeout default; no card rules file existed.

**Why:** Prose-only rules in a frozen contract get skipped by validator builders; safe defaults and gates are safety-relevant (PRD 10.3, 10.4).

**How to apply:** For each schema, mutate a valid fixture to break every cross-reference its descriptions claim, and check that the schema rejects it or a rules file names the rule. To test drift without copying node_modules (pnpm symlinks break when copied), import scripts/contracts_codegen.py, point c.ROOT and c.CONTRACTS at a scratch copy and call c.main(["check"]). Also print each invalid fixture's errors to confirm it fails for exactly the rule in its name (import contracts_codegen, iterate c.fixtures(c.load_schemas()), call c.validate; set PYTHONIOENCODING=utf-8 on Windows or cp1252 print crashes on fixture text). The card fix (commit 3d4b3c4) added contracts/card.rules.md CR-01..CR-05 and a schema-level "only gates offer irreversible options" rule; that is the accepted pattern for schema-inexpressible rules: number them, mark "validator" vs "schema", and point to the P1 validator.

Event contract (P0-03, reviewed 2026-09-25): registry-only rules are EV-01..EV-12 in contracts/event.rules.md, checked by scripts/contracts_events.py (event_problems, stream_problems). Fast probe: import contracts_codegen + contracts_events, call event_problems on each fixtures/events/{invalid,registry/invalid} file and print the first problem. The generated header includes a sha of registry.yaml, so a registry text edit alone trips drift (verified with the scratch-copy probe above; also copy config/ into the scratch root).

Generated tilo_contracts pydantic models do NOT enforce JSON Schema if/then conditionals (e.g. providers prices: status "set" with null prices validates). Consumers that validate only via the pydantic model miss those rules. Seen in P0-04 review (2026-09-25): config loader accepted status: set with nulls and price() fell back to a bare assert (None prices under python -O). Probe: mutate the config to trip each if/then branch and load it through the consumer.

## JSONL stores: splitlines() vs ensure_ascii=False
str.splitlines() also splits on U+2028/U+2029/U+0085, which json.dumps(ensure_ascii=False) leaves raw. Any JSONL reader must split on "\n" only. Probe: append a payload containing "\u2028", then reopen and run the verify CLI (found in FR-MEM-04 round 5).
