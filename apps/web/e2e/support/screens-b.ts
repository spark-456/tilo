// Shared by the AGW-08 group B smoke specs (S-13..S-24, PRD 18.3): both viewports, no machine ids,
// axe, and the UX-1 zero-layout-shift check with a slow client.
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { expectNoDeadControls } from "./screens";
import { DESKTOP, MOBILE } from "./viewports";

/** `?speed=100` fast-forwards the recorded replay (about 2 s in all). */
export const FAST = "?speed=100";

/** Both viewports: heading, no dead controls, no machine ids, then axe once at the end. */
export async function visit(page: Page, path: string, name: string, check: () => Promise<void>) {
  for (const viewport of [DESKTOP, MOBILE]) {
    await page.setViewportSize(viewport);
    await page.goto(`${path}${FAST}`);
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    await check();
    await expect(page.getByTestId("fixture-replay-banner")).toBeVisible();
    await expect(page.locator("button.primary").count()).resolves.toBeLessThanOrEqual(1); // UX-1
    await expectNoDeadControls(page);
    // People read names, never machine ids (the run reference HR-4 asks for is the one exception).
    const text = (await page.getByTestId("screen-page").innerText()).replace("village_basic_1", "");
    expect(text).not.toMatch(/\b[a-z]+_[a-z0-9_]+\b|\b[A-Z]_[a-z0-9]+\b/);
    await expectTypeScale(page);
  }
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).analyze();
  expect(axe.violations).toEqual([]);
}

/** PRD 18.2: every text size on the screen is on the 12/14/16/20/24/32/40 px scale, and the page
 * title is above the section titles, which are above the row text, measured not eyeballed. */
export async function expectTypeScale(page: Page) {
  const sizes = await page.getByTestId("screen-page").evaluate((root) => {
    const used = new Set<number>();
    for (const el of root.querySelectorAll<HTMLElement>("*")) {
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent?.trim());
      if (own) used.add(Number.parseFloat(getComputedStyle(el).fontSize));
    }
    const px = (sel: string) => {
      const el = root.querySelector(sel);
      return el ? Number.parseFloat(getComputedStyle(el).fontSize) : 0;
    };
    return {
      used: [...used],
      h1: px("h1"),
      h2: px(".screen-section h2, .world-card h2"),
      row: px(".bitem-main b, .world-body .bitem-sub"),
    };
  });
  for (const size of sizes.used) expect([12, 14, 16, 20, 24, 32, 40], `${size}px`).toContain(size);
  expect(sizes.h1).toBeGreaterThan(sizes.h2);
  if (sizes.row) expect(sizes.h2).toBeGreaterThan(sizes.row);
}

/** A placeholder button is visible and titled "Coming soon" (its aria-disabled is checked by
 * `expectNoDeadControls`). */
export const soon = (page: Page, label: string) =>
  expect(page.getByRole("button", { name: new RegExp(label) }).first()).toHaveAttribute(
    "title",
    "Coming soon",
  );

/** UX-1: with a slow client and events arriving, nothing on the screen moves. Each row is the
 * test id, the path and a text that appears only once everything has arrived. */
export function noLayoutShift(rows: ReadonlyArray<readonly [string, string, string]>) {
  for (const viewport of [DESKTOP, MOBILE]) {
    for (const [id, path, settled] of rows) {
      test(`${id} UX_1 has zero layout shifts while a slow client answers at ${viewport.width}x${viewport.height}`, async ({
        page,
      }) => {
        test.setTimeout(60_000);
        await page.setViewportSize(viewport);
        // Warm the dev server (dependency optimisation, fonts) before the shifts are watched, so a
        // fresh server cannot show a cold-start reflow that no user sees.
        await page.goto(`${path}?speed=100`);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await page.addInitScript(() => {
          const w = window as unknown as { __shifts: number[] };
          w.__shifts = [];
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries())
              w.__shifts.push((entry as unknown as { value: number }).value);
          }).observe({ type: "layout-shift", buffered: true });
        });
        await page.goto(`${path}?client_delay_ms=800&speed=100`, { waitUntil: "commit" });
        await expect(page.getByText(settled).first()).toBeVisible({ timeout: 20_000 });
        await page.waitForTimeout(300); // let a late shift be reported
        const shifts = await page.evaluate(
          () => (window as unknown as { __shifts: number[] }).__shifts,
        );
        expect(shifts).toEqual([]);
      });
    }
  }
}
