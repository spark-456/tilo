// UI-10 B4: the lens tabs of a sample City are keyboard-focusable with the reason on the page, the lens pill stays
// inside the map at 320 and 390, the legend is a tidy two-column grid on a phone and tap targets are >= 24px.
// Run on a private port: TILO_WEB_PORT=5796 pnpm --filter @tilo/web exec playwright test e2e/park-world-b4.spec.ts
import { type Page, expect, test } from "@playwright/test";

async function open(page: Page) {
  await page.goto("/world/k1");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
}

test("UI_10_B4_sample_lens_tabs_take_focus_and_the_reason_is_visible", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  const nav = page.getByRole("navigation", { name: "Run views" });
  for (const name of ["Story", "Trace", "Delivery", "Inspect"]) {
    const link = nav.getByRole("link", { name });
    await link.focus();
    await expect(link).toBeFocused();
    await expect(link).toHaveAttribute("aria-disabled", "true");
  }
  const reason = page.locator(".park-world-nostage");
  await expect(reason).toBeVisible();
  await expect(reason).toHaveText("Sample world: there is no recorded run to open");
  const live = page.getByRole("link", { name: "Open live view" });
  await live.focus();
  await expect(live).toBeFocused();
});

for (const width of [320, 390]) {
  test(`UI_10_B4_${width}_lens_pill_stays_inside_the_map_and_targets_are_24px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 });
    await open(page);
    const map = await page.locator(".park-world-map").first().boundingBox();
    const nav = await page.getByRole("navigation", { name: "Run views" }).boundingBox();
    if (!map || !nav) throw new Error("no map or lens nav");
    expect(nav.x).toBeGreaterThanOrEqual(map.x - 0.5);
    expect(nav.x + nav.width).toBeLessThanOrEqual(map.x + map.width + 0.5);
    expect(nav.x + nav.width).toBeLessThanOrEqual(width);
    const links = page.getByRole("navigation", { name: "Run views" }).getByRole("link");
    for (let i = 0; i < (await links.count()); i++) {
      const box = await links.nth(i).boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(24);
    }
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
