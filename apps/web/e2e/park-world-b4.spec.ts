// UI-10 B4: the lens tabs of a sample City are keyboard-focusable with the reason on the page, the lens pill stays
// inside the map at 320 and 390, the legend is a tidy two-column grid on a phone and tap targets are >= 24px.
// Run on a private port: TILO_WEB_PORT=5796 pnpm --filter @tilo/web exec playwright test e2e/park-world-b4.spec.ts
import { type Page, expect, test } from "@playwright/test";

async function open(page: Page) {
  await page.goto("/world/k1");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
}

// POLISH-2: a sample world offers no lens links or live view (they read as broken when greyed out): one chip says why.
// The lens pill's own layout (inside the map at 320 and 390, 24px targets) is pinned in vitest for live worlds
// (World.WORLD-DESIGN.test.tsx, World.stage.test.tsx); a fixture build has no live world to open here.
test("UI_10_B4_sample_has_no_lens_tabs_and_the_reason_is_a_visible_chip", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  await expect(page.getByRole("navigation", { name: "Run views" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Open live view" })).toHaveCount(0);
  const reason = page.locator(".park-world-nostage");
  await expect(reason).toBeVisible();
  await expect(reason).toHaveText("Live view is for real runs");
});

for (const width of [320, 390]) {
  test(`UI_10_B4_${width}_the_sample_chip_stays_on_the_page_and_nothing_overflows`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 });
    await open(page);
    const chip = await page.locator(".park-world-nostage").boundingBox();
    if (!chip) throw new Error("no chip");
    expect(chip.x).toBeGreaterThanOrEqual(0);
    expect(chip.x + chip.width).toBeLessThanOrEqual(width);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
}

test("UI_10_B4_390_legend_is_a_two_column_grid_with_no_orphan_row", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const items = page.locator(".park-world-legenditem");
  expect(await items.count()).toBe(4);
  const boxes = [];
  for (let i = 0; i < 4; i++) {
    const b = await items.nth(i).boundingBox();
    if (!b) throw new Error("legend item has no box");
    boxes.push(b);
  }
  // two rows of two: the first two share a row, the last two share the next, columns line up
  expect(Math.abs((boxes[0]?.y ?? 0) - (boxes[1]?.y ?? 99))).toBeLessThan(2);
  expect(Math.abs((boxes[2]?.y ?? 0) - (boxes[3]?.y ?? 99))).toBeLessThan(2);
  expect(Math.abs((boxes[0]?.x ?? 0) - (boxes[2]?.x ?? 99))).toBeLessThan(2);
});
