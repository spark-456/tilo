import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP });

test("PRD-9.7 stage: with WebGL2 unavailable, the Story-lens fallback panel replaces the canvas", async ({
  page,
}) => {
  // Simulate a browser with no WebGL2 support: make every webgl2 context
  // request return null, exactly what PixiJS sees on a real WebGL2-less
  // browser, without needing special launch flags or a different browser.
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (type: string, ...args: unknown[]) {
      if (type === "webgl2") return null;
      return Reflect.apply(original, this, [type, ...args]);
    };
  });

  await page.goto("/");

  await expect(page.getByTestId("stage-frame").locator("canvas")).toHaveCount(0);

  const fallback = page.getByTestId("stage-fallback");
  await expect(fallback).toBeVisible();
  await expect(fallback).toContainText(/story lens/i);
  await expect(fallback).toContainText(/run/i);
});
