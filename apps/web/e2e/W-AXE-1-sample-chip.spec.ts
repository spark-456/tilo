import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 } });

test("UI_10_W_AXE_1_Ledger_sample_chip_keeps_24px_hit_area", async ({ page }) => {
  await page.goto("/ledger");
  const chip = page.locator("button.park-shell__sample");
  await expect(chip).toBeVisible();
  const box = await chip.boundingBox();
  expect(box).not.toBeNull();
  expect(box?.width).toBeGreaterThanOrEqual(24);
  expect(box?.height).toBeGreaterThanOrEqual(24);
  const results = await new AxeBuilder({ page }).withRules(["target-size"]).analyze();
  expect(results.violations).toEqual([]);
  await chip.click();
  await expect(page.getByRole("dialog", { name: "Sample data" })).toBeVisible();
});
