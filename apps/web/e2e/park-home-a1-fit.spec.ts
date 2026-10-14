// A1 / UI-10 (14 Oct QA, agy-bridge/reports/QA-SWEEP-14OCT-A-home.md item 1): on a laptop-sized window the example
// chips and the composer laid over the stat tiles and the right panel. Bounding boxes at 1440x900, 1280x720 and
// 1920x1080: no panel reaches under the composer, every spend tile and the October spend card is whole and above
// it, and where the window is too short (1280x720) the greeting column scrolls instead of being covered.
// Run on a private port: TILO_WEB_PORT=5795 pnpm --filter @tilo/web exec playwright test
// e2e/park-home-a1-fit.spec.ts --project=chromium --no-deps --workers=1
import { type Page, expect, test } from "@playwright/test";

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

const SIZES = [
  { name: "1440x900", width: 1440, height: 900, allVisible: true },
  { name: "1920x1080", width: 1920, height: 1080, allVisible: true },
  { name: "1280x720", width: 1280, height: 720, allVisible: false },
] as const;

async function openHome(page: Page): Promise<void> {
  await page.goto("/", { timeout: 120_000 });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    /^Good (morning|evening), Alex\.$/,
    { timeout: 120_000 },
  );
  await expect(page.getByRole("button", { name: "Start task", exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  // the composer's height is published once the composer is laid out; wait for the property
  await page.waitForFunction(
    () =>
      document
        .querySelector<HTMLElement>(".park-home-root")
        ?.style.getPropertyValue("--park-home-composer-h") !== "",
  );
}

for (const size of SIZES) {
  test.describe(`UI-10 A1 home fit at ${size.name}`, () => {
    test.use({ viewport: { width: size.width, height: size.height } });

    test(`UI_10_A1_${size.name}_no_panel_runs_under_the_composer`, async ({ page }) => {
      await openHome(page);
      const m = await page.evaluate(() => {
        const q = (s: string): Box | null => {
          const r = document.querySelector(s)?.getBoundingClientRect();
          return r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null;
        };
        return {
          chips: q(".park-home-chips"),
          panel: q(".park-home-panel"),
          left: q(".park-home-leftcol"),
          today: q(".park-home-today"),
        };
      });
      const { chips, panel, left, today } = m;
      expect(chips && panel && left && today).toBeTruthy();
      if (!(chips && panel && left && today)) return;
      // the greeting column and the Today panel end above the chips row (the narrowest thing under them)
      expect(left.y + left.h, "greeting column bottom vs chips top").toBeLessThanOrEqual(chips.y);
      const sideBySide = today.x < chips.x + chips.w && today.x + today.w > chips.x;
      const limit = sideBySide ? chips.y : panel.y;
      expect(today.y + today.h, "Today panel bottom vs the composer").toBeLessThanOrEqual(limit);
    });

    test(`UI_10_A1_${size.name}_stat_tiles_and_spend_card_are_whole_${
      size.allVisible ? "on_screen" : "behind_one_scroll"
    }`, async ({ page }) => {
      await openHome(page);
      if (!size.allVisible) {
        // too short to show everything: the greeting column is the one scroller, and it scrolls
        const scrolls = await page
          .locator(".park-home-leftcol")
          .evaluate(
            (el) => el.scrollHeight > el.clientHeight && getComputedStyle(el).overflowY === "auto",
          );
        expect(scrolls).toBe(true);
        await page.locator(".park-home-leftcol").evaluate((el) => {
          el.scrollTop = el.scrollHeight;
        });
      }
      const tiles = await page.evaluate(() => {
        const left = document.querySelector(".park-home-leftcol")?.getBoundingClientRect();
        return [...document.querySelectorAll(".park-home-kpis .park-kpi")].map((el) => {
          const r = el.getBoundingClientRect();
          return {
            text: (el.textContent ?? "").trim(),
            top: r.top,
            bottom: r.bottom,
            // fully inside the column that holds it
            inside: !!left && r.top >= left.top - 0.5 && r.bottom <= left.bottom + 0.5,
            clipped: [...el.querySelectorAll("*")].some((c) => c.scrollWidth > c.clientWidth + 1),
          };
        });
      });
      expect(tiles).toHaveLength(5);
      for (const t of tiles) {
        expect(t.inside, `${t.text} is inside the greeting column`).toBe(true);
        expect(t.clipped, `${t.text} has no cut text`).toBe(false);
      }
      const kpisClipped = await page
        .locator(".park-home-kpis")
        .evaluate((el) => el.scrollHeight - el.clientHeight);
      expect(kpisClipped, "the tile strip itself does not scroll").toBeLessThanOrEqual(1);

      if (size.allVisible) {
        // the October spend card (Today panel, last block) is fully inside the panel's visible box
        const spend = await page.evaluate(() => {
          const today = document.querySelector(".park-home-today")?.getBoundingClientRect();
          const card = document.querySelector(".park-home-spend")?.getBoundingClientRect();
          const panel = document.querySelector(".park-home-panel")?.getBoundingClientRect();
          return today && card && panel
            ? { inside: card.bottom <= today.bottom + 0.5, aboveComposer: card.bottom <= panel.top }
            : null;
        });
        expect(spend).toEqual({ inside: true, aboveComposer: true });
      }
    });
  });
}
