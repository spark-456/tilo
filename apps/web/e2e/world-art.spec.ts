import { type Page, expect, test } from "@playwright/test";
import { watchConsole } from "./support/screens";
import { DESKTOP } from "./support/viewports";
import { canvasColours, canvasSnapshot, fixtureUrl, stageCanvas, stageSeq } from "./support/world";

// Bundle B of #227 (PRD 9.1, 9.4, 18.3 S-04): the stage draws the ported isometric art, and what
// it draws follows the layout and the recorded events only. These tests read the canvas, so they
// pin behaviour (a building's state changes the picture, an event with no world effect does not)
// rather than any one pixel of art.

test.use({ viewport: DESKTOP });

const at = (seq: number) => fixtureUrl("village-basic", { seq });

async function shot(page: Page, seq: number): Promise<string> {
  await page.goto(at(seq));
  await expect.poll(() => stageSeq(page)).toBe(seq);
  return canvasSnapshot(page);
}

test("FR-WLD-04 art: a finished run is a drawn world, not a bare iso grid", async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto("/");
  await expect(stageCanvas(page)).toBeVisible();
  const bare = await canvasColours(page);
  await shot(page, 44);
  const drawn = await canvasColours(page);
  expect(
    drawn,
    "buildings, plots and tags add colours the bare grid does not have",
  ).toBeGreaterThan(bare * 8);
  expect(problems).toEqual([]);
});

test("FR-WLD-04 art: a building's state changes the picture, planned to constructing to operational to completed", async ({
  page,
}) => {
  // Mail Room (B1): planned at 8, constructing at 21, operational at 23, completed at 40.
  const picture = new Map<number, string>();
  for (const seq of [8, 21, 23, 40]) picture.set(seq, await shot(page, seq));
  expect(new Set(picture.values()).size).toBe(4);
});

test("HR-5 art: an event with no world effect does not change the picture", async ({ page }) => {
  // 22 is a data transfer and 35 a channel message: recorded, shown in the Trace, never drawn.
  expect(await shot(page, 22)).toBe(await shot(page, 21));
  expect(await shot(page, 35)).toBe(await shot(page, 34));
});

test("HR-7 art: a gate waiting for a person and a gate a person opened look different", async ({
  page,
}) => {
  const [shut, waiting, open] = [await shot(page, 33), await shot(page, 34), await shot(page, 37)];
  expect(new Set([shut, waiting, open]).size).toBe(3);
});

test("FR-WLD-04 art: replaying live ends on the same picture as jumping to the last seq", async ({
  browser,
}) => {
  // Live playback (with motion and with reduced motion, where moves become jumps) and ?seq=44
  // must agree to the pixel: one reducer, one frame function, one renderer.
  const jumped = await shot(await browser.newPage({ viewport: DESKTOP }), 44);
  for (const reducedMotion of ["no-preference", "reduce"] as const) {
    const ctx = await browser.newContext({ viewport: DESKTOP, reducedMotion });
    const page = await ctx.newPage();
    await page.goto(fixtureUrl("village-basic", { speed: 1000 }));
    await expect.poll(() => stageSeq(page), { timeout: 20_000 }).toBe(44);
    await page.waitForTimeout(2_500);
    expect(await canvasSnapshot(page), reducedMotion).toBe(jumped);
    await ctx.close();
  }
});
