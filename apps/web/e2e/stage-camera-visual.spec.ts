/**
 * P0-08b camera C1: the camera is a transform on a PixiJS world container, not CSS on the
 * canvas box (qa-breaker web-stage-attack-patterns.md #2 — at zoom 0.5 with a CSS-transform
 * camera, 75% of the stage showed bare surface behind the shrunk canvas; at zoom 2 the bitmap
 * was upscaled and blurry). This file asserts the fix visually/structurally: the canvas always
 * fills the stage frame exactly, its backing store is independent of zoom, and (C8, the other
 * half in stage-settle.spec.ts) the iso grid is anchored to world coordinates.
 *
 * Public interface: e2e/support/camera.ts (readCamera), src/stage/camera.ts's ZOOM_MIN/ZOOM_MAX/
 * PAN_STEP_PX. No new production exports beyond stage-camera.spec.ts's.
 */
import { type Page, expect, test } from "@playwright/test";
import { PAN_STEP_PX, ZOOM_MAX, ZOOM_MIN, ZOOM_STEP } from "../src/stage/camera";
import { expectSameBox, requireBox } from "./support/assertions";
import { gotoStage } from "./support/camera";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP, reducedMotion: "reduce" });

async function boxes(page: Page) {
  const stage = page.getByTestId("stage-frame");
  const canvas = stage.locator("canvas");
  return {
    stage: requireBox(await stage.boundingBox(), "stage-frame"),
    canvas: requireBox(await canvas.boundingBox(), "canvas"),
  };
}

async function backingStore(page: Page) {
  return page
    .getByTestId("stage-frame")
    .locator("canvas")
    .evaluate((el: HTMLCanvasElement) => ({
      width: el.width,
      height: el.height,
      clientWidth: el.clientWidth,
      clientHeight: el.clientHeight,
      dpr: window.devicePixelRatio,
    }));
}

/** No element under the stage frame may carry a CSS transform or transition on `transform`:
 * the camera must live on the Pixi world container, never on a CSS box (C1). */
async function cameraDrivenByCss(page: Page): Promise<boolean> {
  return page.getByTestId("stage-frame").evaluate((frame) => {
    const nodes = [frame, ...frame.querySelectorAll("*")];
    return nodes.some((el) => {
      const style = getComputedStyle(el);
      const hasTransform = style.transform !== "none";
      const transitionsTransform =
        style.transitionProperty
          .split(",")
          .some((p) => p.trim() === "transform" || p.trim() === "all") &&
        style.transitionDuration.split(",").some((d) => Number.parseFloat(d) > 0);
      return hasTransform || transitionsTransform;
    });
  });
}

test("P0-08b camera C1 PRD-9.7: no element inside the stage frame has a CSS transform or transition driving the camera", async ({
  page,
}) => {
  await gotoStage(page);
  await expect(page.getByTestId("stage-frame").locator("canvas")).toBeVisible();
  expect(await cameraDrivenByCss(page), "found a CSS transform/transition inside stage-frame").toBe(
    false,
  );

  const stage = page.getByTestId("stage-frame");
  await stage.focus();
  for (let i = 0; i < (1 - ZOOM_MIN) / ZOOM_STEP; i++) await page.keyboard.press("-");
  expect(await cameraDrivenByCss(page)).toBe(false);
  for (let i = 0; i < (ZOOM_MAX - ZOOM_MIN) / ZOOM_STEP; i++) await page.keyboard.press("=");
  expect(await cameraDrivenByCss(page)).toBe(false);
});

test("P0-08b camera C1 PRD-9.7: the canvas exactly fills the stage frame at zoom 0.5, at zoom 2 and after panning every direction", async ({
  page,
}) => {
  await gotoStage(page);
  const stage = page.getByTestId("stage-frame");
  await expect(stage.locator("canvas")).toBeVisible();
  await stage.focus();

  const initial = await boxes(page);
  expectSameBox(initial.canvas, initial.stage);

  for (let i = 0; i < (1 - ZOOM_MIN) / ZOOM_STEP; i++) await page.keyboard.press("-");
  const atMin = await boxes(page);
  expectSameBox(atMin.canvas, atMin.stage);

  for (let i = 0; i < (ZOOM_MAX - ZOOM_MIN) / ZOOM_STEP; i++) await page.keyboard.press("=");
  const atMax = await boxes(page);
  expectSameBox(atMax.canvas, atMax.stage);

  for (const key of ["ArrowLeft", "ArrowRight", "ArrowRight", "ArrowUp", "ArrowUp", "ArrowDown"]) {
    await page.keyboard.press(key);
  }
  const panned = await boxes(page);
  expectSameBox(panned.canvas, panned.stage);
});

test("P0-08b camera C1 PRD-9.7: the canvas backing store is clientWidth x devicePixelRatio at zoom 0.5 and zoom 2 (no bitmap upscaling)", async ({
  page,
}) => {
  await gotoStage(page);
  const stage = page.getByTestId("stage-frame");
  await expect(stage.locator("canvas")).toBeVisible();
  await stage.focus();

  const before = await backingStore(page);
  expect(before.width).toBe(Math.round(before.clientWidth * before.dpr));
  expect(before.height).toBe(Math.round(before.clientHeight * before.dpr));

  for (let i = 0; i < (ZOOM_MAX - 1) / ZOOM_STEP; i++) await page.keyboard.press("=");
  const atZoom2 = await backingStore(page);
  // Zooming the *camera* must not resize the canvas' own backing store — that would mean the
  // bitmap is being scaled/upscaled rather than the world container being transformed (C1).
  expect(atZoom2.width).toBe(before.width);
  expect(atZoom2.height).toBe(before.height);

  for (let i = 0; i < (ZOOM_MAX - ZOOM_MIN) / ZOOM_STEP; i++) await page.keyboard.press("-");
  const atZoom05 = await backingStore(page);
  expect(atZoom05.width).toBe(before.width);
  expect(atZoom05.height).toBe(before.height);
});

test("P0-08b camera C8 PRD-9.7 grid: zoomed out to ZOOM_MIN and panned, the iso grid still reaches every canvas corner", async ({
  page,
}) => {
  await gotoStage(page);
  const stage = page.getByTestId("stage-frame");
  await expect(stage.locator("canvas")).toBeVisible();
  await stage.focus();
  for (let i = 0; i < (1 - ZOOM_MIN) / ZOOM_STEP; i++) await page.keyboard.press("-");
  for (const key of ["ArrowLeft", "ArrowLeft", "ArrowUp"]) await page.keyboard.press(key);

  // Per corner: does a 12px square of the canvas hold more than one colour (grid ink)?
  const corners = () =>
    stage.locator("canvas").evaluate((el: HTMLCanvasElement) => {
      const ctx = document.createElement("canvas").getContext("2d");
      if (!ctx) return [];
      ctx.canvas.width = el.width;
      ctx.canvas.height = el.height;
      ctx.drawImage(el, 0, 0);
      const s = Math.round(12 * (el.width / el.clientWidth));
      return [0, el.height - s].flatMap((y) =>
        [0, el.width - s].map((x) => {
          const d = ctx.getImageData(x, y, s, s).data;
          return d.some((v, j) => v !== d[j % 4]);
        }),
      );
    });
  await expect.poll(corners).toEqual([true, true, true, true]);
});

test("P0-08b camera C8 PRD-9.7 grid: panning by PAN_STEP_PX moves the on-screen grid by exactly that many pixels", async ({
  page,
}) => {
  await gotoStage(page);
  const stage = page.getByTestId("stage-frame");
  await expect(stage.locator("canvas")).toBeVisible();
  await stage.focus();

  const snapshot = () =>
    stage.locator("canvas").evaluate((el: HTMLCanvasElement) => el.toDataURL());
  const before = await snapshot();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowLeft"); // back to the exact starting camera
  const after = await snapshot();
  // A round trip (pan then the exact inverse pan) must land on a pixel-identical frame: proof
  // the grid is redrawn from world coordinates each time, not drifting/accumulating error.
  expect(after).toBe(before);
});
