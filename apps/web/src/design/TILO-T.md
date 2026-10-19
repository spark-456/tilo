# Tilo T design layer: what screen builders use

Spec: `design/tilo-t/` (`PROMPT.md`, `Tilo T Motion.dc.html` wins on timing). Code: `src/design/tilo-t/` (import from `index.ts`).
`support.js` is never ported. The `.dc.html` files are a spec, not code.

- **Tokens** `tokens.css`: light `data-theme="studio"`, dark `studioDark` (or `studio` + `data-time="night"`, Park's night).
  Use `var(--bg --card --sunk --ink --ink2 --ink3 --line --line2 --pri --onPri --lime --amber --red --sh1..3 --mono --fH --fB)`,
  blueprint `--bp --bpLine --bpInk`, city `--cityGround --groundL --groundR --road` (Park owns `--ground`). Ink `#0B0B0C`, accent lime `#C8F23A`.
- **Keyframes** `motion.css`: every keyframe of `tilo-studio.css` and `tilo-t.css`, same names (`tRise`, `tMarch`, `tParcel`, `tConfetti`...). Start one from your own CSS class.
- **Easing**: `var(--tt-ease-standard | --tt-ease-walk | --tt-ease-leap)` or `EASING` in `motion.ts`. standard = appearing, panels, camera. walk = agents, parcels. leap = pool loader.
- **Reduced motion**: handled globally in `motion.css` (walk, rise and flight become a fade, loops stop). Give each element its fallback from the Motion spec.
- **Loops**: add `useLoopPaused(ref)` (class `tt-paused`) so they stop in a hidden tab or off-screen. Animate only `transform`, `opacity`, `filter`.
- **Icons** `<Icon name size />` (24px grid, 1.8 stroke, `ICON_NAMES`). **Buddy** `<Buddy mood role size />`, moods
  idle talk think happy listen sad hand work swim; static poses under reduced motion.
- **States** `<EmptyState> <LoadingState layout> <ErrorState>` (+ `StateAction`): reuse, do not invent new ones.
- **Doodles**: `<DoodleGutter />` is mounted by `ParkApp`; it shows outside the content column from 1200px up. Set `--tt-column` if a page is narrower.

## The event-trigger rule (HR-1, PRD 9.4)

Every non-ambient animation names its trigger event in code, as a comment or a constant next to where it starts:
`// triggeredBy: building.constructing` (or `triggeredBy: "artifact.delivered"`). No event, no animation. The only exception is
ambient decoration: clouds, doodles, idle blinks, the loading shimmer. A mood is picked from a recorded event
(work from `building.constructing`, hand from `approval.requested`, happy from `world.completed`, sad from `world.failed`).

New `@keyframes` or `animation:` outside `motion.css` fails `src/honesty/animation.static.test.ts`; add it to the allowlist with a reason, or route it through the choreographer.
