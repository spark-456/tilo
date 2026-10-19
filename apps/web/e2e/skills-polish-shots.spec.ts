import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { type Page, expect, test } from "@playwright/test";

const outputDir =
  process.env.SKILLS_POLISH_DIR ?? "C:/dev/Tilo/agy-bridge/evidence/SKILLS-POLISH/after";

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

for (const width of [1440, 390] as const) {
  test.describe(`SKILLS_POLISH @${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 } });

    test(`capture skills list at ${width}`, async ({ page }) => {
      test.setTimeout(90_000);
      await preparePage(page);
      await page.goto("/skills");
      await expect(page.getByRole("heading", { name: "Skills", exact: true })).toBeVisible({
        timeout: 30_000,
      });
      await finishNavigation(page);

      // Light
      await page
        .locator("[data-park]")
        .evaluate((node: HTMLElement) => node.setAttribute("data-time", "day"));
      await page.waitForTimeout(300);
      await page.screenshot({
        path: resolve(outputDir, `${width}-light-skills-list.png`),
        fullPage: true,
        animations: "disabled",
      });

      // Dark
      await page
        .locator("[data-park]")
        .evaluate((node: HTMLElement) => node.setAttribute("data-time", "night"));
      await page.waitForTimeout(300);
      await page.screenshot({
        path: resolve(outputDir, `${width}-dark-skills-list.png`),
        fullPage: true,
        animations: "disabled",
      });
    });

    test(`capture skill drawer at ${width}`, async ({ page }) => {
      test.setTimeout(90_000);
      await preparePage(page);
      await page.goto("/skills?id=invoice");
      await expect(page.locator(".park-skill-drawer")).toBeVisible({
        timeout: 30_000,
      });
      await finishNavigation(page);

      // Light
      await page
        .locator("[data-park]")
        .evaluate((node: HTMLElement) => node.setAttribute("data-time", "day"));
      await page.waitForTimeout(300);
      await page.screenshot({
        path: resolve(outputDir, `${width}-light-skill-drawer.png`),
        fullPage: true,
        animations: "disabled",
      });

      // Dark
      await page
        .locator("[data-park]")
        .evaluate((node: HTMLElement) => node.setAttribute("data-time", "night"));
      await page.waitForTimeout(300);
      await page.screenshot({
        path: resolve(outputDir, `${width}-dark-skill-drawer.png`),
        fullPage: true,
        animations: "disabled",
      });
    });

    test(`capture teach wizard flow at ${width}`, async ({ page }) => {
      test.setTimeout(90_000);
      await preparePage(page);
      await page.goto("/skills");
      await expect(page.getByRole("heading", { name: "Skills", exact: true })).toBeVisible({
        timeout: 30_000,
      });
      await finishNavigation(page);

      // Open teach
      await page.getByRole("button", { name: "+ Teach Tilo a skill" }).click();
      await expect(page.locator('[data-testid="skills-teach"]')).toBeVisible({
        timeout: 10_000,
      });

      // Step 1: Light
      await page
        .locator("[data-park]")
        .evaluate((node: HTMLElement) => node.setAttribute("data-time", "day"));
      await page.waitForTimeout(300);
      await page.screenshot({
        path: resolve(outputDir, `${width}-light-teach-step1.png`),
        fullPage: true,
        animations: "disabled",
      });

      // Step 1: Dark
      await page
        .locator("[data-park]")
        .evaluate((node: HTMLElement) => node.setAttribute("data-time", "night"));
      await page.waitForTimeout(300);
      await page.screenshot({
        path: resolve(outputDir, `${width}-dark-teach-step1.png`),
        fullPage: true,
        animations: "disabled",
      });

      // Type description so Next enables
      const textarea = page.locator("textarea.park-teach__text");
      await textarea.fill(
        "Monitor competitors pricing weekly and summarize changes in a spreadsheet",
      );
      await page.waitForTimeout(200);

      // Click Next: show an example
      const nextBtn = page.getByRole("button", { name: /Next/i }).first();
      await nextBtn.click();
      await page.waitForTimeout(500);

      // Step 2: Light & Dark
      await page
        .locator("[data-park]")
        .evaluate((node: HTMLElement) => node.setAttribute("data-time", "day"));
      await page.waitForTimeout(300);
      await page.screenshot({
        path: resolve(outputDir, `${width}-light-teach-step2.png`),
        fullPage: true,
        animations: "disabled",
      });

      await page
        .locator("[data-park]")
        .evaluate((node: HTMLElement) => node.setAttribute("data-time", "night"));
      await page.waitForTimeout(300);
      await page.screenshot({
        path: resolve(outputDir, `${width}-dark-teach-step2.png`),
        fullPage: true,
        animations: "disabled",
      });

      // Click Next: review the steps
      const reviewBtn = page.getByRole("button", { name: /review the steps/i }).first();
      if ((await reviewBtn.count()) > 0) {
        await reviewBtn.click();
        await page.waitForTimeout(500);

        // Step 3: Light & Dark
        await page
          .locator("[data-park]")
          .evaluate((node: HTMLElement) => node.setAttribute("data-time", "day"));
        await page.waitForTimeout(300);
        await page.screenshot({
          path: resolve(outputDir, `${width}-light-teach-step3.png`),
          fullPage: true,
          animations: "disabled",
        });

        await page
          .locator("[data-park]")
          .evaluate((node: HTMLElement) => node.setAttribute("data-time", "night"));
        await page.waitForTimeout(300);
        await page.screenshot({
          path: resolve(outputDir, `${width}-dark-teach-step3.png`),
          fullPage: true,
          animations: "disabled",
        });
      }
    });
  });
}
