import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "P0-SKILLS-PAGE",
);

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`P0-SKILLS-PAGE ${width} ${theme} has responsive hero grid and no clipped text`, async ({
      page,
    }) => {
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/skills");
      await expect(page.getByRole("heading", { name: "Skills", exact: true })).toBeVisible({
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

      // Verify Teach Tilo hero section is visible
      const banner = page.locator('section[aria-label="Teach Tilo a skill"]');
      await expect(banner).toBeVisible();

      // Verify bottom pill for approval is NOT present
      const waitingPill = page.locator(
        '.park-shell__runbar:has-text("Waiting for your approval")',
      );
      await expect(waitingPill).toHaveCount(0);

      const shotPath = `${width}-${theme}-Skills.png`;
      await page.screenshot({
        path: resolve(evidence, shotPath),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
