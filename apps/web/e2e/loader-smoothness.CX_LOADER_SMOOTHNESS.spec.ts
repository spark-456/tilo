import { expect, test } from "@playwright/test";

test("CX_LOADER_SMOOTHNESS_boot_cover_stays_fixed_without_long_frame_gaps_or_layout_shift", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const metrics: {
      maxFrameGap: number;
      worstFrameAt: number;
      cls: number;
    } = {
      maxFrameGap: 0,
      worstFrameAt: 0,
      cls: 0,
    };
    Reflect.set(window, "__loaderMetrics", metrics);
    Reflect.set(window, "__loaderLoopComplete", false);
    window.addEventListener("tilo-boot-loop-complete", () => {
      Reflect.set(window, "__loaderLoopComplete", true);
    });
    let previous: number | null = null;
    const frame = (now: number) => {
      const loopComplete = Reflect.get(window, "__loaderLoopComplete") === true;
      if (previous !== null && !loopComplete && now - previous > metrics.maxFrameGap) {
        metrics.maxFrameGap = now - previous;
        metrics.worstFrameAt = now;
      }
      previous = now;
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const shift = entry as PerformanceEntry & { value: number; hadRecentInput: boolean };
        if (!shift.hadRecentInput) metrics.cls += shift.value;
      }
    }).observe({ type: "layout-shift", buffered: true });
  });

  await page.goto("/");
  const cover = page.locator("#tilo-boot-cover");
  await expect(cover).toBeVisible();
  expect(await cover.evaluate((element) => getComputedStyle(element).position)).toBe("fixed");
  await expect
    .poll(() => page.locator("#root").evaluate((element) => !element.hasAttribute("inert")), {
      timeout: 30_000,
    })
    .toBe(true);
  await page.waitForTimeout(1_000);

  const metrics = await page.evaluate(() => Reflect.get(window, "__loaderMetrics"));
  console.log("CX_LOADER_SMOOTHNESS metrics", JSON.stringify(metrics));
  expect(metrics.maxFrameGap).toBeLessThanOrEqual(50);
  expect(metrics.cls).toBeLessThan(0.05);
});
