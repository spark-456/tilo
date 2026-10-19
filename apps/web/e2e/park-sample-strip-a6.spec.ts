// A6 / UI-10 (14 Oct QA, Home at night): the sample strip was a near-transparent panel over the lit city. The
// rendered colours at 1440x900 and 390x844, day and night: the strip's own background is opaque and its text
// (the strip, the Sample badge, the dismiss glyph) is at least 4.5:1 on it.
// Run on a private port: TILO_WEB_PORT=5795 pnpm --filter @tilo/web exec playwright test
// e2e/park-sample-strip-a6.spec.ts --project=chromium --no-deps --workers=1
import { type Page, expect, test } from "@playwright/test";

const SIZES = [
  { name: "1440x900", width: 1440, height: 900 },
  { name: "390x844", width: 390, height: 844 },
] as const;

async function openHome(page: Page, night: boolean): Promise<void> {
  await page.goto("/", { timeout: 120_000 });
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 120_000 });
  await expect(page.locator(".park-first-run-banner--home")).toBeVisible();
  if (night)
    await page.locator("[data-park]").evaluate((el) => el.setAttribute("data-time", "night"));
}

for (const size of SIZES) {
  for (const night of [false, true]) {
    const theme = night ? "night" : "day";
    test.describe(`UI-10 A6 sample strip at ${size.name}, ${theme}`, () => {
      test.use({ viewport: { width: size.width, height: size.height } });

      test(`UI_10_A6_${size.name}_${theme}_the_strip_is_opaque_and_its_text_reads`, async ({
        page,
      }) => {
        await openHome(page, night);
        const m = await page.evaluate(() => {
          const parse = (c: string): [number, number, number, number] => {
            const n = (c.match(/[\d.]+/g) ?? []).map(Number);
            return [n[0] ?? 0, n[1] ?? 0, n[2] ?? 0, n[3] ?? 1];
          };
          const lum = (c: number[]): number => {
            const v = c.slice(0, 3).map((x) => {
              const s = (x ?? 0) / 255;
              return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
            });
            return 0.2126 * (v[0] ?? 0) + 0.7152 * (v[1] ?? 0) + 0.0722 * (v[2] ?? 0);
          };
          const ratio = (a: number[], b: number[]): number => {
            const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
            return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
          };
          // an element's surface: itself composited over the strip's opaque background
          const strip = document.querySelector<HTMLElement>(".park-first-run-banner--home");
          if (!strip) return null;
          const [br, bg, bb, ba] = parse(getComputedStyle(strip).backgroundColor);
          const mix = (c: [number, number, number, number], under: number[]): number[] => [
            c[0] * c[3] + (under[0] ?? 0) * (1 - c[3]),
            c[1] * c[3] + (under[1] ?? 0) * (1 - c[3]),
            c[2] * c[3] + (under[2] ?? 0) * (1 - c[3]),
          ];
          const probe = (el: Element | null, own: boolean): number | null => {
            if (!el) return null;
            const s = getComputedStyle(el);
            const bg2 = own ? mix(parse(s.backgroundColor), [br, bg, bb]) : [br, bg, bb];
            return ratio(mix(parse(s.color), bg2), bg2);
          };
          return {
            stripAlpha: ba,
            text: probe(strip.querySelector(":scope > span"), false),
            badge: probe(strip.querySelector("[class*='badge'], .park-sample-badge"), true),
            dismiss: probe(strip.querySelector("button"), true),
          };
        });
        expect(m).not.toBeNull();
        if (!m) return;
        expect(m.stripAlpha).toBe(1);
        expect(m.text ?? 21).toBeGreaterThanOrEqual(4.5);
        expect(m.badge ?? 21).toBeGreaterThanOrEqual(4.5);
        expect(m.dismiss ?? 21).toBeGreaterThanOrEqual(4.5);
      });
    });
  }
}
