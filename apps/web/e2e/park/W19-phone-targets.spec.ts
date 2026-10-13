import { expect, test } from "@playwright/test";

for (const route of ["worlds", "agenda", "team"]) {
  test(`UI_10_W19 ${route} phone controls meet target sizes`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.clock.install({ time: new Date("2026-09-24T09:00:00+01:00") });
    await page.goto(`/${route}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator("main")).not.toHaveClass(/park-shell__booting/);
    // Staged fixture reads use the app scheduler: settle them without a wall-clock sleep.
    await page.clock.runFor(2_000);
    const targets = page.locator(
      'header a, header button, main a[href], main button, main input:not([type="hidden"]), main select, main textarea, main [tabindex="0"]',
    );
    const failures: string[] = [];
    let checked = 0;
    for (const target of await targets.all()) {
      if (!(await target.isVisible()) || !(await target.isEnabled())) continue;
      await target.scrollIntoViewIfNeeded();
      const result = await target.evaluate((element) => {
        const box = element.getBoundingClientRect();
        const primary = element.matches(
          ".park-btn--primary, .park-worlds-new, .park-worlds-dec__yes, .park-agenda-accept, .park-agenda-pinit, .park-agenda-addbtn",
        );
        return {
          name:
            element.getAttribute("aria-label") ?? element.textContent?.trim() ?? element.tagName,
          width: box.width,
          height: box.height,
          minimum: primary ? 44 : 24,
        };
      });
      checked++;
      if (result.width < result.minimum || result.height < result.minimum) {
        failures.push(
          `${result.name}: ${result.width}x${result.height}, minimum ${result.minimum}`,
        );
      }
    }
    expect(checked, "enumeration must include page controls as well as the header").toBeGreaterThan(
      8,
    );
    expect(failures).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390,
    );
  });
}
