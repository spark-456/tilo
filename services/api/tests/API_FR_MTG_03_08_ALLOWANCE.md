# FR-MTG-03/04/08 owner allowance piece

The owner caller resolves the same `deps.get_spend_ledger` and configured per-user daily cap
as intake. After ownership preflight, an atomic worst-case hold covers the operation before
safety/model invocation. Each Router call receives at most the remaining held budget; valid
reported remaining credits settle actual Router usage. Unknown or failed usage consumes the
sent budget conservatively. Close releases unused credits, including on publication refusal.
Caps <=0, invalid caps/budgets, exhaustion and open holds refuse429 `allowance_capped`.
The hold uses the sampled UTC day and authenticated owner. SEC-16 per-unit accounting stays.

This piece adds no route, price, environment variable or activation. The default server budget
still refuses503. Internal offline adapters retain compatibility; production callers supply
the allowance. The existing allowance factory is process-wide memory (BQ-PPL11B-6), so this
does not claim distributed cross-instance accounting. Durable draft/autopilot factories,
fresh retention/CAS, default-off owner routes and whole-chain review remain prerequisites.
