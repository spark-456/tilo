// #227 Bundle G2 part B (S-15, S-19, S-21, S-22): the kill switch is the one danger-styled control
// on S-15, figures say their state in words, and S-22's reviews go to the screens that show them.
import { type Page, expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

const tile = (page: Page, id: string, label: string) =>
  page.getByTestId(id).locator("li", { hasText: label }).first();

test("UX-1 G2b S-15 Stop all autopilot is the one danger-styled control", async ({ page }) => {
  test.setTimeout(90_000);
  const problems = watchConsole(page);
  for (const viewport of [DESKTOP, MOBILE]) {
    await page.setViewportSize(viewport);
    await page.goto("/autonomy?speed=100");
    const stop = page.getByRole("button", { name: /Stop all autopilot/ });
    await expect(stop).toBeVisible({ timeout: 20_000 });
    await expect(page.locator("main .danger")).toHaveCount(1);
    expect(await stop.evaluate((el) => getComputedStyle(el).borderTopStyle)).toBe("solid");
    await expect(page.getByRole("button", { name: /New rule/ })).toHaveCount(0);
  }
  expect(problems).toEqual([]);
});

test("UX-1 G2b figures on S-15, S-19 and S-21 say their state in words", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  await page.goto("/autonomy");
  await expect(tile(page, "autonomy", "Waiting for you")).toContainText("All clear");
  await page.goto("/connections");
  await expect(tile(page, "connections", "Waiting for consent")).toContainText("All clear");
  await page.goto("/library/artifacts");
  await expect(tile(page, "artifact-history", "Artifacts")).toContainText("None yet");
  await page.goto("/library/artifacts?speed=100");
  await expect(tile(page, "artifact-history", "Delivered")).toContainText("Delivered", {
    timeout: 20_000,
  });
});

test("UX-1 G2b S-22 reviews are links to the screens that show the access", async ({ page }) => {
  await page.setViewportSize(MOBILE);
  await page.goto("/settings");
  await expect(page.getByRole("link", { name: "Review Gmail access" })).toHaveAttribute(
    "href",
    "/connections",
  );
  await expect(page.getByRole("link", { name: "Review Email" })).toHaveAttribute(
    "href",
    "/channels",
  );
  await expect(page.getByRole("button", { name: /Review Style profile/ })).toHaveCount(0);
});
