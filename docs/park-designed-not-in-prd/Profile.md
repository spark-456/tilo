# Park Profile page: designed, not in the PRD (WEB-12)

Rows for plan section 8b (AG-WEB folds them in). Each element is built as designed in
`Tilo App Profile.dc.html`; none has a PRD requirement or an endpoint yet.

| Element | Fixture source | Status |
| --- | --- | --- |
| Profile form (six fields), Cancel and "Save changes" | `getUser()` fixture; edits are page state, Save only toasts "Profile saved" | literal/local state; no write endpoint |
| Notification matrix (5 events x Phone/Email/Slack) and the "decisions keep one channel" rule | literal in `ProfilePage.tsx` (the design's initial matrix) | local state, calls nothing |
| Quiet hours switch | literal (on) | local state, calls nothing |
| Time of day and motion cards | the shell's prefs through `app.setPref("time" or "motion", ...)` | wired to the shell store (the only persisted settings on the page) |
| Two-step sign-in "Manage", Face ID "Change" | literal rows | toast only |
| Signed-in devices, "Sign out", "Sign out everywhere else" | literal three sessions | local state; toasts |
| Plan card, "Compare plans", payment card, "Update" | literals (Team, 5 seats, Visa ending 4242) | toast only; billing is out of scope |
| Invoices list and "Download" | literal three invoices | toast only |
| Agent spend card ("£2,412 of £8,000", 30% bar, "Open the Ledger") | literal; could be wired to `getLedger()` later | literal; link goes to the Ledger page with `app.go("ledger")` |
| "Connectors" header button | none | `app.go("connectors")` |
