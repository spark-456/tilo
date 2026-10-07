// NFR-01 (ticket NFR-01-LANDING): the landing page (/) is painted first and its city is drawn afterwards (a
// poster holds the backdrop's place). Nothing may move on the way: not when the first frame replaces the root
// frame, not when the boot splash goes, not when the city replaces the poster, not when the pins appear. A cold
// load of "/" at 1440 and 390 is measured from the start of navigation with a layout-shift PerformanceObserver
// (entries without recent input), and the measurement waits until the CITY has been drawn (the poster is
// gone), the fonts are in and two frames have passed (promises only, no fixed sleep). The cumulative shift
// must be 0. park-shell-cls.spec.ts measures the same page, but only up to "the shell is up".
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-landing-cls.spec.ts --project=chromium --no-deps --workers=1
import { type Page, expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it
// once per worker so no test pays for it.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(240_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/", { timeout: 200_000 });
  await page
    .locator("header")
    .waitFor({ timeout: 200_000 })
    .catch(() => undefined);
  await page.close();
});

const observe = (page: Page) =>
  page.addInitScript(() => {
    const seen = { total: 0 };
    const po = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        const shift = e as PerformanceEntry & { value: number; hadRecentInput: boolean };
        if (!shift.hadRecentInput) seen.total += shift.value;
      }
    });
    po.observe({ type: "layout-shift", buffered: true });
    Reflect.set(window, "__shift", { seen, po });
  });

const shift = (page: Page): Promise<number> =>
  page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise<void>((done) =>
      requestAnimationFrame(() => requestAnimationFrame(() => done())),
    );
    const held = Reflect.get(window, "__shift") as {
      seen: { total: number };
      po: PerformanceObserver;
    };
    for (const e of held.po.takeRecords()) {
      const s = e as PerformanceEntry & { value: number; hadRecentInput: boolean };
      if (!s.hadRecentInput) held.seen.total += s.value;
    }
    return held.seen.total;
  });

for (const [name, viewport] of Object.entries(SIZES)) {
  test.describe(`landing layout shift at ${name}`, () => {
    test.use({ viewport });

    test(`NFR_01_LANDING_e2e_${name}_cold_landing_shifts_nothing_from_the_first_frame_to_the_drawn_city`, async ({
      page,
    }) => {
      await observe(page);
      await page.goto("/", { waitUntil: "commit" });
      await expect(page.getByLabel("Describe your task")).toBeVisible();
      // the city is drawn: its pictures are in the backdrop and the poster has gone
      await expect(page.locator(".park-shell__scene img").first()).toBeAttached({
        timeout: 20_000,
      });
      await expect(page.getByTestId("park-shell-poster")).toHaveCount(0);
      await expect.poll(() => page.evaluate(() => document.fonts.status)).toBe("loaded");
      expect(await shift(page)).toBe(0);
    });
  });
}
