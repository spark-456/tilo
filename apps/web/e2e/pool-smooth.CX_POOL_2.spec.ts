import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

test.use({ trace: "on" });

test("CX_POOL_2_pool_cycle_records_screenshots_trace_and_frame_gaps", async ({
  page,
}, testInfo) => {
  test.setTimeout(90_000);
  const evidence = join(testInfo.config.rootDir, "..", "..", "agy-bridge", "evidence", "CX-POOL-2");
  mkdirSync(evidence, { recursive: true });
  await page.addInitScript(() => {
    Object.defineProperty(document.fonts, "load", { value: () => new Promise(() => undefined) });
  });
  await page.goto("/park/home", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".tt-pool-overlay[data-phase='leap']")).toBeVisible({
    timeout: 60_000,
  });
  await page.screenshot({ path: join(evidence, "pool-0.png") });
  await page.waitForTimeout(1300);
  await page.screenshot({ path: join(evidence, "pool-50.png") });
  await expect(page.locator(".tt-pool-overlay[data-phase='swim']")).toBeVisible();
  await page.bringToFront();
  const gaps = await page.evaluate(
    () =>
      new Promise<{ gaps: number[]; longTasks: string[]; visibility: string }>((resolve) => {
        const values: number[] = [];
        const longTasks: string[] = [];
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            longTasks.push(`${entry.duration.toFixed(1)}ms@${entry.startTime.toFixed(1)}`);
          }
        }).observe({ type: "longtask", buffered: false });
        const end = performance.now() + 3000;
        let previous = 0;
        const tick = (now: number) => {
          if (previous) values.push(now - previous);
          previous = now;
          if (now < end) requestAnimationFrame(tick);
          else resolve({ gaps: values, longTasks, visibility: document.visibilityState });
        };
        requestAnimationFrame(tick);
      }),
  );
  await page.screenshot({ path: join(evidence, "pool-100.png") });
  const max = Math.max(...gaps.gaps);
  console.log(
    `frames=${gaps.gaps.length} maxGapMs=${max.toFixed(1)} gapsOver50=${gaps.gaps.filter((gap) => gap > 50).length} longTasks=${gaps.longTasks.join(",")} visibility=${gaps.visibility}`,
  );
  expect(gaps.gaps.length).toBeGreaterThan(20);
  expect(max, `max RAF gap ${max.toFixed(1)} ms`).toBeLessThanOrEqual(50);
});
