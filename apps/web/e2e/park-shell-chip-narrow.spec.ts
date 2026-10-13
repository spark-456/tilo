// WEB-3b follow-up: at narrow widths the "Sample data" chip must not overlap or clip the nav. Below 840px the six tabs
// are one page button (`.park-shell__pagebtn`, QA-DEMO-1 B2) that names the current page and opens a menu of all six,
// so "not clipped" means the page name is whole and every page is reachable from the menu: the chip's box never
// intersects the page button's box, the label is not truncated at 390 and wider, and the chip keeps its accessible
// name "Sample data".
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-shell-chip-narrow.spec.ts --project=chromium --no-deps --workers=1
import { expect, test } from "@playwright/test";

const WIDTHS = [320, 360, 375, 390, 414, 560] as const;
const HOME_WHOLE_FROM = 390; // the narrowest width at which the reference nav leaves the Home tab room

for (const width of WIDTHS) {
  test.describe(`park nav chip at ${width}`, () => {
    test.use({ viewport: { width, height: 844 } });

    test(`UI_10_WEB_3b_e2e_${width}_the_sample_chip_does_not_overlap_or_clip_the_nav_tabs`, async ({
      page,
    }) => {
      test.setTimeout(150_000);
      await page.goto("/", { timeout: 120_000 });
      const nav = page.locator("header.park-shell__nav");
      const chip = nav.getByRole("button", { name: "Sample data" });
      await expect(chip).toBeVisible({ timeout: 120_000 });
      const m = await nav.evaluate((header) => {
        const box = (el: Element) => {
          const r = el.getBoundingClientRect();
          return { l: r.left, r: r.right, t: r.top, b: r.bottom };
        };
        const tabs = header.querySelector(".park-shell__pagebtn") as HTMLElement;
        const chipEl = header.querySelector("button.park-shell__sample") as HTMLElement;
        const home = tabs.querySelector(".park-shell__pagelabel") as HTMLElement;
        return {
          chip: box(chipEl),
          tabs: box(tabs),
          home: box(home),
          homeText: home.textContent,
          clipped: home.scrollWidth > home.clientWidth,
        };
      });
      const overlap = (a: { l: number; r: number }, b: { l: number; r: number }) =>
        a.l < b.r && b.l < a.r;
      // The chip never sits over the tab strip (and so never over any tab drawn inside it).
      expect(
        overlap(m.chip, m.tabs),
        `chip ${JSON.stringify(m.chip)} vs tabs ${JSON.stringify(m.tabs)}`,
      ).toBe(false);
      // The page is named whole ("Home", not "Ho..."), and every page is in the menu.
      expect(m.homeText).toBe("Home");
      if (width >= HOME_WHOLE_FROM) expect(m.clipped).toBe(false);
      await nav.locator("button.park-shell__pagebtn").click();
      await expect(page.getByRole("menuitem")).toHaveCount(6);
      await expect(chip).toHaveAccessibleName("Sample data");
    });

    test(`UI_10_WEB_3b_e2e_${width}_the_sample_chip_is_a_24px_target_and_its_focus_ring_hugs_the_dot`, async ({
      page,
    }) => {
      test.setTimeout(150_000);
      await page.goto("/", { timeout: 120_000 });
      const chip = page
        .locator("header.park-shell__nav")
        .getByRole("button", { name: "Sample data" });
      await expect(chip).toBeVisible({ timeout: 120_000 });
      const box = await chip.boundingBox();
      expect(box?.width, "WCAG 2.5.8 target width").toBeGreaterThanOrEqual(24);
      expect(box?.height, "WCAG 2.5.8 target height").toBeGreaterThanOrEqual(24);
      // P0-08b W4: a 24px box is insufficient if another control covers its hit area.
      const unobscured = await chip.evaluate((el) => {
        const r = el.getBoundingClientRect();
        return [1, r.width / 2, r.width - 1].every((x) =>
          [1, r.height / 2, r.height - 1].every((y) =>
            el.contains(document.elementFromPoint(r.left + x, r.top + y)),
          ),
        );
      });
      expect(unobscured, "P0_08b_W4 sample target is fully clickable").toBe(true);
      await chip.focus();
      await page.keyboard.press("Shift+Tab");
      await page.keyboard.press("Tab");
      await expect(chip).toBeFocused();
      const ring = await chip.evaluate((el) => {
        const outline = (e: Element) => {
          const c = getComputedStyle(e);
          return `${c.outlineStyle} ${c.outlineWidth}`;
        };
        return {
          button: outline(el),
          dot: outline(el.querySelector(".park-shell__sampledot") as Element),
        };
      });
      // <=430px the dot carries the ring; wider, the chip pill does
      if (width <= 430) expect(ring).toEqual({ button: "none 3px", dot: "solid 3px" });
      else expect(ring.button).toBe("solid 3px");
    });
  });
}
