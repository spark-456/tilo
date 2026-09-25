---
name: cards-api-st3b
description: ST-3b (FR-HIL-01/02, services/api tilo_api.cards) review history; body-declared identity feeding open_gate, merge swallowing cards, gate strand; check on any card, answer, channel or approval route ticket
metadata:
  type: project
---

ST-3b round 1 (ea775d2 on feat/FR-HIL-01-cards, stacked on P4-01), 2026-09-25: FAIL.
- Biggest: POST /worlds/{w}/cards/{c}/answer takes `actor`, `channel`, `pin_verified` from the JSON body with no session; GET takes `as_user` from the query. The part it writes is exactly what `tilo_policy.open_gate` (coverage.opens_gate) trusts: authz.ref == owner and channel/pin from data. Probe: unauthenticated POST actor=u_owner channel=web on a T3 gate -> open_gate Decision run, authz u_owner. channel=web sidesteps SEC-06 PIN entirely.
- No PRD 10.1 role check at all (Viewer answers needs_you, question.answered authz None, answered_by always "person" so Team Lead answers mislabelled).
- A stranger's approve marks the record resolved before open_gate refuses it: owner gets already_resolved and the gate card vanishes from the list (gate stranded).
- actor "" or tl_ id emits authz that fails common authz (ref must be user_id for person); no validation of emitted parts against event data schemas.
- Merge stores only an alias: merged card's what_happened/options are dropped, answer with its own option -> invalid_option; one answer/timeout closes the group. Merge key ignores run_id.
- Gate/consent timeout emits question.answered (registry hud: "card closes on every channel") while the card stays open; question.answered data has no card_id. Consent answer emits no event but resolves the card.
- ST-3a (FR-HIL-07 branch) already has deps.Principal / get_current_principal; ST-3b ignored it. The test-writer's API_ST3b.md pinned the insecure body shape (ambiguity 7 punted "who may answer" to open_gate).

**Why:** open_gate only checks that authz.ref names the owner/approver; it cannot know whether the API verified that identity. Authorisation is only as good as the stamp's source.

**How to apply:** On any route that emits approval.resolved, connection.consented, policy.changed or question.answered, check the identity comes from a verified principal (or a service-authenticated channels caller for whatsapp + pin), not the body. Probe: scratchpad probe_st3b.py pattern (TestClient + open_gate on the written part). Related: [[t3-invariant-gaps]], [[redaction-and-kill-switch]].
