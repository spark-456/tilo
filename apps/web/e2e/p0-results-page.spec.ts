import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "P0-RESULTS-PAGE",
);

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`P0-RESULTS-PAGE ${width} ${theme} shows a readable delivered result`, async ({
      page,
    }) => {
      test.setTimeout(60_000);
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto(`/world/k1?theme=${theme}`);
      await expect(page.getByTestId("park-page-world")).toBeVisible({ timeout: 30_000 });
      await page.addScriptTag({ type: "module", url: "/e2e/support/p0ResultsHarness.tsx" });
      const result = page.getByTestId("result-tab");
      await expect(result).toBeVisible();
      await expect(result.locator('[data-testid="run-result"]')).toHaveCount(1);
      await expect(result.getByText("Move → the next review after approval.")).toBeVisible();
      await expect(result.locator(".tw-res-actions button")).toHaveCount(4);
      await result.locator('[data-testid="working-files"] summary').click();
      const workingName = result.locator(".tw-res-files__name", {
        hasText: "Supplier comparison and recommendations for the October launch.md",
      });
      await expect(workingName).toBeVisible();
      if (width === 390)
        expect(await workingName.evaluate((name) => name.scrollWidth > name.clientWidth)).toBe(
          false,
        );
      const overflow = await page
        .getByTestId("result-visual-host")
        .evaluate((host) => host.scrollWidth > host.clientWidth);
      expect(overflow).toBe(false);
      await page.screenshot({
        path: resolve(evidence, `${width}-${theme}-result.png`),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}

test("P0_RESULTS_docx_document_preview_renders_in_the_browser", async ({ page }) => {
  test.setTimeout(60_000);
  mkdirSync(evidence, { recursive: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/world/k1?docx=1");
  await expect(page.getByTestId("park-page-world")).toBeVisible({ timeout: 30_000 });
  await page.addScriptTag({ type: "module", url: "/e2e/support/p0ResultsHarness.tsx" });
  const preview = page.getByTestId("result-preview");
  await expect(preview.getByRole("heading", { name: "Decision brief" })).toBeVisible();
  await expect(preview.locator("strong", { hasText: "option B" })).toBeVisible();
  await expect(preview.getByRole("table")).toContainText("Cost");
  expect(
    await page
      .getByTestId("result-visual-host")
      .evaluate((host) => host.scrollWidth > host.clientWidth),
  ).toBe(false);
  await page.screenshot({
    path: resolve(evidence, "390-light-docx.png"),
    fullPage: true,
    animations: "disabled",
  });
});
