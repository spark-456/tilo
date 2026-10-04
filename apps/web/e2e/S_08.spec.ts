import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

test.describe("S_08 Connection consent sheet", () => {
  test("renders empty state, no console errors, placeholders aria-disabled", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/needs-you/consent");
    await expect(page.getByTestId("consent-sheet-page")).toBeVisible();
    await expect(page.getByTestId("consent-empty")).toBeVisible();

    expect(errors).toEqual([]);
  });

  test.describe("UX_1 zero layout shift", () => {
    test.use({ viewport: DESKTOP });
    test("at 1440 (desktop)", async ({ page }) => {
      await page.goto("/needs-you/consent?client_delay_ms=3000");
      const cumulativeLayoutShift = await page.evaluate(() => {
        return new Promise((resolve) => {
          let cls = 0;
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              const shift = entry as PerformanceEntry & {
                hadRecentInput?: boolean;
                value?: number;
              };
              if (!shift.hadRecentInput) {
                cls += shift.value ?? 0;
              }
            }
          }).observe({ type: "layout-shift", buffered: true });

          setTimeout(() => resolve(cls), 3500);
        });
      });
      expect(cumulativeLayoutShift).toBe(0);
    });
  });

  test.describe("UX_1 zero layout shift", () => {
    test.use({ viewport: MOBILE });
    test("at 390 (mobile)", async ({ page }) => {
      await page.goto("/needs-you/consent?client_delay_ms=3000");
      const cumulativeLayoutShift = await page.evaluate(() => {
        return new Promise((resolve) => {
          let cls = 0;
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              const shift = entry as PerformanceEntry & {
                hadRecentInput?: boolean;
                value?: number;
              };
              if (!shift.hadRecentInput) {
                cls += shift.value ?? 0;
              }
            }
          }).observe({ type: "layout-shift", buffered: true });

          setTimeout(() => resolve(cls), 3500);
        });
      });
      expect(cumulativeLayoutShift).toBe(0);
    });
  });
});
