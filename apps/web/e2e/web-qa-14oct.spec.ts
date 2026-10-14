// WEB-QA-14OCT-1 (UI-10): the live-site polish pass.
//   1. the Home sample strip and its dismiss never overlap a neighbour, at 1440x900 and 390x844 (and the other
//      sizes the QA pass used), the dismiss is a real target, and a dismissal is remembered;
//   2. phone Home: the example chips clear the "decisions waiting" banner and the placeholder fits its input;
//   3. a deep link to the stage or a lens of a sample-company world lands on that world's Park page (lens links
//      shown disabled), never "Not found" in the old shell.
// Run on a private port: TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test
// e2e/web-qa-14oct.spec.ts --project=chromium --no-deps --workers=1
import { type Locator, type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { DESKTOP, MOBILE } from "./support/viewports";

type Box = { x: number; y: number; width: number; height: number };
const overlaps = (a: Box, b: Box) =>
  a.x < b.x + b.width - 0.5 &&
  b.x < a.x + a.width - 0.5 &&
  a.y < b.y + b.height - 0.5 &&
  b.y < a.y + a.height - 0.5;

async function box(l: Locator): Promise<Box> {
  const b = await l.boundingBox();
  if (!b) throw new Error("element has no box");
  return b;
}

async function openHome(page: Page) {
  await page.goto("/", { timeout: 120_000 });
  await expect(page.getByTestId("park-page-home")).toBeVisible({ timeout: 120_000 });
  await expect(page.locator(".park-first-run-banner")).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(800); // the city and panels settle
}

const SIZES = [
  ["desktop 1440x900", DESKTOP],
  ["wide 1920x1080", { width: 1920, height: 1080 }],
  ["tablet 768x1024", { width: 768, height: 1024 }],
  ["phone 390x844", MOBILE],
] as const;

for (const [name, viewport] of SIZES) {
  test.describe(`Home sample strip at ${name}`, () => {
    test.use({ viewport });

    test(`UI-10 WEB-QA-14OCT banner dismiss does not overlap status at ${name}`, async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await openHome(page);
      const banner = page.locator(".park-first-run-banner");
      const dismiss = banner.getByRole("button", { name: "Dismiss sample banner" });
      const b = await box(banner);
      const d = await box(dismiss);
      // the control sits inside the strip, beside its text, and is a real target
      expect(d.x).toBeGreaterThanOrEqual(b.x);
      expect(d.x + d.width).toBeLessThanOrEqual(b.x + b.width + 0.5);
      const text = await box(banner.locator("> span"));
      expect(overlaps(text, d), "strip text vs dismiss").toBe(false);
      const min = viewport.width < 481 ? 44 : 24;
      expect(d.width).toBeGreaterThanOrEqual(min);
      expect(d.height).toBeGreaterThanOrEqual(min);
      // nothing else on the page lies under the strip
      for (const sel of [
        ".park-home-hero",
        ".park-home-pin__card",
        ".park-shell__sample",
        ".park-shell__pagebtn",
        ".park-home-needs",
      ]) {
        for (const el of await page.locator(sel).all()) {
          if (!(await el.isVisible())) continue;
          expect(overlaps(b, await box(el)), `strip vs ${sel}`).toBe(false);
        }
      }
      // the strip stays in the viewport
      expect(b.x).toBeGreaterThanOrEqual(0);
      expect(b.x + b.width).toBeLessThanOrEqual(viewport.width);
      // the honesty label stays after the strip is gone: the top bar's own pill
      await dismiss.click();
      await expect(banner).toHaveCount(0);
      await expect(page.locator(".park-shell__sample")).toBeVisible();
      // and a dismissal is remembered on a reload
      await page.reload();
      await expect(page.getByTestId("park-page-home")).toBeVisible({ timeout: 120_000 });
      await expect(page.locator(".park-first-run-banner")).toHaveCount(0);
      expect(problems).toEqual([]);
    });
  });
}

test.describe("phone Home", () => {
  test.use({ viewport: MOBILE });

  test("UI-10 WEB-QA-14OCT phone Home chips clear the decisions banner and the placeholder fits", async ({
    page,
  }) => {
    const problems = collectConsoleProblems(page);
    await openHome(page);
    const needs = await box(page.locator(".park-home-needs"));
    const chips = page.locator(".park-home-chip");
    expect(await chips.count()).toBeGreaterThan(0);
    for (const chip of await chips.all()) {
      const c = await box(chip);
      expect(overlaps(c, needs), "chip vs decisions banner").toBe(false);
      expect(c.x).toBeGreaterThanOrEqual(0);
      expect(c.x + c.width).toBeLessThanOrEqual(MOBILE.width);
    }
    const hero = await box(page.locator(".park-home-hero"));
    const banner = await box(page.locator(".park-first-run-banner"));
    expect(overlaps(banner, hero), "strip vs greeting").toBe(false);
    // the placeholder is shown whole: its text is no wider than the input's content box
    const fits = await page.evaluate(() => {
      const input = document.querySelector<HTMLInputElement>(".park-home-input");
      if (!input) return null;
      const cs = getComputedStyle(input);
      const probe = document.createElement("span");
      probe.style.cssText = `position:absolute;visibility:hidden;white-space:pre;font:${cs.font};letter-spacing:${cs.letterSpacing}`;
      probe.textContent = input.placeholder;
      document.body.append(probe);
      const need = probe.getBoundingClientRect().width;
      probe.remove();
      const room =
        input.clientWidth - Number.parseFloat(cs.paddingLeft) - Number.parseFloat(cs.paddingRight);
      return { placeholder: input.placeholder, need, room };
    });
    expect(fits).not.toBeNull();
    expect(fits?.need, JSON.stringify(fits)).toBeLessThanOrEqual((fits?.room ?? 0) + 0.5);
    expect(problems).toEqual([]);
  });
});

for (const [name, viewport] of [
  ["desktop", DESKTOP],
  ["phone", MOBILE],
] as const) {
  test.describe(`world deep links at ${name}`, () => {
    test.use({ viewport });

    for (const lens of ["stage", "story", "trace", "delivery"]) {
      test(`UI-10 WEB-QA-14OCT /world/k1/${lens} on a full load is k1's Park page with the lens links disabled (${name})`, async ({
        page,
      }) => {
        const problems = collectConsoleProblems(page);
        await page.goto(`/world/k1/${lens}`, { timeout: 120_000 });
        await expect(page.getByTestId("park-page-world")).toBeVisible({ timeout: 120_000 });
        expect(new URL(page.url()).pathname).toBe("/world/k1");
        await expect(page.locator("body")).not.toContainText("Nothing is at this address");
        await expect(page.getByTestId("fixture-replay-banner")).toHaveCount(0);
        const story = page.getByRole("link", { name: "Story", exact: true });
        await expect(story).toHaveAttribute("aria-disabled", "true");
        expect(problems).toEqual([]);
      });
    }

    test(`UI-10 WEB-QA-14OCT an unknown world's lens address is still Not found (${name})`, async ({
      page,
    }) => {
      await page.goto("/world/nope/stage", { timeout: 120_000 });
      await expect(page.getByRole("heading", { level: 1, name: "Not found" })).toBeVisible({
        timeout: 120_000,
      });
    });
  });
}
