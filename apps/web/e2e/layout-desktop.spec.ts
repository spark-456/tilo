import { expect, test } from "@playwright/test";
import { expectWithinPx, requireBox } from "./support/assertions";
import { DESKTOP } from "./support/viewports";
import { BARE_STAGE_PATH } from "./support/world";

test.use({ viewport: DESKTOP });

test("PRD-18.3 layout: desktop 1440x900 renders a 72px left rail, centre stage and 360px right rail", async ({
  page,
}) => {
  // WEB-CUTOVER: "/" is the Park Home (its own shell); the old app's three-column frame (no levels panel, which only a
  // world address adds) is the task flow's page.
  await page.goto(BARE_STAGE_PATH);

  const leftRail = page.getByTestId("left-rail");
  const stage = page.getByTestId("stage-frame");
  const rightRail = page.getByTestId("right-rail");

  await expect(leftRail).toBeVisible();
  await expect(stage).toBeVisible();
  await expect(rightRail).toBeVisible();

  const leftBox = requireBox(await leftRail.boundingBox(), "left rail");
  const stageBox = requireBox(await stage.boundingBox(), "centre stage");
  const rightBox = requireBox(await rightRail.boundingBox(), "right rail");

  expectWithinPx(leftBox.width, 72);
  expectWithinPx(rightBox.width, 360);
  // The centre stage takes what's left of the 1440px viewport.
  expectWithinPx(stageBox.width, 1440 - 72 - 360);
});
