import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { type Page, expect, test } from "@playwright/test";

const evidenceDir = resolve("C:/dev/Tilo/agy-bridge/evidence/AGENDA-GCAL");
mkdirSync(evidenceDir, { recursive: true });

async function prepare(page: Page, theme: "day" | "night" = "day") {
  await page.addInitScript((val: string) => {
    localStorage.setItem("tilo.time", val);
    sessionStorage.setItem("tilo-boot-seen", "1");
  }, theme);
}

async function finishNav(page: Page) {
  const bootCover = page.locator("#tilo-boot-cover");
  if ((await bootCover.count()) > 0) {
    await bootCover.waitFor({ state: "detached", timeout: 15_000 }).catch(() => {});
  }
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.waitForTimeout(600);
}

test.describe("AGENDA-GCAL Evidence Screenshots", () => {
  for (const width of [1440, 390] as const) {
    for (const theme of ["light", "dark"] as const) {
      test(`AGENDA-GCAL ${width} ${theme} week and month`, async ({ page }) => {
        test.setTimeout(120_000);
        await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
        await prepare(page, theme === "dark" ? "night" : "day");

        await page.goto("/agenda");
        await expect(page.locator('[data-testid="park-page-agenda"]')).toBeVisible({
          timeout: 60_000,
        });
        await finishNav(page);

        if (theme === "dark") {
          await page
            .locator("[data-park]")
            .evaluate((node: HTMLElement) => node.setAttribute("data-time", "night"));
          await page.waitForTimeout(300);
        }

        // Switch to Week view (or Day view on mobile if desired)
        const weekBtn = page.getByRole("radio", { name: /week/i });
        if ((await weekBtn.count()) > 0 && width === 1440) {
          await weekBtn.click();
          await page.waitForTimeout(400);
        }

        // Capture Week screenshot
        await page.screenshot({
          path: resolve(evidenceDir, `${width}-${theme}-week.png`),
          fullPage: true,
          animations: "disabled",
        });

        if (width === 390) {
          await page.screenshot({
            path: resolve(evidenceDir, `${width}-${theme}-day.png`),
            fullPage: true,
            animations: "disabled",
          });
        }

        // Switch to Month view
        const monthBtn = page.getByRole("radio", { name: /month/i });
        if ((await monthBtn.count()) > 0) {
          await monthBtn.click();
          await page.waitForTimeout(400);
        }

        // Capture Month screenshot
        await page.screenshot({
          path: resolve(evidenceDir, `${width}-${theme}-month.png`),
          fullPage: true,
          animations: "disabled",
        });
      });
    }
  }
});
