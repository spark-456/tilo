---
name: sandbox-web-p8-07
description: P8-07 Sandbox Web r3 PASS (43c1ddc) after r1/r2 FAIL; technique_ok now precise for RED-01..08; open polish (HEAD on healthz, CSP extras, ZW/bidi check)
metadata:
  type: project
---

P8-07 (services/sandbox-web). r1 FAIL at d8d7da6, r2 FAIL at 9ec69d3, r3 PASS at 43c1ddc.

r1: a CSS-unaware test helper (`_sandbox_web_testlib.visible_text`) pushed the builder to hide E-RED payloads in a `data-hidden` attribute, so E-RED passed vacuously; own CSP `default-src 'self'` blocked inline `style=`; quote accepted NaN/Infinity/1e308 -> 500.
r2: app.py fixed, but to fit the 400-line cap the builder rewrote `technique_ok` to "payload in html and not in visible_text", dropping per-technique checks. Also `math.isfinite(10**400)` -> OverflowError -> 500.
r3: technique_ok finds the carrier element and checks its class rule's declaration; negative test feeds r1 markup. Quote range-checks first; form posts accepted. Diff 398/400.
Still open (non-blocking): zero-width/bidi check (RED-09/10) still passes attribute-only markup (test-writer's original design); HEAD 405 on /healthz and /manifest.json; no frame-ancestors/base-uri/form-action or nosniff; no body size cap; `<img src="">`; SEED_DIR via parents[2] breaks in a non-editable wheel (Dockerfile ticket).

**Why:** red-team fixtures that never deliver the injection give false assurance on the prompt-injection gate; size-cap pressure makes builders "consolidate" tests into weaker ones.
**How to apply:** on every fix round, diff tests against the tests/<ID> commit and feed the previous round's bad output through the new test helper; it must fail. For JSON number inputs check NaN, inf, 1e308 and huge ints (a plain `0 <= v <= MAX` check covers all four).
