import { expect, test } from "@playwright/test";

test("CX_POOL_2_pool_loop_has_no_frame_gap_over_50ms", async ({ page }) => {
  test.setTimeout(90_000);
  await page.addInitScript(() => {
    // Keep AppShell in its real font-wait state without blocking Vite's module startup.
    Object.defineProperty(document.fonts, "load", {
      value: () => new Promise(() => undefined),
    });
  });
  await page.goto("/park/home", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".tt-pool-overlay[data-phase='swim']")).toBeVisible({
    timeout: 60_000,
  });
  const gaps = await page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const gaps: number[] = [];
        const end = performance.now() + 3_000;
        let previous = 0;
        const frame = (now: number) => {
          if (previous) gaps.push(now - previous);
          previous = now;
          if (now < end) requestAnimationFrame(frame);
          else resolve(gaps);
        };
        requestAnimationFrame(frame);
      }),
  );
  expect(gaps.length).toBeGreaterThan(90);
  expect(
    Math.max(...gaps),
    `frame gaps (ms): ${gaps.filter((gap) => gap > 50).join(", ")}`,
  ).toBeLessThanOrEqual(50);
});
