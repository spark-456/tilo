import type { Page } from "@playwright/test";

/**
 * P0-08b camera C2 (the new test interface): `[data-testid="stage-frame"]` carries
 * `data-camera-x`, `data-camera-y` and `data-camera-zoom`, always equal to the camera
 * currently drawn on the canvas (see e2e/support/assertions.ts for the field meanings).
 * This is the one place e2e specs read the camera from; it replaces reading a CSS
 * transform off `[data-testid="camera"]` (P0-08a).
 */
export async function readCamera(page: Page): Promise<{ x: number; y: number; zoom: number }> {
  return page.getByTestId("stage-frame").evaluate((el) => ({
    x: Number.parseFloat(el.getAttribute("data-camera-x") ?? "NaN"),
    y: Number.parseFloat(el.getAttribute("data-camera-y") ?? "NaN"),
    zoom: Number.parseFloat(el.getAttribute("data-camera-zoom") ?? "NaN"),
  }));
}
