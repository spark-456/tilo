---
name: fixture-player-attack-patterns
description: P0-08b fixture player recurring defects - bad ?fixture= names log console.error, seq-order handling, camera e2e flakes under load
metadata:
  type: project
---
Recurring across P0-08b-player rounds 3-5 (2026-09-26):
- ?fixture=nope / %20 / ../x : Vite SPA fallback returns index.html, JSON.parse throws, useWorldFixture logs console.error and the UI shows no error. Still open in round 5.
- ?fixture= (empty) shows the "Fixture replay" banner but loads nothing.
- Duplicate or out-of-order seq was fixed in round 5 (applyEvent, store.apply and runWorld.applyOne all drop seq <= state.seq).
- stage-camera*.spec.ts wheel and touch tests flake on a loaded machine (different ones fail each run, even with workers=1). These are camera-ticket specs, not the player's.
**Why:** so later rounds check these first.
**How to apply:** route fake fixtures with page.route `**/fixtures/<name>.*`. Never pipe a Playwright script through `tail`, because it buffers all output. `locator.textContent()` on a missing element waits 30 s; use allTextContents().
