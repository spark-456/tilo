# Tilo · Park City app

Open **Tilo App.dc.html** for the full web app. Open **Tilo iOS Native.dc.html** for the native iPhone concept (the earlier **Tilo Mobile.dc.html** stays for reference).

## Structure
- `Tilo App.dc.html` is the shell. It holds the theme tokens (CSS variables, day and night), the top nav, the router, page transitions, the world loader, toasts, the account menu, notifications and the shared city backdrop.
- Pages are `Tilo App <Page>.dc.html`: Home, Worlds, World (detail), Skills, Ledger, Agenda, Team, Profile, Connectors. Each one is a single component that gets one `app` prop.
- `tilo-app.js` has all the fixture data (`TiloApp.data`) and the render kit (`TiloApp.kit(h)`): icons, agents, buildings and world maps. Results are memoised, so each one is drawn only once.
- `tilo-world.js` and `tilo-park.js` are the isometric engines. Static art is drawn once as SVG images. Only cars and walkers are live layers.

## The `app` prop (shell → page contract)
`{ page, params, go(page, params), dec, decide(key), needsLeft, added, addWorld(mode, query), toast(msg, actionLabel?, action?), time, night, motion, setPref(key, value), prefs, vw, vh, pins }`

Cross-page links: Ledger “Add a backup” opens `go('team', { focus: 'share' })`. Picking a backup in Team calls `setPref('backup', id)`, and the Ledger wait times update. Ledger cost-per-run cards open `go('skills', { id })`.

Routes: `#home`, `#worlds`, `#world/<id>`, `#skills`, `#ledger`, `#agenda`, `#team`, `#profile`, `#connectors`. In the console, `window.tiloNavigate(page, params)` moves between them.

## Loading and motion
- Boot: a splash shows while the city builds, then fades out. Page files are prefetched in the background.
- Page change: a 3px progress bar runs under the nav, and the content fades and lifts in over about 0.4s.
- Opening a world: a loader card shows 3 steps with a progress bar, about 1.2s for cities and less for small jobs.
- The city only animates on Home. On every other page it's paused, which saves CPU and GPU. `motion: still` turns animation off everywhere, and so does the system's reduce-motion setting.
- Only the nav and the Home panels blur what's behind them. Page sheets are solid, so they're cheap to draw.

## Tokens
These are defined once in the shell's `<helmet>` as `:root` and `[data-time="night"]` variables:
- Surfaces: `--sheet --card --sunk --pop --field --btn2`
- Text: `--ink --ink2 --ink3`
- Lines: `--line --line2`
- Brand: `--hero --heroInk --heroSoft`
- Status: `--run --sch --ok --amber --red` (plus their `Soft`, `Ink` and `Tile` variants)

- Extra tints: `--blueSoft --blueInk --pinkSoft --orangeSoft --greenSoft` and the pinboard `--cork --corkDot --corkFrame`

Type: Nunito 900 for headings, Nunito Sans 600–800 for UI.

## Pages merged from the v3 sheets
- Skills: inline teach flow (record, guided, describe, upload → Tilo’s version with “Ask me first” steps → try run that stops to ask → save), questions agents saved up, rate recent runs with fixes, ready-for-review → trusted, who helped, learned-skills library with cost per run and pause, and global tool access.
- Ledger: donut breakdown, cost per run sparklines, approval wait times, what Tilo gave back, and an Activity feed (spend, approvals, gates, shared, savings) with inline approve.
- Agenda: Team and My boards as a pinboard or grouped list, Tilo suggestions you accept or dismiss, weekend toggle, Tilo-joins badges, and an event panel with brief, notes, follow-ups and per-meeting switches.
- Team: there was no v3 Team sheet, so it gained the team-side pieces of the others: approval coverage with backup approvers, a Helped Tilo column and per-person details.

## Native iOS concept
`Tilo iOS Native.dc.html` uses system type, large titles, Liquid Glass bars and a floating tab bar with a separate Ask button, sheets with detents, swipe actions, a side-button Face ID sign-off, a Live Activity, an actionable lock-screen notification, Dynamic Island and interactive widgets. Approving on any screen updates the others.

## Building it for real
- Swap the fixtures in `tilo-app.js` for API calls. The shapes are already the data model: worlds, decisions, skills, ledger, agenda, team, connectors and notifications.
- Approvals go through `decide(key)`. That's the server call, and it's also what the phone signs with Face ID.
- Connector tiles use monograms. Replace them with the official logos.
- The mobile app should be native (SwiftUI) and use the same API. Agents run in the cloud, never on the device (see the footer in 1i of the native canvas).
