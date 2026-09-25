# evals/checks

Check code lives at [`evals/src/tilo_evals/checks.py`](../src/tilo_evals/checks.py), not here.

Part a (this ticket) ships only the registry: `@register`, `get`, `is_registered`,
`AUTORATER_CHECKS`. The five deterministic checks (EFF-07; PRD 19.2, 19.3) --
`schema_valid`, `equals_ground_truth`, `recipients_within`, `no_side_effects`,
`flagged_or_blocked` -- land in part b.
