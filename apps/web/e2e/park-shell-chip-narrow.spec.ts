// WEB-3b follow-up: at narrow widths the "Sample data" chip must not overlap or clip the nav tabs. The tabs scroll sideways
// inside their own container (`.park-shell__tabs`), so "not clipped" means every tab's text is reachable: the chip's box
// never intersects the tabs container's box, the container is wide enough to show the first tab (Home) fully, and the
// chip keeps its accessible name "Sample data".
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-shell-chip-narrow.spec.ts --project=chromium --no-deps --workers=1
import { expect, test } from "@playwright/test";

const WIDTHS = [360, 375, 390, 414, 560] as const;

for (const width of WIDTHS) {
  test.describe(`park nav chip at ${width}`, () => {
    test.use({ viewport: { width, height: 844 } });

    test(`UI_10_WEB_3b_e2e_${width}_the_sample_chip_does_not_overlap_or_clip_the_nav_tabs`, async ({
      page,
    }) => {
      test.setTimeout(150_000);
      await page.goto("/park", { timeout: 120_000 });
      const nav = page.locator("header.park-shell__nav");
      const chip = nav.getByRole("button", { name: "Sample data" });
      await expect(chip).toBeVisible({ timeout: 120_000 });
      const m = await nav.evaluate((header) => {
        const box = (el: Element) => {
          const r = el.getBoundingClientRect();
          return { l: r.left, r: r.right, t: r.top, b: r.bottom };
        };
        const tabs = header.querySelector(".park-shell__tabs") as HTMLElement;
        const chipEl = header.querySelector("button.park-shell__sample") as HTMLElement;
        const home = tabs.querySelector(".park-shell__tab") as HTMLElement;
        return {
          chip: box(chipEl),
          tabs: box(tabs),
          home: box(home),
          homeText: home.textContent,
          tabsScroll: tabs.scrollWidth,
          tabsClient: tabs.clientWidth,
          allTabs: [...tabs.querySelectorAll(".park-shell__tab")].map((t) => box(t)),
        };
      });
      const overlap = (a: { l: number; r: number }, b: { l: number; r: number }) =>
        a.l < b.r && b.l < a.r;
      // The chip never sits over the tab strip (and so never over any tab drawn inside it).
      expect(
        overlap(m.chip, m.tabs),
        `chip ${JSON.stringify(m.chip)} vs tabs ${JSON.stringify(m.tabs)}`,
      ).toBe(false);
      // The first tab is fully inside the visible strip: its text is not clipped ("Home", not "Hom").
      expect(m.homeText).toBe("Home");
      expect(m.home.l).toBeGreaterThanOrEqual(m.tabs.l - 0.5);
      expect(m.home.r).toBeLessThanOrEqual(m.tabs.r + 0.5);
      // The other tabs are still reachable by scrolling the strip.
      expect(m.allTabs).toHaveLength(6);
      await expect(chip).toHaveAccessibleName("Sample data");
    });
  });
}
