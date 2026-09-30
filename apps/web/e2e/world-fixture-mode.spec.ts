import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";
import { canvasSnapshot, fixtureUrl, stageCanvas, stageSeq } from "./support/world";

// P1: fixture mode loads contracts/fixtures/layout/valid/village_basic.json and
// contracts/fixtures/streams/village-basic.jsonl (imported from contracts/, not copied) and
// plays the stream into the world on the stage's PixiJS world container (the camera sub-ticket's
// seam). The stage frame exposes data-seq = the highest seq applied to the world state.
//
// The village-basic stream's recorded `ts` spans ~141s (09:30:02.000Z to 09:32:23.500Z); playing
// that out at 1x inside a test would be impractical, so the "reaches the final event" case below
// uses `?speed` (this ticket's own P8/HR-6 time-compression param) purely as a test-timing
// convenience — P8's own acceptance test (world-playback.spec.ts) is what actually verifies
// ?speed's behaviour (the visible "N×" badge, etc.).

const VILLAGE_BASIC_LAST_SEQ = 44;

test.use({ viewport: DESKTOP });

test("FR-WLD-04 fixture mode: ?fixture=village-basic starts data-seq at 0 before any event is applied", async ({
  page,
}) => {
  await page.goto(fixtureUrl("village-basic", { speed: 1000 }));
  // data-seq must exist and start at 0 — asserted as early as possible, before the first event's
  // effect has necessarily landed (HR-2: "nothing moves before the first event either", checked
  // fully in world-honesty.spec.ts).
  const raw = await page.getByTestId("stage-frame").getAttribute("data-seq");
  expect(raw, 'stage-frame must carry a data-seq attribute, "0" before playback starts').toBe("0");
});

test("FR-WLD-04 fixture mode: the village-basic stream plays into the world, ending at seq 44", async ({
  page,
}) => {
  await page.goto(fixtureUrl("village-basic", { speed: 1000 }));
  const canvas = stageCanvas(page);
  await expect(canvas).toBeVisible();
  const before = await canvasSnapshot(page);

  await expect
    .poll(async () => stageSeq(page), {
      message: "data-seq never reached the village-basic stream's final seq (44)",
      timeout: 20_000,
    })
    .toBe(VILLAGE_BASIC_LAST_SEQ);

  const after = await canvasSnapshot(page);
  expect(
    after,
    "the canvas pixels never changed while 44 events played — nothing was drawn on the world container",
  ).not.toBe(before);
});

test("FR-WLD-04 fixture mode: playback starts promptly — data-seq advances past 0 within a couple of seconds", async ({
  page,
}) => {
  await page.goto(fixtureUrl("village-basic"));
  await expect.poll(async () => stageSeq(page), { timeout: 5_000 }).toBeGreaterThan(0);
});
