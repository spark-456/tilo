---
name: cards-store-attack-patterns
description: Defects found attacking tilo_api.cards CardStore (ST-3b, FR-HIL-01/02); reuse on any in-memory store keyed by client-supplied ids
metadata:
  type: project
---
Attack results on ST-3b CardStore (2026-09-25, branch feat/FR-HIL-01-cards):
- Resubmitting a card with an existing id overwrote the record, reopening a resolved gate; a second approve emitted a second approval.resolved (new outbox_id). Worst finding.
- actor from the HTTP body was written straight into authz.ref: "", "alice" and 5000-char values produced schema-invalid approval.resolved parts.
- Schema-valid created_at like 2026-02-31 (the timestamp regex allows day 31 in any month) crashed submit with ValueError.
- timeout 10**12 (the schema sets no maximum) made tick() raise OverflowError, which stopped timeouts for every card.
- CR-01/CR-02 (safe_default is an option, option ids unique) were not enforced for needs_you/meeting cards.
- Submit is O(n) per card: 5000 submits took about 40 s.

**Why:** these are id-collision and schema-edge gaps that the builder's tests do not cover.
**How to apply:** on any store/outbox/card ticket, try resubmitting the same id after it resolves, check every value the body supplies against the emitted part's schema, and try dates that match the regex but do not exist and unbounded integers.
