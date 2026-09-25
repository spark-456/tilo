import { expect, test } from "@playwright/test";
import { ZOOM_MIN, ZOOM_STEP } from "../src/stage/camera";
import { requireBox } from "./support/assertions";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP });

/** For each stage corner, whether a 12px CSS square of the canvas holds any
 * pixel other than its first one, i.e. grid ink over the background. */
const cornersWithInk = (page: import("@playwright/test").Page) =>
  page
    .getByTestId("stage-frame")
    .locator("canvas")
    .evaluate((el: HTMLCanvasElement) => {
      const off = document.createElement("canvas");
      off.width = el.width;
      off.height = el.height;
      const ctx = off.getContext("2d");
      if (!ctx) return [];
      ctx.drawImage(el, 0, 0);
      const s = Math.round(12 * (el.width / el.clientWidth));
      return [
        [0, 0],
        [el.width - s, 0],
        [0, el.height - s],
        [el.width - s, el.height - s],
      ].map(([x = 0, y = 0]) => {
        const { data } = ctx.getImageData(x, y, s, s);
        for (let i = 4; i < data.length; i += 4) {
          if (data[i] !== data[0] || data[i + 1] !== data[1] || data[i + 2] !== data[2])
            return true;
        }
        return false;
      });
    });

test("PRD-9.7 stage camera: at ZOOM_MIN after panning, the grid still covers all four stage corners and the canvas fills the frame", async ({
  page,
}) => {
  await page.goto("/");
  const stage = page.getByTestId("stage-frame");
  await expect(stage.locator("canvas")).toBeVisible();
  await stage.focus();

  const zoomOutPresses = Math.round((1 - ZOOM_MIN) / ZOOM_STEP);
  for (let i = 0; i < zoomOutPresses; i++) await page.keyboard.press("-");
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowUp");
  await page.waitForTimeout(600); // > the 320ms camera duration

  const frame = requireBox(await stage.boundingBox(), "stage frame");
  const canvas = requireBox(await stage.locator("canvas").boundingBox(), "canvas");
  expect(canvas).toEqual(frame);
  expect(await cornersWithInk(page)).toEqual([true, true, true, true]);
});

test("PRD-9.7 stage camera: browser shortcuts with Ctrl or Alt are left to the browser", async ({
  page,
}) => {
  await page.goto("/");
  const stage = page.getByTestId("stage-frame");
  await stage.focus();
  const prevented = await stage.evaluate((el) => {
    const result: boolean[] = [];
    for (const init of [
      { key: "-", ctrlKey: true },
      { key: "=", ctrlKey: true },
      { key: "ArrowLeft", altKey: true },
    ]) {
      const ev = new KeyboardEvent("keydown", { ...init, bubbles: true, cancelable: true });
      el.dispatchEvent(ev);
      result.push(ev.defaultPrevented);
    }
    return result;
  });
  expect(prevented).toEqual([false, false, false]);
});
