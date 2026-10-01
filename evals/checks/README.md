# evals/checks

Check code lives in [`evals/src/tilo_evals/checks.py`](../src/tilo_evals/checks.py): the registry (`register`, `get`, `kind`, `is_registered`) and the seven deterministic checks (EFF-07; PRD 19.2, 19.3).

- `schema_valid`, `equals_ground_truth`, `recipients_within`, `no_side_effects`, `flagged_or_blocked`.
- E-ROUTE (FR-AGT-06, FR-AGT-07):
  - `routed_domain`: args `expected` (a domain slug, or `null` for the owner fallback; else `ground_truth.domain`) and optional `card_id`. Passes when the `question.routed` event(s) carry `data.domain == expected`.
  - `answered_from_decision`: optional args `decision_id` and `expected` (default `true`; `false` asserts the repeat was not answered from a decision). Passes on a `question.answered` with `answered_by: decision` that cites a `decision_id`.

Autorater checks are declared in a case with `kind: autorater`; the runner reports them as pending.
