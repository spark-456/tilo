---
name: contract-pitfalls
description: Recurring traps when changing contracts/ and scripts/contracts_codegen.py (drift sandbox, TS tuple/allOf/comment quirks, fixture sync, event registry rules, parallel BQ/ADR ids)
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
- Security review round 3 found that a gating rule keyed only on capability, like "gate_type none", let a T3 or irreversible action through. It also found that "only gates are authorisations" missed consent cards. **How to apply:** gate on risk tier and irreversibility as well as capability. Treat every grant (a connection, scopes, a policy) like a gate: no Director delegation and a `hold` default. A rule keyed on an id (hold) must hold for every item with that id, not just one (`contains`), or a duplicate id defeats it.
- Security review round 4: an option that triggers an action (a gate's approve) needs a fixed id from a closed set, not an id or label a model writes. Its flags must be tied to the thing it acts on with if/then (approve.irreversible equals gate.irreversible). Otherwise a "send" option can be marked reversible and suggested. **How to apply:** for any answer that authorises, fix the ids (allOf of contains/minContains/maxContains gives each id at most once) and state which id opens it.
- Security review round 5: fixed ids were not enough. The person taps the *label* (WhatsApp shows only labels), so an authorising option needs its label fixed by id too. Also, card fields copied from elsewhere (gate tier, irreversible, recipients) need a cross-reference rule back to their source. **How to apply:** never argue "the engine reads ids, so labels don't matter"; fix the labels. For cross-document rules, use `fixtures/<name>/crossref/{valid,invalid}` (contracts-check skips subfolders) plus a named reference-check test.
- json-schema-to-typescript drops a named alias (for example CardOptionId becomes string) when a `$ref` has a sibling `description`. Put the text in the parent's description instead.
- Parallel branches pick BQ ids on their own: P0-08a and P0-02 both used BQ-12. Check other feat/* branches (`git show <b>:docs/open-questions.md`) before choosing a new id. P0-03 used BQ-20 to BQ-26 and ADR-0005, leaving BQ-18/19 and ADR-0004 for P0-04 in flight; the orchestrator may renumber.
- json-schema-to-typescript turns a root-level `allOf` (even of pure if/then) into `{[k: string]: unknown} & X1`. Keep conditionals in one root if/then/else, nesting further if/then inside `then`/`else`.
- A generated TS header must never contain `*/` (a glob like `contracts/**/*.schema.json` closed the comment and broke tsc).
- The P0-03 tests validate one sample event (authz by person u_owner, data {}, target B0001) for every side-effect type. So per-type rules on authz.by or on data cannot live in event.schema.json; they go in the registry (authz_by) and the validator rules (EV-04). Test-writer minimal payloads (question.answered = {answered_by}) also fix which data fields may be required.
- Event rules that need the registry, other fields or other events are EV-xx in contracts/event.rules.md, checked by scripts/contracts_events.py. Registry-only violations go in fixtures/events/registry/invalid/evNN_*.json, because fixtures/events/invalid/ must fail a schema.
- Default `uv run pytest` includes the @slow drift tests; the whole suite takes ~95 s on this laptop, near check-fast's 2-minute budget. Slow P0-03 cost is the test lib re-parsing registry.yaml per parametrized test.

Related: [[prd-gaps-defaults]]
