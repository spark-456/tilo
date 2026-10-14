import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";
import { STAGE_PATH } from "./support/world";

// OLD-UI-OUT-2: the old frame's stage-mode type scale (right rail, nav buttons) went with the frame; stage mode in
// the Park shell hides the lens chrome (src/display/stageMode.fr-wld-12.test.tsx).

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
    await page.goto(STAGE_PATH);
    await expect(page.getByTestId("stage-frame")).toBeVisible();
    await page.waitForTimeout(1000);
    expect(await page.evaluate(() => (window as unknown as { cls: number }).cls)).toBe(0);
  });
}
