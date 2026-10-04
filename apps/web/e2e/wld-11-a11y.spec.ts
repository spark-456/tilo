import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { gotoStage } from "./support/camera";

test.describe("WLD-11 Accessibility", () => {
  test("keyboard world outline is present and can be selected", async ({ page }) => {
    await gotoStage(page, "/?fixture=village-basic");
    const outline = page.getByRole("list", { name: "World objects" });

    const buttons = outline.getByRole("button");
    await expect(buttons.first()).toBeAttached();

    await buttons.first().focus();
    await page.keyboard.press("Enter");

    await expect(buttons.first()).toHaveAttribute("aria-pressed", "true");
  });

  test("story lens is polite and rows have accessible names", async ({ page }) => {
    await page.goto("/world/village-basic/story?fixture=village-basic&speed=100");
    const log = page.getByRole("log", { name: "What happened, in order" });
    await expect(log).toHaveAttribute("aria-live", "polite");

    await expect(log.getByRole("listitem").first()).toHaveAttribute("aria-label", /Step \d+:/);
  });

  test("axe passes zero critical/serious issues on S-04 Trace", async ({ page }) => {
    await gotoStage(page, "/?fixture=village-basic");
    await expect(page.getByTestId("trace-list")).toBeVisible();

    const results = await new AxeBuilder({ page })
      .include('[data-testid="trace-list"]')
      .analyze();

    const severe = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious",
    );
    expect(severe).toEqual([]);
  });
});
