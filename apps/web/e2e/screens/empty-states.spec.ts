// #227 Bundle H1: the EmptyState on S-06, S-07, S-12, S-13 and S-21, at both viewports. Each one
// appears in the box the loading state already held (zero layout shifts), fits it without a
// scrollbar, offers one reachable action, and passes axe. `?speed=0.1` keeps the replay from
// recording anything while the test looks.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { expectTypeScale } from "../support/screens-b";
import { DESKTOP, MOBILE } from "../support/viewports";

const SCREENS = [
  ["S_06", "/needs-you", "needs-empty"],
  ["S_07", "/needs-you/gate", "gate-empty"],
  ["S_12", "/world/w_village_basic/delivery", "delivery-pending"],
  ["S_13", "/library", "library-empty"],
  ["S_21", "/library/artifacts", "history-empty"],
] as const;

for (const viewport of [DESKTOP, MOBILE]) {
  const at = `${viewport.width}x${viewport.height}`;
  for (const [id, path, testid] of SCREENS) {
    test(`${id} H1 empty state: one glyph, title, line and action in its own box, no shift at ${at}`, async ({
      page,
    }) => {
      test.setTimeout(60_000);
      await page.setViewportSize(viewport);
      // Warm the dev server before the shifts are watched (a cold start reflows once, unseen).
      await page.goto(`${path}?speed=0.1`);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
      await page.addInitScript(() => {
        const w = window as unknown as { __shifts: number[] };
        w.__shifts = [];
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries())
            w.__shifts.push((entry as unknown as { value: number }).value);
        }).observe({ type: "layout-shift", buffered: true });
      });
      await page.goto(`${path}?client_delay_ms=800&speed=0.1`, { waitUntil: "commit" });

      const box = page.getByTestId(testid);
      await expect(box).toBeVisible({ timeout: 20_000 });
      await page.waitForTimeout(300); // let a late shift be reported
      const shifts = await page.evaluate(
        () => (window as unknown as { __shifts: number[] }).__shifts,
      );
      expect(shifts).toEqual([]);

      // glyph, title, line, one action
      await expect(box.locator('svg[aria-hidden="true"]')).toHaveCount(1);
      await expect(box.locator(".empty-title")).not.toBeEmpty();
      await expect(box.locator(".empty-line")).not.toBeEmpty();
      const action = box.getByRole("link");
      await expect(action).toHaveCount(1);
      const target = await action.boundingBox();
      expect(target?.height ?? 0).toBeGreaterThanOrEqual(viewport.width < 768 ? 44 : 24);
      expect(target?.width ?? 0).toBeGreaterThanOrEqual(viewport.width < 768 ? 44 : 24);

      // it fits the reserved box it sits in: no scrollbar inside the card
      const overflow = await box.evaluate((el) => {
        const reserved = el.closest<HTMLElement>(".section-box.reserved");
        return reserved ? reserved.scrollHeight - reserved.clientHeight : 0;
      });
      expect(overflow).toBeLessThanOrEqual(1);
      expect(await page.locator("button.primary").count()).toBeLessThanOrEqual(1); // UX-1
      await expectTypeScale(page);
      const axe = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
        .analyze();
      expect(axe.violations).toEqual([]);
    });
  }
}
