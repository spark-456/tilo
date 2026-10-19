import { expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";

test("M1_NOTFOUND_1 unknown address recovers through Worlds search and Home", async ({ page }) => {
  const problems = collectConsoleProblems(page);
  await page.goto("/no-such-page/");
  await expect(page).toHaveURL(/\/no-such-page$/);
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.getByRole("link", { name: "Search worlds", exact: true }).click();
  await expect(page.getByTestId("park-page-worlds")).toBeVisible();
  await expect(page.getByRole("textbox", { name: /search/i })).toBeVisible();
  await page.goto("/no-such-page");
  await page.getByRole("link", { name: "Go to Home", exact: true }).click();
  await expect(page.getByTestId("park-page-home")).toBeVisible();
  await page.goto("/index.html/");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("park-page-home")).toBeVisible();
  await page.goto("/worlds/");
  await expect(page).toHaveURL(/\/worlds$/);
  await expect(page.getByTestId("park-page-worlds")).toBeVisible();
  expect(problems).toEqual([]);
});
