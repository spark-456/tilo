import { expect, test } from "@playwright/test";
import { watchConsole } from "./support/screens";
import { readShifts, resetShifts, watchShifts } from "./support/shifts";
import { DESKTOP, MOBILE } from "./support/viewports";
import { stageFrame } from "./support/world";

// S-04 (PRD 18.3, artboard "Tilo World Player"): the levels panel left of the stage from 1280 px,
// and the decision / finish marks on the replay track. Both read the recorded run only (HR-1).

const WORLD = "/world/w_village_basic?fixture=village-basic&seq=44";

test("S-04 the levels panel sits beside the stage, never over it, and shifts nothing", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  const errors = watchConsole(page);
  await watchShifts(page);
  await page.goto(WORLD);
  const panel = page.getByTestId("levels-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("link", { name: /Inbox/ })).toHaveAttribute(
    "href",
    "/world/w_village_basic/inspect/L1",
  );
  const [p, s] = await Promise.all([panel.boundingBox(), stageFrame(page).boundingBox()]);
  expect(p && s && p.x + p.width <= s.x + 1).toBe(true);
  await resetShifts(page);
  await page.getByRole("button", { name: "Previous event" }).click();
  expect((await readShifts(page)).reduce((a, b) => a + b, 0)).toBeLessThan(0.0001);
  expect(errors).toEqual([]);
});

test("S-04 the replay track marks the decision and the finishes at their stops", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto(WORLD);
  const marks = page.getByTestId("scrub-marks").locator("i");
  await expect(marks).toHaveCount(3);
  const track = await page.getByRole("slider", { name: "Replay position" }).boundingBox();
  const first = await marks.first().boundingBox();
  expect(track && first && first.x > track.x && first.x < track.x + track.width).toBe(true);
  await expect(marks.first()).toHaveAttribute("data-kind", "decision");
});

test("S-04 the panel gives the stage its room below 1280 px and on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 800 });
  await page.goto(WORLD);
  await expect(page.getByTestId("levels-panel")).toBeHidden();
  await page.setViewportSize(MOBILE);
  await page.reload();
  await expect(page.getByTestId("levels-panel")).toHaveCount(0);
});
