---
name: decision-manifest-cc-sh
description: CC-SH r3 PASS (b34fb86): Team Lead Decisions bind answered_by.user, DC-04 refuses reuse after person swap; MF-06 redactor is the only guard for bare tokens in manifest refs
metadata:
  type: project
---

CC-SH round 1 (e3bfd78) FAILED: DC-04 reuse did not re-check answerer authority; manifest ref userinfo denylist.
Round 2 (37cb12b) FAILED: Team Lead Decision bound only the tl_ id, so swapping the person behind it kept their Decisions.
Round 3 (2026-09-25, head b34fb86) PASSED: answered_by.user required for team_lead, forbidden for person (schema); DC-02 and DC-04 compare it to the record's user; web path bans ; and =; cell chars narrowed; MF-06 says the secret redactor scans every manifest string before write and export and refuses (not rewrites) one it would change. just check green, 962 py tests.

Open residuals to check in later tickets (P2 routing / teams.yaml loader, P7 validator, artifact store):
- config/teams.yaml `assigned_by.by` and `.at` are self-declared text in a repo file. A backdated `at` would defeat "removed and assigned again revives nothing" (DC-04) and OB-01's "assigned no later than". ADR-0006 says the loader "records assigned_by; only the owner may write it". Check the P2 loader stamps it from an authenticated owner action, not from the file.
- Manifest schema still accepts tokens in a URL path (e.g. a Slack webhook), a cell id using `:` or `$` (`#access_token:abc`), a connector item id or a file name. MF-06 redactor is the only guard; it does not exist yet. The artifact store and export must not ship without it.
- Generated pydantic DecisionAnswerer has `user: UserId | None` (the generator drops if/then). DC-04 fails closed on None, but code that trusts pydantic alone accepts a Team Lead Decision with no user.
- Person A -> B -> A behind one tl_ id with an unchanged stamp brings A's old Decisions back. Acceptable because A holds the role again.

**Why:** role ids (tl_, policy ids) are mutable indirections, and file-held stamps are self-declared.
**How to apply:** in P2/P7 reviews, check the teams.yaml loader and the redactor-before-export wiring. Related: [[policy-engine-p4-01]], [[t3-invariant-gaps]].
