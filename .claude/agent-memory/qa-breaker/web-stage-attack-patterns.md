---
name: web-stage-attack-patterns
description: Recurring apps/web stage defects and how to catch them (passive wheel console error; CSS-transform camera exposing canvas edges)
metadata:
  type: project
---

1. React `onWheel` handlers that call `e.preventDefault()` log a console error in Chromium/Edge ("Unable to preventDefault inside passive event listener invocation") on every wheel tick, because React attaches wheel as passive. The e2e console-errors spec only checks page load, so it misses this. Found in P0-08a (2026-09-25); fixed with native `{ passive: false }` listener.

2. P0-08a camera was a CSS `translate/scale` on the div holding a viewport-sized Pixi canvas. Zoom out to 0.5 or pan and the canvas edge shows: 75% of the stage is bare surface-2 at zoom 0.5, and zoom 2 upscales the bitmap (blurry). Tests only asserted the transform string. Correct fix: apply camera to a Pixi container (`app.stage.position/scale`) and redraw grid for the visible world rect.

3. Stage `onKeyDown` ignored modifiers, so Ctrl+- / Ctrl+= (browser zoom) and Alt+Arrow were preventDefaulted while the stage had focus.

4. Wheel zoom used `e.deltaY < 0 ? in : out` with a fixed 0.1 step: horizontal swipes / Shift+wheel (deltaY=0) always zoom OUT, and trackpad micro-deltas (deltaY=-2) each zoom a full step (15 ticks = 1 -> 2). Attack with `mouse.wheel(120,0)`, Shift+wheel and tiny deltas. Found P0-08a head c4c4260.

5. P0-08a head 60c0238: Pixi mirrors a CSS-transitioned camera div and stops its ticker with `setTimeout(duration + 50)`. A main-thread long task (>370 ms) right after a keypress, or a hidden tab (timers fire, rAF does not), stops the ticker before any final sync, so the canvas stays at a mid-transition frame until the next resize. Detect: snapshot canvas.toDataURL after settling, force a 2 px viewport resize and back, compare (preserveDrawingBuffer is on). Fix: final sync+render on `transitionend` / at stop, not wall-clock only.

**Why:** console errors and visual defects are automatic FAILs per root CLAUDE.md; load-only or string-only tests give false confidence.
**How to apply:** for any stage/camera change, drive a Playwright script (channel msedge, scratchpad, require the worktree's node_modules/@playwright/test by absolute path, vite on a free port with --strictPort) that wheels, drags, keys (with and without modifiers) and resizes 1920->320, collecting console errors, and compare canvas boundingBox to stage-frame boundingBox after zoom-out and pan.

6. P0-08a head 5757d28: pointer pan kept one shared `last` [x,y] for all pointers, so a two-finger touch (pinch) alternates deltas between fingers and the camera jumps by the finger distance (5 px pinch -> translate(-205px)). Attack via CDP `Input.dispatchTouchEvent` with two touchPoints in a hasTouch/isMobile context. Fix: track per-pointerId, pan only with one active pointer (or implement pinch zoom).
7. CDP `Input.dispatchTouchEvent` semantics (msedge, verified P0-08b-camera 7da095a): `touchEnd` touchPoints = the fingers that LIFT (not the ones remaining); `touchCancel` with any touchPoints is a protocol error (cancel ends all); omitting a finger from `touchMove` does NOT release it. Tests that misuse these fail or pass for the wrong reason. To lift one of two fingers: `touchEnd` with that finger only. For per-finger cancel, dispatch synthetic PointerEvents (stub `Element.prototype.setPointerCapture`, else it throws InvalidPointerId for synthetic ids).
8. Ctrl + mouse wheel notch (deltaY 100, ctrlKey) is treated as trackpad pinch at 0.01/px: one notch = 1.0 zoom (1 -> 0.5 clamp). Possible UX issue; C4 wording allows it.

7. P0-08b-camera (6f125b4): ctrl+wheel treated as trackpad pinch at 0.01/px with no per-event cap, so a real mouse Ctrl+notch (deltaY 100) zooms 1 -> 0.5 clamp in one event. Attack: keyboard.down("Control") + mouse.wheel(0,100). Rest of the Pixi-container camera held up (touch 3 fingers, freeze, long task, DPR 1.25/2, resize sweep, zero console).
CDP touch semantics: touchEnd touchPoints = fingers that LIFT; touchCancel must carry no points. A touchMove omitting a finger does NOT lift it.
8. P0-08b-camera round 3 (50c165f): ctrl cap fixed (PINCH_ZOOM_PER_PX now ZOOM_STEP/100, capped per event). PASS. Full e2e with default parallel workers is flaky on this loaded machine (freeze spec, stage-motion 40 ms "not eased" read, even pre-existing a11y/console specs time out); all green with --workers=1 --repeat-each 4. Treat parallel-only timeouts as environment, rerun serially before failing.

9. P0-08b-player (99886ee): runWorld snaps a same-actor non-move agent.* event (agent.working) at once while that actor's agent.moved is still queued. When the move finishes it writes back the older destination, so the settled canvas equals ?seq=N-1 while data-seq=N. Attack: page.route a custom /fixtures/<name>.* stream (moved, then working 200 ms later) and compare the settled canvas with ?seq=N and ?seq=N-1. Also: "moves" are a delay then a teleport, with no interpolation.

10. P0-08b-player round 3 (7f30d7c): seq-0 lead-in and lerp fixed, 83/83 e2e green serially. New: Stage.tsx calls the world seam once at Pixi init, so useWorldFixture's reducedMotion dep never reaches runWorld; toggling emulateMedia reducedMotion mid-playback keeps agents walking (~160 distinct frames/3s vs ~12). Attack: count distinct canvas toDataURL per rAF before/after page.emulateMedia. Also duplicate seq in a stream -> React duplicate-key console.error in the Trace list. A Pixi system ticker rAF loop (~90/s) runs on "/" even idle (pre-existing, canvas unchanged).

11. P0-08b-player round 4 (f03c78c): reduced-motion toggle fixed (live getter; 90 -> 13 distinct frames). Still open: duplicate seq -> React duplicate-key console.error (reducer applies dups twice); out-of-order seq makes data-seq go down. world-trace-unknown/world-determinism specs snapshot the canvas without waiting for data-seq, so they flake under parallel load (product equal when waited). page.route on **/fixtures/<name>.* serves custom streams without writing files.

12. P0-08b readiness (420cb4f): hit the init window with addInitScript + MutationObserver firing after 2 rAFs (setTimeout 0 lands before useEffect attaches listeners). Pixi init is fast even at 6x CPU throttle, so trusted Playwright input after goto rarely lands pre-ready. Synthetic pointerdown with an inactive pointerId makes setPointerCapture throw before reanchor() -> stale anchor jump; only synthetic, noted non-blocking.

8. P0-08b-player ?fixture= (0741248): the name is interpolated raw into `/fixtures/${name}...`, so `?fixture=%25` (a bare %) makes Vite answer 500 and the browser logs two "Failed to load resource" console errors, even though the in-app alert shows. Always try `%`, `%zz` on any URL built from a param; fix is encodeURIComponent. Also crowd-20 trace-list rows grow 18->19 px (CLS ~7e-5) while village-basic has none: measure layout-shift sources per fixture, not just one. Windows dev serves CROWD-20 case-insensitively (Linux would 404).

Also: stage `main` focus ring is the browser default 1px outline, clipped top/bottom by the viewport; only thin side lines show.
