# ADR-0014: The scenario config contract (`config/scenarios/<id>.yaml`)

- Status: Proposed. The orchestrator relayed the user's approval of the contract change
  (2026-10-05). This ADR waits for the user's sign-off, and the PR is not merged before it.
  `scenario.schema.json` is a new contract at 1.0.0, so no existing contract or fixture changes.
- Deciders: user (sign-off), architect (proposal)
- Requirement: FR-INT-11 (PRD 4.3, 6.4 PR-7, 7.1, 15.2); inputs BQ-202 and the test-writer's
  interface on `tests/FR-INT-11-12-HIL-10` (`packages/planning/tests/API_FR_INT_11_12.md`), and
  issue #272 (generality harness)

## Context
FR-INT-11 (Must): "Scenario configs preload skills, connectors, seed data, autonomy policy and
world theme from `config/scenarios/<id>.yaml`". Its acceptance test: "Loading SC-01's file needs no
code change and passes its smoke test". PRD 4.3 lets a scenario use configuration only, "a skill
set, connectors, autonomy policy, seed data and a world theme". If a scenario needs code, that
code becomes a pillar requirement first. PRD 15.2 lists `scenario.schema.json` ("Scenario
configs", frozen 1 Oct), but no such file exists, and `contracts/README.md` still lists it as to
come. The PRD names the parts of a scenario but gives no keys.

The test-writer pinned the behaviour through a loader (`tilo_planning.scenarios`) and logged
BQ-202. It uses one file per scenario with the keys `id`, `title`, `skills`, `connectors`,
`seed_data` (repo-relative paths), `theme` and `autonomy`, and each autonomy entry is
`{action_type, level, connectors, per_day?, undo_window_s?}`. The loader refuses levels above the
risk table's max and creates policies at approve, as the owner's own, each with a
`policy.changed`. The tests marked the schema "needs contract change" and hold for any schema the
loader can use. Their fictional scenarios (`TS-91`, `TS-92`) and SC-01's expectations (at least
one skill, a Sandbox Web seed, a slug theme, policies valid against `policy.schema.json`) must
satisfy it.

Issue #272 (with the user's decisions in its comments) needs "handles any scenario" to be
provable. No code may be keyed to a scenario. A static check (GEN-06) will allow only the
scenario keys in scenario files and no scenario id in platform source. Held-out bank cases and
generated briefs that need preloaded config must be expressible in this same shape.

## Decision (proposed)
1. **One closed shape for every scenario.** `contracts/scenario.schema.json` 1.0.0 (title
   `Scenario`) is the shape of `config/scenarios/<id>.yaml`. It has exactly seven keys, and
   `additionalProperties` is false at the root and in each autonomy entry:

   | Key | Shape | Required |
   | --- | --- | --- |
   | `id` | `$defs/id`: `^[A-Za-z][A-Za-z0-9_-]{0,31}$`, no final line break | yes |
   | `title` | plain string, 1 to 120 characters | yes |
   | `skills` | unique `common` `skill_id`s, at least one | yes |
   | `connectors` | unique `common` `connector_id`s, may be empty | yes |
   | `seed_data` | unique `$defs/seed_path`s (repo-relative, forward slashes, no absolute path, drive, backslash, empty, `.` or `..` segment, or hidden file), may be empty | yes |
   | `theme` | `common` `slug`, the same as `layout.schema.json` `theme` | yes |
   | `autonomy` | unique `$defs/autonomy_entry`s; absent or empty preloads no policy | no |

   An autonomy entry is `{action_type, level, connectors (1+, unique), per_day?, undo_window_s?
   (0 to 3600, default 60)}`. `per_day` (an integer of at least 0) is required at L2 and L3, as
   `policy.schema.json` requires. Left out at L0 or L1, it means no daily cap. It is never null:
   one spelling (ADR-0011).
2. **Data, not code, and nothing demo-specific.** The schema has no enum of scenario ids, no
   path prefix for seeds, no theme list, and no field for prompts, model ids, brief text, plans,
   budgets, recipients or tiers. A demo, a bank case and a generated brief all use the same
   seven keys. Anything else a scenario seems to need is a pillar requirement (PRD 4.3). The
   schema text names no scenario. Its descriptions are copied into the generated
   `packages/contracts-py/src`, which the FR-INT-11 test scans for scenario ids.
3. **Autonomy entries are policy seeds in `policy.schema.json` terms.** Each entry sets only the
   fields of a policy a scenario may choose (action type, level, connectors, daily limit, undo
   window). Everything else is fixed when the owner approves the task (rule SN-08 has the field
   table). The owner is the signed-in person, never the file. Stamps and history are by that
   owner. Scope recipients, domains and districts are empty, and so are Team Lead domains.
   `limits.credits` is null, conditions are all true, expiry is null and the notify channel is
   `web`. Each policy gets one `policy.changed` (`created`, `authz` by person). A scenario cannot
   name an owner, a tier or a recipient, so it cannot widen what the owner approves.
4. **T3 never above L1: in the loader and in the engine, not in the schema.** A level must be at
   most `max_level` of the action's tier in `config/autonomy.yaml`. Unlisted actions are T3
   (BQ-44), and `max_level.T3` is const L1. Tiers are data, so the schema would have to copy the
   risk table to check this, and the copy would drift. Instead, rule SN-06 makes the loader
   refuse the file, and the T4 tests check it (a `delete_file` entry at L2, plus a property test
   over every action and level). The policy engine already caps every policy at its tier's
   max_level when it decides (`tilo_policy.decide`), and modifiers still raise any single action
   to T3 at run time (PI-07). PI-22 in `docs/security/p4-policy-invariants.md` records this.
5. **Rules beyond the schema.** `contracts/scenario.rules.md` lists SN-01 to SN-09: id equals the
   file name, safe YAML, connectors in the registry, seeds resolve inside the repo root, skills in
   the catalog when one is given, the level cap, entry connectors drawn from the scenario's own
   list or `internal`, owner-only creation at approve, and no scenario code. The prefix `SN`
   avoids `SC-NN`, the scenario id form that the no-scenario-code checks search for.
6. **Shipped files are checked in CI.** `CONFIG_SHAPES` in `scripts/contracts_codegen.py` accepts
   a glob, and `config/scenarios/*.yaml` maps to `scenario`. `just contracts-check` validates
   every shipped scenario file (none today). With no `config/scenarios/`, as in the drift
   sandbox, there is nothing to check.

## Alternatives considered
- **Check T3 per action type in the schema** (for example `delete_file` and `share_file` at
  L0/L1 only). Rejected because it forks the risk table, and an unlisted action (T3 by BQ-44)
  would still pass.
- **Let an entry declare its tier.** Rejected because a tier is decided from the table and
  modifiers, never chosen by a config author (`autonomy_entry_declares_its_risk_tier` is an
  invalid fixture).
- **Cap scenario entries at L2.** Not done: the T4 property test expects every level up to the
  tier's max (L3 for T1 and T2) to load, and PRD 4.3 lets a scenario set its autonomy policy.
  BQ-221 asks the user whether the person must see the policies before approving.
- **A free-form `extra` or `notes` key.** Rejected because issue #272 needs a closed key set.

## Migration and fixture impact
- A new contract, so nothing migrates. Fixtures: `contracts/fixtures/scenario/valid/` (4 files:
  the test-writer's `TS-91` shape; research with Sandbox Web seed paths and no autonomy; a
  bank-like case with empty lists; L3, L0 and an `internal` grant) and
  `contracts/fixtures/scenario/invalid/` (41 files, one per schema rule). All ids, paths and
  addresses are fictional.
- Generated types: `Scenario`, `ScenarioId`, `ScenarioSeedPath` and `ScenarioAutonomyEntry` in
  `packages/contracts-py` and `packages/contracts-ts`.
- `contracts/README.md` lists the contract, `docs/security/p4-policy-invariants.md` gains PI-22,
  and `docs/open-questions.md` gains BQ-221 and BQ-222.

## Consequences
- The FR-INT-11 builder validates each file against this schema, then applies SN-01 and SN-03 to
  SN-08. The builder also ships `config/scenarios/SC-01.yaml`, which `just contracts-check` then
  validates.
- The generality harness (issue #272, GEN-06 rule 4) should check scenario files against this
  schema, or at least take its allowed keys from the schema's `properties`. On
  `feat/GEN-bank`, `SCENARIO_KEYS` is `{skills, connectors, autonomy, seed, theme}`, which would
  refuse `id`, `title` and `seed_data`, so it has to follow the contract. A bank case that needs
  preloaded config writes a file of this shape.
- A `grant_budget` entry has `limits.credits: null`, so the engine gates it (BQ-100). A scenario
  cannot pre-approve top-ups. Allowing it would add `credits` to the entry, an additive change.
- `theme` is a slug only until `config/themes/` exists (FR-WLD-15, Could). A theme check then
  belongs to the loader, not the schema.
- PRD 15.2 dated this contract 1 Oct. It lands on 5 Oct, before any producer, so nothing depends
  on an older shape.
- The optional fields `autonomy` and `per_day` generate as `X | None = None` in Python. Until ADR-0011 is approved, a loader must validate against the JSON Schema, not only
  the pydantic model, so that an explicit null is refused.
