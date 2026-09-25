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

**Why:** PRD 10.4 fixes the T3 list; root CLAUDE.md says T3 always needs a person and a model never authorises. Contracts freeze at CP0 (29 Sep). Recurring pattern: each round the builder closes the named case but leaves an adjacent author-set field (flag, tier, label, free text, second config source) carrying the same meaning.

**How to apply:** On card validator, channels (SEC-06 PIN from gate.risk_tier), plan validator (PG-04/06/11), policy engine or event authz tickets, walk the open list. Probe with jsonschema scripts in the scratchpad (Registry from contracts/*.schema.json, mutate a valid fixture). Ask both "what does the person see and tap, and who wrote it?" and "what does the engine read, and from which of two sources?".
