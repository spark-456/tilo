---
name: web-e2e-env-noise
description: apps/web Playwright noise on this laptop - adblock360 injector console errors, timing project skipped when chromium fails, a11y timeouts under just check load
metadata:
  type: project
---

Seen 2026-09-26 reviewing P0-08b-camera flake fix.
- Console-error specs can fail with `filtering.adblock360.com ... ERR_NAME_NOT_RESOLVED` / "Manager initialization error": a host-level ad injector adds script into the served page. Not app code; check the trace's console `location.url` before failing, then rerun.
- playwright.config has a `timing` project (`dependencies: ["chromium"]`): any chromium failure makes it "did not run". Run it with `--project=timing --no-deps` to actually verify stage-camera-freeze.
- accessibility.spec (axe) times out at 30s when `just check` (19 min pytest) runs concurrently; don't run e2e alongside just check.

**Why:** these look like blocking failures but are environmental. **How to apply:** confirm via trace + rerun before calling FAIL; see [[flaky-timing-tests]].
