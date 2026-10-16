# CX-PERF-1 baseline

Measured 16 Oct 2026 IST against `https://essential-wares-510320-f0.web.app/`.

## Live site

| Surface | Desktop / 4x CPU trace | Lighthouse | Result |
| --- | --- | --- | --- |
| Public Home | Not available | Not available | Landing page loaded, but the browser supplied for this run has no Chrome DevTools Performance panel or Lighthouse runner. CPU throttling was unavailable. |
| Product Home | Not measured | Not measured | `Explore a demo session` and `Continue with Google` were disabled on the live page; its input and Try it button were disabled too. |
| Worlds | Not measured | Not measured | The disabled live entry points above prevented reaching this product route. |
| World | Not measured | Not measured | The disabled live entry points above prevented reaching a world route. |
| Skills | Not measured | Not measured | The disabled live entry points above prevented reaching this product route. |
| Chat | Not measured | Not measured | The disabled live entry points above prevented reaching this product route. |

No live trace, Lighthouse score, frame rate, INP, or long-task duration was collected. No values are inferred for those measures.

## Confirmed code-level polling baseline

- `HttpClient` defaults to a 1,000 ms `pollMs` (`apps/web/src/api/http.ts`).
- `subscribeEvents` scheduled another request after every successful response, including an empty response: one `/worlds/{id}/events` request per second for each open subscription while idle.
- The focused regression test reproduced two requests within 1,000 ms with the tab hidden before the fix.
- A completed or failed world already stops polling when its terminal event is received.
