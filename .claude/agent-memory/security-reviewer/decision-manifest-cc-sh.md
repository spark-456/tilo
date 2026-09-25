---
name: decision-manifest-cc-sh
description: CC-SH r2 FAIL (37cb12b): DC-04 now re-checks Team Lead record/domain/owner, but binds only the tl_ id, not the person; manifest ref allowlist still lets cell-fragment tokens through
metadata:
  type: project
---

CC-SH round 1 (2026-09-25, e3bfd78) FAILED on DC-04 (reuse not re-checking answerer authority) and on the manifest source-ref userinfo denylist.

Round 2 (2026-09-25, head 37cb12b) fixed both as asked: DC-01/02 bind scope to the owner's worlds, DC-04 re-checks person = world owner, Team Lead record exists, same domain, assigned_by = world owner no later than answered_by.at, routed domain matches; manifest ref is an allowlist of 4 closed shapes (URL userinfo/query/fragment all fail). just check green (962 py tests).

Round 2 still FAILED:
- A Team Lead Decision records only `answered_by.ref` = tl_ id. DC-04 never compares the record's `user`, so if the owner replaces the person behind tl_security (same id, same domain, assigned_by unchanged) the former person's Decisions keep answering. Nothing says a user change re-stamps assigned_by.at. Probe: flip reuse.team_lead.user in the valid crossref cases, broken() returns [].
- Residual (not blocking alone): MF-03 says fragment tokens fail, but `art_deck@2#access_token=...` passes (cell part allows `=`), tokens pass as file names / connector item ids / URL path params (`;access_token=`). No rule requires the secret redactor on manifests before export.
- Residual: config/teams.yaml `assigned_by` is self-declared text in a repo file (PRD 8.3 allows the file); low since repo write is already privileged.

**Why:** role ids (tl_, policy ids) are mutable indirections; authority checks that bind only the id miss "same id, different person".
**How to apply:** next round, check DC-04 (or the Decision) binds the answering user, or the contract says any change to a Team Lead record re-stamps assigned_by.at. Same pattern applies to OB-01 over long-lived things. Related: [[policy-engine-p4-01]], [[t3-invariant-gaps]].
