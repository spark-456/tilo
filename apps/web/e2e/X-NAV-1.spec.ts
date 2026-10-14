import { expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";

const ROUTES = [
  "/",
  "/worlds",
  "/world/northline",
  "/skills",
  "/ledger",
  "/agenda",
  "/team",
  "/profile",
  "/connectors",
  "/world/northline/stage",
  "/world/northline/story",
  "/needs-you",
  "/library",
  "/more",
];

for (const width of [390, 1440]) {
  test(`X_NAV_1 every sidebar destination and Park route renders without console errors at ${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const problems = collectConsoleProblems(page);
    for (const path of ROUTES) {
      await page.goto(path);
      await expect(page.locator("[data-park] main")).toBeVisible();
      await expect(page.locator("[data-park] h1")).toBeVisible();
      await expect(page.getByRole("heading", { name: "Page not found", exact: true })).toHaveCount(
        0,
      );
      expect(problems, path).toEqual([]);
    }
  });
}
