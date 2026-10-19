# Prompt for Claude: apply the Tilo T design, motion and frontend upgrades

Paste everything below the line into Claude (Claude Code works best) together with this folder and your app's repo.

---

You're upgrading the Tilo web app to the **Tilo T** design. This folder is the reference. Each `*.dc.html` file opens directly in a browser. The markup uses inline styles, and a `class Component` at the bottom of each file computes the values. Treat these files as the **spec**, not as code to ship. Port them to our stack (components, our CSS approach, our state management) and keep the visuals and timings exactly the same.

## 1. Read these first, in this order
1. `tilo-studio.css`: the design tokens (`--bg --card --sunk --ink --ink2 --ink3 --line --line2 --pri --onPri --lime --amber…`). Themes switch with `data-theme="studio" | "studioDark"`.
2. `tilo-t.css`: **every keyframe** the product uses, plus blueprint and ground tokens and the reduced-motion rule. Port these 1:1.
3. `Tilo T Motion.dc.html`: the motion contract. Each row gives the element, the **trigger event**, what moves and for how long, the easing, and the reduced-motion fallback. When this file and anything else disagree, this file wins.
4. `Tilo T World.dc.html`: the reference implementation of the event-driven world (the `E` array and `renderVals`).
5. `Tilo T Canvas.dc.html`: the hub. It links to every board (World, Flow, Home, Work, Team, Landing, System) at 1440×900 and 390×844, with all states.

Type is Geist (UI) and Geist Mono (event names, labels, numbers). Ink is `#0B0B0C` and the accent is lime `#C8F23A`. Icons come from `tilo-t.js` (`TiloT.ic(h, name, size)`): a 24px grid with a 1.8 stroke. Port them as an icon component.

## 2. The one rule: Tilo never fakes progress
Every work animation is driven by a **recorded agent event**, never a timer. The only motion without an event is ambient decoration (clouds, doodles, idle blinks), and that runs on Home only. This rule is why the design builds trust. Users can see that a building is rising *because* `building.constructing` fired. If you can't tie an animation to an event, don't ship it.

Easing tokens (define once, reuse everywhere):
- `standard` `cubic-bezier(.2,.8,.2,1)`: things appearing, panels, the camera
- `walk` `cubic-bezier(.45,0,.2,1)`: agents moving, parcels
- `leap` `cubic-bezier(.5,0,.5,1)`: the pool loader jump

Reduced motion: every walk, rise and flight becomes a 200–300 ms fade, and loops stop. `tilo-t.css` ends with the global media-query fallback, and the Motion spec lists a fallback for each element.

## 3. How each animation works and why

### World (the core screen)
- **Data model.** Each event is a tuple `[time, type, agent, toAgent, building, storyText, traceDetail, credits, bubbleText?]`. Map our real event stream onto it. **Everything on screen is derived from `events.slice(0, i+1)`:** building states, agent positions, agent moods, speech bubbles, the Story list, the Trace list and the credit total. They share one source, so the Story text can never disagree with what the city shows.
- **Building lifecycle.** Each building has event indexes for planned, constructing, operational and completed (`bState`). Planned is a dashed plot whose dashes march (`tMarch`, a stroke-dashoffset loop). Constructing grows scaffolding from the ground (`tRise`, `scaleY` from a bottom transform-origin, 2.4 s). Completed cross-fades to the finished art and pops a ✓ pin. There are also special states: `needs` (amber, waiting for approval), `failed` (red) and `stopped` (when the world fails).
- **Agent movement is a CSS transition, not a keyframe.** Agents are absolutely positioned. `left`/`top` have `transition: 1.2s walk-easing`. To move an agent, set its new coordinates (`posOf(id)`) and the browser interpolates. This is why it's interruptible: a new event mid-walk just changes the target, with no jumps and no animation queue. Steps bob while walking. Under reduced motion, the transition becomes `opacity .3s`.
- **Handoffs and questions.** On `agent.handoff` or `question.routed`, the sender walks next to the receiver. A bubble with the **real** handoff note pops in (240 ms) and stays for the next 2 events (`talkWin`). The sender shows the `talk` mood and the receiver shows `listen`.
- **Moods** (`moodOf`) drive the Buddy poses: think, work, talk, listen, hand, sad, happy and idle. `work` shows a bobbing tool icon (`tToolBob`: search, browser, sheet, pen or mail, depending on the building's tool). `hand` raises an arm (`tHand`) and pulses an amber chip (`tPulse`) that links to **Needs you**, and it lowers on `approval.resolved`.
- **Camera.** One `transform: translate() scale()` on the city layer and nothing else. Fit is the base. Zoom steps are `fit × 1.35^n` (n from −1 to 3). Follow-agent re-centres on that agent every render, so the camera tracks the walk for free. Clicking a Story line flies to its building in 900 ms with standard easing. Zoom and Fit cancel Follow.
- **Playback.** Pause, 1×, 2× and **Catch up** step through events at 2200, 1100 and 260 ms per event. Catch up switches back to 1× when it reaches the live head. In production, live events arrive from the stream, and Catch up fast-forwards events that are buffered but not yet shown. Use the same stepping for replays of finished worlds.
- **Delivery.** On `artifact.delivered`, a lime parcel arcs from the Hall to the Result hall along an `offset-path` (`tParcel`, 1.6 s walk easing). Then the Result panel slides in from the right (`tSlideR`, 420 ms) on desktop, or rises as a bottom sheet on phone (`tSlideUp`). On `world.completed`, the city goes from muted to full colour (`tLight`, 800 ms) and confetti bursts **once** (`tConfetti`, using `--cx`/`--cy` per piece). It never loops.
- **Failure.** On `world.failed`, construction freezes, the chip turns red and a reason card drops in. It says plainly that nothing was booked or paid.
- **Performance.** The static city art (ground, roads, finished buildings) is drawn once as SVG by `tilo-city.js` and memoised. Only agents, bubbles, parcels and chips are live DOM. Animate only `transform`, `opacity` and `filter`. Pause all loops when the tab is hidden.

### Run start (`Tilo T Run.dc.html`)
This is one 6 s storyboard. Every layer uses its own keyframe (`tRunBtn`, `tRunCard`, `tRunBp`, `tRunPlot`, `tRunDir`, `tRunL1–3`, `tRunHome`, `tRunWorld`) with **percentage windows on a shared clock**, so the layers stay in sync without JS. The sequence: the button dips (90 ms), the prompt card tilts back in 3D (`perspective` + `rotateX`) and becomes a blueprint, the blueprint flies into the empty plot, the plot glows lime, and the Director appears at the drafting table.
The design shows still frames by setting a negative `animation-delay` with `animation-play-state: paused`. That's a handy trick for tests and Storybook too.
**In production:** play it once (not `infinite`) when the user presses Run. Hand over to the World when `world.started` fires. Each plan line must appear when the Director writes it (`world.planned`, streamed), not on the keyframe timer. The timer in the file only stands in for the stream.

### Pool loader (`Tilo T Pool.dc.html`): site load and task start
This is a phase machine: `leap → swim → sink → done`.
- **Leap (2.6 s, leap easing).** The pool scales open (`tPoolOpen`). Tilo jumps up and scales to **4.8×** toward the viewer (`tLeap`, transform-origin bottom centre), which reads as "zooming toward you", while a shadow grows under it (`tLeapShadow`). The trick: a second copy of the water's front half (`clip-path: inset(50% 0 0 0)`) sits *above* Tilo, so he looks like he leaves from behind the lip of the pool and lands back inside it. On re-entry, 12 droplets reuse **one** keyframe (`tDrop`), each with its own `--dx`/`--dy` CSS variables, and a white ring ripples out (`tRipple`).
- **Swim (only while still loading).** Tilo swims laps around an ellipse using `offset-path` (`tSwim`, 4.2 s linear). His body is clipped with `overflow:hidden` so only his head and shoulders show above the water, with a bobbing ring around him.
- **Sink (1.4 s+).** He rises a little, then drops under (`tSink`), bubbles rise (`tBubble`) and the pool closes (`tPoolClose`, starting at 1.15 s).
- **Page behind.** While the loader is up, the page is `blur(8px) saturate(.85)`, scaled to 1.015 and covered with a 35% `--bg` scrim. On sink, the unblur is **delayed 1.1 s**, so focus comes back just as Tilo goes under. It feels like the page surfaces when he submerges.
- **Production rules.** Don't show it for loads under about 300 ms. Once started, the leap always plays to the end, so it never cuts off mid-air. If loading finished during the leap, go straight to sink. Otherwise, swim until ready, then sink. For task start, the loader runs from `world.started` until `world.planned`, and the captions name the real event ("waiting for world.planned"). Use `role="status"`, `aria-live="polite"` and `aria-busy` on the page.

### Landing (`Tilo T Landing.dc.html`)
This is the Studio landing exactly as it was (don't restyle the existing sections), plus new sections: meetings, teams, pins, agenda, connectors, personal and enterprise, why Tilo, and a phone layout. The feature cards use staggered loops on a 9 s cycle: `tLoopA–C` fade each line in one after another, `tLoopD` scales in the result chips, and `tDrag` shows a pin being dragged. **Add:** pause each loop when its section is off-screen (IntersectionObserver), and start loops only after first paint. Connector tiles have empty logo slots. Use official logos only where we hold the licence.

### Meet (`Tilo T Meet.dc.html`)
This is a bust of Tilo whose pose follows `meeting.started` and `meeting.ended` (listen, think, speak, happy, sad). It uses static poses under reduced motion.

## 4. Screens to build or update (desktop 1440 and phone 390, light and dark where shown)
Home + Assistant, Chat, World (live, planning, running, waiting, delivered, done, failed, loading), Result, Run start, Pool loader, Meet, Skills, Agenda, Team, Needs you, Connectors, Landing, Nav, plus the shared States (empty, loading, error) and Components. `Tilo T State.dc.html` holds the shared empty, loading and error patterns, so reuse them and don't invent new ones. `Tilo S Buddy.dc.html` is the Tilo mascot with all its moods, and every screen uses it.

## 5. Acceptance checklist
- Every non-ambient animation names its trigger event in code (a comment or a constant).
- Timings and easings match `Tilo T Motion.dc.html` to within ±50 ms.
- Reduced motion: no walks, rises, flights, confetti or loops. Only fades.
- Agents retarget smoothly when an event arrives mid-walk.
- Story, Trace, the credit count and the city all come from the same event slice.
- Only `transform`, `opacity` and `filter` animate. The static city renders once. Animation pauses when the tab is hidden or the section is off-screen.
- Phone World uses a bottom sheet for Story and Result, and every touch target is at least 44 px.
- No visual regressions on the existing Studio landing sections.

Work screen by screen. Start with the tokens, keyframes and icons, then World, then Run start and the Pool loader, then the remaining pages. After each screen, compare it side by side with the matching board in `Tilo T Canvas.dc.html`.
