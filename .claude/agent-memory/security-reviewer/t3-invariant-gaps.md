---
name: t3-invariant-gaps
description: Where "T3 always needs a person" and authz have leaked in Tilo contracts/config; check these first on policy, card, plan, connector, autonomy.yaml, card-validator and policy-engine tickets
metadata:
  type: project
---

P0-02 review history (all 2026-09-25):
- Round 1 (e7ba97d) FAIL: open T3 modifier set, boolean policy conditions, authz.ref not bound to `by`, non-gate safe_default could be irreversible.
- Round 2 (3d4b3c4) closed those; FAIL on ungated T3/irreversible connector actions, duplicate `hold` ids, consent delegate/default.
- Round 3 (89d5ff2) closed those in the schema. FAIL: gate option semantics unbound (self-declared option irreversible, no fixed approve id).
- Round 4 (4890a6e) closed the ids. FAIL: free-text gate labels ("Hold" on approve) and card gate tier/irreversible unbound to the plan gate.
- Round 5 (0e5cb55) PASS: gate labels fixed per id in schema (Approve / Edit first / Hold); card gate id, action type, irreversible, tier, recipients bound by validator rules CR-09 to CR-12 with cross-reference fixtures in contracts/fixtures/card/crossref/ and a reference check in tests. Deterministic card builder writes gate details and gate options; a model writes only what_happened/why_it_matters.
- Builder test edits across all rounds: ruff reformatting of assert messages plus BQ-01 test giving each `by` a matching ref; not weakened.

Still open (lower severity; check on P1 tickets):
- P1 card validator must actually implement CR-09 to CR-12 and run the crossref fixtures; until then a gate card's tier and irreversible flag are author-set.
- Consent card option labels are free text: `hold` labelled "Connect" and the grant option labelled "Not now" validate. Same shape as the round-4 gate defect; mitigated only because oauth2 grants still pass the provider's consent screen. Who writes consent options is unstated.
- Two base-tier sources with no binding rule: connector action `risk_tier` (schema forces delete to T3) vs `config/autonomy.yaml` actions table (delete_file/share_file at T1 validates). PG-06 reads only the table; relies on the `deletion`/`external_sharing` modifiers "applying", which is not defined as data.
- Connector `capability` is self-declared: an action with a send scope under `scopes.read`, capability `read`, gate_type `none` validates and is ungated (config-author trust).
- Policy at L3 for a base-T3 action type (delete_file) validates; only the engine's max_level cap stops it.
- authz `team_lead` ref is a `tl_` id, not the signed-in user id (PRD 16.2 impersonation).
- gate.action.item is one artifact_ref (multi-attachment sends); gate.recipients is emails only (link or domain shares show as []).
- a needs_you card may carry option id `approve` answered by email; safe only if the engine opens gates solely from gate cards.

P0-03 (event contract, outbox) round 1 (05f9eac, 2026-09-25) FAIL: outbox entry has no field for the thing it sends (no pinned draft/item, no thread target; additionalProperties false; attachments forced empty below T3). A T1 save_file entry cannot name its file; OB-05 binds type/connector/recipients/attachments but not gate.action.item. So approved content != sent content is undetectable and a post-approval redraft skips safety_flag tiering. Closed well: consent ids/labels (CR-13), side-effect authz list in schema, policy never T3 on events and outbox, idempotency_key+authz required, no bodies in channel events.
- P0-03 round 2 (1553bb5) FAIL: item/destination pinned (OB-05, CR-12 crossref). But the entry's authz is bound to nothing: outbox crossref `authorised_by` is approval.requested (the reservation, authz always null) or policy.applied data; approval.resolved (the approve tap) is absent from the case format and `broken()` in test_FR_WLD_03_outbox_crossref.py never reads authz. OB-01 text "authz equals that event's authz" points at approval.requested. Swapping entry authz to policy/other person/team_lead passes. Also new: common `destination` pattern accepts `https://...` URLs.
- P0-03 round 3 (5e5adb9) FAIL: authz now bound (approval.resolved approve on same gate/card/outbox, or policy.applied; transfer authz compared; 9 OB-01 invalid cases). destination is opaque id; EV-13 vis includes district; EV-14 delivered->outbox. New gap: policy-opened entries (reserved_by null) have recipients, destination, connector, undo_window_s and risk_tier bound to nothing. OB-05 binds them only to the gate card (none on the policy path); policy.applied carries only action_type, tier, level, window, item. Entry with new external recipient, other connector, window 0 (policy said 60) passes broken(). Fix: bind to policy scope/limits by policy_id and to policy.applied tier/window, with crossref cases.
- P0-03 round 4 (860b3bc) FAIL: policy path now bound (policy.applied carries connector/destination/district/window; OB-01 scope check; 8 policy crossref cases). New gap: PRD 10.4 L2 = "the user's own instruction explicitly asks for the action", but nothing records or requires that instruction (policy.applied has no instruction ref, fixture cause null, OB-01 coverage omits it). L2 limits.per_day may be null (only L3 needs it), so L2 = limitless L3 with an undo window. Also unbound on both paths: policy.owner / approver vs world owner; policy created_by.at after authz.at passes.
- P0-03 round 5 (ac83d9b) FAIL: r4 closed (instruction_id on policy.applied, owner/world/ts/destination bound in OB-01, L2 per_day required, 6 new cases). New gap: the L2 instruction may be a channel.message_in or world.requested with channel `email` (the valid crossref fixture uses an email forward), yet card.schema bars email from gate answers (unauthenticated sender). Also: one instruction opens any number of sends on its thread (no single-use rule), even after the person cancels one.
- Still open after P0-03 r1: artifact.delivered (format email/google_docs) is side_effect false with no outbox link; team_lead authz on T3 data.transfer validates; vis list not bound to the event's district (no EV rule).

**Why:** PRD 10.4 fixes the T3 list; root CLAUDE.md says T3 always needs a person and a model never authorises. Contracts freeze at CP0 (29 Sep). Recurring pattern: each round the builder closes the named case but leaves an adjacent author-set field (flag, tier, label, free text, second config source) carrying the same meaning.

**How to apply:** On card validator, channels (SEC-06 PIN from gate.risk_tier), plan validator (PG-04/06/11), policy engine or event authz tickets, walk the open list. Probe with jsonschema scripts in the scratchpad (Registry from contracts/*.schema.json, mutate a valid fixture). Ask both "what does the person see and tap, and who wrote it?" and "what does the engine read, and from which of two sources?".
