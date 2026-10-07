# Park World page: designed, not in the PRD (WEB-6)

Rows for plan section 8b (AG-WEB folds them in). Each element is built as designed in
`Tilo App World.dc.html` on the typed fixtures, read through `Api.getWorlds`, `getPlans`, `getDecisions`,
`getSkills` and `getConnectors`. The live Api rejects with `NotBuilt` until the endpoints exist, and the page then
shows "Not connected yet". None of these has a PRD requirement or an endpoint yet.

| Element | Fixture source | Status |
| --- | --- | --- |
| Pause and Resume (button, "Paused" chip, "Paused · agents are waiting" scrim on the map, toasts "Paused. No spend while paused" and "Resumed. Agents are back at work") | none (page state per world id) | Built as local state; nothing is written and no agent is stopped. No pause endpoint or event |
| Share (copies the page address, toast "Link copied. Only your team can open it") | `location.href` | Built. The clipboard write is guarded; no share-link or access endpoint, the toast claim is the design's copy |
| Ask me later on a decision (toast "Tilo will remind you at 16:00") | none (copy only) | Toast only, no reminder is scheduled |
| Run now on a Town (toast "Run started. You’ll get a notification when it finishes") | none (copy only) | Toast only, no run is started |
| Open result (toast "Opening the result in Google Drive") and Share to Slack (toast "Shared to #ops in Slack") on a finished Village | none (copy only) | Toast only, nothing is opened or sent |
| Waiting for you card on a world | `getDecisions()` filtered to `decision.world`; `app.dec`; `app.decide(key)` | Built. Approve goes through `app.decide` only (the store toasts it with Undo); no write of its own |
| Spend note under the spend bar | `DecisionFacts.spendNote` of the world's decision (additive field), else a tier line computed from `spend`, `budget` | Built. The two-state K1 sentence is data (`additive.ts`), not page logic |
| Hero tag on the map (K1: "Level 3 of 6 · Prototypes and suppliers") | `World.heroTag` (additive field), else derived from tier, districts and agents | Built. "Level 3 of 6" is the prototype's constant, no level count exists in a contract |
| Progress bar and label | `World.prog`, else `World.nextV` | Built. The bar jumps; the `width .5s` ease returns with BQ-WEB-3 |
| District rows with counts, chips and bars | `World.districts` | Built. "agents" is plural in the count even for one, as in the design |
| Run history rows (what, when, cost) | `World.runs` | Built. Costs are fixture strings |
| Tools row: monograms and colours from connectors, with a name map for tools the connectors list calls differently ("Google Sheets", "Google Workspace", "Web", "BambooHR"); a world with no skill lists Gmail and Google Drive | `getSkills()` `used` and `tools`, `getConnectors()` | Built as the prototype computes it. The name map and the fallback pair are page constants |
| Your own activity row shows the initials "AM" | `ActivityItem.you` | The initials are the prototype's literal; there is no signed-in user on this page's reads |
| Village ring beside the running line | none | Drawn still (BQ-WEB-3 restores the spin) |
| Links to the live stage and its lenses ("Open live view", Story, Trace, Delivery, Inspect) | the stage routes S-04, S-10, S-11, S-12, S-05 (`screens/meta.ts`) | NOT in the design (plan question A). A City only. Never `app.go`. **Rule (WEB-CUTOVER): a world has a stage only when its data came from the live API** (the page's `getWorlds` result has `source: "live"`, and the world was not started on this page). Then they are real hrefs the browser follows. For a sample (fixture) world the same elements and classes render disabled: no `href`, `role="link"` and `aria-disabled="true"`, the title and visually hidden text "Sample world: there is no recorded run to open" (`aria-describedby`), no pointer cursor or hover; the keyboard skips them. Pinned by `World.stage.test.tsx`, `World.interactions.test.tsx` (live case) and `e2e/park-world.spec.ts`. The live view is the design's button; the lens links are a small pill at the bottom left of the map. Inspect opens the stage's first building (`B1`), because a Park plan's building ids are not stage ids |
