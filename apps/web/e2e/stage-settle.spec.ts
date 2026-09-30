/**
 * P0-08b camera C8, second half (corner-coverage after zoom/pan and the pan round-trip are in
 * stage-camera-visual.spec.ts). qa-breaker found (P0-08a head 60c0238,
 * .claude/agent-memory/qa-breaker/web-stage-attack-patterns.md #5) that stopping the Pixi
 * ticker on a wall-clock `setTimeout(duration + 50)` left the canvas on a mid-transition frame
 * when a main-thread long task delayed that timer past the animation's real end — the ticker
 * stopped, but never rendered the settled camera. The fix must do a final sync + render at the
 * animation's actual end (or lazily whenever the renderer is next asked to draw, e.g. by a
 * resize), not rely on the timer alone.
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

test("P0-08b camera C8 PRD-9.7: a main-thread long task during a pan still leaves the canvas matching the settled camera once it resumes", async ({
  page,
}) => {
  await gotoStage(page);
  const stage = page.getByTestId("stage-frame");
  await expect(stage.locator("canvas")).toBeVisible();
  await stage.focus();
  await page.keyboard.press("ArrowLeft");
  await page.evaluate(() => {
    const t = performance.now();
    while (performance.now() - t < 450); // longer than CAMERA_PAN_MS + the old 50ms timer margin
  });
  await page.waitForTimeout(1500); // let any pending timers/ticker resolve
  await expect.poll(async () => (await readCamera(page)).x).toBeCloseTo(PAN_STEP_PX, 3);
  const settled = await snapshot(page);

  // A resize forces the renderer to draw again from whatever camera it currently holds: the
  // frame must be the settled one, not a stale mid-transition frame frozen by the old bug.
  await page.setViewportSize({ width: DESKTOP.width + 2, height: DESKTOP.height });
  await page.setViewportSize(DESKTOP);
  await page.waitForTimeout(300);
  await expect.poll(() => snapshot(page)).toBe(settled);
});
