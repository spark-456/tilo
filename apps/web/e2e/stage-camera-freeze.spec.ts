/**
 * P0-08b camera C8, frozen/hidden-tab case. The brief calls this out by name: "when the page is
 * frozen/hidden during an eased move (e.g. CDP Page.setWebLifecycleState frozen then active; if
 * that cannot be emulated reliably, say so in your report and skip only that case)". The
 * long-task half of C8 is in stage-settle.spec.ts.
 *
 * Public interface: e2e/support/camera.ts (readCamera); src/stage/camera.ts's PAN_STEP_PX.
 * No new production exports.
 */
import { type Page, expect, test } from "@playwright/test";
import { PAN_STEP_PX } from "../src/stage/camera";
import { gotoStage, readCamera } from "./support/camera";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP, reducedMotion: "no-preference" });

const snapshot = (page: Page) =>
  page
    .getByTestId("stage-frame")
    .locator("canvas")
    .evaluate((el: HTMLCanvasElement) => el.toDataURL());

test("P0-08b camera C8 PRD-9.7: freezing the page mid-ease (backgrounded tab) still leaves the canvas on the settled camera once active again", async ({
  page,
}) => {
  await gotoStage(page);
  const stage = page.getByTestId("stage-frame");
  await expect(stage.locator("canvas")).toBeVisible();
  await stage.focus();
  const start = await readCamera(page);

  const session = await page.context().newCDPSession(page);
  let canEmulateLifecycle = true;
  try {
    await session.send("Page.setWebLifecycleState", { state: "frozen" });
  } catch {
    canEmulateLifecycle = false;
  }
  test.skip(
    !canEmulateLifecycle,
    "this Chromium build/channel does not support Page.setWebLifecycleState; camera C8's " +
      "frozen-tab case is skipped rather than asserted (per the test brief: report and skip only this case)",
  );

  await page.keyboard.press("ArrowLeft");
  await page.waitForTimeout(600); // longer than CAMERA_PAN_MS while frozen: timers may not fire

  await session.send("Page.setWebLifecycleState", { state: "active" });
  await page.waitForTimeout(600);

  await expect.poll(async () => (await readCamera(page)).x).toBeCloseTo(start.x + PAN_STEP_PX, 1);
  const settled = await snapshot(page);
  await page.setViewportSize({ width: DESKTOP.width + 2, height: DESKTOP.height });
  await page.setViewportSize(DESKTOP);
  await page.waitForTimeout(300);
  await expect.poll(() => snapshot(page)).toBe(settled);
});
