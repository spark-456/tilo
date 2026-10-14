import { expect, test } from "@playwright/test";
import { collectConsoleProblems } from "../support/console";

for (const width of [1440, 390]) {
  test(`OLD-UI-OUT-4 all admin bookmarks use Park and replace history at ${width}`, async ({
    page,
  }) => {
    test.setTimeout(150_000);
    await page.setViewportSize({ width, height: 900 });
    const errors = collectConsoleProblems(page);
    for (const [path, target, pageId] of [
      ["autonomy", "/settings?section=autonomy", "settings"],
      ["channels", "/settings?section=channels", "settings"],
      ["estimate", "/settings?section=estimate", "settings"],
      ["pilot", "/settings?section=pilot", "settings"],
      ["settings", "/settings", "settings"],
    ]) {
      await page.goto(`/${path}`);
      await expect(page.getByTestId(`park-page-${pageId}`)).toBeVisible();
      await expect(page).toHaveURL(new RegExp(`${target?.replace("?", "\\?")}$`));
      await expect(page.locator("[data-park]")).toBeVisible();
      await expect(page.getByText("Fixture replay - dev data", { exact: true })).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      expect(await page.evaluate(() => history.state)).toEqual(
        ["settings", "more"].includes(path ?? "") ? null : {},
      );
    }
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "Routines", exact: true })).toBeVisible();
    await expect(
      page.getByText("No routines are recorded in this sample.", { exact: false }),
    ).toBeVisible();
    await page.locator(".park-admin").getByRole("button", { name: "Night", exact: false }).click();
    await expect(page.locator("[data-park]")).toHaveAttribute("data-time", "night");
    await page.screenshot({
      path: `test-results/OLD-UI-OUT-4-settings-${width}.png`,
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
}
