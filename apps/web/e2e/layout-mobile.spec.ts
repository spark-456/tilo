import { expect, test } from "@playwright/test";
import { MOBILE } from "./support/viewports";

test.use({ viewport: MOBILE });

test("PRD-18.3 layout: mobile 390x844 renders bottom tabs and no side rails", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByTestId("bottom-tabs")).toBeVisible();
  await expect(page.getByTestId("stage-frame")).toBeVisible();

  await expect(page.getByTestId("left-rail")).toHaveCount(0);
  await expect(page.getByTestId("right-rail")).toHaveCount(0);
});
