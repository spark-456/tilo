import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidenceDirs = [
  resolve(process.cwd(), "../../agy-bridge/evidence/TW-DARK"),
  resolve(process.cwd(), "../../../../Tilo/agy-bridge/evidence/TW-DARK"),
];

for (const dir of evidenceDirs) {
  try {
    mkdirSync(dir, { recursive: true });
  } catch {}
}

const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
] as const;

for (const { width, height } of VIEWPORTS) {
  for (const theme of ["light", "dark"] as const) {
    test(`TW-DARK World page ${width}px ${theme}`, async ({ page }) => {
      test.setTimeout(60_000);
      await page.setViewportSize({ width, height });
      await page.addInitScript((val) => {
        sessionStorage.setItem("tilo-boot-seen", "1");
        localStorage.setItem("tilo.time", val === "dark" ? "night" : "day");
      }, theme);
      await page.goto("/world/k1");
      await expect(page.getByTestId("park-page-world")).toBeVisible({ timeout: 30_000 });
      if (theme === "dark") {
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      }
      await page.evaluate(() => document.fonts.ready.then(() => undefined));

      for (const dir of evidenceDirs) {
        await page.screenshot({
          path: resolve(dir, `world-${width}-${theme}.png`),
          fullPage: true,
          animations: "disabled",
        });
      }
    });

    test(`TW-DARK Result tab ${width}px ${theme}`, async ({ page }) => {
      test.setTimeout(60_000);
      await page.setViewportSize({ width, height });
      await page.addInitScript((val) => {
        sessionStorage.setItem("tilo-boot-seen", "1");
        localStorage.setItem("tilo.time", val === "dark" ? "night" : "day");
      }, theme);
      await page.goto("/world/k1");
      await expect(page.getByTestId("park-page-world")).toBeVisible({ timeout: 30_000 });
      if (theme === "dark") {
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      }
      // Click the Result tab
      const resultTab = page.locator(".park-world-tab", { hasText: "Result" });
      if (await resultTab.isVisible()) {
        await resultTab.click();
      }
      await page.evaluate(() => document.fonts.ready.then(() => undefined));

      for (const dir of evidenceDirs) {
        await page.screenshot({
          path: resolve(dir, `result-${width}-${theme}.png`),
          fullPage: true,
          animations: "disabled",
        });
      }
    });

    test(`TW-DARK Chat pop-up ${width}px ${theme}`, async ({ page }) => {
      test.setTimeout(60_000);
      await page.setViewportSize({ width, height });
      await page.addInitScript((val) => {
        sessionStorage.setItem("tilo-boot-seen", "1");
        localStorage.setItem("tilo.time", val === "dark" ? "night" : "day");
      }, theme);
      await page.goto("/world/k1");
      await expect(page.getByTestId("park-page-world")).toBeVisible({ timeout: 30_000 });
      if (theme === "dark") {
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      }

      // Open the chat pop-up
      const bubble = page.locator("button.park-bubble");
      if (await bubble.isVisible()) {
        await bubble.click();
        await expect(page.locator(".park-bubble__panel")).toBeVisible({ timeout: 5_000 });
      }
      await page.evaluate(() => document.fonts.ready.then(() => undefined));

      for (const dir of evidenceDirs) {
        await page.screenshot({
          path: resolve(dir, `chat-${width}-${theme}.png`),
          fullPage: true,
          animations: "disabled",
        });
      }
    });
  }
}
