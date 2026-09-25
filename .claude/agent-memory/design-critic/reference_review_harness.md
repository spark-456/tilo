---
name: review-harness-notes
description: How to screenshot/audit apps/web with Playwright from scratchpad, and known noise (Edge injections, cold-Vite CLS, artboard fetch errors)
metadata:
  type: reference
---

- Run Playwright from a scratchpad .cjs via `require("<worktree>/apps/web/node_modules/@playwright/test")` (+ `@axe-core/playwright`), channel msedge.
- Port 5391 may be taken by a parallel reviewer; start vite with `--port <random> --strictPort`.
- Local Edge injects a `SETTINGS-MANAGER` element and a blue shield widget at right edge; ignore both in focus order and screenshots.
- First load after a cold Vite start once showed CLS 0.0002 that did not reproduce on 3 fresh contexts; re-measure before failing on tiny CLS. At 7dca6a9 it DID reproduce 3/3 in dev and in `vite build`+preview: @fontsource swap reflows right-rail text (fallback→Nunito Sans metrics). Log sources via layout-shift entry `sources`; e2e suite had no CLS test.
- `Tilo World Player.dc.html` opened as file:// shows "Could not load the world: Failed to fetch" (fetches worlds/*.json); its frame chrome is still usable for comparison. `Tilo 2 Balanced Refined` is a wide deck; the 390 viewport crops it.
- P0-08a (2026-09-25): iso grid in Stage.tsx bounded |i|,|j| instead of |i-j|,|i+j| and left blank corners; check grid fills the stage in future stage reviews. [[design-critic-stage-checks]]
