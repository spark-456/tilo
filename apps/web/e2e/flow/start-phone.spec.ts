// #289 (Bundle D follow-ups): the phone fit of S-03 at 390x844. Measured in the page, never by a timer:
// each test waits on what it measures. WEB-CUTOVER removed the S-01 tests (the Start screen is the Park Home now).
import { expect, test } from "@playwright/test";
import { MOBILE } from "../support/viewports";

test("#289 S-03 at 390: the panel ends above the bottom tabs, and the cap field is a 44 px target", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE);
  await page.goto("/task/t/approaches");
  const cap = page.getByTestId("budget-cap-input");
  await expect(cap).toBeVisible();
  const box = await cap.boundingBox();
  expect(box?.height ?? 0, "budget cap input height").toBeGreaterThanOrEqual(44);
  const gap = await page.evaluate(() => {
    const shell = document.querySelector(".flow-shell") as HTMLElement;
    const tabs = document.querySelector(".bottom-tabs") as HTMLElement;
    return tabs.getBoundingClientRect().top - shell.getBoundingClientRect().bottom;
  });
  expect(gap, "space between the panel's bottom and the tabs' top").toBeGreaterThanOrEqual(0);
  // The one action is reachable without leaving the panel: it sits inside it, above the tabs.
  const primary = await page.locator(".flow-shell .primary").boundingBox();
  const tabsTop = (await page.locator(".bottom-tabs").boundingBox())?.y ?? 0;
  expect((primary?.y ?? 0) + (primary?.height ?? 0)).toBeLessThanOrEqual(tabsTop);
});
