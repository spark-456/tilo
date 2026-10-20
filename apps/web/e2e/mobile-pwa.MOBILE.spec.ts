// MOBILE: Tilo on a phone. The served manifest and its icons (what Chrome's install check reads), and no page scrolls
// sideways at 360, 390 or 430 px in portrait. The static rules (no-cache index.html, no caching worker) are in
// src/pwa.MOBILE.test.ts.
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { MOBILE_PAGES } from "./support/mobilePages";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("tilo-boot-seen", "1"));
});

test("MOBILE_PWA_the_served_manifest_and_icons_pass_the_install_check", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const href = await page.locator('link[rel="manifest"]').getAttribute("href");
  expect(href).toBe("/manifest.webmanifest");
  const res = await request.get(href ?? "");
  expect(res.ok()).toBe(true);
  const manifest = (await res.json()) as {
    name: string;
    short_name: string;
    start_url: string;
    display: string;
    icons: { src: string; sizes: string; purpose: string }[];
  };
  expect(manifest).toMatchObject({ name: "Tilo", start_url: "/", display: "standalone" });
  expect(manifest.icons.map((i) => i.sizes)).toEqual(
    expect.arrayContaining(["192x192", "512x512"]),
  );
  for (const icon of manifest.icons) {
    const png = await request.get(icon.src);
    expect(png.ok(), icon.src).toBe(true);
    expect(png.headers()["content-type"], icon.src).toContain("image/png");
  }
  const touch = await page.locator('link[rel="apple-touch-icon"]').getAttribute("href");
  expect((await request.get(touch ?? "")).ok()).toBe(true);
});

// Lighthouse 12 dropped its PWA category; the browser's own install check is what Chrome runs before offering
// "Install app". It needs a real profile: an off-the-record context stops at "in-incognito" and checks nothing else.
test("MOBILE_PWA_chrome_install_check_finds_nothing_missing", async ({ playwright, baseURL }) => {
  const dir = mkdtempSync(join(tmpdir(), "tilo-pwa-"));
  const ctx = await playwright.chromium.launchPersistentContext(dir, {
    ...(process.env.CI ? {} : { channel: "msedge" }),
  });
  try {
    const page = await ctx.newPage();
    await page.goto(`${baseURL}/`);
    await page.waitForLoadState("load");
    const cdp = await ctx.newCDPSession(page);
    const manifest = await cdp.send("Page.getAppManifest");
    expect(manifest.errors).toEqual([]);
    expect(manifest.url).toMatch(/\/manifest\.webmanifest$/);
    await expect
      .poll(async () => (await cdp.send("Page.getInstallabilityErrors")).installabilityErrors)
      .toEqual([]);
  } finally {
    await ctx.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

for (const [id, path] of MOBILE_PAGES) {
  test(`MOBILE_no_horizontal_scroll ${id} at 360 390 430`, async ({ page }) => {
    test.setTimeout(90_000);
    for (const width of [360, 390, 430]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(path);
      await page.locator(`[data-testid="park-page-${id}"]`).first().waitFor({ timeout: 30_000 });
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      const wide = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        view: document.documentElement.clientWidth,
      }));
      expect(wide.scroll, `${id} at ${width}`).toBeLessThanOrEqual(wide.view);
    }
  });
}
