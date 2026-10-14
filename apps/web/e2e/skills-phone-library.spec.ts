import { expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";

for (const theme of ["day", "night"]) {
  test(`FR_SKL_06 learned library fits phone in ${theme}`, async ({ page }) => {
    const problems = collectConsoleProblems(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/skills");
    const grid = page.locator(".park-skills-lib-grid");
    await expect(grid).toBeVisible();
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    await page.locator("[data-park]").evaluate((root, time) => {
      root.setAttribute("data-time", time);
    }, theme);
    const list = await page.locator(".park-skills-lib-list").boundingBox();
    const detail = await page.locator(".park-skills-lib-detail").boundingBox();
    expect(list).not.toBeNull();
    expect(detail).not.toBeNull();
    if (!list || !detail) throw new Error("Library list and detail must have layout boxes");
    expect(detail.y).toBeGreaterThanOrEqual(list.y + list.height);
    for (const box of [list, detail]) {
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(390);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390,
    );
    expect(problems).toEqual([]);
  });
}

test("FR_SKL_06 learned library keeps desktop columns", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/skills");
  await expect(page.locator(".park-skills-lib-grid")).toBeVisible();
  const list = await page.locator(".park-skills-lib-list").boundingBox();
  const detail = await page.locator(".park-skills-lib-detail").boundingBox();
  expect(list).not.toBeNull();
  expect(detail).not.toBeNull();
  if (!list || !detail) throw new Error("Library list and detail must have layout boxes");
  expect(detail.x).toBeGreaterThanOrEqual(list.x + list.width);
  expect(detail.y).toBe(list.y);
});
