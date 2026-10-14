// UI-10 B6: the address the demo plan opens plays a recorded run: the stage loads the bundled village-basic stream,
// says it is a replay, and is not "Not found". Run: TILO_WEB_PORT=5796 pnpm --filter @tilo/web exec playwright test
// e2e/park-home-b6.spec.ts --project=chromium --no-deps --workers=1
import { expect, test } from "@playwright/test";

test("UI_10_B6_the_demo_recorded_run_address_shows_a_replay_not_not_found", async ({ page }) => {
  test.setTimeout(150_000); // a cold dev server optimises the stage's dependencies on the first request
  await page.goto("/world/w_village_basic/stage?fixture=village-basic");
  await expect(page.locator('[data-stage-ready="true"]')).toBeVisible({ timeout: 60_000 });
  // UI-10 W20: the recorded stage now shares the Park shell and honest Sample label.
  await expect(page.getByRole("heading", { name: "Sample recording" })).toBeVisible();
  await expect(
    page.getByText("This is a recorded sample, not your task. No work is being sent."),
  ).toBeVisible();
  // W20: Main is the Park shell; the recorded stage also retains its Lens navigation.
  await expect(
    page.locator("[data-park]").getByRole("navigation", { name: "Main", exact: true }),
  ).toBeVisible();
  await expect(
    page.locator("[data-park]").getByRole("navigation", { name: "Lens", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Fixture replay")).toHaveCount(0);
  await expect(page.getByTestId("trace-row").first()).toBeAttached({ timeout: 60_000 });
  await expect(page.getByText("Not found")).toHaveCount(0);
});
