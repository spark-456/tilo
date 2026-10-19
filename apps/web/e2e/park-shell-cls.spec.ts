// WEB-3b: the shell does not move once it is on screen (Core Web Vitals CLS; README "Performance"). A cold
// load of /worlds and / (home) at 1440 and 390 is measured with a layout-shift PerformanceObserver
// (entries without recent input) after the page has settled: the main landmark and the Sample data chip are
// there, the fonts have loaded and two frames have passed (promises only, no fixed sleep). The cumulative
// shift must be 0. Each test is its own browser context, so every load is cold.
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-shell-cls.spec.ts --project=chromium --no-deps --workers=3
import { type Page, expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;
const PATHS = ["/worlds", "/"] as const;

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
    // two frames, so a late paint or reflow has been reported
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
  test.describe(`park shell layout shift at ${name}`, () => {
    test.use({ viewport });

    for (const path of PATHS) {
      test(`WEB_3b_e2e_${name}_cold_load_of_${path === "/" ? "home" : path.slice(1)}_shifts_nothing`, async ({
        page,
      }) => {
        await observe(page);
        await page.goto(path);
        await expect(page.getByRole("main")).toBeVisible();
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await expect(
          page.locator("header").getByRole("button", { name: "Sample data" }),
        ).toBeVisible();
        await expect.poll(() => page.evaluate(() => document.fonts.status)).toBe("loaded");
        expect(await shift(page)).toBe(0);
      });
    }
  });
}
