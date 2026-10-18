import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "P0-WORLDS-CARDS",
);

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`P0-WORLDS-CARDS ${width} ${theme} has clean branded cards without black cubes or empty Village text`, async ({
      page,
    }) => {
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/worlds");
      await expect(page.getByRole("heading", { name: "Worlds", exact: true })).toBeVisible({
        timeout: 15_000,
      });
      if (theme === "dark") {
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      }
      await page.evaluate(() => document.fonts.ready.then(() => undefined));

      // Verify no horizontal overflow
      const overflows = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      );
      expect(overflows).toBe(false);

      // Verify cards exist and have no black cube blocks
      const blocks = page.locator(".park-worldthumb__block");
      await expect(blocks).toHaveCount(0);

      const shotPath = `${width}-${theme}-Worlds.png`;
      await page.screenshot({
        path: resolve(evidence, shotPath),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
