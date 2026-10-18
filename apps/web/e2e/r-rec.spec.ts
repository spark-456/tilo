import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "R-REC",
);

test.use({
  launchOptions: {
    args: [
      "--use-fake-ui-for-media-stream",
      "--auto-select-desktop-capture-source=Entire screen",
      "--allow-http-screen-capture",
    ],
  },
});

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`R-REC ${width} ${theme} contains the recording preview`, async ({ page }) => {
      test.setTimeout(60_000);
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/skills-record-harness.html", { waitUntil: "domcontentloaded" });
      await page.getByRole("button", { name: "+ Teach Tilo a skill" }).click();
      if (theme === "dark") {
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      }
      await page.getByRole("button", { name: "Start recording" }).click();
      await expect(page.getByRole("button", { name: "Stop recording" })).toBeVisible();
      await page.waitForTimeout(1_000);
      await page.getByRole("button", { name: "Stop recording" }).click();
      const preview = page.getByLabel("Recording preview");
      await expect(preview).toBeVisible();
      const box = await preview.boundingBox();
      expect(box?.width).toBeLessThanOrEqual(width);
      expect(box?.height).toBeLessThanOrEqual(360);
      await page.screenshot({
        path: resolve(evidence, `${width}-${theme}.png`),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
