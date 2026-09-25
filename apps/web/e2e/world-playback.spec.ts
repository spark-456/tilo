import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";
import { canvasSnapshot, fixtureUrl, speedBadge, stageCanvas, stageSeq } from "./support/world";

// P8 / HR-6: "playback follows the recorded ts gaps at 1x by default; ?speed=N (N>1) compresses
// time and a visible 'N×' speed badge is shown while compression applies (absent at 1x);
// ?seq=N jumps straight to the state at seq N with no animation (static frame, data-seq = N)."
//
// village-basic's seq 1 -> seq 2 gap is exactly 2s (09:30:02.000Z -> 09:30:04.000Z), used below
// as a fast, concrete proxy for "follows the recorded ts gaps" without waiting out the whole
// ~141s stream.

test.use({ viewport: DESKTOP });

async function waitForSeq(page: import("@playwright/test").Page, seq: number, timeout = 15_000) {
  await expect.poll(() => stageSeq(page), { timeout, intervals: [25] }).toBe(seq);
}

test("HR-6 playback: at 1x (default), seq 1 -> seq 2 takes about the recorded 2s gap", async ({
  page,
}) => {
  await page.goto(fixtureUrl("village-basic"));
  await expect(stageCanvas(page)).toBeVisible();
  await waitForSeq(page, 1);
  const t0 = Date.now();
  await waitForSeq(page, 2, 10_000);
  const elapsedMs = Date.now() - t0;
  expect(elapsedMs, `seq 1->2 took ${elapsedMs}ms, expected ~2000ms at 1x`).toBeGreaterThan(1400);
  expect(elapsedMs, `seq 1->2 took ${elapsedMs}ms, expected ~2000ms at 1x`).toBeLessThan(3200);
});

test("HR-6 playback: no speed badge at 1x (?speed absent)", async ({ page }) => {
  await page.goto(fixtureUrl("village-basic"));
  await expect(stageCanvas(page)).toBeVisible();
  await waitForSeq(page, 1);
  await expect(speedBadge(page)).toHaveCount(0);
});

test("HR-6 playback: ?speed=10 compresses the seq 1 -> seq 2 gap well below 2s and shows a '10×' badge", async ({
  page,
}) => {
  await page.goto(fixtureUrl("village-basic", { speed: 10 }));
  await expect(stageCanvas(page)).toBeVisible();
  await expect(speedBadge(page)).toBeVisible();
  await expect(speedBadge(page)).toContainText("10×");

  await waitForSeq(page, 1);
  const t0 = Date.now();
  await waitForSeq(page, 2, 5_000);
  const elapsedMs = Date.now() - t0;
  expect(
    elapsedMs,
    `?speed=10 should compress the 2000ms gap to ~200ms, took ${elapsedMs}ms`,
  ).toBeLessThan(1000);
});

test("HR-6 playback: ?seq=N jumps straight to N with no animation (a static frame)", async ({
  page,
}) => {
  await page.goto(fixtureUrl("village-basic", { seq: 20 }));
  await expect(stageCanvas(page)).toBeVisible();
  await expect(page.getByTestId("stage-frame")).toHaveAttribute("data-seq", "20");

  const first = await canvasSnapshot(page);
  await page.waitForTimeout(600); // comfortably longer than any single-step animation would take
  const second = await canvasSnapshot(page);
  expect(second, "?seq=N must render a static frame, not keep animating").toBe(first);
});
