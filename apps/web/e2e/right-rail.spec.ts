import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP });

test("PRD-18.3 right rail: honest empty state shows no fake numbers before any events exist", async ({
  page,
}) => {
  // WEB-CUTOVER: "/" is the Park Home; S-02 is the old shell's first screen, with no run on record.
  await page.goto("/task/task_fixture_1/understanding");

  const meter = page.getByTestId("right-rail-meter");
  await expect(meter).toBeVisible();

  const meterText = (await meter.innerText()).trim();
  // No run has started, so the meter must show no digit at all — not even a
  // placeholder "0": PRD 18.3 wants nothing shown until events exist.
  expect(meterText, `meter shows a number before any events exist: "${meterText}"`).not.toMatch(
    /\d/,
  );
  expect(
    meterText.length,
    "meter must show an honest empty-state message, not blank markup",
  ).toBeGreaterThan(0);
});
