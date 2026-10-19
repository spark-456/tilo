// A7 / UI-10 (W18, 14 Oct QA B item 17): /worlds was a blank sheet for 600-900 ms and then every card appeared at
// once. It now shows card-sized placeholders and fills them in. Nothing already on screen may move: the layout
// shift of a cold load of /worlds, from the first paint to the settled page, at 1440x900 and 390x844 (the
// cards reserved their slots, so the cumulative shift stays at the budget below).
// Run on a private port: TILO_WEB_PORT=5795 pnpm --filter @tilo/web exec playwright test
// e2e/park-worlds-cls-a7.spec.ts --project=chromium --no-deps --workers=1
import { type Page, expect, test } from "@playwright/test";
import { watchShifts } from "./support/shifts";

const SIZES = [
  { name: "1440x900", width: 1440, height: 900 },
  { name: "390x844", width: 390, height: 844 },
] as const;

/** Good Core Web Vitals CLS is under 0.1; this page is held to a tenth of that. */
const BUDGET = 0.01;

async function settled(page: Page): Promise<number> {
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  // cards are drawn one per task: wait until every card link is there and the count stops growing
  await expect
    .poll(async () => {
      const a = await page.locator("main a[href^='/world/']").count();
      await page.waitForTimeout(250);
      const b = await page.locator("main a[href^='/world/']").count();
      return a > 0 && a === b;
    })
    .toBe(true);
  await page.waitForTimeout(500);
  return page.evaluate(() =>
    ((window as unknown as { __shifts: number[] }).__shifts ?? []).reduce((s, v) => s + v, 0),
  );
}

for (const size of SIZES) {
  test.describe(`UI-10 A7 worlds list at ${size.name}`, () => {
    test.use({ viewport: { width: size.width, height: size.height } });

    test(`UI_10_A7_${size.name}_cold_load_of_worlds_stays_within_the_shift_budget`, async ({
      page,
    }) => {
      await watchShifts(page);
      await page.goto("/worlds", { timeout: 120_000 });
      const total = await settled(page);
      expect(total, "cumulative layout shift").toBeLessThanOrEqual(BUDGET);
    });

    test(`UI_10_A7_${size.name}_whitespace_search_filters_nothing`, async ({ page }) => {
      await page.goto("/worlds", { timeout: 120_000 });
      await settled(page).catch(() => undefined);
      const cards = page.locator("main a[href^='/world/']");
      const before = await cards.count();
      await page.getByLabel("Search worlds").fill("   ");
      await expect(cards).toHaveCount(before);
      await expect(page.getByText(/No worlds match/)).toHaveCount(0);
    });
  });
}
