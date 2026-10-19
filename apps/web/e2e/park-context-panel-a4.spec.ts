// A4 / UI-10 (14 Oct QA, agy-bridge/reports/QA-SWEEP-14OCT-A-home.md item 9): the "Your context" sheet was a plain
// white list with default bullets, stayed open after a reload and then lay over Home with a backdrop that blocked
// every control. At 1440x900 and 390x844: closed on load (also after it was opened), styled, Esc and the backdrop
// close it, and a closed panel leaves nothing over the page.
// Run on a private port: TILO_WEB_PORT=5795 pnpm --filter @tilo/web exec playwright test
// e2e/park-context-panel-a4.spec.ts --project=chromium --no-deps --workers=1
import { type Page, expect, test } from "@playwright/test";

const SIZES = [
  { name: "1440x900", width: 1440, height: 900 },
  { name: "390x844", width: 390, height: 844 },
] as const;

const dialog = (page: Page) => page.getByRole("dialog", { name: "Your context" });
const opener = (page: Page) => page.getByRole("button", { name: "Your context" });

async function openHome(page: Page): Promise<void> {
  await page.goto("/", { timeout: 120_000 });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    /^Good (morning|evening), Alex\.$/,
    { timeout: 120_000 },
  );
  await expect(page.getByRole("button", { name: "Start task", exact: true })).toBeVisible();
}

for (const size of SIZES) {
  test.describe(`UI-10 A4 context panel at ${size.name}`, () => {
    test.use({ viewport: { width: size.width, height: size.height } });

    test(`UI_10_A4_${size.name}_closed_on_load_and_still_closed_after_a_reload_that_followed_opening_it`, async ({
      page,
    }) => {
      await openHome(page);
      await expect(dialog(page)).toHaveCount(0);
      await opener(page).click();
      await expect(dialog(page)).toBeVisible();
      await page.reload();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 60_000 });
      await expect(dialog(page)).toHaveCount(0);
      await expect(page.locator(".park-popover__backdrop")).toHaveCount(0);
    });

    test(`UI_10_A4_${size.name}_the_sheet_is_styled_and_inside_the_window`, async ({ page }) => {
      await openHome(page);
      await opener(page).click();
      await expect(dialog(page)).toBeVisible();
      const m = await page.evaluate(() => {
        const d = document.querySelector<HTMLElement>('[role="dialog"][aria-label="Your context"]');
        if (!d) return null;
        const r = d.getBoundingClientRect();
        const ul = d.querySelector("ul");
        const li = d.querySelector("li");
        return {
          box: { l: r.left, r: r.right, t: r.top, b: r.bottom },
          listStyle: ul ? getComputedStyle(ul).listStyleType : null,
          radius: getComputedStyle(d).borderTopLeftRadius,
          rowBg: li ? getComputedStyle(li).backgroundColor : null,
          shadow: getComputedStyle(d).boxShadow,
          vw: window.innerWidth,
          vh: window.innerHeight,
        };
      });
      expect(m).not.toBeNull();
      if (!m) return;
      expect(m.listStyle).toBe("none");
      expect(m.radius).not.toBe("0px");
      expect(m.shadow).not.toBe("none");
      expect(m.rowBg).not.toBe("rgba(0, 0, 0, 0)");
      expect(m.box.l).toBeGreaterThanOrEqual(0);
      expect(m.box.r).toBeLessThanOrEqual(m.vw);
      expect(m.box.b).toBeLessThanOrEqual(m.vh);
    });

    test(`UI_10_A4_${size.name}_Esc_and_the_backdrop_close_it_and_a_closed_panel_blocks_nothing`, async ({
      page,
    }) => {
      await openHome(page);
      const start = page.getByRole("button", { name: "Start task", exact: true });
      const onTop = () =>
        start.evaluate((el) => {
          const r = el.getBoundingClientRect();
          const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return !!top && el.contains(top);
        });
      await opener(page).click();
      await expect(dialog(page)).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(dialog(page)).toHaveCount(0);
      expect(await onTop()).toBe(true);

      await opener(page).click();
      await expect(dialog(page)).toBeVisible();
      // the backdrop covers the page: a click on a spot the sheet does not cover closes it (the phone's sheet
      // rises from the bottom, so there the spot is the strip between the nav and the sheet's top edge)
      await page.mouse.click(size.width < 760 ? 8 : 8, size.width < 760 ? 150 : size.height - 8);
      await expect(dialog(page)).toHaveCount(0);
      expect(await onTop()).toBe(true);
    });
  });
}
