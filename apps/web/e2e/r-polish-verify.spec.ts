import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { type Locator, type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";

const sizes = [
  { width: 800, height: 900 },
  { width: 1024, height: 900 },
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
] as const;

const shotDir = process.env.R_POLISH_VERIFY_SHOTS;
if (shotDir) mkdirSync(shotDir, { recursive: true });

async function expectInsideViewport(page: Page, locator: Locator, label: string) {
  const box = await locator.boundingBox();
  const viewport = page.viewportSize();
  if (!(box && viewport)) throw new Error(`${label} has no box`);
  expect(box.x, `${label} left edge`).toBeGreaterThanOrEqual(-0.5);
  expect(box.x + box.width, `${label} right edge`).toBeLessThanOrEqual(viewport.width + 0.5);
}

async function expectNoOverlap(a: Locator, b: Locator, label: string) {
  const [one, two] = await Promise.all([a.boundingBox(), b.boundingBox()]);
  if (!(one && two)) throw new Error(`${label} has no boxes`);
  const width = Math.max(
    0,
    Math.min(one.x + one.width, two.x + two.width) - Math.max(one.x, two.x),
  );
  const height = Math.max(
    0,
    Math.min(one.y + one.height, two.y + two.height) - Math.max(one.y, two.y),
  );
  expect(width * height, label).toBeLessThanOrEqual(1);
}

async function expectNoPageOverflow(page: Page) {
  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }));
  expect(overflow.document, "document horizontal overflow").toBeLessThanOrEqual(0);
  expect(overflow.body, "body horizontal overflow").toBeLessThanOrEqual(0);
}

for (const size of sizes) {
  for (const theme of ["day", "night"] as const) {
    test(`R_POLISH_VERIFY_${size.width}_${theme}_World_and_Home_have_no_overlap`, async ({
      page,
    }) => {
      test.setTimeout(120_000);
      await page.setViewportSize(size);
      await page.addInitScript((value) => {
        localStorage.setItem("tilo.time", value);
        sessionStorage.setItem("tilo-boot-seen", "1");
      }, theme);
      const problems = collectConsoleProblems(page);

      await page.goto("/");
      await expect(page.getByTestId("park-page-home")).toBeVisible({ timeout: 120_000 });
      await page.locator("#tilo-boot-cover").waitFor({ state: "detached", timeout: 30_000 });
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      await expectNoPageOverflow(page);
      await expectInsideViewport(page, page.locator(".park-home-composer"), "Home composer");
      await expectInsideViewport(page, page.locator(".park-home-kpis"), "Home summary tiles");
      if (shotDir) {
        await page.screenshot({
          path: join(shotDir, `${size.width}-${theme}-home.png`),
          fullPage: true,
        });
      }

      await page.goto("/world/k1");
      await expect(page.getByTestId("park-page-world")).toBeVisible({ timeout: 120_000 });
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      await expectNoPageOverflow(page);
      const header = page.locator(".park-world-head");
      const map = page.locator(".park-world-mapcard");
      const panels = page.locator(".park-world-panels");
      await expectInsideViewport(page, header, "World header");
      await expectInsideViewport(page, map, "World stage");
      await expectInsideViewport(page, panels, "World details");
      await expectNoOverlap(header, map, "World header must not cover the stage");
      await expectNoOverlap(map, panels, "World details must not cover the stage");
      if (shotDir) {
        await page.screenshot({
          path: join(shotDir, `${size.width}-${theme}-world.png`),
          fullPage: true,
        });
      }

      expect(problems).toEqual([]);
    });
  }
}
