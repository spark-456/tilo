# Frontend reset: plan and build order

Written 2026-10-03 after a review of the running web app against `design/source/`. Parts: [art-facts.md](art-facts.md) (what the original art sets), [requirements.md](requirements.md) (FR-KIT and FR-UX, proposed), [tickets.md](tickets.md) (FE-00 to FE-19).

## Why
On 3 Oct the world stage drew placeholder diamonds and dots (`renderer.ts`: "Art port is ticket P0-08c", never started), Start was a form in a small card, S-06 to S-09 (the approve loop) were still `ComingSoon` stubs, most "built" screens were short list pages, and nothing checked a screen against its artboard. The PRD says navigation never shows "coming soon" and the world is the product. This plan puts the original art back at the centre, makes it rich enough for any task, and adds a gate so slices stop drifting from the design.

## What "right" looks like
1. **The world looks like the Metropolis designs**: same isometric language, same palette, same characters, richer.
2. **Any task can be built.** The planner describes work with parts from one published list (`config/themes/metropolis/kit.yaml`); the solver packs by their footprints; the renderer draws them; a fallback guarantees a decent building for anything unlisted.
3. **The app around it is one coherent product**: shell, HUD, real navigation, Home from the artboard, a landing page, the approve loop, no stubs.
4. **Nothing merges that does not match its artboard**, checked blind at two viewports.

## Build order

```
Wave 0 (3-4 Oct)   FE-00 decisions ─┐
                   FE-01 design gate │
                   FE-02 art bible, manifest, atlas ◄┘
Wave 1 (4-7 Oct)   FE-03 kit core ─► FE-04 common ─┐
                                  ├► FE-05 ground  ├─► STYLE LOCK (you look, 7 Oct)
                                  └► FE-06 agents ─┘
                   FE-07 shell and nav (parallel, needs FE-01 only)
Wave 2 (7-9 Oct)   FE-08 renderer integration
                   FE-09 / FE-10 / FE-11 domain packs (parallel, after style lock)
                   FE-12 Home    FE-14 approve loop (#84 #199 #200)    FE-13 world screen
                                                            ── CP3, 9 Oct: no stubs on Must routes, world on real art
Wave 3 (9-12 Oct)  FE-15 variety corpus   FE-16 tiers, LOD, perf   FE-17 landing
                   FE-18 remaining screens to design quality
                                                            ── CP4, 12 Oct: design gate
Wave 4 (12-14 Oct) FE-19 polish, density, motion; scenario fixes   ── CP5, 14 Oct
15-17 Oct          freeze, video, deck, submit
```

Critical path: FE-00 → FE-02 → FE-03 → (FE-04, FE-05, FE-06) → style lock → FE-08 → FE-15. Everything else hangs off it or runs beside it.

## Sessions to start (parallel)
Six sessions at most, each in its own worktree with its own branches, so they do not collide.

| Session | Tickets, in order | Paths it owns | Model |
| --- | --- | --- | --- |
| **K0 Kit architect** | FE-00, then FE-02 | `docs/adr/`, `docs/design/`, `config/themes/`, `contracts/theme.schema.json` | Opus |
| **K1 Kit core** | FE-03, then FE-04 | `apps/web/src/kit/` (core, common) | Sonnet |
| **K2 World dressing** | FE-05, FE-06, then FE-09 | `apps/web/src/kit/ground`, `agents`, `packs/a` | Sonnet |
| **K3 Packs** | FE-10, FE-11 | `apps/web/src/kit/packs/b`, `c` | Sonnet |
| **K4 Shell and screens** | FE-01, FE-07, FE-12, FE-14, FE-13, FE-17, FE-18, FE-19 | `apps/web/src/shell`, `screens`, `e2e`, `docs/frontend-reset/parity.md` | Sonnet |
| **K5 Stage** | FE-08, FE-16, FE-15 | `apps/web/src/world/renderer.ts`, `stage/`, `fixtures/worlds` | Sonnet |

Start now: K0 and K4 (they unblock the rest). K1 starts when FE-02's first manifest slice is merged (about a day). K2, K3 and K5 start after K1 has the primitives and the gallery. Pack sessions K3 and the A-pack part of K2 wait for the style lock.

AG-WEB keeps running its open screen tickets but under the FE-01 gate; it does not touch `kit`, `shell`, `stage` or `renderer.ts`. Review traffic goes to the orchestrator as today.

## Decisions I need from you
1. **Approve the addendum** (FR-KIT-01 to -12, FR-UX-01 to -09) so the IDs count.
2. **Lanes**: Claude sessions take the kit, shell and stage paths; Antigravity keeps screens under the gate. This changes `docs/lanes.md`, which says AG-WEB owns all of `apps/web`.
3. **Opus for FE-02 only** (the capability atlas is the deep-understanding work). Everything else Sonnet, Opus on a second failure.
4. **Navigation default**: rail of Home, Worlds, Needs you, Library, then Skills, Ledger, Team, Settings; mobile uses the PRD's five tabs. Say if you want the design's exact five (Home, Worlds, Skills, Ledger, Team) instead.
5. **Landing page copy**: calm, plain, no numbers without a source, one call to action. Tell me if you have a positioning line you want used.
6. **Style lock**: you review `/kit` and a real world around 7 Oct before the packs are built.

## Risks, said plainly
- **Art pipeline performance.** Hand-drawn SVG per building does not hit 55 fps by itself; FE-00's spike decides baking versus live drawing. If the spike fails, the hybrid in the ADR is the fallback.
- **The solver does not exist.** FR-WLD-01 (CL-PLAN) is unstarted. Until it lands the fixtures carry hand geometry and variety is proven on fixtures, not generated plans. FE-02 publishes footprints early so the solver can start.
- **Capacity.** Seven days to CP3 and 14 to submission, with 91 requirement IDs still open elsewhere. If behind: cut domain pack C, then B, then FE-17's live hero (use a static image), then FE-19. Never cut: shell, nav, renderer integration, approve loop.
- **Fixtures are scripted.** The K1 events are authored, not recorded; every replay carries the HR-4 label.
- **Scope creep in art.** Style lock and the manifest-first rule are the guard. New parts need a manifest row and a gallery tile or they do not ship.
- **Review quality.** The reset relies on blind design-critic passes. If the critic passes things you would not, tell me and the bar changes, not the process.
