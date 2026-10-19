import { expect, test } from "@playwright/test";
import { expectWithinPx, requireBox } from "./support/assertions";
import { DESKTOP } from "./support/viewports";
import { STAGE_PATH } from "./support/world";

test.use({ viewport: DESKTOP });

test("PRD-9.7 stage: the PixiJS canvas mounts, fills the centre stage and resizes with it", async ({
  page,
}) => {
  await page.goto(STAGE_PATH);

  const stage = page.getByTestId("stage-frame");
  const canvas = stage.locator("canvas");
  await expect(canvas).toBeVisible();

  const stageBox1 = requireBox(await stage.boundingBox(), "centre stage");
  const canvasBox1 = requireBox(await canvas.boundingBox(), "canvas");
  expectWithinPx(canvasBox1.width, stageBox1.width);
  expectWithinPx(canvasBox1.height, stageBox1.height);

  // Resize the window and confirm the canvas tracks the new stage size.
  await page.setViewportSize({ width: 1200, height: 800 });
  await page.waitForTimeout(250); // let the resize observer / ticker settle

  const stageBox2 = requireBox(await stage.boundingBox(), "centre stage");
  const canvasBox2 = requireBox(await canvas.boundingBox(), "canvas");
  expectWithinPx(canvasBox2.width, stageBox2.width);
  expectWithinPx(canvasBox2.height, stageBox2.height);
  expect(
    Math.abs(canvasBox2.width - canvasBox1.width),
    "canvas width did not change after the window resized",
  ).toBeGreaterThan(5);
});
