# Art facts: what the original Tilo designs already establish

Read from `design/source/` on 2026-10-03 (World Kit canvas rendered and inspected, `tilo-world.js`, `tilo-kit.js`, `tilo-player.js`, `worlds/k1-generator.js`, `design/tokens.json`). This is the ground truth the kit must stay consistent with. FE-02 turns it into the machine-checked art bible.

## 1. The look in one paragraph
Soft, calm, toy-like isometric towns. True isometric at 30 degrees, flat colour fills with three face shades (top lightest, left mid, right darkest), no gradients, no blur, no outlines (a 0.7 stroke in the fill colour hides seams). Warm off-white ground (#EEEBE2), pastel district plots, white pill labels with a 1.5 px line, rounded Nunito type, small round-headed characters with simple faces. Colour tells state (amber needs you, red blocked, green done, blue fyi), and a text or glyph always backs it.

## 2. Rules already in the code (keep them)
| Area | Fact | Where |
| --- | --- | --- |
| Projection | `P(x,y,z) = ((x-y)*cos30, (x+y)*sin30 - z)`; faces are affine-mapped planes (left, right, top) | `tilo-world.js` lines 43-48 |
| Grid | 48-unit tile `T`, 5-unit inset, lane 0.85 T, gap 0.3 T; roads 1.05 tiles wide; agents stand at doors or walk real routes along roads | `tilo-world.js` line 36; World Kit intro |
| Light | One light. Shades come from `mix` and `dk`/`lt` helpers on the tint, never new hexes | `tilo-world.js` lines 5-6 |
| Building spec | `{name, fp:[w,d], fl: floors 1-4, roof: flat/gable/dome, fa: windows/band/arches, i: icon}` | `KIT` and `specOf` |
| Generated buildings | Seeded by `hash(name)`, so the same name always draws the same building | `specOf` |
| Building states | planned (white ghost, dashed outline), constructing (scaffold, builder bots), operational (windows lit), needs you (amber flag pin), blocked (red marker pin), complete (green check pin), skipped/archived (grey) | `building()`, `pin()` |
| Agents | Round head, torso, limbs, role colour on the body, rank badge, 9 expressions (neutral, walking, focused, talking, needs, puzzled, recovering, delighted, sleepy), 2-frame walk | `agent()` |
| Roles (colours) | research, builder, tester, browser, connector, delivery, designer, finance, bot | `ROLE` |
| Gate | Two posts, a crossbar, a lock disc: green when open, grey when closed | `gate()` |
| Cloud cover | White and warm-grey puffs over locked islands | `clouds()` |
| Levels | Stacked plates with lifts and landings, up to the 7-level Metropolis tower | `metro()`, `liftEl()` |
| Motion | Build pop 280 ms overshoot, 60 ms stagger, ground rise 300 ms, camera 650 ms ease, celebration two jumps in 1.3 s | `tokens.json` motion |
| Typography | Nunito 800/900 (display), Nunito Sans (UI), JetBrains Mono (Trace) | `tokens.json` font |

## 3. What the designs do not cover (the gaps this plan closes)
1. **Variety.** 14 named kit buildings plus a generator that picks from only 3 roofs, 3 facades and 1-3 floors. That is a good seed, but it reads as "office park" for every task. A renovation, a harvest, a clinic or a freight forwarder would all look alike.
2. **No published parts list.** The layout contract (`kit.icon`, `kit.parts`) and rule WE-08 say parts and icons come from "published lists for the theme". `config/themes/` does not exist yet, so neither the planner nor the validator has anything to check against.
3. **Footprints are not shared.** The design's `layout()` packs blocks in the browser. The PRD wants a deterministic solver (FR-WLD-01) to own geometry, so the solver needs each part's footprint and height from the same list the renderer uses.
4. **Missing visuals:** policy-authorised gate variant (HR-7), pier and boat (messaging channel), Mail Room and Expert Office buildings, mobile Story tab, S-02, S-03, S-05 inspect for every object type, S-08 standalone sheet, S-09 meeting room, S-16 to S-19 and the landing page.
5. **Ground and world dressing** is one surface (warm paper) with two tree types. No water, no yards, no rail, no seasonal or domain backdrops.
6. **The K1 events are scripted** (`k1-generator.js`), so any use as a replay must carry the HR-4 "scripted demo" label.

## 4. Port permission and limits
ADR-0003 (user approval 2026-09-25) lets Tilo port `tilo-kit.js`, `tilo-world.js`, `tilo-player.js` and `worlds/k1-generator.js`. `support.js` is never copied. Record every ported file in `docs/licences.md`. Fonts are OFL (Nunito, Nunito Sans, JetBrains Mono); Figtree and Fredoka are dead weight and stay out.
