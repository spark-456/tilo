# Handoff: Tilo web app (Park City theme)

## Overview
Tilo is a workspace where AI agents do real work for a team. Each job is a **world**, sized by scale:
- **Village**: a quick task, minutes long.
- **Town**: a routine that runs on a schedule.
- **City**: a multi-week project with districts, buildings, gates and a budget.

People start work, answer questions agents save up, sign off spend, and teach agents new **skills**. Everything an agent spends or decides shows up in the **Ledger**.

This bundle covers the complete web app: 9 pages inside one shell, with shared navigation, notifications, an account menu, loaders and toasts. The mobile app is out of scope for now.

## About the design files
The files in `design/` are **design references built in HTML**. They are working prototypes that show the intended look, copy and behaviour. They are **not production code to copy**.

Your task is to **rebuild these designs in the target codebase** with its own patterns: framework, router, state management and data layer. If there is no codebase yet, use **React + TypeScript (Vite or Next.js App Router)** with CSS variables for tokens. Use CSS Modules or Tailwind mapped to those variables.

**Exception: keep the art engines.** `tilo-world.js` and `tilo-park.js` are bespoke isometric renderers for the city backdrop, buildings, agents and world maps. Port them to TypeScript modules or wrap them as they are. Don't redraw them.

### Running the reference
Serve the `design/` folder over HTTP, then open `Tilo App.dc.html`. For example: `npx serve design` or `python3 -m http.server`.

The `.dc.html` files run on `support.js`, a small runtime:
- The template is HTML with `{{ path }}` holes, `<sc-for>` loops and `<sc-if>` conditionals.
- The logic is a class with `renderVals()`. Read it like a React class component whose return value feeds the template.
- `<dc-import name="X" app="{{ app }}">` mounts the page file `X.dc.html` with an `app` prop.

Ways to inspect the prototype:
- **Deep links:** routes like `#skills`, `#ledger`, `#world/k1` open a page directly.
- **Console:** `window.tiloNavigate('team', { focus: 'share' })` navigates programmatically.

## Fidelity
**High fidelity.** Colours, type, spacing, radii, copy and interactions are final. Recreate them pixel-perfectly. The exact values are in `tokens.css` and in the inline styles of each page file. Exact copy strings are listed in `inventory.md`.

---

## Architecture

```
AppShell                  (Tilo App.dc.html)
├─ CityBackdrop           fixed, full-bleed isometric park city (tilo-park.js)
├─ TopNav                 fixed glass bar: logo · 6 tabs · day/night · bell · avatar
├─ NotificationsPopover / AccountMenu
├─ <Page app={app}/>      one of the 9 pages below
├─ Toast                  one at a time, optional action button
├─ WorldLoader            modal step loader shown when opening a world
└─ BootSplash             first load only
```

### Routes
| Route | Page file | Notes |
|---|---|---|
| `#home` | Tilo App Home | City backdrop visible and animated; panels float on it |
| `#worlds` | Tilo App Worlds | Filter by tier and status, search |
| `#world/<id>` | Tilo App World | Always opened through the WorldLoader |
| `#skills` (`?id`) | Tilo App Skills | `params.id` preselects a skill |
| `#ledger` | Tilo App Ledger | |
| `#agenda` | Tilo App Agenda | |
| `#team` (`?focus`) | Tilo App Team | `params.focus` scrolls to and flashes the coverage card |
| `#profile` (`?tab`) | Tilo App Profile | Tabs: profile, notifications, appearance, security, billing |
| `#connectors` | Tilo App Connectors | |

### The `app` prop (shell → page contract)
Every page receives one object. Keep this contract when you port. It's the cleanest seam to swap in real APIs.
```ts
interface AppCtx {
  page: PageId; params: Record<string, string>;
  go(page: PageId, params?: Record<string, string>): void;   // runs the transition
  dec: Record<DecisionKey, boolean>;  decide(key: DecisionKey): void;  needsLeft: number;
  added: World[];  addWorld(mode: 'quick'|'routine'|'workspace', query: string): World;
  toast(msg: string, actionLabel?: string, action?: () => void): void;
  time: 'day'|'night'; night: boolean; motion: 'lively'|'calm'|'still';
  setPref(key: string, value: unknown): void; prefs: Record<string, unknown>;
  vw: number; vh: number; pins: {x:number;y:number}[]; ready: boolean;
}
```
- `decide(key)` is **the** approval call. It updates the badges, notifications, Ledger KPIs, the Activity feed, Agenda pins, World districts and the Home "Needs you" list. Undo comes through the toast action.
- `prefs.backup` is set by Team ("Add a backup") and read by Ledger (approval wait times).

### Cross-page links (keep these)
- Ledger "Add a backup" → `go('team', { focus: 'share' })`. Team picks a backup → `setPref('backup', id)`. The Ledger wait time changes to "About 20 min with a backup".
- Ledger cost-per-run card → `go('skills', { id })`.
- Notifications → the related world, or Connectors for the HubSpot warning.
- Notification "Settings" → `go('profile', { tab: 'notifications' })`.
- Skill "Used in" chips, Ledger "Open in world" and Agenda "Review and approve" → `go('world', { id })`.

---

## Design tokens
The source of truth is `tokens.css`. Day values sit on `:root`, and night values sit on `[data-time="night"]` on the app root. The day/night button in the nav and **Profile → Appearance** both flip `time`.

| Group | Tokens |
|---|---|
| Ground and surfaces | `--ground #A6D78C` (city grass), `--paper`, `--sheet` (page panel), `--card`, `--sunk`, `--pop` (menus and modals), `--field`, `--btn2`, `--seg`, `--tabOn`, `--chip`, `--track`, `--rowHover`, `--rowOn` |
| Glass (nav and Home only) | `--gBg rgba(255,255,255,.72)`, `--gBd`, `--gFx blur(20px) saturate(1.5)` |
| Text | `--ink #1F1D2B`, `--ink2 #4A4655`, `--ink3 #6B6779`, `--inv` |
| Lines | `--line rgba(31,29,43,.12)`, `--line2 rgba(31,29,43,.07)` |
| Brand | `--hero #5A3FE0`, `--heroInk #4A31CC`, `--heroSoft`, `--logo` |
| Status | `--run`, `--sch #0E7C79` (+Soft), `--ok #1E8A4C` (+Ink/Soft), `--amber #F0A500` (+Soft/Line/Ink/Tile), `--red #C8372D` (+Ink/Soft) |
| Extra tints | `--blueSoft --blueInk --pinkSoft --orangeSoft --greenSoft` |
| Pinboard | `--cork --corkDot --corkFrame` |
| Shadows | `--sh` (cards, nav), `--shPop` (menus, toasts, modals) |
| Overlays | `--veil` (dims the city on inner pages), `--scrim` (behind modals), `--toast`/`--toastInk` |

Hard-coded on purpose:
- `#F0A500` amber with `#1F1D2B` text for "needs you" buttons and badges, in both themes.
- `#FFFFFF` text on hero buttons.
- Sticky-note paper colours on the Agenda pinboard: yellow `#FFF1A8`, pink `#FCD9E6`, blue `#D7E7FC`, green `#DDF1D2`, lilac `#E6DEFC`, amber `#FFDD85`.
- Person avatar pastels: `#E6E1F8 #D9F0EE #FBE4EE #FDEBDD #E2ECFB`, always with `#1F1D2B` initials.

### Typography
Fonts: **Nunito** 800/900 for display and the logo. **Nunito Sans** (opsz 6–12) 400/600/700/800 for all UI. Numbers use `font-variant-numeric: tabular-nums`, set app-wide.

| Role | Spec |
|---|---|
| Page title (h1) | Nunito 900 · 36px · −0.8px · lh 1.05 |
| Section title | Nunito 900 · 24px · −0.4px |
| Card title | Nunito Sans 800 · 17–18px |
| Detail title | Nunito Sans 800 · 22px · −0.3px |
| KPI value | Nunito Sans 800 · 28px · −0.6px |
| Body | Nunito Sans 600 · 14.5–15.5px · lh 1.45 · colour `--ink2` |
| Row title | Nunito Sans 800 · 14.5px |
| Meta / caption | Nunito Sans 600–700 · 12.5–13px · `--ink2`/`--ink3` |
| Eyebrow | Nunito Sans 800 · 12px · +0.6px · UPPERCASE · `--ink3` |
| Logo | Nunito 900 · 27px · −0.5px · `--logo` |

### Shape and spacing
- **Radii:** page sheet 28 · card 22 · inner tile/panel 16–20 · button 11–12 · small button 9–10 · chip 7 · pill 999.
- **Page sheet:** `background: var(--sheet); border: 1px solid var(--gBd); border-radius: 28px; box-shadow: var(--sh); padding: 28px 32px 36px; gap 20–30px` between sections.
- **Card:** `background: var(--card); border: 1px solid var(--line2); border-radius: 22px; padding: 18–22px`.
- **Content column:** `max-width: 1320px; margin: 0 auto; padding: 100px 24px 56px`. The top padding clears the fixed nav.
- **Spacing:** multiples of 2 and 4. Grid gaps are 10, 12, 14 and 18. Row heights are 54–64.

### Core components (build these first)
| Component | Spec |
|---|---|
| Button / primary | h42 · r12 · `--hero` · #FFF · 15px 800 · padding 0 18 (14 with an icon) · hover `filter: brightness(1.08)` |
| Button / secondary | h38–42 · r11–12 · `--btn2` · 1px `--line` · `--ink` · 14–14.5px 800 |
| Button / needs | h28–36 · r8–11 · `#F0A500` · `#1F1D2B` · 12.5–14px 800 |
| Segmented control | track `--seg` r12 p3 gap 2 · item h32 r9 13.5px 800 · selected `--tabOn` + `0 1px 3px rgba(31,29,43,.16)`, text `--ink`, others `--ink2`. The Skills tools grid and the Agenda board-style toggle use a sliding thumb (`translateX`, .4s `cubic-bezier(.34,1.3,.5,1)`) |
| Switch | 44×26 r99 · knob 20 #FFF, shadow `0 1px 3px rgba(31,29,43,.3)` · on `--ok`, off `--track` · knob `translateX(18px)` .25s `cubic-bezier(.3,1.3,.5,1)` |
| Status chip | h22–24 · r7 · 11.5–12px 800 · pairs: okSoft/okInk, heroSoft/heroInk, amberTile/amberInk, chip/ink2 |
| Summary pill | h30 · r999 · 13.5px 800 |
| KPI tile | r18 · padding 16 18 · label 13/800 · value 28/800 · sub 13/700 |
| List row | grid `44px 1fr auto` · gap 12 · padding 8–10 · r16 · hover `--rowHover` · selected `--rowOn` |
| Agent/art tile | square r12–18 · `--sunk` or a role tint · art aligned `flex-end` (agents stand on the tile's bottom edge) |
| Toast | fixed top 92 centred · `--toast` · r16 · 14.5px 700 · green check dot · optional action (h32 r10) · auto-hide after **4.2s** |
| Popover / menu | `--pop` · 1px `--line` · r20 · `--shPop` · p8 · rows h42 r12 |
| Modal scrim | fixed inset 0 · `--scrim` |

---

## Screens

### Shell
- **Nav:** fixed at left/right 16, top 14, height 62, radius 22, glass. The logo tile is 34×34 r12, hero, with a white "visor" (22×12 r5) holding two dots.
  - Tabs are h40 r14 15px 800. The active tab is `--heroSoft`/`--heroInk` with `aria-current="page"`.
  - The Worlds tab shows an amber badge with `needsLeft`.
  - On the right: day/night toggle, a bell with an amber unread dot, and a 38px avatar "AM". The avatar ring turns hero on Profile and Connectors.
  - A 3px progress bar runs along the nav's bottom edge.
- **Notifications popover:** 392 wide. Each row is a 36px tile, title and sub, and a time. Approved items switch to "You approved…" with a green tile.
- **Account menu:** 300 wide. Header with name, email and org/plan. Items: Profile and settings · Connectors ("6 on") · Team and roles · Mobile app ("Concept") · Sign out. Sign out shows a prototype toast.
- **City backdrop:**
  - A 1600×1000 scene, scaled with `max(vw/1600, vh/1000)` and centred.
  - It animates **only on Home**. On every other page it's paused (`animation-play-state: paused`) and covered by `--veil`.
  - Draw it once and cache it per `time|motion`.

### Home
- The city stays visible and floating glass panels sit on it.
- Panels:
  - "Needs you" decision cards with Review.
  - "Live now" world list with progress.
  - "Up next today" from Agenda.
  - "September spend" (£2,412 of £8,000 · forecast £6,300 · £3,420 waiting).
  - A composer to start a Quick task, Routine or Workspace.
- **Composer flow:** idle → drafting (900ms) → plan with cost and steps → start. Starting calls `addWorld()` and toasts with an "Open" action.
- **Map pins:** pins on the city mark three worlds. Their positions come from `app.pins`, which the shell computes from the scene's free spots.

### Worlds
- Header with a SCALE legend. A "Waiting for you" spotlight for K1 when decisions are open.
- Three sections: **Cities** show mini world maps, **Towns** show building strips, **Villages** show single buildings. Each card has spend and agents.
- Filters by tier and status, plus search. Empty state: "Try another filter, or start something new from Home."

### World detail (`#world/<id>`)
- The layout depends on tier:
  - **City:** the isometric world map, a legend (Building, Needs you, Done, Planned), districts with buildings and agent counts, and an Activity feed.
  - **Town:** run history.
  - **Village:** progress, then the result.
- A "Waiting for you" card with Approve and "Ask me later" ("Tilo will remind you at 16:00").
- A side panel with Spend (→ Ledger), Skills used (→ Skills) and Tools (→ Connectors). Share copies the link.
- Opening a world always runs the **WorldLoader** first (see Interactions).

### Skills
1. **Header.** Summary pills ("N trusted", "N learning", "N need your help") and a **Teach a skill** button that scrolls to the teach card.
2. **Teach Tilo something new.** A 4-step inline flow with a step bar; earlier steps can be revisited.
   - **Show it.** Pick one of four methods: Record my screen, Guided walkthrough, Describe it, Upload an example.
     - Record and walkthrough show a mock browser. Recording captures 4 steps at 900ms each, with REC and a pulsing dot.
     - Describe uses a textarea. Upload uses a dropzone.
     - "What Tilo has picked up" lists the captured steps, with a name field below. "Show me Tilo's version" stays disabled until 4 steps are captured.
   - **Tilo's version.** A speech bubble, then 4 plan steps with an **Ask me first** switch on each (step 3 is on by default). Then a one-question card with 3 pill answers, and estimates (Each run ~£0.40 · Time ~1 min · Stops to ask N).
   - **Try run.** The art panel shows a desk building and a lead builder agent.
     - Steps advance every 900ms.
     - A step with Ask me first pauses on amber "Asking you" with **Yes, add it**.
     - When it finishes: "Matched your way of doing it · 4 of 4 steps · 1 min 08s · £0.38", with Fix a step or Looks right.
   - **Save.** Name, scope (Just me / Northwind Ops) and trigger (When I ask / Weekdays 09:00 / When an invoice arrives). The skill starts as **Learning**.
     - Once saved: "'Name' is now a skill", with View in library and Teach another. The draft skill becomes live.
3. **Help your agents get better.** Two columns:
   - Questions agents saved up. Answering turns the card green; "Starter" moves from Needs an answer to Learning.
   - Rate recent runs. Thumbs up or down; down opens "Which step went wrong?" with step chips, a textarea and Save fix.
   - Ready for your review. Run bars (green or red), with Mark as trusted or Keep learning.
   - Who helped this month. −38% mistakes, a count of answers and fixes, and a 4-person leaderboard. Alex's count rises with your actions.
4. **Learned skills.**
   - A library list on the left: search, plus a status chip and cost per run on each row.
   - A detail panel on the right:
     - Header actions: Test run (Try run on drafts), Pause/Resume, Edit steps.
     - Stats: Runs, Success, Last run, Improved.
     - A cost-per-run bar (first run → now, % cheaper).
     - Steps, tool access for this skill (Off/Read/Draft/Act per tool) and Used in chips.
5. **Tools.** Eight tool cards, each with a sliding Off/Read/Draft/Act control and a plain-language hint per level.

### Ledger
1. **Header.** Month picker and Export CSV ("Exported september-2026.csv · also synced to Xero").
2. **5 KPIs:** Spent so far, Month-end forecast, Waiting on you (amber, clickable → K1; green once approved), Saved by memory, Hours handed back.
3. **Spend over time** (SVG 720×270).
   - Running-total line and area, a dotted amber forecast, a dashed even-pace line, a red dotted £8,000 budget line and a today marker.
   - Hovering a day shows a dark tooltip ("Thu 24 Sep · £31 / Running total £2,412").
   - The forecast label reads "If you approve £3,420" until approved, then "Forecast £6,300".
4. **Where it goes.** World/Tool/Agent tabs, a conic donut (140px, inner disc 24px inset) and a legend.
5. **Cost per run.** 4 sparkline cards with % drop; clicking one opens the skill.
6. **Approval wait times.** A histogram of 5 buckets, average waits by type, and an amber callout with **Add a backup**.
7. **What Tilo gave back.** Memory savings by week as 4 bars (grow-in .7s), plus hours by team as a stacked bar and 4 legend tiles.
8. **Activity.**
   - Filter tabs: All, Waiting (count), Spend, Approvals, Gates, Shared, Savings.
   - Day-grouped rows: time, icon tile, title and sub, amount and tag.
   - Clicking a row expands detail key/values, an Approve button for waiting items and Open in world.

### Agenda
1. **Header.** A sync pill ("Google Calendar · synced just now") and **Find a time**.
2. **Boards.** Team board and My board side by side. A sliding toggle switches between two styles:
   - **Pinboard:** cork texture (dot grid 9px) inside a 9px frame. Sticky notes are rotated ±2.4°, with a red pin for people or a purple pin for Tilo. On hover a note straightens, lifts 4px and scales 1.03. A dashed "Pin something…" slot sits at the end.
   - **Grouped:** sections TILO SUGGESTS, NEEDS SOMEONE, THIS WEEK and DONE, with accent bars.
   - Tilo suggestions have a dashed border and two actions:
     - **Find a time** turns on slot finding in the calendar.
     - **Block it** turns the suggestion into a "Focus time" pin and toasts.
   - The Laptop Depot pin is tied to `dec.depot` ("Review and approve" → K1). Enter adds a pin.
3. **This week.**
   - Calendar chips (Work, Personal, Tilo) and a Weekend toggle for 5 or 7 days.
   - Each day header shows the date and its load ("3 events · 1.5 h").
   - The grid runs 08:00–18:00 at **52px per hour**, with a red now line at 09:12.
   - Events show a left colour bar, and a Director face badge if Tilo joins.
   - **Finding:** a banner appears, and dashed pulsing slots (`tiloGhost` 1.6s) show where everyone is free. Booking adds a hero-filled event, posts a "K1 gate review booked" pin and toasts.
4. **Event panel** (sticky, 340 wide). Calendar, title, time, attendee avatars and a Tilo face.
   - Upcoming events show TILO'S BRIEF, or **Ask Tilo for a brief**.
   - Past events show NOTES BY TILO and FOLLOW-UPS.
   - Three switches: Tilo joins and takes notes · Turn action items into pins · Brief before it starts.

### Team
- **Header:** invite by email. The Invite button sits at 60% opacity until the email is valid. Invited people appear as a dashed "?" avatar marked Pending.
- **Members table** (min-width 820, scrolls sideways). Columns: Person, Role (select: Owner/Approver/Member/Viewer; disabled for you), Spend limit, Helped Tilo (count and bar), Active, and a more button.
  - The more button expands a detail row: Signs off, Owns skills, Owns worlds, Helped Tilo, plus Resend invite and Remove from team or Cancel invite.
- **Who signs off, and how fast.** One row per approval type, with approver avatars, the average wait, and either "Covered" or an amber **Add a backup…** select.
  - Arriving with `focus` scrolls here and flashes a 2px amber border for 1.8s.
- **When agents stop and ask.** 5 rule switches.
- **What each role can do.** An 8 × 4 matrix of checks.

### Profile and settings
- Tabs: Profile · Notifications · Appearance · Security · Plan and billing.
  - **Profile:** form fields; Save toasts.
  - **Notifications:** a channel matrix for each event. Decisions must keep at least one channel. Quiet hours.
  - **Appearance:** Day/Night and Motion (lively/calm/still), written to `setPref`.
  - **Security:** two-step verification, approval confirmation, and sessions with sign out (one, or everywhere except this device).
  - **Plan and billing:** Team plan (5 seats, renews 1 October) and invoices.

### Connectors
- **Connected:** Gmail, Calendar, Drive, Slack, Xero, and HubSpot, which shows an attention state ("Sign-in expires in 3 days" → Reconnect → "HubSpot reconnected for 90 days").
- **Available:** Notion, Microsoft 365, Jira, GitHub, Stripe, BambooHR.
- **Detail panel:** account, sync (with a spinner while syncing), "How far agents can go" scopes on the Off/Read/Draft/Act scale, and "Used by" (→ Skills or Agenda).
- Tiles use monograms. **Replace them with the official logos.**

---

## Interactions and motion
| What | Behaviour |
|---|---|
| Page change | Out: opacity 0, translateY(−4px), 200ms. Swap the page and scroll to the top. In: from translateY(10px), opacity .24s ease, transform .38s `cubic-bezier(.2,.8,.2,1)`. The progress bar steps 35% → 78% → 100%, hides at 460ms and resets at 820ms |
| Open a world | Scrim with a centred card (400w r24): the world's art, "OPENING CITY", name and meta, then 3 steps that tick from spinner to green check, plus a 4px bar. Steps advance every 340ms for cities and 250ms for towns and villages. The page swaps in at step 3; the card fades out over 280ms |
| Boot | A paper-coloured splash with the 56px logo and 48px wordmark, a 200px sliding bar (`tiloSlide` 1.1s) and "Loading your city". It waits until the engines are ready, then fades over .45s. Prefetch the page bundles afterwards |
| Approve | `decide(key)` → toast "Approved £3,420 for Laptop Depot" with **Undo**. Everything bound to `dec` updates at once |
| Async actions | 14–16px ring spinners (`tiloSpin` .7s); recording dot `tiloPulse` 1s |
| Entrances | `tiloFade` .3–.4s `cubic-bezier(.2,.8,.2,1)` (translateY 8 → 0) |
| Escape key | Closes the open popover or menu; a click on the backdrop does the same |
| Reduced motion | Turns off all animation and transitions. `motion: 'still'` also freezes the city |
| Focus | `outline: 3px solid #5A3FE0; outline-offset: 2px` on `:focus-visible` |

### Responsive
- The layout is fluid down to about 760px. Two-column grids collapse to one at these widths:
  - Skills library: below 1080.
  - Ledger chart and donut, Agenda calendar and panel: below 1100.
- Wide tables (Members) scroll sideways inside their card. Nav tabs scroll sideways too.

### Performance (keep these)
- Draw the city once per theme and motion, and cache it. Only cars and walkers are live layers.
- Animate the city only on Home. Glass blur is limited to the nav and the Home panels, so inner pages render on solid sheets.
- `TiloApp.kit(h)` memoises every agent, building and world render by key. Keep that cache when you port.

## State and data
- **Shell state:** `page, params, phase, bar, wl (world loader), dec, added, menu, toast, read, prefs, vw, vh`.
- **Page state** is listed per file in `inventory.md`. All of it is local UI state; the server-backed parts come from `TiloApp.data`.
- **Fixtures** in `design/tilo-app.js` already have the shape of the data model. Turn them into typed API responses:
  - `user`, `today`
  - `decisions[]`: `{k, world, title, body, yes, icon, done}`, plus `needsLeft(dec)`
  - `worlds(dec, added)`: `World {id, name, short, tier, tool, st, meta, agents, prog, spend, budget, nextL, nextV, owner, plan?, districts?, activity?, runs?, row?, single?}`
  - `plans(dec)`: city layouts consumed by `kit.world`
  - `TIERS`, `makeWorld`
  - `skills[]`: `{id, name, team, owner, role, runs, rate, last, improved, st, first, now, from, tools: [name, level][], used: worldId[], steps[], ask?}`
  - `learn`: `{rates, reviews, helpers, tools}`
  - `ledger`: `{budget, spent, forecast, daily[24], by{world|tool|role}, tx[], runs, waits, memory, hours, activity[]}`
  - `agenda`: `{days, wkend, today, start, end, now, events[{id,d,s,e,t,cal,joins?,past?,brief?,tiloOnly?}], slots[], details{}, pins[]}`
  - `team`: `{people[], rules[], matrix[], roles[], coverage[]}`
  - `connectors[]`, `notifications[]`
- **Server calls to add:** decide/undo, start world, answer question, rate or fix a run, mark a skill trusted, pause a skill, set tool level, save a skill, book a slot, pins CRUD, invite/role/remove, add backup approver, prefs, connector reconnect/sync.

## Assets
- No raster images. All art is generated SVG from `tilo-world.js` and `tilo-park.js`: city, buildings, agents and their expressions (neutral, focused, needs, delighted, talking, puzzled, sleepy), and icons.
- UI icons come from `kit.icon(name, size)`, a 20×20 viewBox with a 2px round stroke. You can swap in your codebase's icon set if it matches that weight.
- Fonts: Google Fonts, Nunito and Nunito Sans.
- Connector logos: replace the monograms with the official brand assets.

## Files
| File | What it is |
|---|---|
| `design/Tilo App.dc.html` | Shell: tokens, nav, router, loaders, toasts, menus, backdrop |
| `design/Tilo App <Page>.dc.html` | The 9 pages |
| `design/tilo-app.js` | Fixtures (`TiloApp.data`) and render kit (`TiloApp.kit`) |
| `design/tilo-world.js`, `design/tilo-park.js` | Isometric art engines: port, don't rewrite |
| `design/support.js` | Prototype runtime only; not needed in production |
| `tokens.css` | Day and night CSS variables, plus keyframes |
| `inventory.md` | Exact copy, regions, routes and local state per page |
| `PROMPTS.md` | A step-by-step build plan to paste into Claude Code |
| `screenshots/` | Scroll-through captures of every page, plus two night-mode samples |

### About the screenshots
- Named `NN-page-MM.png` in route order, with `MM` running top to bottom.
- Taken at about 910px wide, so they show the **narrow layout**: two-column grids have collapsed to one.
- For the wide layout (1440px), open the reference in a browser. The live files are the source of truth for exact values; the screenshots are for orientation.

The account menu links to "Mobile app", which isn't part of this bundle. Point it at a placeholder for now.
