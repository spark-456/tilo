// Issue #227 B5 (artboard "Tilo World Player" camera control; PRD 9.7, WCAG 2.5.7): the stage has
// visible Zoom in / Zoom out buttons, a pointer alternative to the wheel and the pinch. They take
// the same path as the "+" and "-" keys (one camera, HR-3), so one press is one ZOOM_STEP, and a
// press never drags the view.
import { expect, test } from "@playwright/test";
import { ZOOM_MAX, ZOOM_STEP } from "../src/stage/camera";
import { gotoStage, readCamera } from "./support/camera";
import { DESKTOP, MOBILE } from "./support/viewports";

const URL = "/world/w_village_basic/stage?fixture=village-basic&seq=20";

test.use({ reducedMotion: "reduce" }); // instant moves: no easing to wait out

test("#227 B5 desktop: Zoom in and Zoom out move the camera one step each and never pan", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await gotoStage(page, URL);
  const start = await readCamera(page);
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect.poll(async () => (await readCamera(page)).zoom).toBeCloseTo(start.zoom + ZOOM_STEP);
  const zoomed = await readCamera(page);
  // The point under the stage centre stays there: the offset scales with the zoom, nothing drags.
  const k = zoomed.zoom / start.zoom;
  expect(zoomed.x).toBeCloseTo(start.x * k);
  expect(zoomed.y).toBeCloseTo(start.y * k);
  await page.getByRole("button", { name: "Zoom out" }).click();
  await expect.poll(async () => (await readCamera(page)).zoom).toBeCloseTo(start.zoom);
});

test("#227 B5 desktop: Zoom in stops at the camera's limit", async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await gotoStage(page, URL);
  const zoomIn = page.getByRole("button", { name: "Zoom in" });
  for (let i = 0; i < 25; i++) await zoomIn.click();
  await expect.poll(async () => (await readCamera(page)).zoom).toBeCloseTo(ZOOM_MAX);
});

test("#227 B5: the buttons are at least 24 px on desktop and 44 px on a phone, named, and in the tab order", async ({
  page,
}) => {
  for (const [viewport, size] of [
    [DESKTOP, 24],
    [MOBILE, 44],
  ] as const) {
    await page.setViewportSize(viewport);
    await gotoStage(page, URL);
    for (const name of ["Zoom in", "Zoom out"]) {
      const box = await page.getByRole("button", { name }).boundingBox();
      expect(box?.width ?? 0).toBeGreaterThanOrEqual(size);
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(size);
      // Nothing of the page (the sheet, the replay region, the tabs) covers the button's centre.
      // (Edge draws its own <settings-manager> widget over pages; that is the browser's, not ours.)
      const covered = await page.getByRole("button", { name }).evaluate((el) => {
        const r = el.getBoundingClientRect();
        const top = document
          .elementsFromPoint(r.left + r.width / 2, r.top + r.height / 2)
          .find((e) => e.tagName.toLowerCase() !== "settings-manager");
        return top !== undefined && !el.contains(top);
      });
      expect(covered, `${name} at ${viewport.width}x${viewport.height}`).toBe(false);
    }
  }
  await page.getByRole("button", { name: "Zoom in" }).focus();
  await expect(page.getByRole("button", { name: "Zoom in" })).toBeFocused();
});
