---
name: api-authz-redaction
description: tilo-api route authz, kill-switch and vis-redaction defects seen in review (ST-3a onward); check on any tilo-api, Principal/role resolver, Firestore rules, redacted-view or kill-switch ticket
metadata:
  type: project
---

ST-3a (FR-HIL-07/09, SEC-07, PI-13; branch feat/FR-HIL-07-kill-switch-redaction, c7da4b0, stacked on P4-01) round 1, 2026-09-25: FAIL.
- Biggest: GET /worlds/{id}/events and GET /worlds/{id} have no world-membership check; `_visible` returns True for vis "all" for any principal. A stranger gets 200 with every vis:"all" event; `Principal` (user_id, role, districts) has no world/org binding, so districts granted in world A match same-named districts in world B. API_ST3a.md (test-writer's pinned spec) never required membership, so tests could not catch it.
- Kill switch fails open: Stop all loop mutates a policy then does `store.policy_worlds[policy_id]` (KeyError -> 500) — org-level policies (PRD 15.3) with no world mapping or a malformed record abort the loop, later policies stay L3, and the mutated one has no policy.changed.
- Pause takes `channel: str` from the body unvalidated into world.paused data: "sms" emits a schema-invalid event.
- Seq gaps in the filtered stream reveal hidden-event counts (SEC-07 "counts"); policy.changed is always vis "all" even for a district-scoped policy; vis "all" events keep a hidden `district` id; 404 vs 403 oracle on world/policy ids.
- Probe script pattern: scratchpad python importing services/api/tests/_api_lib factories, TestClient(app, raise_server_exceptions=False), dependency_overrides for get_store/get_current_principal.

**Why:** Test-writer pins an API.md "exact shape"; builders implement exactly that, so anything the spec omits (membership, input validation, partial-failure behaviour) ships unguarded. Same recurring pattern as [[t3-invariant-gaps]]: adjacent unbound field carries the authority.

**How to apply:** On every tilo-api read route ask "does a non-member get 200?"; on every bulk safety action ask "what happens at the first bad record?"; validate every client-supplied field that lands in an event against its data schema.
