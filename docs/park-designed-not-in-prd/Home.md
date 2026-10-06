# Home: designed but not in the PRD

Page: `apps/web/src/park/pages/Home/` (WEB-4). Reference: `design_handoff_tilo_web_app/design/Tilo App Home.dc.html`.
Every element runs on the typed fixtures through `park/api` (`getUser`, `getToday`, `getWorlds`, `getAgenda`, `getLedger`); no backend work yet.

| Element | Fixture source | Status |
| --- | --- | --- |
| Greeting panel: date line, "Good morning/evening, Alex.", summary ("38 agents are at work across 4 worlds" is the design's own text, not computed) | `user.first`, `today.long`; agent and world counts are static copy | built on fixtures; the counts need a real source |
| Amber "Needs you" pill ("N decisions waiting in <world>" + Review) and the "You’re all caught up" state | `app.needsLeft` (from `dec`); the world named and opened by Review is the first world from `getWorlds` whose state is "needs" | built on fixtures; no scenario name in the page code |
| Today panel, "Live now": the worlds that need you or run, five at most, with art and progress | `getWorlds(dec, added)` | built on fixtures |
| Today panel, "Up next today": first two events of today after 09:18, "Tilo’s brief is ready", "Tilo routine" | `getAgenda().events` (`today`, `brief`, `cal`) | built on fixtures |
| Today panel, "September spend": spent, budget, forecast, "waiting on you" and the two-colour bar | `getLedger()` (`spent`, `budget`, `forecast`, transactions with `st: "waiting"`) | built on fixtures; the design draws these as fixed text, the page derives them from the ledger so Ledger and Home agree |
| Map pins (three worlds on the city) | `app.pins` positions from the shell; worlds picked from `getWorlds` (not ones just started): pin 0 the first that needs you or runs, pin 1 the next running one, pin 2 the first scheduled one | built; positions arrive with the shell (WEB-3b) |
| Composer: three sizes of job, example chips, 900 ms drafting line, plan card (tier, agents, cost, time, three steps), Change brief, start | page-local copy in `homeData.ts` (the design reads `D.TIERS`, which the Api does not serve) | built; calls `app.addWorld`; the plan is canned copy, not a model's plan |

## Known differences from the reference

- The composer input's `:focus-visible` ring (3px, `#5a3fe0`, offset 2px) is not in the reference, which draws no ring there; it stays for keyboard users (WCAG 2.2 AA). Follow-up from review: confirm the ring with the designer.
- The "38 agents ... 4 worlds" summary and the composer's example chips are page-local copy from the design; the Api serves neither (no tier call, no agent count), so they have no source yet.
