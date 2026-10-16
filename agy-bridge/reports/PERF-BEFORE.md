# CX-PERF-1 baseline

Measured 16 Oct 2026 IST on the [live site](https://essential-wares-510320-f0.web.app/) with Chrome 156 at 1440 × 900. The trace script uses the Chrome DevTools Protocol Performance trace, a Long Tasks observer, and a three-second automated scroll. CPU rate 4 means Chrome's fourfold throttle. Lighthouse 13.5.0 used its desktop preset.

| Surface | Desktop trace | 4× CPU trace | Lighthouse desktop |
| --- | --- | --- | --- |
| Public Home `/` | 4 tasks ≥100 ms, maximum 212 ms; 254 scroll frames, 1 gap >50 ms, maximum gap 153 ms | 11 tasks ≥100 ms, maximum 2,178 ms; 26 scroll frames, 9 gaps >50 ms, maximum gap 1,354 ms | **77**; FCP 1.88 s, LCP 2.38 s, TBT 45 ms, CLS 0.006 |
| Product Home, Worlds, a World, Skills, Chat | Not measured: the unauthenticated live entry points were disabled in this browser run | Not measured | Not measured |

The 4× Lighthouse run produced **no score**: `NO_TTI_CPU_IDLE_PERIOD` after the page exceeded the load time limit. It reported FCP 4.51 s and LCP 6.22 s, but TBT was unavailable. The desktop Lighthouse score is below the 85 target. The trace observer runs from navigation through the scroll; its task counts do not isolate idle work. INP requires a real interaction and was not measured.

Recorded artifacts: `CX-PERF-1/live-home-desktop.json.gz`, `live-home-4x.json.gz`, their `.metrics.json` summaries, and the two `live-home-lighthouse*.json.xz` reports. The trace script is `apps/web/perf-measure.mjs`. The trace starts before navigation, waits one second after DOM content is loaded, scrolls for three seconds, then waits one second; it records frame intervals from `requestAnimationFrame`.

Code baseline: `HttpClient.subscribeEvents` issued another `/worlds/{id}/events` request after every successful empty response at its 1,000 ms default interval, including while the tab was hidden. The focused regression test reproduced the hidden-tab requests before the polling fix.
