# evals/checks

The check code lives at [`evals/src/tilo_evals/checks.py`](../src/tilo_evals/checks.py), not
here. This directory stays as a documented pointer to that module (P8-06 ticket spec) so a
reader following `evals/` top to bottom finds the checks where they expect them, without a
second, parallel copy to keep in sync.

Deterministic checks (EFF-07; PRD 19.2, 19.3): `schema_valid`, `equals_ground_truth`,
`recipients_within`, `no_side_effects`, `flagged_or_blocked`. A case names checks by their
registered name in `evals/case.schema.json`'s `checks` list; `tilo_evals.load_cases` rejects an
unregistered name. Autorater checks (`kind: autorater`) are names added to
`tilo_evals.checks.AUTORATER_CHECKS`; the runner never runs them in replay. No autorater check is
registered yet (P8-06 spec) -- a later ticket adds its first one.
