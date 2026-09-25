---
name: t3-invariant-gaps
description: Where "T3 always needs a person" and authz have leaked in Tilo contracts/config; check these first on policy, card, plan, connector, autonomy.yaml and policy-engine tickets
metadata:
  type: project
---

P0-02 review round 1 (2026-09-25, head e7ba97d) FAILED on open T3 sets: risk_tier_table modifiers could be dropped, policy conditions were plain booleans, authz.ref was not tied to `by`, non-gate card safe_default could be irreversible.

Round 2 (head 3d4b3c4) closed all four in the schema: 6 unique modifiers over a closed enum, conditions const true, authz ref bound per `by` (u_/pol_/tl_), non-gate options all reversible. What was still open:
- connector action: `gate_type: none` is only forced to `approval` for write/send/share/delete capabilities. `{capability: search|read|list, risk_tier: T3, irreversible: true, gate_type: none}` validates, and plan.rules.md PG-11 says gate_type none "needs no gate". So a T3 or irreversible action can be declared ungated.
- gate card: CR-02 (unique option ids) is validator-only, so two options with id `hold`, one irreversible, pass the schema. card.rules.md marks CR-03 as "schema" but it depends on CR-02.
- consent card: `delegate` is allowed and safe_default may be the grant option (`connect`). ADR-0002 bans delegate only on gates.
- policy with action_type of a T3 base tier at L3 is schema-valid; only the engine's max_level cap stops it (no rule id yet).

**Why:** PRD 10.4 fixes the T3 list. Root CLAUDE.md says T3 always needs a person and a model never authorises. Contracts freeze at CP0 (29 Sep), so any gap left in them becomes permanent.

**How to apply:** On later tickets that touch connectors.yaml, the plan validator (PG-04/PG-11), the card validator (CR-01/CR-02), the policy engine or event authz, check whether each open item above was closed in the schema or by a numbered rule with a test. Probe with small jsonschema scripts in the scratchpad: build a referencing Registry from contracts/*.schema.json, mutate a valid fixture, check validity. Do not rely on fixture coverage alone.
