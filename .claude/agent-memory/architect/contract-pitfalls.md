---
name: contract-pitfalls
description: Recurring traps when changing contracts/ and scripts/contracts_codegen.py (drift test sandbox, TS tuple generation, fixture sync, formatter versions)
metadata:
  type: project
---

Traps found while building P0-02 (2026-09-25), still true while the codegen setup is unchanged:

- The FR-WLD-02 drift test runs `just contracts-check` in a sandbox copy that holds only contracts/, packages/contracts-*, scripts/ and root build files — no config/. Anything contracts-check reads outside that set must be optional.
  **Why:** a required config/ check made that acceptance test fail.
  **How to apply:** P0-03 (event registry) and later checks must not need config/ or services/ to pass in that sandbox.
- json-schema-to-typescript 16 turns `prefixItems` + `items: false` into `never[]`; the codegen rewrites tuples to draft-07 `items: [...]` for TS only. Check the generated TS after any new tuple or unusual keyword.
- Dropping or adding a field means rewriting every fixture of that contract, invalid ones too, or they fail for the wrong reason. Afterwards run `pnpm exec biome format --write contracts`, because json.dumps layout differs from Biome.
- Profiles have no cost field: cost rank is derived from config/prices.yaml (ADR-0002). Card answers live in the answering event and the Decision, not on the card.
- The test-writer's files were formatted by an older ruff from pre-commit; P0-02 moved pre-commit to the uv.lock ruff. If fmt-check fails on fresh test files, reformat them and list them as formatting-only in tests_modified.
- Every file in fixtures/<name>/invalid/ must fail the JSON Schema itself (FR-WLD-02 test). A rule that compares two values (for example a card's safe_default naming an option id) can't have a fixture there. Number it in <name>.rules.md as "validator" and say that the P1 validator's tests cover it.
- Security review (P0-02 round 2) failed shapes that config could weaken. The T3 modifier list could be emptied, policy conditions could be set false, authz.ref was not tied to `by`, and a non-gate card could default to an irreversible option. **How to apply:** in any new contract, pin safety lists with minItems or const, and bind an id to its discriminator with if/then. Anything applied without a person (timeouts, defaults) must be reversible in the schema.
- json-schema-to-typescript drops a named alias (for example CardOptionId becomes string) when a `$ref` has a sibling `description`. Put the text in the parent's description instead.
- Parallel branches pick BQ ids on their own: P0-08a and P0-02 both used BQ-12. Check other feat/* branches (`git show <b>:docs/open-questions.md`) before choosing a new id.

Related: [[prd-gaps-defaults]]
