import { type Page, expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

const sizes = (page: Page) =>
  page.evaluate(() =>
    [".right-rail h2", ".right-rail p", ".nav-btn"].map((sel) => {
      const style = getComputedStyle(document.querySelector(sel) as Element);
      return Number.parseFloat(sel === ".nav-btn" ? style.minHeight : style.fontSize);
    }),
  );

test("PRD-18.2 stage mode: the display setting scales type and targets by 1.25", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/");
  const normal = await sizes(page);
  await page.goto("/?display=stage");
  const scaled = await sizes(page);
  scaled.forEach((v, i) => expect(v / (normal[i] ?? 0)).toBeCloseTo(1.25, 2));
});

for (const viewport of [DESKTOP, MOBILE]) {
  test(`PRD-18.2 layout: no layout shift while the shell and fonts load at ${viewport.width}px`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.addInitScript(() => {
      const w = window as unknown as { cls: number };
      w.cls = 0;
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) w.cls += (e as unknown as { value: number }).value;
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto("/");
    await expect(page.getByTestId("stage-frame")).toBeVisible();
    await page.waitForTimeout(1000);
    expect(await page.evaluate(() => (window as unknown as { cls: number }).cls)).toBe(0);
  });
}
