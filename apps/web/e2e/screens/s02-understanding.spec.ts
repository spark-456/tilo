import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

// biome-ignore format: compact spec
for (const viewport of [DESKTOP, MOBILE]) {
  test(`FR-INT-03 FR-INT-04 FR-INT-05 S-02: renders brief chips, applied preference and questions at ${viewport.width}x${viewport.height}, axe clean`, async ({ page }) => {
    test.setTimeout(60_000);
    const problems = watchConsole(page);
    await page.setViewportSize(viewport);
    await page.goto("/");
    await page.getByLabel("Describe your task").fill("Compare the two supplier quotes"); // S-01 needs text
    await page.getByRole("button", { name: "Start task" }).click();

    await expect(page.getByRole("heading", { level: 1, name: "Understanding" })).toBeVisible();
    const goalInput = page.getByTestId("brief-chip-goal").locator("input");
    await expect(goalInput).toBeVisible();
    await expect(page.getByTestId("brief-chip-audience").locator("input")).toBeVisible();
    await expect(page.getByTestId("brief-chip-sensitivity").locator("select")).toBeVisible();
    const fontSize = await goalInput.evaluate((el) => getComputedStyle(el).fontSize);
    expect(Number.parseFloat(fontSize)).toBeGreaterThanOrEqual(14);
    await expect(page.getByTestId("applied-preference")).toContainText("Using your preference: PDF output");
    await expect(page.getByTestId("applied-preference")).toContainText("mem_output_format");

    await page.getByTestId("skip-question-0").click();
    await expect(page.getByTestId("assumed-note")).toHaveText("Assumed: Shipping is included in each total");

    const primary = page.locator("button.primary");
    await expect(primary).toHaveCount(1);
    await expect(primary).toHaveText("Continue");

    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations).toEqual([]);

    await primary.click();
    await expect(page.getByRole("heading", { level: 1, name: "Approaches" })).toBeVisible();
    expect(problems).toEqual([]);
  });
}
