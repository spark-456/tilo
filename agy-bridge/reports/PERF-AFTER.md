# CX-PERF-1 after

Measured 16 Oct 2026 IST against `https://essential-wares-510320-f0.web.app/` and the focused `CX-PERF-1` client test.

## Live site

| Surface | Desktop / 4x CPU trace | Lighthouse | Result |
| --- | --- | --- | --- |
| Public Home | Not available | Not available | The browser supplied for this run has no Chrome DevTools Performance panel or Lighthouse runner. CPU throttling was unavailable. |
| Product Home | Not measured | Not measured | `Explore a demo session` and `Continue with Google` were disabled on the live page; its input and Try it button were disabled too. |
| Worlds | Not measured | Not measured | The disabled live entry points above prevented reaching this product route. |
| World | Not measured | Not measured | The disabled live entry points above prevented reaching a world route. |
| Skills | Not measured | Not measured | The disabled live entry points above prevented reaching this product route. |
| Chat | Not measured | Not measured | The disabled live entry points above prevented reaching this product route. |

No live trace, Lighthouse score, frame rate, INP, or long-task duration was collected. No values are inferred for those measures.

## Confirmed code-level polling result

- A subscription makes no request while the tab is hidden; becoming visible triggers an immediate request.
- Successful empty responses back off from 2,000 ms to 4,000 ms, 8,000 ms, then a 10,000 ms cap. A newly received event resets the delay to the normal 1,000 ms active-run cadence.
- Terminal-world stopping and error backoff remain in place.
- The focused test covers the hidden-tab pause, immediate resume, and 2,000 ms idle backoff. This is deterministic client behavior, not a live-site timing measurement.
