import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP });

test('PRD-5.5 nav: only screens that exist are navigable, and nothing says "coming soon"', async ({
  page,
}) => {
  await page.goto("/");

  const nav = page.getByRole("navigation", { name: /primary/i });
  await expect(nav).toBeVisible();

  const links = await nav.getByRole("link").allTextContents();
  const buttons = await nav.getByRole("button").allTextContents();
  const labels = [...links, ...buttons].map((t) => t.trim()).filter(Boolean);

  // P0-08a ships only the World screen (PRD 18.3 S-04, this ticket's title:
  // "no fixture player yet") — no other screen exists to navigate to.
  expect(labels).toEqual(["World"]);

  const bodyText = (await page.locator("body").innerText()).toLowerCase();
  expect(bodyText).not.toContain("coming soon");
});
