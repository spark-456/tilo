import { type Page, expect, test } from "@playwright/test";
import { PAN_STEP_PX } from "../src/stage/camera";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP, reducedMotion: "no-preference" });

const snapshot = (page: Page) =>
  page
    .getByTestId("stage-frame")
    .locator("canvas")
    .evaluate((el: HTMLCanvasElement) => el.toDataURL());

test("PRD-9.7 stage camera: a main-thread long task during a pan still leaves the canvas on the settled camera", async ({
  page,
}) => {
  await page.goto("/");
  const stage = page.getByTestId("stage-frame");
  await expect(stage.locator("canvas")).toBeVisible();
  await stage.focus();
  await page.keyboard.press("ArrowLeft");
  await page.evaluate(() => {
    const t = performance.now();
    while (performance.now() - t < 450);
  });
  await page.waitForTimeout(1500);
  await expect
    .poll(() =>
      page.getByTestId("camera").evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).e),
    )
    .toBe(PAN_STEP_PX);
  const settled = await snapshot(page);

  // A resize forces sync + render against the settled transform: the frame must not change.
  await page.setViewportSize({ width: DESKTOP.width + 2, height: DESKTOP.height });
  await page.setViewportSize(DESKTOP);
  await page.waitForTimeout(300);
  await expect.poll(() => snapshot(page)).toBe(settled);
});
