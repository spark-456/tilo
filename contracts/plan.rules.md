# PlanGraph rules beyond the schema (plan.schema.json v1)

`plan.schema.json` checks shape. The deterministic P1 plan validator (FR-INT-09) also enforces
the cross-reference rules below and rejects a plan that breaks any of them. Each rule id is
stable; a failing validation names the rule id. "Schema" marks rules the schema already enforces.

| Rule | Rule | Source |
| --- | --- | --- |
| PG-01 | Unit ids are unique within the plan; gate ids are unique within the plan. | 15.2 |
| PG-02 | Every id in a unit's `depends_on` names a unit in the same plan, and no unit depends on itself. | FR-INT-09 |
| PG-03 | The `depends_on` graph has no cycles. | FR-INT-09 |
| PG-04 | Every irreversible action maps to a gate: for each unit and each action type in its `actions`, some gate has that `action_type` and lists the unit in `guards`. A plan with an email send fails validation unless a gate guards it. | FR-INT-09 |
| PG-05 | Every gate guards only units that list its `action_type` in `actions`. | FR-INT-09 |
| PG-06 | A gate's `risk_tier` is the tier the risk-tier table (`config/autonomy.yaml`, shape `policy.schema.json#/$defs/risk_tier_table`) gives its action type, raised to T3 by any context modifier that applies; never lower. A T3 gate has `policy_ref: null` (schema). | 10.4, FR-HIL-04 |
| PG-07 | `chosen_approach` names one of `approaches[].id`, and approach ids are unique. | FR-INT-08 |
| PG-08 | Approaches are distinct: every pair differs on at least 2 of the 5 `dimensions` (two values differ when they are not equal). | FR-INT-06 |
| PG-09 | Ranges are ordered: `time.min_s <= time.max_s` and `credits.min <= credits.max`. | FR-INT-06 |
| PG-10 | A non-null `policy_ref` names an existing, unexpired policy for the same action type at L2 or L3 whose scope covers the guarded units' connectors and districts. | 10.4, FR-INT-08 |
| PG-11 | Every skill id resolves in the skill registry, every connector id in `config/connectors.yaml`, and every action type in a unit's `actions` is declared by one of that unit's connectors with `gate_type: approval`. A unit's `actions` lists side effects only; read-only actions (`gate_type: none`) are not listed and need no gate. | FR-AGT-03, FR-CON-01 |
| PG-12 | 2 to 3 approaches, at least one unit, a positive budget cap (schema). | FR-INT-06, FR-INT-08 |

The world layout built from the plan has its own rules (`layout.rules.md`, WE-02, WE-05, WE-06).
