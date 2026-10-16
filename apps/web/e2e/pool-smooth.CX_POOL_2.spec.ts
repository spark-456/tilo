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
  const gaps = await page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const values: number[] = [];
        const end = performance.now() + 3000;
        let previous = 0;
        const tick = (now: number) => {
          if (previous) values.push(now - previous);
          previous = now;
          if (now < end) requestAnimationFrame(tick);
          else resolve(values);
        };
        requestAnimationFrame(tick);
      }),
  );
  await page.screenshot({ path: join(evidence, "pool-100.png") });
  const max = Math.max(...gaps);
  console.log(
    `frames=${gaps.length} maxGapMs=${max.toFixed(1)} gapsOver50=${gaps.filter((gap) => gap > 50).length}`,
  );
  expect(gaps.length).toBeGreaterThan(90);
  expect(max, `max RAF gap ${max.toFixed(1)} ms`).toBeLessThanOrEqual(50);
});
