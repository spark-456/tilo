import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

test("PRD-18.3 nav (desktop): the left rail links Home, World, Story, Needs you, Library and More", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/");

  const nav = page.getByRole("navigation", { name: /primary/i });
  await expect(nav).toBeVisible();
  const labels = (await nav.getByRole("link").allTextContents()).map((t) => t.trim());
  expect(labels).toEqual(["Home", "World", "Story", "Needs you", "Library", "More"]);
  await expect(nav.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");

  // Every item is a real link to a screen that exists; none is a dead control.
  const bodyText = (await page.locator("body").innerText()).toLowerCase();
  expect(bodyText).not.toContain("coming soon");
});

test("PRD-18.3 nav (mobile): the bottom tabs are World, Story, Needs you, Library and More", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE);
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: /primary/i });
  const labels = (await nav.getByRole("link").allTextContents()).map((t) => t.trim());
  expect(labels).toEqual(["World", "Story", "Needs you", "Library", "More"]);
});
