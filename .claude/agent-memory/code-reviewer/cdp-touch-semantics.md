---
name: cdp-touch-semantics
description: CDP Input.dispatchTouchEvent semantics that e2e touch tests get wrong (touchEnd lists the ENDING points; touchCancel takes no points)
metadata:
  type: project
---

Probed in Edge (P0-08b-camera review, 2026-09-25): `Input.dispatchTouchEvent` touchEnd with
touchPoints [p] releases p (pointerup for p), it does NOT mean "p remains". A later touchMove
with p's id then fires a fresh pointerdown. touchCancel with any points throws "TouchCancel
must not have any touch points" (it cancels all).

**Why:** stage-camera-touch.spec.ts lift/cancel tests failed for test-side reasons, not code.
**How to apply:** when a touch e2e fails, probe the pointer event log with a scratch config
(testDir in scratchpad, reuseExistingServer on the assigned port) before blaming the builder.
Single-finger cancel needs a synthetic PointerEvent("pointercancel") via page.evaluate.
Also: full parallel e2e runs on this machine can flake with net::ERR_NETWORK_CHANGED and the
freeze spec timing out; rerun with --workers=1 before calling them real.
Round 2 (2026-09-25): freeze spec failed 3/4 default parallel runs yet passed 8/8 isolated
at 8 workers and in a serial full run; its trace showed data-camera-x reach 48, so the cause
was load, not the app. Unzip trace.zip and grep data-camera-* to tell the two apart.
Round 3: freeze spec again failed 2/2 default parallel runs; trace showed page.waitForTimeout(600)
issued while the page was frozen hanging ~16 s (test-harness design, not app); serial 53/53 green.
