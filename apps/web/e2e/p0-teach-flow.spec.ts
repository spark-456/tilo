import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "P0-TEACH-FLOW",
);

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`P0_TEACH_FLOW_review_${width}_${theme}_shows_browser_limit`, async ({ page }) => {
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/skills-record-harness.html", { waitUntil: "domcontentloaded" });
      if (theme === "dark") {
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      }
      await page.getByRole("button", { name: "+ Teach Tilo a skill" }).click();
      await page
        .getByLabel("What it does, step by step")
        .fill("Open YouTube and play the first video");
      await page.getByRole("button", { name: "Next: show an example" }).click();
      await page.getByRole("button", { name: "Next: review the steps" }).click();
      await expect(
        page.getByText("Tilo can't operate a browser yet", { exact: false }),
      ).toBeVisible();
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      await page.screenshot({
        path: resolve(evidence, `${width}-${theme}-review.png`),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
