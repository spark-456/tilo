# Home: designed but not in the PRD

Page: `apps/web/src/park/pages/Home/` (WEB-4). Reference: `design_handoff_tilo_web_app/design/Tilo App Home.dc.html`.
Every element runs on the typed fixtures through `park/api` (`getUser`, `getToday`, `getWorlds`, `getAgenda`, `getLedger`); no backend work yet.

| Element | Fixture source | Status |
| --- | --- | --- |
| Greeting panel: date line, "Good morning/evening, Alex.", summary ("38 agents are at work across 4 worlds" is the design's own text, not computed) | `user.first`, `today.long`; agent and world counts are static copy | built on fixtures; the counts need a real source |
| Amber "Needs you" pill ("N decisions waiting in K1 electric scooter" + Review) and the "You’re all caught up" state | `app.needsLeft` (from `dec`); K1 is named in the copy, Review opens world `k1` | built on fixtures; the world named should come from the decision's world |
| Today panel, "Live now": the worlds that need you or run, five at most, with art and progress | `getWorlds(dec, added)` | built on fixtures |
| Today panel, "Up next today": first two events of today after 09:18, "Tilo’s brief is ready", "Tilo routine" | `getAgenda().events` (`today`, `brief`, `cal`) | built on fixtures |
| Today panel, "September spend": spent, budget, forecast, "waiting on you" and the two-colour bar | `getLedger()` (`spent`, `budget`, `forecast`, transactions with `st: "waiting"`) | built on fixtures; the design draws these as fixed text, the page derives them from the ledger so Ledger and Home agree |
| Map pins (three worlds on the city) | `app.pins` positions from the shell, worlds K1, Onboard 12 new hires, Invoice match by index | built; positions arrive with the shell (WEB-3b) |
| Composer: three sizes of job, example chips, 900 ms drafting line, plan card (tier, agents, cost, time, three steps), Change brief, start | page-local copy in `homeData.ts` (the design reads `D.TIERS`, which the Api does not serve) | built; calls `app.addWorld`; the plan is canned copy, not a model's plan |
