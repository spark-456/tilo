# Scenario rules beyond the schema (scenario.schema.json v1)

PRD 4.3 and FR-INT-11: a scenario is configuration only, a skill set, connectors, seed data, an
autonomy policy and a world theme, loaded from `config/scenarios/<id>.yaml` with no code change
(ADR-0014). `scenario.schema.json` checks one file on its own. The loader
(`tilo_planning.scenarios.load_scenario`) checks the rules below that need other files, and its
`smoke_test` checks SN-03 to SN-07 again against the repo as it is when it runs. Every rule
holds for every scenario: a demo, a held-out bank case (issue #272) or a generated brief. Rule
ids are stable.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| SN-01 | A scenario is the file `config/scenarios/<id>.yaml`, and its `id` equals the file name without `.yaml`. A requested id (the intake form field) must match `$defs/id` in full, with no path, NUL or final line break, before any file is read. Any other id, or an id with no file, is refused. | loader | 4.3, FR-INT-11 |
| SN-02 | The file is read with a YAML safe loader. An empty file, a document that is not a mapping, a YAML tag, or anything that fails the schema is refused, and the error names the offending key or value. Nothing is half-loaded. `just contracts-check` also validates every shipped file against the schema (`CONFIG_SHAPES`). | loader; contracts-check | FR-INT-11 |
| SN-03 | Every id in `connectors` is declared in `config/connectors.yaml`, so it is never the reserved `internal` (FR-CON-01). Preloading a connector grants nothing: each connection still needs the person's `connect` on a consent card (PI-05). | loader; smoke test | 10.3, FR-HIL-08 |
| SN-04 | Each `seed_data` path is joined to the repo root and resolved (symlinks followed), and must be an existing regular file inside the repo root. The smoke test also parses every `.yaml`, `.yml`, `.json` and `.csv` seed. | loader; smoke test | 4.3 |
| SN-05 | When a skill catalog is given (FR-AGT-04), every id in `skills` is in it. Until FR-AGT-04 merges, only the shape is checked (BQ-202). | loader | 8.2, FR-AGT-04 |
| SN-06 | Each `autonomy` entry's `level` is at most the `max_level` of its action type's tier in `config/autonomy.yaml`. An action type the table does not list is T3 (BQ-44), and T3's max is L1 (`policy.schema.json`, `max_level.T3` const), so a scenario never pre-authorises a T3 action above L1. The schema cannot check this because tiers are data. The policy engine also caps every policy at its tier's max_level when it decides (`tilo_policy.decide`), and a modifier such as attachments or new recipients still raises a single action to T3 at run time (PI-07). | loader; engine | 10.4 |
| SN-07 | Every id in an entry's `connectors` is either in the scenario's `connectors` or the reserved `internal`, which stands for an action that goes through no connector (ADR-0002 decision 14). | loader | 10.4 |
| SN-08 | Only the owner creates a policy (PRD 10.1). An entry becomes a policy only when the signed-in owner approves the task, never at intake, and the file names no owner (schema). Each entry gives one record, built as in the table below, with a fresh unique `pol_` id. Each record gets one `policy.changed` (`change: created`, `level`, `authz` by person with `ref` the owner, EV-04). A second approve of the same task creates none. | tilo-api; loader (`Scenario.policies`) | 10.1, 10.4, PI-13 |
| SN-09 | No platform source (`packages/*/src`, `services/*/src`) names or branches on a scenario id. The loader, the API and the smoke test are the same for every scenario, and a scenario that needs code becomes a pillar requirement first. | tests (FR-INT-11, issue #272 GEN-06) | 4.3, G3 |

## SN-08: from an entry to a `policy.schema.json` record

| Policy field | Value |
| --- | --- |
| `id` | A fresh `pol_` id, unique across entries, scenarios and approvals; never taken from the file |
| `owner` | The signed-in owner who approves the task, passed in by the caller; never taken from the file |
| `action_type`, `level` | The entry's |
| `scope` | `connectors`: the entry's; `recipients`, `domains`, `districts`: `[]` |
| `limits` | `per_day`: the entry's, or null when left out (L0 and L1 only, schema); `credits`: null |
| `conditions` | All three `true` (const) |
| `undo_window_s` | The entry's, or 60 |
| `expiry` | null |
| `notify_channel` | `web` |
| `team_lead_domains` | `[]` |
| `created_by` | `{by: owner, at: approval time}` |
| `changed_by` | null |
| `history` | One entry `{by: owner, at: approval time, change, level: the entry's}` |

A `grant_budget` entry gets `limits.credits: null`, which the engine treats as no cap and gates
(BQ-100). A scenario therefore cannot pre-approve budget top-ups. If one ever needs to, the
entry would gain a `credits` field, an additive (minor) change.

Fixtures: `fixtures/scenario/valid/` and `fixtures/scenario/invalid/`, one invalid file per schema
rule. SN-01 and SN-03 to SN-09 compare a file with other files or with the caller. They are
covered by the loader and API acceptance tests on `tests/FR-INT-11-12-HIL-10`
(`packages/planning/tests/test_FR_INT_11_scenario_config.py`,
`services/api/tests/test_FR_INT_11_scenario_preload.py`), which build their own repo roots.
