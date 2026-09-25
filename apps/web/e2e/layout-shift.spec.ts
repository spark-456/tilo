import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

for (const [name, viewport] of Object.entries({ desktop: DESKTOP, mobile: MOBILE })) {
  test.describe(`${name} layout shift`, () => {
    test.use({ viewport });

    test(`PRD-18.2 layout: total layout shift is 0 while the shell and its web fonts load at ${name} size`, async ({
      page,
    }) => {
      await page.addInitScript(() => {
        const w = window as unknown as { __shift: number };
        w.__shift = 0;
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries())
            w.__shift += (entry as unknown as { value: number }).value;
        }).observe({ type: "layout-shift", buffered: true });
      });
      await page.goto("/");
      await expect(page.getByTestId("stage-frame")).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(1000);
      expect(await page.evaluate(() => (window as unknown as { __shift: number }).__shift)).toBe(0);
    });
  });
}
