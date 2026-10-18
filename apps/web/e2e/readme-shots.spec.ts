import { mkdirSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const readmeDir = resolve(__dirname, "../../docs/assets/readme");
const evidenceDir = resolve(__dirname, "../../../../Tilo/agy-bridge/evidence/README-SHOTS");

mkdirSync(readmeDir, { recursive: true });
mkdirSync(evidenceDir, { recursive: true });

async function preparePage(page: any, theme: "day" | "night" = "day") {
  await page.addInitScript((val: string) => {
    localStorage.setItem("tilo.time", val);
    sessionStorage.setItem("tilo-boot-seen", "1");
  }, theme);
}

async function finishNavigation(page: any) {
  const bootCover = page.locator("#tilo-boot-cover");
  if (await bootCover.count() > 0) {
    await bootCover.waitFor({ state: "detached", timeout: 15_000 }).catch(() => {});
  }
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.waitForTimeout(500);
}

test.describe("README Screenshots @1440", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("Capture 1440 Home, Worlds, World running, Result, Agenda, Teach Tilo, Team, Skills", async ({ page }) => {
    test.setTimeout(180_000);
    await preparePage(page, "day");

    // 1. Home
    await page.goto("/");
    await expect(page.locator('[data-testid="park-page-home"]')).toBeVisible({ timeout: 60_000 });
    await finishNavigation(page);
    await page.screenshot({
      path: resolve(readmeDir, "1440-home.png"),
      fullPage: false,
      animations: "disabled",
    });

    // Evidence light & dark for Home
    await page.screenshot({
      path: resolve(evidenceDir, "1440-light-Home.png"),
      fullPage: false,
      animations: "disabled",
    });
    await page.locator("[data-park]").evaluate((node: HTMLElement) => node.setAttribute("data-time", "night"));
    await page.waitForTimeout(300);
    await page.screenshot({
      path: resolve(evidenceDir, "1440-dark-Home.png"),
      fullPage: false,
      animations: "disabled",
    });
    await page.locator("[data-park]").evaluate((node: HTMLElement) => node.setAttribute("data-time", "day"));
    await page.waitForTimeout(300);

    // 2. Worlds
    await page.goto("/worlds");
    await expect(page.locator('[data-testid="park-page-worlds"]')).toBeVisible({ timeout: 60_000 });
    await finishNavigation(page);
    await page.screenshot({
      path: resolve(readmeDir, "1440-worlds.png"),
      fullPage: false,
      animations: "disabled",
    });

    // 3. A running World
    await page.goto("/world/hires");
    await expect(page.locator('[data-testid="park-page-world"]')).toBeVisible({ timeout: 60_000 });
    await finishNavigation(page);
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: resolve(readmeDir, "1440-world-running.png"),
      fullPage: false,
      animations: "disabled",
    });

    // 4. The Result tab
    await page.goto("/world/comp");
    await expect(page.locator('[data-testid="park-page-world"]')).toBeVisible({ timeout: 60_000 });
    await finishNavigation(page);
    const resultTab = page.locator('#park-world-tab-result');
    if (await resultTab.isVisible()) {
      await resultTab.click();
    } else {
      await page.getByRole("tab", { name: "Result" }).click();
    }
    await page.waitForTimeout(500);
    await page.screenshot({
      path: resolve(readmeDir, "1440-world-result.png"),
      fullPage: false,
      animations: "disabled",
    });

    // 5. Agenda (calendar and pinboards)
    await page.goto("/agenda");
    await expect(page.locator('[data-testid="park-page-agenda"]')).toBeVisible({ timeout: 60_000 });
    await finishNavigation(page);
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: resolve(readmeDir, "1440-agenda.png"),
      fullPage: false,
      animations: "disabled",
    });

    // 6. Teach Tilo
    await page.goto("/skills");
    await expect(page.locator('[data-testid="park-page-skills"]')).toBeVisible({ timeout: 60_000 });
    await finishNavigation(page);
    const startTeachBtn = page.getByRole("button", { name: /Start teaching/i });
    if (await startTeachBtn.isVisible()) {
      await startTeachBtn.click();
      await page.waitForTimeout(500);
      await expect(page.locator('[data-testid="skills-teach"]')).toBeVisible({ timeout: 10_000 });
    }
    await page.screenshot({
      path: resolve(readmeDir, "1440-teach-tilo.png"),
      fullPage: false,
      animations: "disabled",
    });

    // 7. Skills (gallery)
    await page.goto("/skills");
    await expect(page.locator('[data-testid="park-page-skills"]')).toBeVisible({ timeout: 60_000 });
    await finishNavigation(page);
    await page.screenshot({
      path: resolve(readmeDir, "1440-skills.png"),
      fullPage: false,
      animations: "disabled",
    });

    // 8. Team
    await page.goto("/team");
    await expect(page.locator('[data-testid="park-page-team"]')).toBeVisible({ timeout: 60_000 });
    await finishNavigation(page);
    await page.screenshot({
      path: resolve(readmeDir, "1440-team.png"),
      fullPage: false,
      animations: "disabled",
    });
  });
});

test.describe("README Screenshots @390", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("Capture 390 Home, a World, Agenda", async ({ page }) => {
    test.setTimeout(120_000);
    await preparePage(page, "day");

    // 9. Home (390)
    await page.goto("/");
    await expect(page.locator('[data-testid="park-page-home"]')).toBeVisible({ timeout: 60_000 });
    await finishNavigation(page);
    await page.screenshot({
      path: resolve(readmeDir, "390-home.png"),
      fullPage: false,
      animations: "disabled",
    });

    // Evidence light & dark for 390
    await page.screenshot({
      path: resolve(evidenceDir, "390-light-Home.png"),
      fullPage: false,
      animations: "disabled",
    });
    await page.locator("[data-park]").evaluate((node: HTMLElement) => node.setAttribute("data-time", "night"));
    await page.waitForTimeout(300);
    await page.screenshot({
      path: resolve(evidenceDir, "390-dark-Home.png"),
      fullPage: false,
      animations: "disabled",
    });
    await page.locator("[data-park]").evaluate((node: HTMLElement) => node.setAttribute("data-time", "day"));
    await page.waitForTimeout(300);

    // 10. A World (390)
    await page.goto("/world/hires");
    await expect(page.locator('[data-testid="park-page-world"]')).toBeVisible({ timeout: 60_000 });
    await finishNavigation(page);
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: resolve(readmeDir, "390-world.png"),
      fullPage: false,
      animations: "disabled",
    });

    // 11. Agenda (390)
    await page.goto("/agenda");
    await expect(page.locator('[data-testid="park-page-agenda"]')).toBeVisible({ timeout: 60_000 });
    await finishNavigation(page);
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: resolve(readmeDir, "390-agenda.png"),
      fullPage: false,
      animations: "disabled",
    });
  });
});
