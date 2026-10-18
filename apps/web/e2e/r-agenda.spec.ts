import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "R-AGENDA",
);

test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/agenda", { timeout: 120_000 });
  await page.getByRole("heading", { name: "Agenda", exact: true }).waitFor({ timeout: 120_000 });
  await page.close();
});

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`R-AGENDA ${width} ${theme} calendar, boards, and cards`, async ({ page }) => {
      test.setTimeout(120_000);
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/agenda", { timeout: 120_000 });
      await expect(page.getByRole("heading", { name: "Agenda", exact: true })).toBeVisible({
        timeout: 120_000,
      });
      if (theme === "dark")
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      await expect(page.getByLabel("This week")).toBeVisible();
      await expect(page.getByLabel("Boards")).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: resolve(evidence, `${width}-${theme}.png`),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
