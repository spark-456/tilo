# ADR-0003a: Porting the Park City prototypes (addendum to ADR-0003)

- Status: Accepted (2026-10-06; the user's handoff, relayed by the supervisor)
- Deciders: product owner; recorded by the web lane (WEB-0)

## Context
ADR-0003 item 4 allows Tilo's own design prototypes `tilo-kit.js`, `tilo-world.js`, `tilo-player.js` and `worlds/k1-generator.js` to be ported into `apps/web`, and bars `support.js`. On 6 Oct 2026 the user handed over `design_handoff_tilo_web_app/` (Claude Design, Park City theme). Its README tells the builder to port `tilo-world.js` and `tilo-park.js` as TypeScript modules rather than redraw them, and its fixtures and render kit live in `tilo-app.js`. The root CLAUDE.md hard rule names only the four earlier files.

## Decision
1. `design_handoff_tilo_web_app/design/tilo-world.js`, `tilo-park.js` and `tilo-app.js` (render kit, memoised by key, and the fixture data model) are the user's own prototypes and may be ported into `apps/web/src/park/`, under the same terms as ADR-0003 item 4. The user's instruction in the README covers the first two by name; the kit and fixtures follow under the same instruction.
2. `support.js` (Claude Design's runtime, here and under `design/source/`) is never ported or imported.
3. A port keeps the prototype's behaviour: the same names, numbers and cache keys, no `window.*` globals, typed React output instead of strings of markup. Each port ships a parity test that runs the prototype in Node and the TypeScript module with the same inputs and compares the output (PR bodies cite it, BQ-WEB-5).
4. The ported files carry a header naming their source file and this ADR. Every dependency or font keeps its entry in `docs/licences.md`; no third-party asset is copied (UX-8), so connector tiles stay monograms (BQ-WEB-1).
5. Ambient non-agent motion on the Park backdrop (cars, walkers, the city animating on Home only, paused elsewhere, frozen by motion `still` and reduced motion) is allowed. This is the user's 6 Oct 2026 10:35 IST decision ("ensure the frontend design is perfectly the same as the one I have provided"), relayed by the supervisor. Agents still animate only from recorded events, and world progress stays event-driven (HR-1, HR-2). The honesty scan is relaxed only by a narrow allowlist entry, with a reason, for the non-agent layers, made in WEB-3 and reviewed by code-reviewer and security-reviewer.
6. Root CLAUDE.md is not edited by this change. The user adds the three file names to its hard rule; until then this ADR is the record.

## Consequences
- The web lane may start WEB-1 (engines, kit, fixtures) now.
- Ambient motion ships on by default behind one flag (`PARK_AMBIENT_MOTION`); the honesty scan is touched only in WEB-3, narrowly, after review.
