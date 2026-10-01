import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;

for (const [name, viewport] of Object.entries(SIZES)) {
  test.describe(`${name} accessibility`, () => {
    test.use({ viewport });

    test(`PRD-17.5 accessibility: WCAG 2.2 AA axe scan is clean at ${name} size`, async ({
      page,
    }) => {
      await page.goto("/");
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze();
      expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
    });

    test(`PRD-17.5 accessibility: landmarks exist at ${name} size`, async ({ page }) => {
      await page.goto("/");
      await expect(page.getByRole("navigation")).toBeVisible();
      await expect(page.getByRole("main")).toBeVisible();
    });

    test(`PRD-17.5 accessibility: interactive targets meet the ${
      name === "mobile" ? "44x44" : "24x24"
    } px minimum`, async ({ page }) => {
      await page.goto("/");
      const minSide = name === "mobile" ? 44 : 24;
      const targets = page.getByRole("link").or(page.getByRole("button"));
      const count = await targets.count();
      expect(count, "no interactive targets found to check").toBeGreaterThan(0);
      for (let i = 0; i < count; i++) {
        const box = await targets.nth(i).boundingBox();
        if (!box) continue;
        expect(box.width, `target ${i} is narrower than ${minSide}px`).toBeGreaterThanOrEqual(
          minSide,
        );
        expect(box.height, `target ${i} is shorter than ${minSide}px`).toBeGreaterThanOrEqual(
          minSide,
        );
      }
    });
  });
}

test("PRD-17.5 accessibility: keyboard focus is always visible", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");

  const outline = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return null;
    const style = getComputedStyle(el);
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      boxShadow: style.boxShadow,
    };
  });

  expect(outline, "Tab did not move focus to any element").not.toBeNull();
  const safeOutline = outline as NonNullable<typeof outline>;
  const hasVisibleOutline =
    safeOutline.outlineStyle !== "none" && Number.parseFloat(safeOutline.outlineWidth) > 0;
  const hasVisibleBoxShadow = safeOutline.boxShadow !== "none";
  expect(
    hasVisibleOutline || hasVisibleBoxShadow,
    "the focused element has no visible focus indicator (PRD 17.5 keyboard pass)",
  ).toBe(true);
});
