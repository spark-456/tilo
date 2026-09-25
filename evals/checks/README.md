# evals/checks

Check code lives at [`evals/src/tilo_evals/checks.py`](../src/tilo_evals/checks.py), not here.

Part a (this ticket) ships only the registry: `@register`, `get`, `is_registered`. The five deterministic
checks (EFF-07; PRD 19.2, 19.3) land in part b. A `kind: autorater` check is declared, not registered;
`load_cases` skips its registry lookup.
