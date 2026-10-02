import type { Page } from "@playwright/test";

type Shifts = { __shifts: number[] };

/** Records layout shifts the way CLS counts them (not within 500 ms of an input). Call before goto. */
export async function watchShifts(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as Shifts;
    w.__shifts = [];
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const shift = entry as unknown as { value: number; hadRecentInput: boolean };
        if (!shift.hadRecentInput) w.__shifts.push(shift.value);
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
}

/** Starts a new measurement. Waits first: shifts from earlier actions are reported late. */
export async function resetShifts(page: Page): Promise<void> {
  await page.waitForTimeout(600);
  await page.evaluate(() => {
    (window as unknown as Shifts).__shifts = [];
  });
}

/** The shifts since the last reset, after letting a late one be reported. */
export async function readShifts(page: Page): Promise<number[]> {
  await page.waitForTimeout(400);
  return page.evaluate(() => (window as unknown as Shifts).__shifts);
}
