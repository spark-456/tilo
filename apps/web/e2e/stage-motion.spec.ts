/**
 * P0-08b camera C7 (the eased-vs-instant timing half; the other half of C7 — Ctrl/Meta/Alt
 * keyboard shortcuts still passing through — is in stage-camera.spec.ts). PRD 18.2 "Motion:
 * ... 320 ms camera; ... reduced motion respected"; HR-3 (movement is cosmetic and the world
 * never runs ahead of input).
 *
 * P0-08a read the camera's motion off a CSS `transition-duration` on a `[data-testid="camera"]`
 * div. P0-08b's camera is a PixiJS world-container transform instead (C1), so there is no CSS
 * transition to read: this file drives the same before/after-320ms comparison against the live
 * camera value itself, via `data-camera-x` on `[data-testid="stage-frame"]`
 * (see e2e/support/camera.ts's `readCamera`).
 *
 * Public interface: e2e/support/camera.ts (readCamera); src/stage/camera.ts's CAMERA_PAN_MS,
 * PAN_STEP_PX. No new production exports.
 */
import { expect, test } from "@playwright/test";
import { CAMERA_PAN_MS, PAN_STEP_PX } from "../src/stage/camera";
import { gotoStage, readCamera } from "./support/camera";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP });

test("P0-08b camera C7 PRD-18.2/9.7 motion: a keyboard pan eases toward its target over about the 320ms design-system duration, not instantly", async ({
  page,
}) => {
  await gotoStage(page);
  const stage = page.getByTestId("stage-frame");
  await stage.focus();
  const before = await readCamera(page);
  const target = before.x - PAN_STEP_PX;

  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(40); // well under CAMERA_PAN_MS: still mid-ease
  const soon = (await readCamera(page)).x;
  expect(
    soon,
    "camera already reached its final target well before the 320ms pan finished — it is not eased",
  ).not.toBeCloseTo(target, 1);

  await page.waitForTimeout(CAMERA_PAN_MS + 300);
  await expect.poll(async () => (await readCamera(page)).x).toBeCloseTo(target, 3);
});

test.describe("reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("HR-3 P0-08b camera C7 PRD-18.2/9.7 motion: reduced motion makes a keyboard pan land on its target immediately, not over 320ms", async ({
    page,
  }) => {
    await gotoStage(page);
    const stage = page.getByTestId("stage-frame");
    await stage.focus();
    const before = await readCamera(page);
    const target = before.x - PAN_STEP_PX;

    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(30); // far less than CAMERA_PAN_MS
    await expect.poll(async () => (await readCamera(page)).x).toBeCloseTo(target, 3);
  });
});
