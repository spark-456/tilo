import { expect, test } from "@playwright/test";
import { collectConsoleProblems } from "../support/console";

for (const viewport of [
  { width: 320, height: 640 },
  { width: 390, height: 844 },
]) {
  test.describe(`W9 at ${viewport.width}`, () => {
    test.use({ viewport });
    test.beforeEach(async ({ page }) => {
      await page.clock.setFixedTime(new Date(2026, 8, 24, 12));
    });

    for (const route of ["team", "connectors", "agenda", "profile"]) {
      test(`UI_10_W9_${route}_fits_the_small_screen`, async ({ page }) => {
        test.setTimeout(150_000);
        const problems = collectConsoleProblems(page);
        await page.goto(`/${route}`, { timeout: 120_000 });
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await page.evaluate(() => document.fonts.ready);
        const size = await page.evaluate(() => ({
          scrollWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
          innerWidth: window.innerWidth,
        }));
        expect(size.scrollWidth).toBeLessThanOrEqual(size.innerWidth);
        expect(problems).toEqual([]);
      });
    }

    test("UI_10_W9_team_wait_times_has_a_24px_target", async ({ page }) => {
      await page.goto("/team");
      const link = page.getByRole("link", { name: "See wait times" });
      await expect(link).toBeVisible();
      const box = await link.boundingBox();
      expect(box?.width).toBeGreaterThanOrEqual(24);
      expect(box?.height).toBeGreaterThanOrEqual(24);
    });

    test("UI_10_W9_agenda_events_have_24px_targets", async ({ page }) => {
      await page.goto("/agenda");
      const events = page.locator("button.park-agenda-event");
      await expect(events.first()).toBeVisible();
      const boxes = await events.evaluateAll((els) =>
        els.map((el) => {
          const r = el.getBoundingClientRect();
          return { width: r.width, height: r.height };
        }),
      );
      for (const box of boxes) {
        expect(box.width).toBeGreaterThanOrEqual(24);
        expect(box.height).toBeGreaterThanOrEqual(24);
      }
    });
  });
}
