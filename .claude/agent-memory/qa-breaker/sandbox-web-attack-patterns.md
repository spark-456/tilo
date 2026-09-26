---
name: sandbox-web-attack-patterns
description: P8-07 sandbox-web probes that found defects - NaN/Infinity/1e308 quote 500s, unlabelled seed values, fake hidden-text techniques
metadata:
  type: project
---
Found in P8-07 round 1 (2026-09-25):
- Starlette `request.json()` accepts NaN/Infinity; `isinstance(v,(int,float))` passes them; JSONResponse then 500s. 1e308*rate -> inf -> 500. Huge ints (10**400) give 400-digit quotes.
- Generic value renderer dropped dict keys, so pricing numbers (monthly/annual/seats) appeared unlabelled; quote page rendered "True" and no <form>.
- CSS hidden techniques put payload in a `data-hidden` attribute of an empty div, so the technique hides nothing - check payload is element TEXT under the hiding style.
- Hand-written lines (tests included) ran 571 vs 400 cap: count with `git diff --numstat` excluding seed/ and uv.lock.
Round 2: fix used `math.isfinite(value)` before the range check -> a 400-digit JSON int raises OverflowError -> 500 (range check first, or compare ints before isfinite). The new HTML <form method=post> sends urlencoded but endpoint only parses JSON -> 422 for every browser submit; always submit the rendered form as a browser would.

**Why:** these are the likely regressions on later rounds. **How to apply:** re-run the same probes on any sandbox-web change. See [[eval-harness-recording-validation]].
