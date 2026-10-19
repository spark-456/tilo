import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  test(`FR_MTG_08 OLDUI5 routines address replaces into Park Worlds at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/routines", { timeout: 60_000 });
    await expect(page).toHaveURL(/\/worlds$/);
    await expect(page.getByTestId("park-page-worlds")).toBeVisible();
    await expect(page.locator("[data-park]")).toBeVisible();
  });
}
