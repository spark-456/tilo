import { type Page, expect, test } from "@playwright/test";
import { ZOOM_MIN, ZOOM_STEP } from "../src/stage/camera";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP, reducedMotion: "reduce" });

const camera = (page: Page) =>
  page.getByTestId("camera").evaluate((el) => {
    const { a, e, f } = new DOMMatrix(getComputedStyle(el).transform);
    return { zoom: a, x: e, y: f };
  });

test("PRD-9.7 stage camera: wheel zoom is vertical-only and proportional, left drag pans, browser shortcuts pass", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") errors.push(m.text());
  });
  await page.goto("/");
  await expect(page.getByTestId("stage-frame").locator("canvas")).toBeVisible();
  await page.mouse.move(700, 450);
  await page.mouse.wheel(-120, 0);
  await page.mouse.wheel(120, 0);
  for (let i = 0; i < 15; i++) await page.mouse.wheel(0, -2);
  await expect.poll(async () => (await camera(page)).zoom).toBeCloseTo(1.03, 5);
  for (let i = 0; i < 3; i++) await page.mouse.wheel(0, 500);
  await expect.poll(async () => (await camera(page)).zoom).toBeCloseTo(1.03 - 3 * ZOOM_STEP, 5);

  for (const button of ["right", "left"] as const) {
    await page.mouse.move(600, 400);
    await page.mouse.down({ button });
    await page.mouse.move(500, 350);
    await page.mouse.up({ button });
  }
  await expect.poll(async () => (await camera(page)).x).toBe(-100);
  expect((await camera(page)).y).toBe(-50);

  const prevented = await page.getByTestId("stage-frame").evaluate((el) =>
    [
      { key: "-", ctrlKey: true },
      { key: "ArrowLeft", altKey: true },
    ].map((init) => {
      const ev = new KeyboardEvent("keydown", { ...init, bubbles: true, cancelable: true });
      el.dispatchEvent(ev);
      return ev.defaultPrevented;
    }),
  );
  expect(prevented).toEqual([false, false]);
  expect(errors).toEqual([]);
});

test("PRD-9.7 stage camera: zoomed out and panned, the grid still reaches every corner", async ({
  page,
}) => {
  await page.goto("/");
  const stage = page.getByTestId("stage-frame");
  await expect(stage.locator("canvas")).toBeVisible();
  await stage.focus();
  for (let i = 0; i < (1 - ZOOM_MIN) / ZOOM_STEP; i++) await page.keyboard.press("-");
  for (const key of ["ArrowLeft", "ArrowLeft", "ArrowUp"]) await page.keyboard.press(key);
  await expect.poll(async () => (await camera(page)).zoom).toBeCloseTo(ZOOM_MIN, 5);
  // Per corner: does a 12 px square of the canvas hold more than one colour (grid ink)?
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
