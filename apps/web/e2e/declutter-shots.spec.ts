import { copyFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { type Page, expect, test } from "@playwright/test";

const outputDir = process.env.DECLUTTER_DIR ?? "C:/dev/Tilo/agy-bridge/evidence/DECLUTTER/before";

mkdirSync(outputDir, { recursive: true });

async function preparePage(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("tilo.time", "day");
    sessionStorage.setItem("tilo-boot-seen", "1");
  });
}

async function finishNavigation(page: Page) {
  const bootCover = page.locator("#tilo-boot-cover");
  if ((await bootCover.count()) > 0) {
    await bootCover.waitFor({ state: "detached", timeout: 15_000 }).catch(() => {});
  }
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.waitForTimeout(600);
}

const PAGES = [
  { name: "Home", path: "/", testId: "park-page-home" },
  { name: "Worlds", path: "/worlds", testId: "park-page-worlds" },
  { name: "World", path: "/world/hires", testId: "park-page-world" },
  { name: "Skills", path: "/skills", testId: "park-page-skills" },
  { name: "Team", path: "/team", testId: "park-page-team" },
  { name: "Connectors", path: "/connectors", testId: "park-page-connectors" },
  { name: "Needs", path: "/needs", testId: "park-page-needs" },
  { name: "Ledger", path: "/ledger", testId: "park-page-ledger" },
];

for (const width of [1440, 390] as const) {
  test.describe(`DECLUTTER @${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 } });

    for (const p of PAGES) {
      test(`capture ${p.name} at ${width} light & dark`, async ({ page }) => {
        test.setTimeout(60_000);
        await preparePage(page);
        await page.goto(p.path);
        await expect(page.locator(`[data-testid="${p.testId}"]`)).toBeVisible({
          timeout: 30_000,
        });
        await finishNavigation(page);

        // Light mode
        await page
          .locator("[data-park]")
          .evaluate((node: HTMLElement) => node.setAttribute("data-time", "day"));
        await page.waitForTimeout(300);

        const lightPath = resolve(outputDir, `${width}-light-${p.name}.png`);
        await page.screenshot({
          path: lightPath,
          fullPage: true,
          animations: "disabled",
        });

        // Dark mode
        await page
          .locator("[data-park]")
          .evaluate((node: HTMLElement) => node.setAttribute("data-time", "night"));
        await page.waitForTimeout(300);

        const darkPath = resolve(outputDir, `${width}-dark-${p.name}.png`);
        await page.screenshot({
          path: darkPath,
          fullPage: true,
          animations: "disabled",
        });

        // Also duplicate aliases for Needs / Skills
        if (p.name === "Needs") {
          copyFileSync(lightPath, resolve(outputDir, `${width}-light-NeedsYou.png`));
          copyFileSync(darkPath, resolve(outputDir, `${width}-dark-NeedsYou.png`));
          copyFileSync(lightPath, resolve(outputDir, `${width}-light-Needs-you.png`));
          copyFileSync(darkPath, resolve(outputDir, `${width}-dark-Needs-you.png`));
        }
        if (p.name === "Skills") {
          copyFileSync(lightPath, resolve(outputDir, `${width}-light-Skills-list.png`));
          copyFileSync(darkPath, resolve(outputDir, `${width}-dark-Skills-list.png`));
        }
      });
    }
  });
}
