// #352 (UX-1, PRD 18.1): a Section's reserve has two numbers, lines on a wide screen and lines on a phone
// (apps/web kit.tsx `--lines`, `--lines-narrow`). Every routed screen is walked at 390x844 (the narrow
// number must be the one in force) and at 1440x900 (the wide one); at both, nothing shifts while a slow
// client answers and no reserved box clips its content sideways.
import { type Page, expect, test } from "@playwright/test";
import { ALL_ROUTES } from "./support/routes";

type Box = { wide: number; narrow: number; height: number; font: number; sideways: number };

const VIEWPORTS = [
  { width: 1440, height: 900, which: "wide" },
  { width: 390, height: 844, which: "narrow" },
] as const;

async function boxes(page: Page): Promise<Box[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll<HTMLElement>(".section-box.reserved")).map((el) => ({
      wide: Number.parseFloat(el.style.getPropertyValue("--lines")),
      narrow: Number.parseFloat(el.style.getPropertyValue("--lines-narrow")),
      height: el.getBoundingClientRect().height,
      font: Number.parseFloat(getComputedStyle(el).fontSize),
      sideways: el.scrollWidth - el.clientWidth,
    })),
  );
}

const seen: Record<string, number> = { wide: 0, narrow: 0 };

// One worker walks the file in order, so the closing test sees every box the walk met.
test.describe.configure({ mode: "serial" });

for (const viewport of VIEWPORTS) {
  for (const path of ALL_ROUTES) {
    test(`UX_1 #352 reserved boxes use the ${viewport.which} number, shift nothing and clip nothing at ${viewport.width}x${viewport.height} ${path}`, async ({
      page,
    }) => {
      test.setTimeout(90_000);
      await page.setViewportSize(viewport);
      await page.goto(`${path}?speed=100`); // warm the dev server before the shifts are watched
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      await page.addInitScript(() => {
        const w = window as unknown as { __shifts: number[] };
        w.__shifts = [];
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries())
            w.__shifts.push((entry as unknown as { value: number }).value);
        }).observe({ type: "layout-shift", buffered: true });
      });
      await page.goto(`${path}?client_delay_ms=800&speed=100`, { waitUntil: "commit" });
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({
        timeout: 20_000,
      });
      await page.waitForTimeout(1500); // the slow client has answered; let a late shift be reported
      const shifts = await page.evaluate(
        () => (window as unknown as { __shifts: number[] }).__shifts,
      );
      expect(shifts).toEqual([]);
      for (const box of await boxes(page)) {
        const lines = viewport.which === "narrow" ? box.narrow : box.wide;
        expect(box.height).toBeCloseTo(lines * 1.6 * box.font, 0);
        expect(box.sideways).toBeLessThanOrEqual(1);
        if (box.narrow !== box.wide) seen[viewport.which] += 1;
      }
    });
  }
}

test("UX_1 #352 the walk met two-number reserves on both screen sizes", () => {
  // Runs last in the file (one worker per file keeps the order): a sweep that never meets a
  // two-number reserve would pass without proving anything.
  expect(seen.narrow).toBeGreaterThanOrEqual(8);
  expect(seen.wide).toBeGreaterThanOrEqual(8);
});
