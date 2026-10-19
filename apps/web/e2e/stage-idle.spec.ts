import { expect, test } from "@playwright/test";
import { CAMERA_TRANSITION_MS } from "../src/stage/camera";
import { gotoStage } from "./support/camera";
import { DESKTOP } from "./support/viewports";
import { fixtureUrl } from "./support/world";

const STILL_WORLD = fixtureUrl("village-basic", { seq: 44 });

test.use({ viewport: DESKTOP });

test("PRD-9.7/HR-2 stage: the iso grid has no idle animation of any kind", async ({ page }) => {
  await gotoStage(page, STILL_WORLD);

  const canvas = page.getByTestId("stage-frame").locator("canvas");
  await expect(canvas).toBeVisible();
  await page.waitForTimeout(500); // let any initial mount animation finish

  const first = await canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL());
  await page.waitForTimeout(1500); // no user interaction and no event in between
  const second = await canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL());

  expect(
    second === first,
    "the canvas' pixels changed with no interaction and no event — that is idle animation, forbidden by HR-2",
  ).toBe(true);
});

test("P0-08b camera C10 PRD-9.7/HR-2 stage: after a camera move settles, the canvas stays pixel-identical for 2s of idle", async ({
  page,
}) => {
  await gotoStage(page, STILL_WORLD);
  const stage = page.getByTestId("stage-frame");
  const canvas = stage.locator("canvas");
  await expect(canvas).toBeVisible();
  await stage.focus();

  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("=");
  await page.waitForTimeout(CAMERA_TRANSITION_MS + 200); // the "=" zoom uses the longer transition

  const first = await canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL());
  await page.waitForTimeout(2000); // no user interaction and no event in between
  const second = await canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL());

  expect(
    second === first,
    "the canvas changed with no interaction after the camera settled — idle animation, forbidden by HR-2",
  ).toBe(true);
});
