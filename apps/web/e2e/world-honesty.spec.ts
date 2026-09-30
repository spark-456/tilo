import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";
import { canvasSnapshot, fixtureUrl, stageCanvas, stageSeq } from "./support/world";

// P7 / HR-2 ("No idle animation implies work that is not happening"): "after the last event's
// animations finish the canvas is pixel-identical over 3 s and nothing renders; nothing moves
// before the first event either." Same canvas.toDataURL() comparison apps/web/e2e/stage-idle.spec.ts
// already uses for the same rule on the bare iso grid.

test.use({ viewport: DESKTOP });

test("HR-2 honesty: once the run finishes, the canvas is pixel-identical for at least 3s and nothing renders", async ({
  page,
}) => {
  await page.goto(fixtureUrl("village-basic", { speed: 1000 }));
  await expect(stageCanvas(page)).toBeVisible();
  await expect.poll(() => stageSeq(page), { timeout: 20_000 }).toBe(44);

  // HR-3 caps any in-flight movement at 2s; give it comfortable room to actually settle.
  await page.waitForTimeout(2_500);
  const first = await canvasSnapshot(page);
  await page.waitForTimeout(3_000);
  const second = await canvasSnapshot(page);

  expect(
    second,
    "the canvas' pixels changed 3s after the last event settled, with no new event — forbidden idle animation (HR-2)",
  ).toBe(first);
});

test("HR-2 honesty: nothing moves before the first event lands — the world is static while the fixture data is still loading", async ({
  page,
}) => {
  // Delay whichever request(s) fetch the fixture's layout/stream so there is a real window
  // before the first event can possibly be applied. Matches both this ticket's file-naming
  // conventions (village_basic.json from contracts/, village-basic.jsonl) without pinning down
  // the exact endpoint the builder wires up.
  await page.route(/village[-_]basic/i, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 800));
    await route.continue();
  });

  await page.goto(fixtureUrl("village-basic"));
  const canvas = stageCanvas(page);
  await expect(canvas).toBeVisible();

  // Sample twice while the (delayed) fixture data is still in flight.
  await page.waitForTimeout(200);
  const seqDuringLoad1 = await stageSeq(page);
  const snapshot1 = await canvasSnapshot(page);
  await page.waitForTimeout(400);
  const seqDuringLoad2 = await stageSeq(page);
  const snapshot2 = await canvasSnapshot(page);

  expect(seqDuringLoad1, "an event was applied before the fixture stream had even loaded").toBe(0);
  expect(seqDuringLoad2, "an event was applied before the fixture stream had even loaded").toBe(0);
  expect(
    snapshot2,
    "the canvas changed while no event had been applied yet — idle animation before the first event",
  ).toBe(snapshot1);

  // Sanity: once the delayed data does arrive, playback does start (proves the delay above was
  // real and this was not just an already-finished page).
  await expect.poll(() => stageSeq(page), { timeout: 10_000 }).toBeGreaterThan(0);
});
