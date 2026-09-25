---
name: web-stage-attack-patterns
description: Recurring apps/web stage defects and how to catch them (passive wheel console error; CSS-transform camera exposing canvas edges)
metadata:
  type: project
---

1. React `onWheel` handlers that call `e.preventDefault()` log a console error in Chromium/Edge ("Unable to preventDefault inside passive event listener invocation") on every wheel tick, because React attaches wheel as passive. The e2e console-errors spec only checks page load, so it misses this. Found in P0-08a (2026-09-25); fixed with native `{ passive: false }` listener.

2. P0-08a camera was a CSS `translate/scale` on the div holding a viewport-sized Pixi canvas. Zoom out to 0.5 or pan and the canvas edge shows: 75% of the stage is bare surface-2 at zoom 0.5, and zoom 2 upscales the bitmap (blurry). Tests only asserted the transform string. Correct fix: apply camera to a Pixi container (`app.stage.position/scale`) and redraw grid for the visible world rect.

3. Stage `onKeyDown` ignored modifiers, so Ctrl+- / Ctrl+= (browser zoom) and Alt+Arrow were preventDefaulted while the stage had focus.

**Why:** console errors and visual defects are automatic FAILs per root CLAUDE.md; load-only or string-only tests give false confidence.
**How to apply:** for any stage/camera change, drive a Playwright script (channel msedge, scratchpad, require the worktree's node_modules/@playwright/test by absolute path, vite on a free port with --strictPort) that wheels, drags, keys (with and without modifiers) and resizes 1920->320, collecting console errors, and compare canvas boundingBox to stage-frame boundingBox after zoom-out and pan.
