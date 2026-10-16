import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

test.use({ trace: "off" });

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
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Profiler.enable");
  await cdp.send("Profiler.start");
  const gaps = await page.evaluate(
    () =>
      new Promise<{ gaps: number[]; longTasks: number[] }>((resolve) => {
        const values: number[] = [];
        const longTasks: number[] = [];
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) longTasks.push(entry.duration);
        }).observe({ type: "longtask", buffered: true });
        const end = performance.now() + 3000;
        let previous = 0;
        const tick = (now: number) => {
          if (previous) values.push(now - previous);
          previous = now;
          if (now < end) requestAnimationFrame(tick);
          else resolve({ gaps: values, longTasks });
        };
        requestAnimationFrame(tick);
      }),
  );
  const { profile } = await cdp.send("Profiler.stop");
  const nodeById = new Map(profile.nodes.map((node) => [node.id, node]));
  const cpuById = new Map<number, number>();
  profile.samples.forEach((id, index) => {
    cpuById.set(id, (cpuById.get(id) ?? 0) + (profile.timeDeltas[index] ?? 0));
  });
  const topCpu = [...cpuById]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([id, micros]) => {
      const call = nodeById.get(id)?.callFrame;
      return `${call?.functionName || "(anonymous)"}@${call?.url?.split("/").pop() || "native"}:${(micros / 1000).toFixed(1)}ms`;
    });
  await page.screenshot({ path: join(evidence, "pool-100.png") });
  const max = Math.max(...gaps.gaps);
  console.log(
    `frames=${gaps.gaps.length} maxGapMs=${max.toFixed(1)} gapsOver50=${gaps.gaps.filter((gap) => gap > 50).length} longTasks=${gaps.longTasks.map((duration) => duration.toFixed(1)).join(",")} topCpu=${topCpu.join(";")}`,
  );
  expect(gaps.gaps.length).toBeGreaterThan(20);
  expect(max, `max RAF gap ${max.toFixed(1)} ms`).toBeLessThanOrEqual(50);
});
