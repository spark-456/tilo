import { expect, test } from "@playwright/test";
import { MOBILE } from "./support/viewports";
import { STAGE_PATH } from "./support/world";

test.use({ viewport: MOBILE });

test("PRD-18.3 layout: mobile 390x844 renders bottom tabs and no side rails", async ({ page }) => {
  // WEB-CUTOVER: "/" is the Park Home (its own shell); the old app's frame is the stage address.
  await page.goto(STAGE_PATH);

  await expect(page.getByTestId("bottom-tabs")).toBeVisible();
  await expect(page.getByTestId("stage-frame")).toBeVisible();

  await expect(page.getByTestId("left-rail")).toHaveCount(0);
  await expect(page.getByTestId("right-rail")).toHaveCount(0);
});
