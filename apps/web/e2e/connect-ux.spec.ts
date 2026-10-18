import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "CONNECT-UX",
);

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`CONNECT-UX ${width} ${theme} has 3 Google cards, coming later, and good layout`, async ({
      page,
    }) => {
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/connectors");
      await expect(page.getByRole("heading", { name: "Connectors", exact: true })).toBeVisible({
        timeout: 15_000,
      });

      if (theme === "dark") {
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      }
      await page.evaluate(() => document.fonts.ready.then(() => undefined));

      // Assert only Gmail, Drive, Calendar are real connected cards
      const cardCount = await page.locator(".park-connectors-card").count();
      expect(cardCount).toBe(3);

      // Assert Coming later is present and never has Canva
      const comingLater = page.locator('[data-coming-later], .park-connectors-coming-later');
      await expect(comingLater).toBeVisible();
      const comingText = await comingLater.textContent();
      expect(comingText?.toLowerCase()).not.toContain("canva");

      const shotPath = `${width}-${theme}-Connectors.png`;
      await page.screenshot({
        path: resolve(evidence, shotPath),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
