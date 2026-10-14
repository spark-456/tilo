// WEB-W2 (issue 933): a toast never overlaps the top bar or the sample banner, at 1440 and 390.
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/park-toast-overlap.spec.ts --project=chromium --no-deps --workers=1
import { type Locator, expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

const overlaps = (a: { x: number; y: number; width: number; height: number }, b: typeof a) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

async function box(l: Locator) {
  const b = await l.boundingBox();
  if (!b) throw new Error("element has no box");
  return b;
}

for (const [name, viewport] of [
  ["desktop", DESKTOP],
  ["mobile", MOBILE],
] as const) {
  test.describe(`toast placement at ${name}`, () => {
    test.use({ viewport });

    test(`WEB_W2_e2e_${name}_a_toast_does_not_overlap_the_bar_or_the_sample_banner`, async ({
      page,
    }) => {
      test.setTimeout(150_000);
      await page.goto("/agenda", { timeout: 120_000 });
      const banner = page.locator(".park-first-run-banner").first();
      await expect(banner).toBeVisible({ timeout: 120_000 });
      await page.getByRole("button", { name: "Block it" }).click();
      const toast = page.locator(".park-toast").first();
      await expect(toast).toBeVisible();
      await page.waitForTimeout(400); // the enter transition
      const t = await box(toast);
      expect(overlaps(t, await box(banner)), "toast over the sample banner").toBe(false);
      const bar = page.locator("header.park-shell__nav");
      expect(overlaps(t, await box(bar)), "toast over the top bar").toBe(false);
      expect(t.x).toBeGreaterThanOrEqual(0);
      expect(t.x + t.width).toBeLessThanOrEqual(viewport.width);
      expect(t.y + t.height).toBeLessThanOrEqual(viewport.height);
    });
  });
}
