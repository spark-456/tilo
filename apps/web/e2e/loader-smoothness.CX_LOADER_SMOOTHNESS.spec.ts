import { type Locator, type Page, expect, test } from "@playwright/test";

const sampleFrame = async (page: Page, image: Locator) => {
  await page.evaluate(() => Reflect.set(window, "__loaderFrameProbe", true));
  const box = await image.boundingBox();
  if (!box) throw new Error("loader image has no browser bounds");
  const session = await page.context().newCDPSession(page);
  const frame = await session.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    clip: { ...box, scale: 1 },
  });
  await session.detach();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => {
          Reflect.set(window, "__loaderFrameProbe", false);
          resolve();
        });
      }),
  );
  return frame.data;
};

test("R_LOADER_boot_cover_advances_frames_without_long_gaps_or_layout_shift", async ({ page }) => {
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
    Reflect.set(window, "__resetLoaderMetrics", () => {
      metrics.maxFrameGap = 0;
      metrics.worstFrameAt = 0;
      metrics.cls = 0;
      previous = null;
    });
    const frame = (now: number) => {
      const loopComplete = Reflect.get(window, "__loaderLoopComplete") === true;
      const probingFrame = Reflect.get(window, "__loaderFrameProbe") === true;
      if (
        previous !== null &&
        !loopComplete &&
        !probingFrame &&
        now - previous > metrics.maxFrameGap
      ) {
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
  await page.evaluate(() => Reflect.get(window, "__resetLoaderMetrics")());
  const firstFrame = await sampleFrame(page, cover.locator("img"));
  await page.waitForTimeout(800);
  const laterFrame = await sampleFrame(page, cover.locator("img"));
  expect(firstFrame).not.toBe(laterFrame);
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
