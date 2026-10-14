import { expect, test } from "@playwright/test";

for (const width of [320, 390, 1440]) {
  test(`UI_10_W21_reachable_kept_screens_have_Park_chrome_at_${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    for (const path of [
      "/start",
      "/world/w_village_basic/story",
      "/world/w_village_basic/trace",
      "/library",
      "/plate",
    ]) {
      await page.goto(path);
      await expect(page.locator("[data-park] nav")).toBeVisible();
      await expect(page.getByRole("button", { name: "Your context", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Account menu", exact: true })).toBeVisible();
      await expect(page.locator("main")).toHaveCount(1);
      await expect(page.locator("main h1").first()).toBeVisible();
      await expect(page.getByText("Fixture replay")).toHaveCount(0);
      await expect(
        page.getByText("Sample run data — recorded, not your task", { exact: true }),
      ).toBeVisible();
      const nav = await page.locator(".park-shell__nav").boundingBox();
      const content = await page.locator('[data-park-chrome="on"]').boundingBox();
      expect(nav).not.toBeNull();
      expect(content).not.toBeNull();
      if (!nav || !content) throw new Error("W21 shell and content must have visible boxes");
      expect(content.y).toBeGreaterThanOrEqual(nav.y + nav.height);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
    }
  });
}
