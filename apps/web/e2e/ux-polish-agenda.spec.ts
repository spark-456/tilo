import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "UX-POLISH",
);

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`UX-POLISH-AGENDA ${width} ${theme} has polished controls and no overlap`, async ({
      page,
    }) => {
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/agenda");
      await expect(page.getByRole("heading", { name: "Agenda", exact: true })).toBeVisible({
        timeout: 10_000,
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
        path: resolve(evidence, `${width}-${theme}-Agenda.png`),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
