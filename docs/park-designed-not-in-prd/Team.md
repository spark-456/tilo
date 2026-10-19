# Park Team page: designed, not in the PRD (WEB-10)

Rows for plan section 8b (AG-WEB folds them in). Source: `design_handoff_tilo_web_app/design/Tilo App Team.dc.html`.
Everything below is local page state on the typed fixtures; none of it calls an `Api` method, so a reload resets it.

| Element | Fixture source | Status |
| --- | --- | --- |
| Invite by email (adds a "Pending" row, toast "Invite sent to ...") | none (page state) | Built, no Api; wire to an invite endpoint later |
| Change a member's role (select, limit resets to the role's default) | `team.people`, `team.roles` | Built, no Api |
| Remove from team / Cancel invite | `team.people` | Built, no Api |
| Resend invite (toast only) | none | Built, no Api |
| Five "When agents stop and ask" switches | `team.rules` defaults | Built, page state only |
| Add a backup approver per coverage row (only "Sharing outside the company" is also written to `prefs.backup` through `app.setPref`) | `team.coverage` | Built, partly wired |
| Static strings: "Now / 2h ago / Yesterday" activity and the coverage wait times ("6 min", "2 h 10 min") | `team.people[].active`, `team.coverage[].wait` | The fixture's own text, not computed from a clock or the Ledger |
