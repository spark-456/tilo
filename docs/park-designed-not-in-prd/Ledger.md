# Ledger: designed but not in the PRD (WEB-7)

Every element below is built as designed on the typed fixtures (`park/api/fixtures/ledger.ts`, read through
`Api.getLedger()`). The live Api rejects with `NotBuilt` until the endpoint exists, and the page then shows
"Not connected yet". AG-WEB folds these rows into plan section 8b.

| Element | Fixture source | Status |
| --- | --- | --- |
| Month picker ("September 2026", toast "August and earlier months live here") | none (copy only) | Built, toast only. No month history in any contract |
| Export CSV (toast "Exported september-2026.csv · also synced to Xero") | none (copy only) | Built, toast only. No export or Xero sync endpoint |
| KPI row: Spent so far, Month-end forecast, Waiting on you, Saved by memory, Hours handed back | `ledger.spent`, `forecast`, `budget`, `tx[dec=depot]`, `memory`, `hours` | Built. "Up £120 on August" and "About 6 working days" are static copy (no prior-month data) |
| Waiting on you tile opens the K1 world, turns green with "Laptop Depot approved today" after `decide("depot")` | `tx[dec=depot]`, `app.dec` | Built. Goes through `app.decide(key)` only |
| Spend over time chart: running total, forecast, even-pace and budget lines, today marker, hover tooltip, "Motor dev kit £1,140" and "If you approve £3,420" / "Forecast £6,300" labels | `ledger.daily`, `budget`, `forecast`, `tx` | Built. The forecast kinks (day 25, +£70) and the spike label are the prototype's constants |
| Where it goes: World, Tool, Agent grouping with donut and legend | `ledger.by` | Built. Donut colours are the prototype's palette |
| Cost per run: 4 sparkline cards with % drop, opening the skill | `ledger.runs` | Built. Card opens `go("skills", { id })` |
| Approval wait times: 5-bucket histogram, average by type, amber "Add a backup" callout, "About 20 min with a backup" | `ledger.waits`, `app.prefs.backup` | Built. "Most asks get a yes in 9 minutes" is static copy; Add a backup goes to `go("team", { focus: "share" })` |
| What Tilo gave back: memory savings by week (4 bars), hours by team (stacked bar and 4 tiles) | `ledger.memory`, `ledger.hours` | Built. Week labels are static copy |
| Activity feed: filter tabs with the waiting count, day groups, expandable rows, Approve and Open in world | `ledger.activity`, `app.dec` | Built. The "You approved £3,420 for Laptop Depot" and "Sent the supplier brief to 3 battery suppliers" rows are produced by the page from `dec`, as in the prototype; no event feed backs them yet |
