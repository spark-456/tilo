# Park Profile page: designed, not in the PRD (WEB-12)

Rows for plan section 8b (AG-WEB folds them in). Each element is built as designed in
`Tilo App Profile.dc.html`; none has a PRD requirement or an endpoint yet.

| Element | Fixture source | Status |
| --- | --- | --- |
| Profile form (six fields), Cancel and "Save changes" | `getUserSettings()` (`GET /v1/me/settings`, FR-SET-01, ADR-0039); a version 0 document starts from the sign-in name and email | `saveUserSettings()` (`PUT`), "Profile saved" only after a live answer; failures keep the form (BQ-SETWEB-1) |
| Notification matrix (5 events x Phone/Email/Slack) and the "decisions keep one channel" rule | the stored document (FR-SET-02); labels from `getProfileSettings()` | drafts until its own "Save changes" (`PUT`); the rule is also the server's |
| Quiet hours switch | the stored `quiet_hours.enabled`; the threshold line is always "Not available yet" (BQ-USET-3) | saved with the matrix |
| Time of day and motion cards | the shell's prefs through `app.setPref("time" or "motion", ...)` | wired to the shell store (the only persisted settings on the page) |
| Two-step sign-in "Manage", Face ID "Change" | literal rows | toast only |
| Signed-in devices, "Sign out", "Sign out everywhere else" | literal three sessions | local state; toasts |
| Plan card, "Compare plans", payment card, "Update" | literals (Team, 5 seats, Visa ending 4242) | toast only; billing is out of scope |
| Invoices list and "Download" | literal three invoices | toast only |
| Agent spend card ("£2,412 of £8,000", 30% bar, "Open the Ledger") | literal; could be wired to `getLedger()` later | literal; link goes to the Ledger page with `app.go("ledger")` |
| "Connectors" header button | none | `app.go("connectors")` |
