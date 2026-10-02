# ADR-0010: A policy fixture for the plan fixture's `pol_finance_updates`

- Status: Proposed — awaiting user approval (2026-10-02, architect; issue #65). It adds a file to
  the frozen fixture set in `contracts/`, so it waits for the user's approval like any other
  contract change (root `CLAUDE.md`). No schema changes.
- Deciders: user (approval), architect (proposal)
- Requirement: FR-INT-09 (PRD 7.1, 10.4; `contracts/plan.rules.md` PG-10)

## Context
Gate `G1` in `contracts/fixtures/plan/valid/three_approaches_policy_gate.json` has
`policy_ref: "pol_finance_updates"`. It guards unit `U4` (`send_email` over `gmail` in district
`D2`). The id also appears in `fixtures/plan/invalid/four_approaches.json`, which fails for its
own reason. No fixture under `contracts/fixtures/policy/valid/` has that id: the fixtures there
are `pol_drive_saves`, `pol_autopilot_l2` and `pol_status_updates`. PG-10 says a non-null
`policy_ref` names an existing, unexpired L2 or L3 policy for the same action type whose scope
covers the guarded units' connectors and districts. So the committed plan fixture names a policy
the fixture set does not define. SP works around this by hand-building `pol_finance_updates` in
`packages/planning/tests/_plan_validator_lib.py` (`build_fake_policies`).

## Decision (proposed)
Add one valid policy fixture that the plan fixture's gate resolves to. No schema changes, so
`policy.schema.json` stays at its current version.

```diff
+contracts/fixtures/policy/valid/l2_finance_updates.json
+{
+  "id": "pol_finance_updates",
+  "owner": "u_owner",
+  "action_type": "send_email",
+  "scope": {
+    "connectors": ["gmail"],
+    "recipients": [],
+    "domains": ["example.com"],
+    "districts": ["D2"]
+  },
+  "limits": {
+    "per_day": 20,
+    "credits": 50
+  },
+  "conditions": {
+    "no_attachments": true,
+    "no_new_recipients": true,
+    "no_safety_flags": true
+  },
+  "level": "L2",
+  "undo_window_s": 60,
+  "expiry": null,
+  "notify_channel": "web",
+  "team_lead_domains": [],
+  "created_by": {
+    "by": "u_owner",
+    "at": "2026-09-29T09:30:00.000Z"
+  },
+  "changed_by": null,
+  "history": [
+    {
+      "by": "u_owner",
+      "at": "2026-09-29T09:30:00.000Z",
+      "change": "Created at L2 for finance summaries to example.com",
+      "level": "L2"
+    }
+  ]
+}
```

Notes on the values:
- The connector, district, action type and level are the ones the issue asked for and the ones
  PG-10 checks.
- `domains` is narrowed to `example.com`, because a narrower scope is the safer example. PG-10
  does not compare domains, since a plan has no recipients yet.
- `expiry` is null, like the policy SP built by hand. A dated expiry would make PG-10's
  "unexpired" check fail once that date passes.
- Every stamp is the owner's, as OB-01 and BQ-72 require.

A named reference check pairs the two fixtures: `validate_plan` on the plan fixture with the
committed policy fixtures passes PG-10, with no synthetic policy. Suggested name:
`test_FR_INT_09_plan_fixture_policy_ref_resolves_to_a_policy_fixture` (test-writer).

## Alternatives considered
- **Point the gate at an existing policy.** `pol_autopilot_l2` is scoped to district `D1`, so
  PG-10 would fail for `U4` in `D2`. Moving `U4` to `D1` would edit a frozen plan fixture and
  lose the only plan case that has a policy gate in a second district.
- **Keep the synthetic policy in the test library.** The committed fixture set would keep a
  dangling reference, and anyone checking the fixtures against each other would find it.
  Rejected.

## Migration and fixture impact
- One new file under `contracts/fixtures/policy/valid/`. Run `pnpm exec biome format --write
  contracts` after adding it.
- Existing checks pick it up without changes:
  - `just contracts-check` validates it against the schema and round-trips it through the
    generated model.
  - `tests/contracts/test_PRD_10_4_policy_level_and_tier.py` mutates the first valid fixture by
    name. That is still `l1_team_lead_opens_drive_saves.json`, which sorts before the new file.
- `packages/planning/tests/_plan_validator_lib.py` can drop its hand-built `POL_FINANCE_UPDATES`.
  `build_fake_policies` already merges the committed fixtures first. The negative variants
  (expired, L1, wrong scope) stay test-local.
- No producer or stored data changes.

## Consequences
- Unblocks: FR-INT-09 (PG-10 checked fixture to fixture), and gives later FR-INT-08 and P4 tests
  a real L2 policy in a second district.
- The fixture is an example. `u_owner` and `example.com` are the usual fixture placeholders.
