// A3 / UI-10 (14 Oct QA, agy-bridge/reports/QA-SWEEP-14OCT-A-home.md item 4): a 4,500-character unbroken task ran
// out of the plan card and under "Open the sample world", the task box had no cap, Esc did not close the card,
// "Change brief" dropped focus on <body>, and the card lay over the stat tiles and the right panel.
// Bounding boxes at 1440x900. Run on a private port: TILO_WEB_PORT=5795 pnpm --filter @tilo/web exec playwright
// test e2e/park-home-a3-plan-card.spec.ts --project=chromium --no-deps --workers=1
import { type Page, expect, test } from "@playwright/test";

test.use({ viewport: { width: 1440, height: 900 } });

const input = (page: Page) => page.getByRole("textbox", { name: "Describe your task" });
const start = (page: Page) => page.getByRole("button", { name: "Start task", exact: true });

async function openHome(page: Page): Promise<void> {
  await page.goto("/", { timeout: 120_000 });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    /^Good (morning|evening), Alex\.$/,
    { timeout: 120_000 },
  );
  await expect(start(page)).toBeVisible();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
}

async function openPlan(page: Page, text: string): Promise<void> {
  await input(page).fill(text);
  await start(page).click();
  await expect(page.locator(".park-home-plan")).toBeVisible({ timeout: 10_000 });
}

test.describe("UI-10 A3 home plan card at 1440x900", () => {
  test("UI_10_A3_the_task_box_has_the_servers_cap_and_a_long_paste_stops_there", async ({
    page,
  }) => {
    await openHome(page);
    await expect(input(page)).toHaveAttribute("maxlength", "4000");
    await input(page).fill("B".repeat(4500));
    expect((await input(page).inputValue()).length).toBe(4000);
  });

  test("UI_10_A3_a_long_unbroken_task_stays_inside_the_card_and_clear_of_the_buttons", async ({
    page,
  }) => {
    await openHome(page);
    await openPlan(page, "A".repeat(4000));
    const m = await page.evaluate(() => {
      const r = (s: string) => document.querySelector(s)?.getBoundingClientRect();
      const card = r(".park-home-plan");
      const query = r(".park-home-plan__query");
      const confirm = r(".park-home-confirm");
      return {
        card: card && { l: card.left, r: card.right, t: card.top, b: card.bottom },
        query: query && { l: query.left, r: query.right, b: query.bottom },
        confirm: confirm && { l: confirm.left, t: confirm.top },
        scrollW: document.documentElement.scrollWidth,
      };
    });
    expect(m.card && m.query && m.confirm).toBeTruthy();
    if (!(m.card && m.query && m.confirm)) return;
    expect(m.query.r, "title ends inside the card").toBeLessThanOrEqual(m.card.r);
    expect(m.query.r, "title ends before the confirm button").toBeLessThanOrEqual(
      m.confirm.l + 0.5,
    );
    expect(m.query.b, "title ends inside the card").toBeLessThanOrEqual(m.card.b);
    expect(m.scrollW).toBeLessThanOrEqual(1440);
  });

  test("UI_10_A3_the_plan_card_does_not_lie_over_the_stat_tiles_or_the_right_panel", async ({
    page,
  }) => {
    await openHome(page);
    await openPlan(page, "Compare three suppliers for office coffee");
    const m = await page.evaluate(() => {
      const r = (s: string) => document.querySelector(s)?.getBoundingClientRect();
      const q = (el: DOMRect | undefined) =>
        el && { l: el.left, r: el.right, t: el.top, b: el.bottom };
      const left = document.querySelector<HTMLElement>(".park-home-leftcol");
      const tiles = [...document.querySelectorAll(".park-home-kpis .park-kpi")].map((e) =>
        e.getBoundingClientRect(),
      );
      const leftBox = left?.getBoundingClientRect();
      // a tile counts as shown when it lies inside the column's visible box; the column scrolls for the rest
      const shown = tiles.filter(
        (t) => leftBox && t.top >= leftBox.top - 0.5 && t.bottom <= leftBox.bottom + 0.5,
      );
      return {
        card: q(r(".park-home-plan")),
        left: q(leftBox),
        today: q(r(".park-home-today")),
        scrolls: !!left && left.scrollHeight > left.clientHeight,
        tiles: tiles.length,
        shown: shown.length,
      };
    });
    expect(m.card && m.left && m.today).toBeTruthy();
    if (!(m.card && m.left && m.today)) return;
    expect(m.left.b, "greeting column ends above the card").toBeLessThanOrEqual(m.card.t);
    expect(m.today.b, "Today panel ends above the card").toBeLessThanOrEqual(m.card.t);
    // the tiles are not lost: they are all there, behind the column's own scroll
    expect(m.tiles).toBe(5);
    expect(m.scrolls).toBe(true);
  });

  test("UI_10_A3_Esc_closes_the_plan_card_and_focus_is_in_the_task_box", async ({ page }) => {
    await openHome(page);
    await openPlan(page, "Compare three suppliers");
    await page.keyboard.press("Escape");
    await expect(page.locator(".park-home-plan")).toHaveCount(0);
    await expect(input(page)).toBeFocused();
    await expect(input(page)).toHaveValue("Compare three suppliers");
  });

  test("UI_10_A3_Change_brief_returns_focus_to_the_task_box", async ({ page }) => {
    await openHome(page);
    await openPlan(page, "Compare three suppliers");
    await page.getByRole("button", { name: "Change brief" }).click();
    await expect(page.locator(".park-home-plan")).toHaveCount(0);
    await expect(input(page)).toBeFocused();
  });
});
