import { expect, test } from "@playwright/test";

for (const viewport of [
  { width: 320, height: 640 },
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
]) {
  test(`UI_10_W14 clear header, no ghost splash and clickable pins at ${viewport.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.clock.install({ time: new Date("2026-09-24T09:00:00+01:00") });
    await page.goto("/");
    await expect(page.locator("header")).toBeVisible();
    await expect(page.locator("main")).not.toHaveClass(/park-shell__booting/);
    // Check on the first UI paint, rather than waiting for the splash to finish fading.
    expect(
      await page
        .locator(".park-shell__bootlogo, .park-shell__bootstate")
        .evaluateAll((nodes) =>
          nodes.every((node) => getComputedStyle(node).visibility === "hidden"),
        ),
    ).toBe(true);

    const sample = page.getByRole("button", { name: "Sample data", exact: true });
    await expect(sample).toBeVisible();
    const box = await sample.boundingBox();
    expect(box).not.toBeNull();
    expect(box?.width).toBeGreaterThanOrEqual(24);
    expect(box?.height).toBeGreaterThanOrEqual(24);
    expect(
      await sample.evaluate((button) => {
        const rect = button.getBoundingClientRect();
        return [0.1, 0.5, 0.9].every((x) =>
          [0.1, 0.5, 0.9].every((y) =>
            button.contains(
              document.elementFromPoint(rect.left + rect.width * x, rect.top + rect.height * y),
            ),
          ),
        );
      }),
    ).toBe(true);
    await sample.click();
    await expect(page.getByRole("dialog", { name: "Sample data" })).toBeVisible();
    await page.keyboard.press("Escape");

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(
      await page.locator(".park-home-pin__card").evaluateAll((buttons) =>
        buttons.every((button) => {
          const rect = button.getBoundingClientRect();
          return [0.1, 0.5, 0.9].every((x) =>
            [0.1, 0.5, 0.9].every((y) =>
              button.contains(
                document.elementFromPoint(rect.left + rect.width * x, rect.top + rect.height * y),
              ),
            ),
          );
        }),
      ),
    ).toBe(true);
  });
}
