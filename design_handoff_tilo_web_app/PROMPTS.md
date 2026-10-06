# Building Tilo with Claude Code: a phased plan

Put this folder at the root of your repo (or an empty one) and run Claude Code from there. Paste the prompts **one at a time**. Review the result and commit after each one. Small, checked phases translate far better than one giant prompt.

---

**0 · Orient (no code yet)**
> Read `design_handoff_tilo_web_app/README.md`, `tokens.css` and `inventory.md`, then skim `design/Tilo App.dc.html` and `design/tilo-app.js`. Serve `design/` and open `Tilo App.dc.html` to see the reference. Then propose:
> - a folder structure
> - the component list, starting with the core components table
> - how you'll port `tilo-world.js` and `tilo-park.js` as TypeScript modules
> - TypeScript types for every fixture in `tilo-app.js`
>
> Don't write code until I approve.

**1 · Foundation**
> Set up the app (React + TS, or our existing stack). Add `tokens.css` as global CSS variables, with night mode on `[data-time="night"]`. Load the Nunito and Nunito Sans fonts. Port `tilo-app.js` into typed fixtures behind an `api/` layer that returns promises. Port the two art engines and the memoised kit as modules.

**2 · Core components**
> Build the core components from the README exactly as specified: buttons (primary, secondary, needs), segmented control (plain and sliding thumb), switch, status chip, summary pill, KPI tile, list row, agent/art tile, card, page sheet, toast, popover/menu and modal scrim. Add a `/dev/components` page that shows each one in day and night.

**3 · Shell**
> Build the AppShell:
> - city backdrop: cached, animated only on Home, paused with `--veil` elsewhere
> - fixed glass nav with tabs, needs badge, day/night, bell popover and account menu
> - router with the hash routes and the `AppCtx` contract
> - page transition and progress-bar timings
> - world loader and boot splash
> - toast with Undo
> - an app store holding `dec`, `added` and `prefs`, with `decide(key)` as the single approval path

**4–12 · One page per prompt**
> Build the **{Page}** page to match `design/Tilo App {Page}.dc.html` pixel for pixel. Use the README section for {Page} and its entry in `inventory.md` for exact copy. Reuse the core components and read everything through `AppCtx` and `api/`. When you're done, list anything you couldn't match.

Suggested order: Home → Worlds → World → Ledger → Skills → Agenda → Team → Connectors → Profile.

**13 · Wire-up pass**
> Check every cross-page link and every effect of `decide`, using the README's "Cross-page links" list and the Approve row. Approving Laptop Depot must update the nav badge, notifications, Home, Worlds, World, the Ledger KPIs, Activity and the chart, and the Agenda pin. Undo must revert all of them.

**14 · Polish**
> Check day and night on every page. Check reduced motion and `motion: still`, focus rings, Escape to close, responsive collapse below 1100/1080px, and empty states. Profile the city backdrop and keep only cars and walkers animated.

---

## Tips for the best match
- Ask Claude Code to compare its build with the reference **side by side** after each page: same width, same theme.
- When something drifts, point it at the exact element's inline style in the `.dc.html` file. Every value lives there.
- Keep the copy exactly as written. It's final. `inventory.md` has every static string.
