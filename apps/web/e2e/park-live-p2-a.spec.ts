// LIVE-P2-A (agy-bridge/reports/LIVE-QA-14OCT-1730.md rows 20, 24, 25, 26, 27, 29): bounding boxes and names.
// Run on a private port: TILO_WEB_PORT=5795 pnpm --filter @tilo/web exec playwright test
// e2e/park-live-p2-a.spec.ts --project=chromium --no-deps --workers=1 (heavy.lock first).
import { type Page, expect, test } from "@playwright/test";

const input = (page: Page) => page.getByRole("textbox", { name: "Describe your task" });

async function openHome(page: Page): Promise<void> {
  await page.goto("/", { timeout: 120_000 });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    /^Good (morning|afternoon|evening), Alex\.$/,
    { timeout: 120_000 },
  );
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
}

test.describe("LIVE-P2-A at 1440x900", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("LIVE_P2_A_20_the_open_plan_card_scrolls_nothing_and_closes_back_to_the_tiles", async ({
    page,
  }) => {
    await openHome(page);
    await input(page).fill("Compare three suppliers for office coffee");
    await page.getByRole("button", { name: "Start task", exact: true }).click();
    await expect(page.locator(".park-home-plan")).toBeVisible({ timeout: 10_000 });
    const m = await page.evaluate(() => {
      const box = (s: string) => {
        const el = document.querySelector<HTMLElement>(s);
        return el
          ? { scroll: el.scrollHeight, client: el.clientHeight, shown: el.offsetParent !== null }
          : null;
      };
      return {
        left: box(".park-home-leftcol"),
        today: box(".park-home-today"),
        kpis: box(".park-home-kpis"),
      };
    });
    expect(m.left && m.today).toBeTruthy();
    expect(m.left?.scroll, "greeting column has nothing to scroll").toBeLessThanOrEqual(
      (m.left?.client ?? 0) + 1,
    );
    expect(m.today?.scroll, "Today panel has nothing to scroll").toBeLessThanOrEqual(
      (m.today?.client ?? 0) + 1,
    );
    expect(m.kpis?.shown ?? false, "the stat tiles step aside while the card is open").toBe(false);
    await page.keyboard.press("Escape");
    await expect(page.locator(".park-home-kpis")).toBeVisible();
  });

  test("LIVE_P2_A_25_worlds_cards_have_names_and_27_the_breadcrumb_is_a_real_address", async ({
    page,
  }) => {
    await page.goto("/worlds", { timeout: 120_000 });
    const cards = page.locator("a.park-worlds-card:not(.park-worlds-skeleton)");
    await expect(cards.first()).toBeVisible({ timeout: 60_000 });
    const names = await cards.evaluateAll((els) => els.map((e) => e.getAttribute("aria-label")));
    expect(names.length).toBeGreaterThan(0);
    for (const n of names) expect((n ?? "").trim().length).toBeGreaterThan(0);

    await page.goto("/world/k1", { timeout: 120_000 });
    const back = page.locator(".park-world-back").first();
    await expect(back).toBeVisible({ timeout: 60_000 });
    expect(new URL((await back.getAttribute("href")) ?? "", page.url()).pathname).toBe("/worlds");
  });

  test("LIVE_P2_A_24_the_demo_toast_stays_off_the_map_legend", async ({ page }) => {
    await page.goto("/world/k1", { timeout: 120_000 });
    await expect(page.locator(".park-world-back").first()).toBeVisible({ timeout: 60_000 });
    const approve = page.getByRole("button", { name: /^Approve/ }).first();
    test.skip((await approve.count()) === 0, "no demo decision on this world to raise the toast");
    await approve.click();
    const toast = page.locator(".park-toast").first();
    await expect(toast).toBeVisible();
    await page.waitForTimeout(400); // the toast's own 0.25 s entrance
    const legend = page.locator(".park-world-legend:not([hidden])").first();
    if ((await legend.count()) === 0) return;
    const a = await toast.boundingBox();
    const b = await legend.boundingBox();
    if (!(a && b)) return;
    const overlap =
      a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
    expect(overlap, "the toast does not cover the legend").toBe(false);
  });
});

test.describe("LIVE-P2-A at 390x844", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("LIVE_P2_A_26_team_is_cards_not_a_sideways_table_and_skill_names_wrap", async ({ page }) => {
    await page.goto("/team", { timeout: 120_000 });
    await expect(page.locator(".park-team-members")).toBeVisible({ timeout: 60_000 });
    const t = await page.evaluate(() => {
      const scroll = document.querySelector<HTMLElement>(".park-team-scroll");
      const table = document.querySelector<HTMLElement>(".park-team-table");
      return {
        page: document.documentElement.scrollWidth,
        scrollOver: scroll ? scroll.scrollWidth - scroll.clientWidth : 0,
        tableW: table?.getBoundingClientRect().width ?? 0,
      };
    });
    expect(t.page).toBeLessThanOrEqual(390);
    expect(t.scrollOver, "the members card does not scroll sideways").toBeLessThanOrEqual(1);
    expect(t.tableW).toBeLessThanOrEqual(390);

    await page.goto("/skills", { timeout: 120_000 });
    await expect(page.locator(".park-skills-lib-row-name").first()).toBeVisible({
      timeout: 60_000,
    });
    const clipped = await page
      .locator(".park-skills-lib-row-name")
      .evaluateAll(
        (els) => els.filter((e) => getComputedStyle(e).textOverflow === "ellipsis").length,
      );
    expect(clipped, "skill names wrap instead of ending in an ellipsis").toBe(0);
  });
});
