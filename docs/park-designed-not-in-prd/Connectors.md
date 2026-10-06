# Park Connectors page: designed, not in the PRD (WEB-11)

Rows for plan section 8b (`docs/web-app-rebuild-plan.md`). AG-WEB folds them into the running list.

| Element | Fixture source | Status |
| --- | --- | --- |
| Search field "Search 60+ tools" (filters the two lists by name and category) | `getConnectors()` | Filters the loaded connectors only. There is no 60-tool catalogue, so "60+" is the design's copy, not a count |
| Connect (Add a tool) | `getConnectors()` | Page-local: the Api has no connect call. Shows "Signing in" at once and lands Read access on a promise continuation (the design waits 1.4 s on a timer; page code holds none before WEB-3b). Live mode hands off to the S-08 consent sheet |
| Reconnect (HubSpot banner) | `getConnectors()` | Page-local: no Api call. Shows "Waiting for HubSpot", then marks HubSpot connected and toasts "HubSpot reconnected for 90 days" |
| Disconnect and the access level (Read, Draft, Act) in the detail drawer | `getConnectors()` | Page-local: no Api call; the level and the disconnect last only while the page is open |
| Sync now | none | Toast only ("Syncing <tool>..."); no Api call |
| Monogram tiles instead of logos | `Connector.mono`, `Connector.col` | Decided: BQ-WEB-1, monograms stay |
| Banner text "HubSpot sign-in expires in 3 days" | the connector record (`bannerText` in `view.ts`: its `sync` text, first skill and scope) | Shown for any connector in the `attention` state; the "3 days" comes from the fixture `sync` text, not hard-coded. The reconnect toast's days come from `getConnectorTerms().reconnectDays` |
| "Healthy" line in the drawer | `Connector.st`, `Connector.sync` | Static copy built from the sync text; no health check exists |
