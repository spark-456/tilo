import { type Page, expect } from "@playwright/test";
import { STAGE_PATH } from "./world";

/**
 * P0-08b stage readiness: `[data-testid="stage-frame"]` gains `data-stage-ready="true"` (and the
 * data-camera-* attributes) with the first frame drawn after Pixi's init resolves, never before.
 * Specs that send input or read the camera right after a navigation wait for it first.
 */
export async function waitForStage(page: Page): Promise<void> {
  await expect(page.getByTestId("stage-frame")).toHaveAttribute("data-stage-ready", "true");
}

/** page.goto, then wait until the stage has drawn its first frame. */
export async function gotoStage(page: Page, url = STAGE_PATH): Promise<void> {
  await page.goto(url);
  await waitForStage(page);
}

/** page.reload, then wait until the stage has drawn its first frame. */
export async function reloadStage(page: Page): Promise<void> {
  await page.reload();
  await waitForStage(page);
}

/**
 * P0-08b camera C2 (the new test interface): `[data-testid="stage-frame"]` carries
 * `data-camera-x`, `data-camera-y` and `data-camera-zoom`, always equal to the camera
 * currently drawn on the canvas (see e2e/support/assertions.ts for the field meanings).
 * This is the one place e2e specs read the camera from; it replaces reading a CSS
 * transform off `[data-testid="camera"]` (P0-08a). It waits for the first drawn frame.
 */
export async function readCamera(page: Page): Promise<{ x: number; y: number; zoom: number }> {
  await waitForStage(page);
  return page.getByTestId("stage-frame").evaluate((el) => ({
    x: Number.parseFloat(el.getAttribute("data-camera-x") ?? "NaN"),
    y: Number.parseFloat(el.getAttribute("data-camera-y") ?? "NaN"),
    zoom: Number.parseFloat(el.getAttribute("data-camera-zoom") ?? "NaN"),
  }));
}
