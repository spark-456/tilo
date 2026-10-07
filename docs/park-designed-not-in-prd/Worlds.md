# Worlds page: designed, not in the PRD

Elements of `apps/web/src/park/pages/Worlds/` (design `Tilo App Worlds.dc.html`) that no PRD requirement names. Each is built as designed on the typed fixtures through `park/api/` and can be wired to a real endpoint later. AG-WEB folds these rows into `docs/web-app-rebuild-plan.md` section 8b.

| Element | Fixture source | Status |
| --- | --- | --- |
| New world button (goes to Home, where a world is started) | `app.go("home")`; no data | built on fixtures |
| Search box (filters worlds by name, case-insensitive) | `park/api/fixtures/worlds.ts` (`worlds()`), filtered in the page | built on fixtures |
| Status tabs with counts (All, Needs you, Running, Scheduled, Ready; "Running" also holds a world that needs you) | `park/api/fixtures/worlds.ts` (`st` of each world) | built on fixtures |
| SCALE legend (All sizes, Cities, Towns, Villages) and the three sized sections with their size glyph, count and blurb | `park/api/fixtures/worlds.ts` (`tier` of each world) | built on fixtures |
| "Waiting for you" box for K1 electric scooter (agent figure, "N buildings paused", one card per decision with Approve and Open in world) | `park/api/fixtures/decisions.ts` (`getDecisions`), `needsLeft` from the store | built on fixtures |
| Approved or sent state of a decision card (check mark and "Approved · just now") | `park/api/fixtures/decisions.ts` (`done`), `dec` from the store | built on fixtures |
| "You're all caught up" banner | `needsLeft === 0` from the store; copy is the design's own | built on fixtures |
| City card: mini world map, progress bar and percentage, Spend, Agents and next milestone | `park/api/fixtures/worlds.ts` (`prog`, `spend`, `of`, `agents`, `nextL`, `nextV`), `park/api/fixtures/worlds.ts` `plans()` through `getPlans` for the map | built on fixtures |
| Town card: building strip, next step and spend line, thin progress line | `park/api/fixtures/worlds.ts` (`row`, `nextL`, `nextV`, `spend`, `of`, `prog`) | built on fixtures |
| Village card: single building tile and "when" line | `park/api/fixtures/worlds.ts` (`single`, `when`) | built on fixtures |
| "Starting" chip and ring on a world just started from Home | `park/api/fixtures/worlds.ts` (`makeWorld`, `isNew`), `added` from the store | built on fixtures |
| Status chip wording ("2 decisions", Running, Scheduled, Ready) | `park/api/fixtures/worlds.ts` (`st`), `needsLeft` from the store | built on fixtures |
| Empty state ("Nothing needs you right now", "No worlds match") | derived from the filters; copy is the design's own | built on fixtures |
