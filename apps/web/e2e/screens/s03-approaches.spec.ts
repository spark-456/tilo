import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

// biome-ignore format: compact e2e spec
for (const viewport of [DESKTOP, MOBILE]) {
  test(`FR-INT-06 FR-INT-08 S-03: renders approach cards, budget copy and approves at ${viewport.width}x${viewport.height}, axe clean`, async ({ page }) => {
    test.setTimeout(60_000);
    const problems = watchConsole(page);
    await page.setViewportSize(viewport);
    await page.goto("/task/task_fixture_1/approaches");

    await expect(page.getByRole("heading", { level: 1, name: "Approaches" })).toBeVisible();
    await expect(page.getByTestId("approach-card-quick")).toBeVisible();
    await expect(page.getByTestId("approach-card-thorough")).toBeVisible();
    await expect(page.getByTestId("approach-card-quick").getByTestId("recommended-badge")).toHaveText("Recommended");
    await expect(page.getByTestId("select-approach-quick")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("select-approach-thorough")).toHaveAttribute("aria-pressed", "false");

    // 14 px exactly (the minimum on the type scale): the badge and the select button must not compound.
    for (const id of ["recommended-badge", "select-approach-quick", "budget-cap-input"]) {
      const size = await page.getByTestId(id).first().evaluate((el) => getComputedStyle(el).fontSize);
      expect(Number.parseFloat(size), id).toBeGreaterThanOrEqual(14);
    }
    for (const id of ["recommended-badge", "select-approach-quick"]) {
      await expect(page.getByTestId(id).first()).toHaveCSS("font-size", "14px");
    }

    const primary = page.locator("button.primary");
    await expect(primary).toHaveCount(1);
    await expect(primary).toHaveText("Start this approach");
    await expect(primary).toBeDisabled();

    await page.getByTestId("select-approach-thorough").click();
    await expect(page.getByTestId("select-approach-thorough")).toHaveAttribute("aria-pressed", "true");
    await expect(primary).toBeEnabled();
    const cap = page.getByTestId("budget-cap-input");
    await expect(cap).toHaveValue("130");
    await expect(page.getByTestId("budget-line")).toHaveText("This run can use up to 130 credits (about US$0.65). You can pause it any time.");

    const hint = page.getByTestId("budget-cap-hint");
    await expect(cap).toHaveAttribute("aria-describedby", "budget-cap-hint");
    for (const bad of ["", "0", "1.5", "-5", "301", "1e20"]) {
      await cap.fill(bad);
      await expect(cap, bad).toHaveAttribute("aria-invalid", "true");
      await expect(primary, bad).toBeDisabled();
      await expect(hint, bad).toHaveText("Enter a whole number from 1 to 300 credits.");
      await expect(page.getByTestId("budget-line"), bad).not.toHaveText(/\d/);
    }

    await cap.fill("250");
    await expect(cap).toHaveAttribute("aria-invalid", "false");
    await expect(hint).toHaveText("");
    await expect(primary).toBeEnabled();
    await expect(page.getByTestId("budget-line")).toHaveText("This run can use up to 250 credits (about US$1.25). You can pause it any time.");

    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations).toEqual([]);

    await primary.click();
    await expect(page.getByRole("heading", { level: 1, name: "World" })).toBeVisible();
    expect(problems).toEqual([]);
  });
}
