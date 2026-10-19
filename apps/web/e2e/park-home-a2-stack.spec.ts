// A2 / UI-10 (14 Oct QA, agy-bridge/reports/QA-SWEEP-14OCT-A-home.md item 2): under 1180px Home left out the spend
// tiles, the Sample worlds list, Up next today and October spend. They now stack in one scrolling column:
// greeting, composer, spend tiles, Today panel, legal strip. Bounding boxes at 1024x768, 768x1024 and 390x844:
// everything exists, sits inside the window sideways, follows the one above it and is reachable by scrolling.
// Run on a private port: TILO_WEB_PORT=5795 pnpm --filter @tilo/web exec playwright test
// e2e/park-home-a2-stack.spec.ts --project=chromium --no-deps --workers=1
import { type Page, expect, test } from "@playwright/test";

const SIZES = [
  { width: 1024, height: 768 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
] as const;

interface Box {
  name: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

async function openHome(page: Page): Promise<void> {
  await page.goto("/", { timeout: 120_000 });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    /^Good (morning|evening), Alex\.$/,
    { timeout: 120_000 },
  );
  await expect(page.getByRole("button", { name: "Start task", exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
}

for (const size of SIZES) {
  const label = `${size.width}x${size.height}`;
  test.describe(`UI-10 A2 home stack at ${label}`, () => {
    test.use({ viewport: size });

    test(`UI_10_A2_${label}_tiles_worlds_agenda_and_spend_are_rendered_in_one_column`, async ({
      page,
    }) => {
      await openHome(page);
      const found = await page.evaluate(() => {
        const box = (name: string, el: Element | null): Box | null => {
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return {
            name,
            x: r.x,
            y: r.y + (document.querySelector(".park-home-root")?.scrollTop ?? 0),
            w: r.width,
            h: r.height,
          };
        };
        const today = document.querySelector(".park-home-today");
        const titles = [...(today?.querySelectorAll(".park-home-title") ?? [])].map(
          (e) => e.textContent ?? "",
        );
        return {
          titles,
          tiles: document.querySelectorAll(".park-home-kpis .park-kpi").length,
          asides: document.querySelectorAll('aside[aria-label="Today"]').length,
          boxes: [
            box("greeting", document.querySelector(".park-home-hero")),
            box("composer", document.querySelector(".park-home-composer")),
            box("tiles", document.querySelector(".park-home-kpis")),
            box("today", today),
            box("spend", document.querySelector(".park-home-spend")),
          ],
          scrollW: document.documentElement.scrollWidth,
        };
      });
      expect(found.tiles).toBe(5);
      expect(found.titles.join("|")).toMatch(/Sample worlds.*spend/);
      expect(found.titles.join("|")).not.toContain("Up next today");
      expect(found.asides, "no Today aside under 1180").toBe(0);
      const boxes = found.boxes.filter((b): b is Box => b !== null);
      expect(boxes.map((b) => b.name)).toEqual(["greeting", "composer", "tiles", "today", "spend"]);
      // sideways: inside the window, and the page does not scroll sideways
      for (const b of boxes) {
        expect(b.x, `${b.name} left edge`).toBeGreaterThanOrEqual(0);
        expect(b.x + b.w, `${b.name} right edge`).toBeLessThanOrEqual(size.width + 0.5);
      }
      expect(found.scrollW).toBeLessThanOrEqual(size.width);
      // downwards: each block follows the one above it (the spend card is inside the Today panel)
      const [greeting, composer, tiles, today, spend] = boxes as [Box, Box, Box, Box, Box];
      expect(composer.y).toBeGreaterThanOrEqual(greeting.y + greeting.h - 0.5);
      expect(tiles.y).toBeGreaterThanOrEqual(composer.y + composer.h - 0.5);
      expect(today.y).toBeGreaterThanOrEqual(tiles.y + tiles.h - 0.5);
      expect(spend.y + spend.h).toBeLessThanOrEqual(today.y + today.h + 0.5);
    });

    test(`UI_10_A2_${label}_the_spend_card_is_reachable_by_scrolling_the_page`, async ({
      page,
    }) => {
      await openHome(page);
      const reach = await page.evaluate(() => {
        const root = document.querySelector<HTMLElement>(".park-home-root");
        const spend = document.querySelector<HTMLElement>(".park-home-spend");
        if (!(root && spend)) return null;
        spend.scrollIntoView({ block: "end" });
        const r = spend.getBoundingClientRect();
        const rr = root.getBoundingClientRect();
        // the element on top at the card's centre is the card (or inside it): nothing lies over it
        const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return {
          inside: r.top >= rr.top - 0.5 && r.bottom <= rr.bottom + 0.5,
          clear: !!top && spend.contains(top),
        };
      });
      expect(reach).toEqual({ inside: true, clear: true });
    });
  });
}
