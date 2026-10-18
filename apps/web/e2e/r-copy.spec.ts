import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "R-COPY",
);
const COPY =
  "YouTube isn't connected, and liking or commenting posts publicly as you. Tilo can watch and summarise a video, or draft a comment for you to post.";

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`R-COPY ${width} ${theme} explains the YouTube limitation`, async ({ page }) => {
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/skills-record-harness.html", { waitUntil: "domcontentloaded" });
      await page.getByRole("button", { name: "+ Teach Tilo a skill" }).click();
      if (theme === "dark") {
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      }
      await page.getByLabel("What it does, step by step").fill("Help with YouTube videos");
      await page.getByRole("button", { name: "Next: show an example →" }).click();
      const review = page.getByRole("button", { name: "Next: review the steps →" });
      await expect(review).toBeEnabled();
      await review.click();
      await expect(page.getByText(COPY)).toBeVisible();
      await page.screenshot({
        path: resolve(evidence, `${width}-${theme}.png`),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
