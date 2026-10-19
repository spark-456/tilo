import type { Page } from "@playwright/test";

// Shared expectations for the P0-08b-player fixture-mode / playback acceptance tests. PRD
// 9.6/9.7/9.4 leave the exact URL params and markup unspecified, so test-writer picks this one
// here (same convention as apps/web/e2e/support/assertions.ts for P0-08a), reusing the camera
// ticket's stage-frame seam (data-camera-x/-y/-zoom, a PixiJS world container) and App.tsx's
// existing `?display=stage` param (see apps/web/src/App.tsx):
//
//   URL params (on the stage address, STAGE_PATH = /world/w_village_basic/stage; WEB-CUTOVER moved the
//   stage there, "/" is the Park Home now):
//     ?fixture=<name>   Turns on fixture mode and plays a recorded stream into the world.
//                        `village-basic` (and `village-basic-unknown`, this ticket's own extra
//                        HR-5 fixture) are served straight from contracts/ /
//                        apps/web/fixtures/ (see loadFixture() below for the exact files each
//                        name maps to). Any other name is served from
//                        apps/web/fixtures/<name>.layout.json + apps/web/fixtures/<name>.events.jsonl
//                        (P9's crowd-20 fixture).
//     ?seq=N            Jumps straight to the state at seq N, no animation (a static frame).
//                        Without it, playback plays from the start following the recorded `ts`
//                        gaps at 1x.
//     ?speed=N           N != 1 changes the pace (clamped to 0.1..1000); a visible
//                        "Replay at N× speed" badge shows while it applies (absent at 1x, i.e.
//                        without this param or with ?speed=1).
//     ?display=stage     Existing App.tsx param (1920x1080 presenter layout).
//
//   DOM (data-testid, matching apps/web/e2e/support/assertions.ts's existing convention):
//     [data-testid="stage-frame"]  already exists (P0-08a); this ticket adds a `data-seq`
//                                  attribute to it, holding the highest seq applied to the world
//                                  state (a plain numeric string, e.g. `data-seq="12"`; "0"
//                                  before the first event is applied).
//     [data-testid="trace-list"]  the Trace lens (PRD 9.6): one row per *applied* event, known
//                                  or unknown (HR-5), in seq order.
//     [data-testid="trace-row"]   one row inside trace-list, carrying `data-seq` and
//                                  `data-event-type` attributes and visible text that includes
//                                  both the seq and the type.
//     [data-testid="speed-badge"] the HR-6 "Replay at N× speed" badge (role=status); absent (not just hidden) at 1x.
//     [data-testid="fixture-replay-banner"] the HR-4/BQ-07 permanent label containing the text
//                                  "Fixture replay", with role="status" or inside a landmark
//                                  region with an accessible name. Never removed, hidden by CSS
//                                  or covered by another element — see fixtureReplayLabel() below.

export const FIXTURE_QUERY = {
  villageBasic: "village-basic",
  villageBasicUnknown: "village-basic-unknown",
  crowd20: "crowd-20",
} as const;

/** The live stage (S-04) of the fixture world: `/world/:id` is the Park World overview since WEB-CUTOVER. */
export const STAGE_PATH = "/world/w_village_basic/stage";

/** A page whose stage has no world to draw: the decorative bare iso grid. The old S-01 landing and S-02 were such
 * pages; both are gone (WEB-CUTOVER, OLD-UI-OUT wave 1), so it is the stage address of a world that has no run. */
export const BARE_STAGE_PATH = "/world/w_no_run/stage";

export function fixtureUrl(
  name: string,
  extra: Record<string, string | number> = {},
  base: string = STAGE_PATH,
): string {
  const params = new URLSearchParams({ fixture: name });
  for (const [k, v] of Object.entries(extra)) params.set(k, String(v));
  return `${base}?${params.toString()}`;
}

/** The stage-frame element, whose `data-seq` attribute tracks the highest applied seq. */
export function stageFrame(page: Page) {
  return page.getByTestId("stage-frame");
}

export function stageCanvas(page: Page) {
  return stageFrame(page).locator("canvas");
}

export async function stageSeq(page: Page): Promise<number> {
  const raw = await stageFrame(page).getAttribute("data-seq");
  return raw === null ? Number.NaN : Number(raw);
}

/** A base64 PNG-ish snapshot of the canvas' current pixels, for pixel-identical comparisons
 * (same pattern as apps/web/e2e/stage-idle.spec.ts / stage-settle.spec.ts). */
export async function canvasSnapshot(page: Page): Promise<string> {
  return stageCanvas(page).evaluate((el: HTMLCanvasElement) => el.toDataURL());
}

export function traceList(page: Page) {
  return page.getByTestId("trace-list");
}

export function traceRows(page: Page) {
  return traceList(page).getByTestId("trace-row");
}

export function speedBadge(page: Page) {
  return page.getByTestId("speed-badge");
}

/** How many distinct colours the canvas holds: a bare iso grid has a handful, drawn art hundreds. */
export async function canvasColours(page: Page): Promise<number> {
  return stageCanvas(page).evaluate(async (el: HTMLCanvasElement) => {
    const img = new Image();
    img.src = el.toDataURL();
    await img.decode();
    const c = document.createElement("canvas");
    [c.width, c.height] = [img.width, img.height];
    const ctx = c.getContext("2d");
    if (!ctx) return 0;
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, c.width, c.height).data;
    const seen = new Set<number>();
    for (let i = 0; i < d.length; i += 4) {
      seen.add(((d[i] ?? 0) << 16) | ((d[i + 1] ?? 0) << 8) | (d[i + 2] ?? 0));
    }
    return seen.size;
  });
}

/** HR-4/BQ-07: the permanent "Fixture replay" label, exposed to assistive tech. */
export function fixtureReplayLabel(page: Page) {
  return page.getByTestId("fixture-replay-banner");
}
