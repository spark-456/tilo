import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidenceDirs = [
  resolve(process.cwd(), "../../agy-bridge/evidence/TW-3"),
  resolve(process.cwd(), "../../../../Tilo/agy-bridge/evidence/TW-3"),
];

for (const dir of evidenceDirs) {
  try {
    mkdirSync(dir, { recursive: true });
  } catch {}
}

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`TW-3 ${width} ${theme} stage buildings islands camera replay`, async ({ page }) => {
      test.setTimeout(120_000);
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.addInitScript((val) => {
        sessionStorage.setItem("tilo-boot-seen", "1");
        localStorage.setItem("tilo.time", val === "dark" ? "night" : "day");
      }, theme);
      await page.goto("/world/k1");
      await expect(page.getByTestId("park-page-world")).toBeVisible({ timeout: 60_000 });
      if (theme === "dark") {
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      }
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      for (const dir of evidenceDirs) {
        await page.screenshot({
          path: resolve(dir, `${width}-${theme}-TW-3.png`),
          fullPage: true,
          animations: "disabled",
        });
      }
    });
  }
}
