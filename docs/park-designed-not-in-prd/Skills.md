# Skills: designed but not in the PRD

Page: `apps/web/src/park/pages/Skills/` (WEB-8a: header, summary pills, Teach flow). Reference: `design_handoff_tilo_web_app/design/Tilo App Skills.dc.html`.
Sections 8b ("Help your agents get better") and 8c (library, detail, tools grid) are later tickets.
Every element runs on the typed fixtures through `park/api` (`getSkills`, `getLearn`, `getUser`, `saveSkill`); no backend work yet.

| Element | Fixture source | Status |
| --- | --- | --- |
| Header: "Skills", total ("N skills"), intro line | `getSkills()` length; intro is design copy | built on fixtures |
| Pills "N trusted", "N learning", "N need your help" / "Nothing waiting" | `getSkills()` (`st`, `ask`) plus `getLearn().reviews`; the draft skill the person saves counts as learning | built on fixtures |
| Teach a skill (scrolls to the card; starts over after a save) | none | built |
| Teach card: four ways to show it, mock browser, "What Tilo has picked up", skill name | page-local copy in `teachData.ts` (the Api serves no teaching session); the record address is `mail.<domain of the person's email>/accounts` | built; captured steps are canned copy, not read from a recording |
| Tilo's version: four plan steps with "Ask me first", one question, estimates | page-local copy; "Stops to ask" is counted from the switches | built; the plan is canned copy, not a model's plan |
| Try run: desk and lead builder, a step every 900 ms, "Asking you" with "Yes, add it", result line | page-local copy; timers through `useSchedule` | built; the run is a staged practice, not a real run (the result "1 min 08s · £0.38" is the design's own text) |
| Save: name, scope (Just me / the person's org), trigger, "starts as Learning", saved banner, View in library, Teach another | `saveSkill(draft skill + learning override)`; scope label is `getUser().org`, owner `getUser().name`; the draft is the first skill whose `st` is `draft` | built on fixtures; the live Api rejects (NotBuilt) and the page then takes the "Saved" state back and says it could not save |

## Known differences from the reference

- The recording dot, the spinners and the colour fades are drawn still (BQ-WEB-3); the page scrolls to the card at once, not smoothly (the honesty scan bans smooth scrolling).
- "1 skill" is singular where the reference prints "1 skills".
- A name that is empty is not saved (the reference has no rule).
- Back from Save lands on Try run with the run not started, as in the reference; opening Try run from the step bar starts it.
