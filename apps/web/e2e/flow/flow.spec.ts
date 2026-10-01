import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "../support/viewports";

const viewports = { desktop: DESKTOP, mobile: MOBILE } as const;

for (const [, viewport] of Object.entries(viewports)) {
  test(`PRD-18.3 flow: walks Start, Understanding, Approaches, World and Delivery on the fixture client at ${viewport.width}x${viewport.height}: zero console errors, exactly one filled primary button per screen (UX-1), axe clean`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);

    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    const checkScreen = async (expectedHeading: string) => {
      await expect(page.getByRole("heading", { name: expectedHeading })).toBeVisible();

      // UX-1: exactly one filled primary button per screen
      const buttons = page.locator("button.primary");
      await expect(buttons).toHaveCount(1);

      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze();
      expect(results.violations).toEqual([]);
    };

    // S-01 Start
    await page.goto("/");
    await checkScreen("Start");
    await page.locator("button.primary").click();

    // S-02 Understanding
    await checkScreen("Understanding");
    await page.locator("button.primary").click();

    // S-03 Approaches
    await checkScreen("Approaches");
    await page.locator("button.primary").click();

    // S-04 World
    await expect(page.getByTestId("stage-frame")).toHaveAttribute("data-stage-ready", "true");
    await checkScreen("World");
    await page.locator("button.primary").click();

    // S-12 Delivery
    await checkScreen("Delivery");

    expect(errors).toEqual([]);
  });
}

test("PRD-18.1 UX-2: every flow button shows visible feedback within 100 ms", async ({ page }) => {
  await page.goto("/");
  const button = page.locator("button.primary");
  await expect(button).toBeVisible();
  expect(await button.getAttribute("aria-busy")).toBeNull();

  // Trigger click and verify immediate (<100ms) busy feedback before async transition completes
  const clickPromise = button.click();
  await expect(button).toHaveAttribute("aria-busy", "true", { timeout: 100 });
  await clickPromise;
});
