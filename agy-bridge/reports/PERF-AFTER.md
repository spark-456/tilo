# CX-PERF-1 after the polling fix

Measured 16 Oct 2026 IST from a local **production build** of `cx/PERF-1` (`vite build` then `vite preview` at `127.0.0.1:5683`) with Chrome 156, 1440 × 900, and the same trace script and Lighthouse desktop preset as [PERF-BEFORE.md](PERF-BEFORE.md). These are diagnostic measurements, **not a controlled live before/after comparison**: the local host, code base, and machine load differ from the deployed site. The branch has not been deployed.

| Surface | Desktop trace | 4× CPU trace | Lighthouse desktop |
| --- | --- | --- | --- |
| Public Home `/` | 2 tasks ≥100 ms, maximum 681 ms; 106 scroll frames, 4 gaps >50 ms, maximum gap 1,302 ms | 28 tasks ≥100 ms, maximum 6,965 ms; 23 scroll frames, 3 gaps >50 ms, maximum gap 7,524 ms | **53**; FCP 1.19 s, LCP 2.30 s, TBT 747 ms, CLS 0.001 |
| Product Home, Worlds, a World, Skills, Chat | Not measured: the live authenticated product routes were inaccessible to this browser run | Not measured | Not measured |

The production preview did **not** demonstrate the targets: desktop Lighthouse remained below 85 and traces contained long tasks and scroll gaps. These numbers cannot be used to claim a regression or improvement against the live site because the environments differ. The trace observer spans startup and scroll, so idle-only long tasks were not separately measured. INP was not measured. A development-server attempt was discarded because Vite's transform cost distorted the result; the first 4× navigation timed out.

Recorded artifacts: `CX-PERF-1/prod-home-desktop.json.gz`, `prod-home-4x.json.gz`, their `.metrics.json` summaries, and `prod-home-lighthouse-desktop.json.xz`.

The focused `CX-PERF-1` test confirms the code change: polling stops while hidden, resumes immediately when visible, and backs off on empty responses from 2,000 ms to 4,000 ms, 8,000 ms, then a 10,000 ms cap. A new event restores the 1,000 ms active-run cadence; terminal-world stopping remains intact. This fixes the confirmed idle request loop but does not establish smooth rendering on the measured surfaces.
