import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { watchConsole } from "../support/screens";
import { DESKTOP, MOBILE } from "../support/viewports";

for (const viewport of [DESKTOP, MOBILE]) {
  test(`FR-INT-06 FR-INT-08 S-03: renders approach cards, budget copy and approves at ${viewport.width}x${viewport.height}, axe clean`, async ({
    page,
  }) => {
    test.setTimeout(60_000);
    const problems = watchConsole(page);
    await page.setViewportSize(viewport);
    await page.goto("/task/task_fixture_1/approaches");

    await expect(page.getByRole("heading", { level: 1, name: "Approaches" })).toBeVisible();
    const quick = page.getByTestId("approach-card-quick");
    const thorough = page.getByTestId("approach-card-thorough");
    await expect(quick).toBeVisible();
    await expect(thorough).toBeVisible();
    await expect(quick.getByTestId("recommended-badge")).toHaveText("Recommended");
    await expect(page.getByTestId("select-approach-quick")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await expect(page.getByTestId("select-approach-thorough")).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    await page.getByTestId("select-approach-thorough").click();
    await expect(page.getByTestId("select-approach-thorough")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByTestId("budget-cap-input")).toHaveValue("130");
    await expect(page.getByTestId("budget-line")).toHaveText(
      "This run can use up to 130 credits (about US$0.65). You can pause it any time.",
    );

    await page.getByTestId("budget-cap-input").fill("520");
    await expect(page.getByTestId("budget-line")).toHaveText(
      "This run can use up to 520 credits (about US$2.60). You can pause it any time.",
    );

    const primary = page.locator("button.primary");
    await expect(primary).toHaveCount(1);
    await expect(primary).toHaveText("Start this approach");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(results.violations).toEqual([]);

    await primary.click();
    await expect(page.getByRole("heading", { level: 1, name: "World" })).toBeVisible();
    expect(problems).toEqual([]);
  });
}
